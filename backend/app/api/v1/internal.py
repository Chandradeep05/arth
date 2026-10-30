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

from app.core.auth import require_internal_secret
from app.core.logging import get_logger
from app.core.market_calendar import get_market_state

logger = get_logger(__name__)
router = APIRouter(prefix="/internal", tags=["internal"])

ALERT_EVAL_LOCK = "alert_eval_lock"
ALERT_EVAL_LOCK_TTL = 120  # seconds
_in_process_eval_lock = asyncio.Lock()
_last_eval_time = [0.0]


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
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=503,
            content={"skipped": True, "reason": "Database pool unavailable — check asyncpg connection"},
        )
    now = datetime.now(timezone.utc)
    now_epoch = time.time()

    # Deduplication & cooldown guard (prevents redundant executions across dual schedulers)
    if redis:
        last_run = await redis.get("alert_eval_last_run")
        if last_run:
            try:
                if (now_epoch - float(last_run)) < 120.0:
                    logger.info("alert_eval_skipped_cooldown", elapsed=round(now_epoch - float(last_run), 1))
                    return {"skipped": True, "reason": "Evaluated recently within 120s cooldown"}
            except Exception:
                pass
        await redis.set("alert_eval_last_run", str(now_epoch), ex=300)
    else:
        if (now_epoch - _last_eval_time[0]) < 120.0:
            logger.info("alert_eval_skipped_cooldown_in_process", elapsed=round(now_epoch - _last_eval_time[0], 1))
            return {"skipped": True, "reason": "Evaluated recently within 120s cooldown"}
        _last_eval_time[0] = now_epoch

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
            return await _run_eval(db, redis, now)
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
            return await _run_eval(db, redis, now)


async def _run_eval(db, redis, now: datetime) -> dict:
    run_id = secrets.token_hex(6)
    started = time.monotonic()
    alerts = await db.fetch(
        "SELECT id, user_id, symbol, alert_type, threshold, trigger_state FROM alerts WHERE is_active = true ORDER BY symbol"
    )
    if not alerts:
        return {"run_id": run_id, "evaluated": 0, "triggered": 0, "skipped_no_cache": 0}

    all_symbols = list({row["symbol"] for row in alerts})
    active_symbols = set()
    skipped_market_closed = 0

    # Market-aware session gate: strictly evaluate symbols whose exchanges are currently OPEN
    for sym in all_symbols:
        mstate, _ = get_market_state(sym, now)
        if mstate != "open":
            skipped_market_closed += 1
            logger.debug("alert_skipped_market_not_open", symbol=sym, state=mstate)
        else:
            active_symbols.add(sym)

    symbols = list(active_symbols)
    prices = {}         # symbol -> price (float)
    quote_sources = {}  # symbol -> provider name string
    cache_miss = 0

    for symbol in symbols:
        price = None
        if redis:
            for key in [f"quote:{symbol}", f"market:quote:{symbol}", f"tick:{symbol}"]:
                raw = await redis.get(key)
                if raw:
                    try:
                        data = json.loads(raw)
                        price = (data.get("price") or data.get("close") or
                                 data.get("last_price") or
                                 (data.get("data") or {}).get("price"))
                        if price:
                            prices[symbol] = float(price)
                            quote_sources[symbol] = data.get("provider") or data.get("source") or "cache"
                            break
                    except Exception:
                        continue
        if symbol not in prices:
            cache_miss += 1

    # For any symbols that missed the cache (or if Redis is not configured), fetch quote via MarketDataProvider
    provider_errors = 0
    if cache_miss > 0:
        from app.data.market_data_provider import market_data as provider
        for symbol in symbols:
            if symbol in prices:
                continue
            try:
                res = await provider.get_quote(symbol)
                quote_data = res.data if hasattr(res, "data") else res
                actual_provider = getattr(res, "provider", None) or "unknown"
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
            except Exception as sym_err:
                provider_errors += 1
                logger.warning("alert_eval_quote_fetch_failed", symbol=symbol, error=str(sym_err))

    evaluated = 0
    triggered = 0

    for alert in alerts:
        symbol = alert["symbol"]
        current = prices.get(symbol)
        if current is None:
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
            # If UPDATE matches 0 rows, another evaluator already triggered.
            async with db.transaction():
                updated = await db.execute(
                    "UPDATE alerts SET trigger_state = $1, last_evaluated_value = $2, last_triggered_at = $3 "
                    "WHERE id = $4 AND trigger_state = 'armed'",
                    "triggered", current, now, alert["id"],
                )
                # Only insert notification if we actually flipped the state
                if updated and updated != "UPDATE 0":
                    curr_sym = "₹" if symbol.endswith((".NS", ".BO")) else "$"
                    dir_sym = "≥" if direction == "above" else "≤"
                    # Use actual provider from DataResult, not guessed from symbol suffix
                    actual_source = quote_sources.get(symbol, "unknown")
                    # Get real session name from market state engine
                    _, session_label = get_market_state(symbol, now)
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
                        f"{symbol} crossed {direction} {curr_sym}{threshold:.2f}",
                        body_text,
                    )
                    triggered += 1
                    logger.info("alert_triggered", symbol=symbol, price=current, threshold=threshold)
        elif cleared and state == "triggered":
            await db.execute(
                "UPDATE alerts SET trigger_state = $1, last_evaluated_value = $2 WHERE id = $3",
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
        return {"skipped": True, "reason": "Redis not configured"}
    if db is None:
        return {"skipped": True, "reason": "Database pool unavailable"}
        
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
        has_price = False
        for key in [f"quote:{s}", f"market:quote:{s}", f"tick:{s}"]:
            if await redis.exists(key):
                has_price = True
                break
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
            res = await market_data.get_quote(symbol)
            if res.available and res.data:
                await redis.set(
                    f"quote:{symbol}",
                    json.dumps(res.data, default=str),
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
            result = await market_data.get_quote(symbol)
            if result.available and result.data:
                return result.data.get("price")
        except Exception as e:
            logger.warning("eval_price_fetch_failed", symbol=symbol, error=str(e))
        return None

    try:
        count = await outcome_tracker.evaluate_pending(fetch_price_func=_fetch_price)
        return {"evaluated": count, "status": "ok"}
    except Exception as e:
        logger.error("evaluate_predictions_failed", error=str(e))
        return {"evaluated": 0, "status": "error", "error": str(e)}

