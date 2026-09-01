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
    db = request.state.db
    now = datetime.now(timezone.utc)

    if redis:
        acquired = await redis.set(ALERT_EVAL_LOCK, "1", nx=True, ex=ALERT_EVAL_LOCK_TTL)
        if not acquired:
            logger.info("alert_eval_skipped_locked")
            return {"skipped": True, "reason": "Another evaluation running"}

    try:
        return await _run_eval(db, redis, now)
    finally:
        if redis:
            await redis.delete(ALERT_EVAL_LOCK)


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
            await db.execute(
                "INSERT INTO notifications (user_id, alert_id, title, body) VALUES ($1, $2, $3, $4)",
                alert["user_id"], alert["id"],
                f"{symbol} {direction} {threshold}",
                f"Price: {current:.2f} | Threshold: {threshold:.2f}",
            )
            await db.execute(
                "UPDATE alerts SET trigger_state = $1, last_evaluated_value = $2, last_triggered_at = $3 WHERE id = $4",
                "triggered", current, now, alert["id"],
            )
            triggered += 1
            logger.info("alert_triggered", symbol=symbol, price=current, threshold=threshold)
        elif cleared and state == "triggered":
            await db.execute(
                "UPDATE alerts SET trigger_state = $1, last_evaluated_value = $2 WHERE id = $3",
                "armed", current, alert["id"],
            )

    return {"evaluated": evaluated, "triggered": triggered, "skipped_no_cache": cache_miss, "at": now.isoformat()}
