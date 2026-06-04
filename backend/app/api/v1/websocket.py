"""
WebSocket endpoint for real-time price streaming.

Features:
- Endpoint: /ws/prices
- Client subscribes to symbols via JSON messages
- Server polls Yahoo Finance every 5 seconds for subscribed symbols
- Pushes price updates as JSON
- Heartbeat ping every 30 seconds
- Max 10 symbols per connection
- Graceful disconnect handling

Protocol:
  Client -> Server:
    {"action": "subscribe", "symbols": ["RELIANCE.NS", "TCS.NS"]}
    {"action": "unsubscribe", "symbols": ["TCS.NS"]}
    {"action": "ping"}

  Server -> Client:
    {"type": "price_update", "symbol": "RELIANCE.NS", "data": {...}}
    {"type": "subscribed", "symbols": ["RELIANCE.NS", "TCS.NS"]}
    {"type": "unsubscribed", "symbols": ["TCS.NS"]}
    {"type": "pong", "timestamp": "..."}
    {"type": "error", "message": "..."}
    {"type": "heartbeat", "timestamp": "..."}
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.config import get_settings
from app.core.logging import get_logger
from app.data.adapters.yahoo import YahooFinanceAdapter

logger = get_logger(__name__)

router = APIRouter()

# Shared adapter instance for all WebSocket connections
_adapter = YahooFinanceAdapter()

# ── Constants ──────────────────────────────────────────────────────
MAX_SYMBOLS_PER_CONNECTION = 10
POLL_INTERVAL_SECONDS = 5


async def _safe_send_json(ws: WebSocket, data: Dict[str, Any]) -> bool:
    """Send JSON to the WebSocket client, returning False if the connection is closed."""
    try:
        if ws.client_state == WebSocketState.CONNECTED:
            await ws.send_json(data)
            return True
    except Exception:
        pass
    return False


async def _price_poller(
    ws: WebSocket,
    subscribed: Set[str],
    stop_event: asyncio.Event,
) -> None:
    """
    Background task: poll Yahoo Finance for subscribed symbols every 5 seconds.

    Runs until stop_event is set (on disconnect).
    """
    while not stop_event.is_set():
        if subscribed:
            # Copy the set to avoid mutation during iteration
            symbols = list(subscribed)
            for symbol in symbols:
                if stop_event.is_set():
                    return
                try:
                    quote = await _adapter.get_quote(symbol)
                    if quote:
                        # Convert datetime to ISO string for JSON serialization
                        if isinstance(quote.get("timestamp"), datetime):
                            quote["timestamp"] = quote["timestamp"].isoformat()
                        sent = await _safe_send_json(ws, {
                            "type": "price_update",
                            "symbol": symbol,
                            "data": quote,
                        })
                        if not sent:
                            return
                except Exception as e:
                    logger.warning(
                        "ws_price_fetch_failed",
                        symbol=symbol,
                        error=str(e),
                    )

        # Wait for the poll interval, but break early if stopped
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=POLL_INTERVAL_SECONDS)
            return  # stop_event was set
        except asyncio.TimeoutError:
            pass  # Normal — just loop again


async def _heartbeat_sender(
    ws: WebSocket,
    stop_event: asyncio.Event,
) -> None:
    """
    Background task: send heartbeat pings at the configured interval.

    Keeps the WebSocket alive and lets the client detect stale connections.
    """
    settings = get_settings()
    interval = settings.ws_heartbeat_interval

    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            return  # stop_event was set
        except asyncio.TimeoutError:
            pass  # Normal — time to send heartbeat

        sent = await _safe_send_json(ws, {
            "type": "heartbeat",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        if not sent:
            return


@router.websocket("/ws/prices")
async def price_stream(ws: WebSocket) -> None:
    """
    WebSocket endpoint for real-time price streaming.

    Clients subscribe to symbols and receive continuous price updates
    polled from Yahoo Finance.
    """
    await ws.accept()

    # Track connection in metrics (import lazily to avoid circular imports)
    try:
        from app.engines.observability.metrics import metrics_collector
        metrics_collector.record_ws_connection(delta=1)
    except ImportError:
        pass

    client_host = ws.client.host if ws.client else "unknown"
    logger.info("ws_connected", client=client_host)

    subscribed: Set[str] = set()
    stop_event = asyncio.Event()

    # Start background tasks
    poller_task = asyncio.create_task(_price_poller(ws, subscribed, stop_event))
    heartbeat_task = asyncio.create_task(_heartbeat_sender(ws, stop_event))

    try:
        while True:
            raw = await ws.receive_json()
            action = raw.get("action", "").lower()

            if action == "subscribe":
                symbols = raw.get("symbols", [])
                if not isinstance(symbols, list):
                    await _safe_send_json(ws, {
                        "type": "error",
                        "message": "'symbols' must be a list",
                    })
                    continue

                # Enforce max symbols limit
                new_symbols = {s.upper() for s in symbols if isinstance(s, str)}
                if len(subscribed | new_symbols) > MAX_SYMBOLS_PER_CONNECTION:
                    await _safe_send_json(ws, {
                        "type": "error",
                        "message": f"Max {MAX_SYMBOLS_PER_CONNECTION} symbols per connection",
                    })
                    continue

                subscribed.update(new_symbols)
                logger.info(
                    "ws_subscribed",
                    client=client_host,
                    symbols=list(new_symbols),
                    total=len(subscribed),
                )
                await _safe_send_json(ws, {
                    "type": "subscribed",
                    "symbols": sorted(subscribed),
                })

            elif action == "unsubscribe":
                symbols = raw.get("symbols", [])
                remove = {s.upper() for s in symbols if isinstance(s, str)}
                subscribed -= remove
                logger.info(
                    "ws_unsubscribed",
                    client=client_host,
                    symbols=list(remove),
                    remaining=len(subscribed),
                )
                await _safe_send_json(ws, {
                    "type": "unsubscribed",
                    "symbols": sorted(remove),
                })

            elif action == "ping":
                await _safe_send_json(ws, {
                    "type": "pong",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

            else:
                await _safe_send_json(ws, {
                    "type": "error",
                    "message": f"Unknown action: {action}. Use 'subscribe', 'unsubscribe', or 'ping'.",
                })

    except WebSocketDisconnect:
        logger.info("ws_disconnected", client=client_host, reason="client_disconnect")
    except Exception as e:
        logger.error("ws_error", client=client_host, error=str(e))
    finally:
        # Signal background tasks to stop
        stop_event.set()

        # Wait for background tasks to finish
        for task in [poller_task, heartbeat_task]:
            try:
                await asyncio.wait_for(task, timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                task.cancel()

        # Update metrics
        try:
            from app.engines.observability.metrics import metrics_collector
            metrics_collector.record_ws_connection(delta=-1)
        except ImportError:
            pass

        logger.info("ws_cleanup_complete", client=client_host)
