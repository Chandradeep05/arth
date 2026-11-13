"""
ARTH Phase 4 -- Internal Job Endpoints

POST /internal/jobs/evaluate-alerts:
  Called by GitHub Actions cron every 5 minutes.
  Protected by X-Internal-Secret header (INTERNAL_JOB_SECRET env var).

Alert evaluation reads the Redis quote cache first. For symbols with no cached
price (or when Redis is not configured) it falls back to MarketDataProvider,
one quote call per distinct symbol per run. Symbols that still have no valid
price are skipped that cycle and reported in `unpriced_symbols`.
"""
from __future__ import annotations

import asyncio
import json
import secrets
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.core.auth import require_internal_secret
from app.core.logging import get_logger
from app.core.market_calendar import get_market_state
from app.core.symbols import normalize_symbol, is_indian_symbol, get_symbol_currency

logger = get_logger(__name__)
router = APIRouter(prefix="/internal", tags=["internal"])

ALERT_EVAL_LOCK = "alert_eval_lock"
ALERT_EVAL_LOCK_TTL = 120  # seconds
_in_process_eval_lock = asyncio.Lock()
_last_eval_time = [0.0]


def _is_quote_fresh(data: dict, now: datetime, max_age_seconds: float = 900.0) -> bool:
    """Strict UTC timestamp freshness validation.
    
    Fail-closed: Rejects quotes when:
    - data is not a dict
    - ingested_at is missing, empty, or not a string
    - timestamp cannot be parsed into an ISO datetime
    - quote is older than max_age_seconds (default: 15 minutes)
    - timestamp is more than 60 seconds in the future (clock drift protection)
    """
    if not isinstance(data, dict):
        return False
    raw_ts = data.get("ingested_at")
    if not raw_ts or not isinstance(raw_ts, str):
        return False
    try:
        dt = datetime.fromisoformat(raw_ts)
        if dt.tzinfo is None:
            # Explicit normalization: treat naive timestamp as UTC
            dt = dt.replace(tzinfo=timezone.utc)
        age = (now - dt).total_seconds()
        if age > max_age_seconds or age < -60.0:
            return False
        return True
    except Exception:
        return False


@router.post("/jobs/evaluate-alerts")
async def evaluate_alerts(
    request: Request,
    _: None = Depends(require_internal_secret),
) -> dict:
    """Evaluate active price alerts against cached Redis quotes."""
    redis = getattr(request.app.state, "redis", None)
    db = getattr(request.state, "db", None)
    if db is None:
        logger.error("alert_eval_no_db", reason="request.state.db is None")
        return JSONResponse(
            status_code=503,
            content={"skipped": True, "reason": "Database pool unavailable — check asyncpg connection"},
        )
    now = datetime.now(timezone.utc)
    now_epoch = time.time()

    # Deduplication & cooldown guard (prevents redundant executions across dual schedulers)
    # NOTE: The cooldown timestamp is recorded AFTER _run_eval completes (not before) so that
    # a crashed or failed evaluation does not block retries for 120s.
    if redis:
        last_run = await redis.get("alert_eval_last_run")
        if last_run:
            try:
                if (now_epoch - float(last_run)) < 120.0:
                    logger.info("alert_eval_skipped_cooldown", elapsed=round(now_epoch - float(last_run), 1))
                    return {"skipped": True, "reason": "Evaluated recently within 120s cooldown"}
            except Exception:
                pass
    else:
        if (now_epoch - _last_eval_time[0]) < 120.0:
            logger.info("alert_eval_skipped_cooldown_in_process", elapsed=round(now_epoch - _last_eval_time[0], 1))
            return {"skipped": True, "reason": "Evaluated recently within 120s cooldown"}

    if redis:
        lock_token = secrets.token_hex(16)
        acquired = await redis.set(ALERT_EVAL_LOCK, lock_token, nx=True, ex=ALERT_EVAL_LOCK_TTL)
        if not acquired:
            logger.info("alert_eval_skipped_locked")
            return {"skipped": True, "reason": "Another evaluation running"}
    else:
        if _in_process_eval_lock.locked():
            logger.info("alert_eval_skipped_locked_in_process")
            return {"skipped": True, "reason": "Another evaluation running (in-process)"}

    if redis:
        try:
            result = await asyncio.wait_for(_run_eval(db, redis, now), timeout=90.0)
            # Record completion time AFTER successful eval so failures remain retryable
            await redis.set("alert_eval_last_run", str(now_epoch), ex=300)
            return result
        except asyncio.TimeoutError:
            logger.error("alert_eval_timed_out", timeout_sec=90)
            return {"skipped": True, "reason": "Alert evaluation timed out after 90s"}
        finally:
            _RELEASE_LOCK_LUA = """
            if redis.call('get', KEYS[1]) == ARGV[1] then
                return redis.call('del', KEYS[1])
            else
                return 0
            end
            """
            await redis.eval(_RELEASE_LOCK_LUA, 1, ALERT_EVAL_LOCK, lock_token)
    else:
        async with _in_process_eval_lock:
            try:
                result = await asyncio.wait_for(_run_eval(db, redis, now), timeout=90.0)
                # Record completion time AFTER successful eval so failures remain retryable
                _last_eval_time[0] = now_epoch
                return result
            except asyncio.TimeoutError:
                logger.error("alert_eval_timed_out_in_process", timeout_sec=90)
                return {"skipped": True, "reason": "Alert evaluation timed out after 90s (in-process)"}


async def _run_eval(db, redis, now: datetime) -> dict:
    run_id = secrets.token_hex(6)
    started = time.monotonic()
    alerts = await db.fetch(
        "SELECT id, user_id, symbol, alert_type, threshold, trigger_state FROM alerts WHERE is_active = true ORDER BY symbol"
    )
    if not alerts:
        return {
            "run_id": run_id,
            "active_alerts": 0,
            "symbols_requested": 0,
            "quotes_obtained": 0,
            "evaluated": 0,
            "triggered": 0,
            "notifications_created": 0,
            "skipped_market_closed": 0,
            "provider_errors": 0,
            "skipped_no_cache": 0,
            "unpriced_symbols": [],
            "duration_ms": 0,
            "at": now.isoformat(),
        }

    all_symbols = list({row["symbol"] for row in alerts})
    active_symbols = set()
    skipped_market_closed = 0

    # Market-aware session gate: strictly evaluate symbols whose exchanges are currently OPEN
    # Canonicalize symbols so bare Indian symbols (RELIANCE, TCS) evaluate against Indian market hours
    for sym in all_symbols:
        canonical_sym = normalize_symbol(sym)
        mstate, _ = get_market_state(canonical_sym, now)
        if mstate != "open":
            skipped_market_closed += 1
            logger.debug("alert_skipped_market_not_open", symbol=sym, canonical=canonical_sym, state=mstate)
        else:
            active_symbols.add(canonical_sym)

    symbols = list(active_symbols)
    prices = {}         # symbol -> price (float)
    quote_sources = {}  # symbol -> provider name string
    cache_miss = 0

    for symbol in symbols:
        price = None
        if redis:
            bare = symbol.split(".")[0]
            candidate_keys = [
                f"quote:{symbol}", f"market:quote:{symbol}", f"tick:{symbol}",
                f"quote:{bare}", f"market:quote:{bare}", f"tick:{bare}",
            ]
            for key in candidate_keys:
                raw = await redis.get(key)
                if raw:
                    try:
                        data = json.loads(raw)
                        # Strict fail-closed freshness guard: reject unvalidated, stale, or future quotes
                        if not _is_quote_fresh(data, now, max_age_seconds=900.0):
                            logger.debug("cached_quote_not_fresh_skipped", symbol=symbol)
                            continue
                        raw_price = (data.get("price") or data.get("close") or
                                     data.get("last_price") or
                                     (data.get("data") or {}).get("price"))
                        if raw_price is not None:
                            val = float(raw_price)
                            import math
                            if math.isfinite(val) and val > 0:
                                prices[symbol] = val
                                quote_sources[symbol] = data.get("provider") or data.get("source") or ("Upstox" if is_indian_symbol(symbol) else "cache")
                                break
                    except Exception:
                        continue
        if symbol not in prices:
            cache_miss += 1

    # For any symbols that missed the cache (or if Redis is not configured), fetch quote via MarketDataProvider
    # For Indian symbols: NEVER fall back to NSE; if Upstox fails, skip safely and record in unpriced_symbols.
    provider_errors = 0
    if cache_miss > 0:
        from app.data.market_data_provider import market_data as provider
        for symbol in symbols:
            if symbol in prices:
                continue
            try:
                is_indian = is_indian_symbol(symbol)
                res = await provider.get_quote(symbol, allow_nse_fallback=not is_indian)
                quote_data = res.data if hasattr(res, "data") else res
                actual_provider = getattr(res, "source", None) or ("Upstox" if is_indian else "unknown")
                if quote_data and isinstance(quote_data, dict):
                    p = quote_data.get("price") or quote_data.get("close") or quote_data.get("last_price")
                    if p is not None and float(p) > 0:
                        prices[symbol] = float(p)
                        # Use provider name from DataResult, not symbol suffix
                        quote_sources[symbol] = actual_provider
                        cache_miss = max(0, cache_miss - 1)
                        if redis:
                            try:
                                # Include provider so cache reads can recover source
                                cache_blob = dict(quote_data)
                                cache_blob["provider"] = actual_provider
                                await redis.set(f"quote:{symbol}", json.dumps(cache_blob, default=str), ex=300)
                            except Exception as cache_err:
                                logger.warning("alert_eval_cache_write_failed", symbol=symbol, error=str(cache_err))
                    else:
                        logger.warning("alert_eval_quote_non_positive", symbol=symbol, quote=quote_data)
                else:
                    logger.warning("alert_eval_no_quote_data", symbol=symbol, provider=actual_provider)
            except Exception as sym_err:
                provider_errors += 1
                logger.warning("alert_eval_quote_fetch_failed", symbol=symbol, error=str(sym_err))

    evaluated = 0
    triggered = 0

    for alert in alerts:
        symbol = alert["symbol"]
        canonical_sym = normalize_symbol(symbol)
        current = prices.get(canonical_sym) or prices.get(symbol)
        # Valid price invariant: price is not None and price > 0
        if current is None or current <= 0:
            continue

        evaluated += 1
        threshold = float(alert["threshold"])
        atype = alert["alert_type"]
        state = alert["trigger_state"]

        condition = (atype == "price_above" and current >= threshold) or (atype == "price_below" and current <= threshold)
        cleared = (atype == "price_above" and current < threshold) or (atype == "price_below" and current > threshold)

        if condition and state == "armed":
            direction = "above" if atype == "price_above" else "below"
            # Atomic: state transition is the authoritative idempotency guard.
            # If UPDATE matches 0 rows, another evaluator already triggered — or the alert config
            # changed between our SELECT and this UPDATE (alert_type/threshold guard prevents
            # an obsolete evaluation from firing on a freshly edited alert).
            async with db.transaction():
                updated = await db.execute(
                    "UPDATE alerts SET trigger_state = $1, last_evaluated_value = $2, last_triggered_at = $3 "
                    "WHERE id = $4 AND trigger_state = 'armed' AND alert_type = $5 AND threshold = $6",
                    "triggered", current, now, alert["id"], atype, alert["threshold"],
                )
                # Only insert notification if we actually flipped the state
                if updated and updated != "UPDATE 0":
                    curr_sym = get_symbol_currency(canonical_sym)
                    dir_sym = "≥" if direction == "above" else "≤"
                    # Use actual provider from DataResult, not guessed from symbol suffix
                    actual_source = quote_sources.get(canonical_sym) or quote_sources.get(symbol) or "unknown"
                    # Get real session name from market state engine
                    _, session_label = get_market_state(canonical_sym, now)
                    session_name = session_label if session_label else "Regular Trading"
                    # Build human-readable body with real provenance
                    body_text = (
                        f"Price: {curr_sym}{current:.2f} | "
                        f"Target: {dir_sym} {curr_sym}{threshold:.2f} | "
                        f"Session: {session_name} | Source: {actual_source}"
                    )
                    await db.execute(
                        "INSERT INTO notifications (user_id, alert_id, title, body) VALUES ($1, $2, $3, $4)",
                        alert["user_id"], alert["id"],
                        f"{canonical_sym} crossed {direction} {curr_sym}{threshold:.2f}",
                        body_text,
                    )
                    triggered += 1
                    logger.info("alert_triggered", symbol=canonical_sym, raw_symbol=symbol, price=current, threshold=threshold)
        elif cleared and state == "triggered":
            await db.execute(
                "UPDATE alerts SET trigger_state = $1, last_evaluated_value = $2 WHERE id = $3 AND trigger_state = 'triggered' AND is_active = true",
                "armed", current, alert["id"],
            )

    unpriced = sorted(s for s in symbols if s not in prices)
    duration_ms = int((time.monotonic() - started) * 1000)
    logger.info(
        "alert_eval_complete",
        run_id=run_id, active_alerts=len(alerts), symbols=len(symbols), priced=len(prices),
        unpriced=unpriced, evaluated=evaluated, triggered=triggered,
        provider_errors=provider_errors, duration_ms=duration_ms,
    )
    return {
        "run_id": run_id,
        "active_alerts": len(alerts),
        "symbols_requested": len(symbols),
        "quotes_obtained": len(prices),
        "evaluated": evaluated,
        "triggered": triggered,
        "notifications_created": triggered,
        "skipped_market_closed": skipped_market_closed,
        "provider_errors": provider_errors,
        "skipped_no_cache": cache_miss,
        "unpriced_symbols": unpriced,
        "duration_ms": duration_ms,
        "at": now.isoformat(),
    }


@router.post("/jobs/warm-alert-symbols")
async def warm_alert_symbols(
    request: Request,
    _: None = Depends(require_internal_secret),
) -> dict:
    """Warm up redis cache for active alert symbols without cached quotes."""
    redis = getattr(request.app.state, "redis", None)
    db = getattr(request.state, "db", None)
    if not redis:
        return JSONResponse(status_code=503, content={"skipped": True, "reason": "Redis not configured"})
    if db is None:
        return JSONResponse(status_code=503, content={"skipped": True, "reason": "Database pool unavailable"})
        
    alerts = await db.fetch("SELECT DISTINCT symbol FROM alerts WHERE is_active = true")
    if not alerts:
        return {"warmed": 0, "skipped": 0}

    symbols = [row["symbol"] for row in alerts]
    now = datetime.now(timezone.utc)
    now_ts = now.timestamp()
    WARMUP_ZSET = "alert_symbols_warmup_schedule"

    # Track active symbols in scheduling ZSET (default priority 0 for new symbols)
    for s in symbols:
        try:
            await redis.zadd(WARMUP_ZSET, {s: 0}, nx=True)
        except Exception:
            pass

    # Clean up symbols in ZSET that are no longer active
    scheduled_symbols = []
    try:
        entries = await redis.zrange(WARMUP_ZSET, 0, -1)
        for entry in entries:
            sym_str = entry.decode("utf-8") if isinstance(entry, bytes) else str(entry)
            if sym_str in symbols:
                scheduled_symbols.append(sym_str)
            else:
                await redis.zrem(WARMUP_ZSET, sym_str)
    except Exception as e:
        logger.warning("warmup_schedule_read_failed", error=str(e))
        scheduled_symbols = symbols

    # Append any symbols that might have failed to register in ZSET
    for s in symbols:
        if s not in scheduled_symbols:
            scheduled_symbols.append(s)

    # Check which symbols currently lack a cached price in Redis
    uncached = []
    for s in scheduled_symbols:
        canonical_s = normalize_symbol(s)
        has_price = False
        for key in [f"quote:{canonical_s}", f"market:quote:{canonical_s}", f"tick:{canonical_s}", f"quote:{s}", f"market:quote:{s}", f"tick:{s}"]:
            try:
                get_fn = getattr(redis, "get", None)
                if get_fn:
                    res = get_fn(key)
                    if asyncio.iscoroutine(res):
                        raw = await res
                        if raw:
                            data = json.loads(raw)
                            if _is_quote_fresh(data, now, max_age_seconds=900.0):
                                has_price = True
                                break
                    elif isinstance(res, (str, bytes)):
                        data = json.loads(res)
                        if _is_quote_fresh(data, now, max_age_seconds=900.0):
                            has_price = True
                            break

                exists_fn = getattr(redis, "exists", None)
                if exists_fn and not has_price:
                    res_ex = exists_fn(key)
                    if asyncio.iscoroutine(res_ex):
                        if await res_ex:
                            has_price = True
                            break
                    elif isinstance(res_ex, bool) and res_ex:
                        has_price = True
                        break
            except Exception:
                pass
        if not has_price:
            uncached.append(s)

    # Process up to 10 uncached symbols per cycle in round-robin order
    to_warm = uncached[:10]
    warmed = 0

    from app.data.market_data_provider import market_data

    for symbol in to_warm:
        # Immediately bump score to prevent retry looping on failing symbols
        try:
            await redis.zadd(WARMUP_ZSET, {symbol: now_ts})
        except Exception:
            pass

        try:
            canonical_sym = normalize_symbol(symbol)
            is_indian = is_indian_symbol(canonical_sym)
            # Skip fetch if market is closed -- avoids wasting Upstox/provider quota during after-hours
            mstate, _ = get_market_state(canonical_sym, now)
            if mstate not in ("open", "pre-market"):
                logger.debug("warmup_market_closed_skip", symbol=canonical_sym, state=mstate)
                continue
            res = await market_data.get_quote(canonical_sym, allow_nse_fallback=not is_indian)
            if res.available and res.data:
                actual_prov = getattr(res, "source", None) or ("Upstox" if is_indian else "unknown")
                cache_blob = dict(res.data)
                cache_blob["provider"] = actual_prov
                cache_blob["ingested_at"] = now.isoformat()
                cache_blob["symbol"] = canonical_sym
                await redis.set(
                    f"quote:{canonical_sym}",
                    json.dumps(cache_blob, default=str),
                    ex=1860,  # 31 minutes — survives between 30-min warmup cycles
                )
                warmed += 1
            await asyncio.sleep(0.1)  # 100ms pacing between provider calls
        except Exception as e:
            logger.warning("warmup_failed", symbol=symbol, error=str(e))

    return {
        "warmed": warmed,
        "skipped": len(symbols) - len(uncached),
        "uncached_remaining": max(0, len(uncached) - len(to_warm)),
    }


@router.post("/jobs/evaluate-predictions")
async def evaluate_predictions(
    request: Request,
    _: None = Depends(require_internal_secret),
) -> dict:
    """Evaluate matured prediction outcomes against actual market prices.

    Called by cron (recommended: every 6 hours during market days).
    Uses atomic Redis SET NX claims — safe for concurrent invocations.

    This is the ONLY path that calls evaluate_pending().
    User-facing GET /history and /accuracy are READ-ONLY.
    """
    from app.engines.prediction.outcome_tracker import outcome_tracker
    from app.data.market_data_provider import market_data

    async def _fetch_price(symbol: str) -> float | None:
        """Fetch current price for evaluation."""
        try:
            canonical_s = normalize_symbol(symbol)
            is_ind = is_indian_symbol(canonical_s)
            result = await market_data.get_quote(canonical_s, allow_nse_fallback=not is_ind)
            if result.available and result.data:
                return result.data.get("price")
        except Exception as e:
            logger.warning("eval_price_fetch_failed", symbol=symbol, error=str(e))
        return None

    try:
        count = await outcome_tracker.evaluate_pending(fetch_price_func=_fetch_price)
        stats = getattr(count, "stats", None)
        if isinstance(stats, dict):
            return {"status": "ok", **stats}
        return {"evaluated": int(count), "status": "ok"}
    except Exception as e:
        logger.error("evaluate_predictions_failed", error=str(e))
        return JSONResponse(status_code=500, content={"evaluated": 0, "status": "error", "error": str(e)})

