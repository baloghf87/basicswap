"""Consumes the BasicSwap node's WebSocket to trigger low-latency refreshes.

BasicSwap's WebSocket is push-only and its offer events (new_offer,
offer_revoked, offer_expired, offer_created) carry only partial data, so we
use them purely as invalidation signals and re-fetch /json/offers. If the
WebSocket is unavailable, the service still stays fresh via interval polling.
"""

from __future__ import annotations

import asyncio
import json
import logging

import websockets

log = logging.getLogger("orderbook_api.ws")

# Events that mean the order book may have changed.
REFRESH_EVENTS = {
    "new_offer",
    "offer_created",
    "offer_revoked",
    "offer_expired",
}


async def run_ws_consumer(ws_url: str, service) -> None:
    backoff = 1
    while True:
        try:
            async with websockets.connect(
                ws_url, ping_interval=30, open_timeout=10
            ) as ws:
                log.info("Connected to BasicSwap WebSocket at %s", ws_url)
                backoff = 1
                async for raw in ws:
                    _handle_message(raw, service)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning(
                "BasicSwap WebSocket disconnected (%s); retrying in %ds. "
                "Interval polling continues meanwhile.",
                e,
                backoff,
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)


def _handle_message(raw, service) -> None:
    try:
        msg = json.loads(raw)
    except (ValueError, TypeError):
        return
    event = msg.get("event") if isinstance(msg, dict) else None
    if event in REFRESH_EVENTS:
        service.request_refresh()
