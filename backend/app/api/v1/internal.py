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
from app.core.symbols import normalize_symbol, is_indian_symbol, get_symbol_currency, AMBIGUOUS_SYMBOLS

logger = get_logger(__name__)
router = APIRouter(prefix="/internal", tags=["internal"])

ALERT_EVAL_LOCK = "alert_eval_lock"
ALERT_EVAL_LOCK_TTL = 120  # seconds
_in_process_eval_lock = asyncio.Lock()
_last_eval_time = [0.0]


def _parse_timestamp_to_utc(raw_ts: object) -> Optional[datetime]:
    """Parse various timestamp representations into an aware UTC datetime."""
    if raw_ts is None or isinstance(raw_ts, bool):
        return None
    if isinstance(raw_ts, datetime):
        if raw_ts.tzinfo is None:
            return raw_ts.replace(tzinfo=timezone.utc)
        return raw_ts.astimezone(timezone.utc)
    if isinstance(raw_ts, (int, float)):
        val = float(raw_ts)
        if val > 1e11:  # milliseconds
            val = val / 1000.0
        try:
            return datetime.fromtimestamp(val, tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None
    if isinstance(raw_ts, str):
        s = raw_ts.strip()
        if not s:
            return None
        # Try numeric epoch string
        try:
            val = float(s)
            if val > 1e11:
                val = val / 1000.0
            return datetime.fromtimestamp(val, tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            pass
        # Try ISO / datetime format
        try:
            clean = s.replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass
    return None


_MARKET_TIMESTAMP_KEYS = ("timestamp", "last_trade_time", "market_time", "datetime", "time", "t")


def _is_quote_fresh(data: dict, now: datetime, max_age_seconds: float = 900.0) -> bool:
    """Strict UTC timestamp freshness validation.
    
    Fail-closed policy:
    1. Rejects quotes if data is not a dict.
    2. Inspects market data timestamp candidates: 'timestamp', 'last_trade_time', 'market_time',
       'datetime', 'time', 't'.
    3. If a market timestamp field is present (key exists with non-null value):
       - It must parse into an aware UTC datetime. If malformed or unparseable (including
         empty, whitespace-only, or invalid format strings), the quote is REJECTED immediately.
         It does NOT fall back to ingested_at.
       - If valid, verifies it is not older than max_age_seconds and not more than 60s
         in the future (clock drift protection).
    4. Ingestion timestamp resolution ('ingested_at' primary, '_cached_at' fallback):
       - If 'ingested_at' is present and non-null, it MUST parse successfully. If malformed
         or unparseable, the quote is rejected immediately (fail-closed, does not fall through
         to '_cached_at').
       - If 'ingested_at' is absent or explicitly None, '_cached_at' may provide fallback.
       - If an ingestion timestamp is resolved, enforces freshness and clock-skew limits.
    5. Fallback & combination rules:
       - If a valid fresh market timestamp exists without any ingestion metadata, it is accepted.
       - If both market and ingestion timestamps exist, both must be valid and fresh.
       - If NO market timestamp was provided, a valid, fresh ingestion timestamp is strictly required.
       - If neither a usable market timestamp nor a valid ingestion timestamp exists, rejects.
    """
    if not isinstance(data, dict):
        return False

    # 1. Inspect candidate market-data timestamp fields
    market_raw = None
    has_market_field = False
    for k in _MARKET_TIMESTAMP_KEYS:
        if k in data and data[k] is not None:
            market_raw = data[k]
            has_market_field = True
            break

    # If a market timestamp field was supplied, it must parse successfully and be fresh.
    # An unparseable or malformed market timestamp must fail closed and NEVER fall back to ingested_at.
    if has_market_field:
        market_dt = _parse_timestamp_to_utc(market_raw)
        if market_dt is None:
            return False
        age = (now - market_dt).total_seconds()
        if age > max_age_seconds or age < -60.0:
            return False

    # 2. Ingestion timestamp resolution ('ingested_at' primary, '_cached_at' fallback)
    # If ingested_at is present and non-null, it must parse successfully.
    # A malformed non-null ingested_at fails closed immediately rather than falling through.
    ingest_raw = None
    has_ingest_field = False

    if "ingested_at" in data and data["ingested_at"] is not None:
        ingest_raw = data["ingested_at"]
        has_ingest_field = True
    elif "_cached_at" in data and data["_cached_at"] is not None:
        ingest_raw = data["_cached_at"]
        has_ingest_field = True

    if has_ingest_field:
        ingest_dt = _parse_timestamp_to_utc(ingest_raw)
        if ingest_dt is None:
            return False
        ingest_age = (now - ingest_dt).total_seconds()
        if ingest_age > max_age_seconds or ingest_age < -60.0:
            return False

    # If no market timestamp was provided, a valid ingestion timestamp is strictly required.
    if not has_market_field:
        if not has_ingest_field:
            return False
        return True

    return True


def _is_quote_identity_valid(data: dict, requested_symbol: str) -> bool:
    """Validate that the quote data matches the requested symbol, exchange, and currency.

    Prevents cross-market and cross-exchange contamination:
    - Indian equities/indices must not match US exchange quotes or USD currency.
    - US equities must not match Indian exchange quotes or INR currency.
    - Ambiguous symbols (e.g. HAL) must not match across exchanges (HAL.NS vs HAL NYSE).
    - Fails closed when an ambiguous instrument's exchange/market identity cannot be established.
    """
    if not isinstance(data, dict):
        return False

    requested_sym = (requested_symbol or "").strip().upper()
    requested_canon = normalize_symbol(requested_sym)
    is_indian = is_indian_symbol(requested_canon)
    bare_req = requested_sym.split(".")[0]

    quote_ex = str(data.get("exchange") or "").strip().upper()
    quote_curr = str(data.get("currency") or "").strip().upper()
    quote_market = str(data.get("market") or "").strip().lower()
    quote_prov = str(data.get("provider") or data.get("source") or "").strip().lower()

    # 1. Symbol identity check
    quote_sym = data.get("symbol")
    if quote_sym and isinstance(quote_sym, str):
        quote_clean = quote_sym.strip().upper()
        quote_canon = normalize_symbol(quote_clean)
        bare_quote = quote_clean.split(".")[0]

        # For cross-market ambiguous tickers (e.g. HAL)
        if bare_req in AMBIGUOUS_SYMBOLS or bare_quote in AMBIGUOUS_SYMBOLS:
            # If canonical symbols don't match, immediate rejection
            if requested_canon != quote_canon:
                return False

            if is_indian:
                # Immediate rejection on foreign metadata
                if quote_ex in ("NYSE", "NASDAQ", "AMEX", "US", "BATS", "ARCA") or quote_curr in ("USD", "$"):
                    return False
                # If quote symbol does NOT carry explicit Indian suffix (.NS/.BO),
                # it MUST establish Indian identity via exchange, currency, market, or provider
                if not quote_clean.endswith((".NS", ".BO")):
                    has_indian_id = (
                        quote_ex in ("NSE", "BSE")
                        or quote_curr in ("INR", "\u20b9")
                        or quote_market in ("india", "in")
                        or quote_prov in ("upstox", "nse")
                    )
                    if not has_indian_id:
                        # Fail-closed: cannot verify that bare HAL is Indian HAL.NS
                        return False
            else:
                # US ambiguous symbol
                if quote_ex in ("NSE", "BSE", "INDIA") or quote_curr in ("INR", "\u20b9"):
                    return False
                if quote_clean.endswith((".NS", ".BO")):
                    return False
        else:
            if requested_canon != quote_canon:
                return False
    else:
        # Quote data omits symbol entirely
        if bare_req in AMBIGUOUS_SYMBOLS:
            if is_indian:
                has_indian_id = (
                    quote_ex in ("NSE", "BSE")
                    or quote_curr in ("INR", "\u20b9")
                    or quote_market in ("india", "in")
                    or quote_prov in ("upstox", "nse")
                )
                if not has_indian_id:
                    return False
            else:
                return False

    # 2. Exchange / Currency / Market integrity check
    if is_indian:
        if quote_ex in ("NYSE", "NASDAQ", "AMEX", "US", "BATS", "ARCA"):
            return False
        if quote_curr in ("USD", "$", "EUR", "GBP"):
            return False
        if quote_market in ("us", "usa", "united states"):
            return False
        if requested_sym.endswith(".NS") and quote_ex == "BSE":
            return False
        if requested_sym.endswith(".BO") and quote_ex == "NSE":
            return False
    else:
        if quote_ex in ("NSE", "BSE", "INDIA"):
            return False
        if quote_curr in ("INR", "\u20b9"):
            return False
        if quote_market in ("india", "in"):
            return False

    return True


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
            return JSONResponse(
                status_code=504,
                content={"status": "error", "error": "Gateway Timeout", "reason": "Alert evaluation timed out after 90s"}
            )
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
                return JSONResponse(
                    status_code=504,
                    content={"status": "error", "error": "Gateway Timeout", "reason": "Alert evaluation timed out after 90s (in-process)"}
                )


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
            canonical_sym = normalize_symbol(symbol)
            bare = symbol.split(".")[0]
            candidate_keys = [
                f"quote:{canonical_sym}", f"quote:{symbol}",
                f"market:quote:{canonical_sym}", f"market:quote:{symbol}",
                f"tick:{canonical_sym}", f"tick:{symbol}",
                f"upstox:quote:{canonical_sym}", f"upstox:quote:{symbol}",
            ]
            # Exclude bare keys for tickers with cross-exchange ambiguities (e.g. HAL)
            if bare not in AMBIGUOUS_SYMBOLS and bare != symbol and bare != canonical_sym:
                candidate_keys.extend([f"quote:{bare}", f"market:quote:{bare}", f"tick:{bare}"])

            for key in candidate_keys:
                raw = await redis.get(key)
                if raw:
                    try:
                        data = json.loads(raw)
                        # Strict fail-closed quote identity guard: reject wrong-exchange/wrong-currency quotes
                        if not _is_quote_identity_valid(data, requested_symbol=symbol):
                            logger.debug("cached_quote_identity_mismatch_skipped", symbol=symbol, key=key)
                            continue
                        # Strict fail-closed freshness guard: reject unvalidated, stale, or future quotes
                        if not _is_quote_fresh(data, now, max_age_seconds=900.0):
                            logger.debug("cached_quote_not_fresh_skipped", symbol=symbol, key=key)
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
                    # Strict fail-closed identity & freshness validation on provider response
                    if not _is_quote_identity_valid(quote_data, requested_symbol=symbol):
                        logger.warning("alert_eval_provider_quote_identity_mismatch", symbol=symbol)
                        continue

                    # For live provider responses without an explicit timestamp (e.g. mock objects),
                    # stamp ingested_at = now so newly fetched live data is accepted unless explicitly stale
                    quote_to_check = quote_data
                    if not any(k in quote_data for k in _MARKET_TIMESTAMP_KEYS + ("ingested_at",)):
                        quote_to_check = dict(quote_data)
                        quote_to_check["ingested_at"] = now.isoformat()

                    if not _is_quote_fresh(quote_to_check, now, max_age_seconds=900.0):
                        logger.warning("alert_eval_provider_quote_stale", symbol=symbol)
                        continue
                    p = quote_data.get("price") or quote_data.get("close") or quote_data.get("last_price")
                    if p is not None:
                        try:
                            val = float(p)
                            import math
                            if math.isfinite(val) and val > 0:
                                prices[symbol] = val
                                # Use provider name from DataResult, not symbol suffix
                                quote_sources[symbol] = actual_provider
                                cache_miss = max(0, cache_miss - 1)
                                if redis:
                                    try:
                                        canonical_sym = normalize_symbol(symbol)
                                        # Include provider and ingestion timestamp so cache reads can validate freshness
                                        cache_blob = dict(quote_data)
                                        cache_blob["provider"] = actual_provider
                                        cache_blob["ingested_at"] = now.isoformat()
                                        cache_blob["symbol"] = canonical_sym
                                        await redis.set(
                                            f"quote:{canonical_sym}",
                                            json.dumps(cache_blob, default=str),
                                            ex=300,
                                        )
                                        if symbol != canonical_sym and symbol.split(".")[0] not in AMBIGUOUS_SYMBOLS:
                                            await redis.set(
                                                f"quote:{symbol}",
                                                json.dumps(cache_blob, default=str),
                                                ex=300,
                                            )
                                    except Exception as cache_err:
                                        logger.warning("alert_eval_cache_write_failed", symbol=symbol, error=str(cache_err))
                            else:
                                logger.warning("alert_eval_quote_non_positive_or_non_finite", symbol=symbol, price=val)
                        except (ValueError, TypeError):
                            logger.warning("alert_eval_quote_invalid_price_format", symbol=symbol, raw_price=p)
                    else:
                        logger.warning("alert_eval_quote_price_missing", symbol=symbol, quote=quote_data)
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
        # Valid price invariant: price is not None, finite, and price > 0
        import math
        if current is None or not math.isfinite(current) or current <= 0:
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
        return {"warmed": 0, "skipped": 0, "uncached_remaining": 0}

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
        for key in [f"quote:{canonical_s}", f"market:quote:{canonical_s}", f"tick:{canonical_s}", f"upstox:quote:{canonical_s}", f"quote:{s}", f"market:quote:{s}", f"tick:{s}", f"upstox:quote:{s}"]:
            try:
                get_fn = getattr(redis, "get", None)
                if get_fn:
                    res = get_fn(key)
                    raw = await res if asyncio.iscoroutine(res) else res
                    if raw:
                        try:
                            data = json.loads(raw)
                            if _is_quote_identity_valid(data, requested_symbol=s) and _is_quote_fresh(data, now, max_age_seconds=900.0):
                                has_price = True
                                break
                        except Exception:
                            pass
                        # Key was present in Redis but failed freshness validation (stale or corrupted).
                        # Fail-closed: NEVER fall back to exists_fn for this key -- it is known to be stale!
                        continue

                # Only consult exists_fn if get_fn is completely absent (e.g. minimal test mock without get)
                if not get_fn:
                    exists_fn = getattr(redis, "exists", None)
                    if exists_fn:
                        res_ex = exists_fn(key)
                        ex = await res_ex if asyncio.iscoroutine(res_ex) else res_ex
                        if ex:
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
                raw_p = result.data.get("price")
                if raw_p is not None:
                    try:
                        p_float = float(raw_p)
                        import math
                        if math.isfinite(p_float) and p_float > 0:
                            return p_float
                    except (ValueError, TypeError):
                        pass
        except Exception as e:
            logger.warning("eval_price_fetch_failed", symbol=symbol, error=str(e))
        return None

    try:
        count = await outcome_tracker.evaluate_pending(fetch_price_func=_fetch_price)
        stats = getattr(count, "stats", None)
        if isinstance(stats, dict):
            eligible = stats.get("eligible", 0)
            evaluated = stats.get("evaluated", 0)
            if eligible > 0 and evaluated == 0:
                logger.warning("evaluate_predictions_stalled", eligible=eligible, evaluated=evaluated, stats=stats)
                return JSONResponse(
                    status_code=502,
                    content={
                        "status": "stalled",
                        "error": "Eligible predictions could not be evaluated due to pricing failures",
                        **stats
                    }
                )
            return {"status": "ok", **stats}
        return {"evaluated": int(count), "status": "ok"}
    except Exception as e:
        logger.error("evaluate_predictions_failed", error=str(e))
        return JSONResponse(status_code=500, content={"evaluated": 0, "status": "error", "error": str(e)})

