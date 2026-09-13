"""
ARTH Phase 4 -- Internal Job Endpoints

POST /internal/jobs/evaluate-alerts:
  Called by GitHub Actions cron every 5 minutes.
  Protected by X-Internal-Secret header (INTERNAL_JOB_SECRET env var).

Alert evaluation reads Redis quote cache ONLY.
Zero fresh provider API calls -- respects credit budget.
Symbols with no cached price are skipped that cycle.
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request

from app.core.auth import require_internal_secret
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/internal", tags=["internal"])

ALERT_EVAL_LOCK = "alert_eval_lock"
ALERT_EVAL_LOCK_TTL = 120  # seconds


@router.post("/jobs/evaluate-alerts")
async def evaluate_alerts(
    request: Request,
    _: None = Depends(require_internal_secret),
) -> dict:
    """Evaluate active price alerts against cached Redis quotes."""
    redis = getattr(request.app.state, "redis", None)
    db = getattr(request.state, "db", None)
    if db is None:
        return {"skipped": True, "reason": "Database pool unavailable — check asyncpg connection"}
    now = datetime.now(timezone.utc)

    if redis:
        lock_token = secrets.token_hex(16)
        acquired = await redis.set(ALERT_EVAL_LOCK, lock_token, nx=True, ex=ALERT_EVAL_LOCK_TTL)
        if not acquired:
            logger.info("alert_eval_skipped_locked")
            return {"skipped": True, "reason": "Another evaluation running"}

    try:
        return await _run_eval(db, redis, now)
    finally:
        if redis:
            _RELEASE_LOCK_LUA = """
            if redis.call('get', KEYS[1]) == ARGV[1] then
                return redis.call('del', KEYS[1])
            else
                return 0
            end
            """
            await redis.eval(_RELEASE_LOCK_LUA, 1, ALERT_EVAL_LOCK, lock_token)


async def _run_eval(db, redis, now: datetime) -> dict:
    alerts = await db.fetch(
        "SELECT id, user_id, symbol, alert_type, threshold, trigger_state FROM alerts WHERE is_active = true ORDER BY symbol"
    )
    if not alerts:
        return {"evaluated": 0, "triggered": 0, "skipped_no_cache": 0}

    symbols = list({row["symbol"] for row in alerts})
    prices = {}
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
                            break
                    except Exception:
                        continue
        if symbol not in prices:
            cache_miss += 1

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
                    await db.execute(
                        "INSERT INTO notifications (user_id, alert_id, title, body) VALUES ($1, $2, $3, $4)",
                        alert["user_id"], alert["id"],
                        f"{symbol} {direction} {threshold}",
                        f"Price: {current:.2f} | Threshold: {threshold:.2f}",
                    )
                    triggered += 1
                    logger.info("alert_triggered", symbol=symbol, price=current, threshold=threshold)
        elif cleared and state == "triggered":
            await db.execute(
                "UPDATE alerts SET trigger_state = $1, last_evaluated_value = $2 WHERE id = $3",
                "armed", current, alert["id"],
            )

    return {"evaluated": evaluated, "triggered": triggered, "skipped_no_cache": cache_miss, "at": now.isoformat()}


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
    uncached = []
    
    for symbol in symbols:
        price = None
        for key in [f"quote:{symbol}", f"market:quote:{symbol}", f"tick:{symbol}"]:
            if await redis.exists(key):
                price = True
                break
        if not price:
            uncached.append(symbol)
            
    # Process up to 5 uncached symbols
    to_warm = uncached[:5]
    warmed = 0
    
    from app.data.market_data_provider import market_data
    
    for symbol in to_warm:
        try:
            res = await market_data.get_quote(symbol)
            if res.success and res.data:
                await redis.set(
                    f"quote:{symbol}",
                    json.dumps(res.data),
                    ex=1860  # 31 minutes — survives between 30-min warmup cycles
                )
                warmed += 1
        except Exception as e:
            logger.warning("warmup_failed", symbol=symbol, error=str(e))
            
    return {"warmed": warmed, "skipped": len(symbols) - len(uncached), "uncached_remaining": max(0, len(uncached) - 5)}
