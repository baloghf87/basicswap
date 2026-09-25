"""Public REST + WebSocket API for the BasicSwap order book.

This is the interface downstream consumers use. See docs/ORDERBOOK_API.md for
the full contract. The OpenAPI schema is served at /openapi.json and Swagger UI
at /docs.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from . import __version__
from .config import config
from .orderbook import OrderBookService
from .ws_consumer import run_ws_consumer

logging.basicConfig(
    level=getattr(logging, config.log_level, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("orderbook_api.server")

service = OrderBookService(config)
_tasks: list[asyncio.Task] = []


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    _tasks.append(asyncio.create_task(service.run_forever(), name="refresh-loop"))
    _tasks.append(
        asyncio.create_task(
            run_ws_consumer(config.bsx_ws_url, service), name="ws-consumer"
        )
    )
    log.info("orderbook_api %s started; upstream=%s", __version__, config.bsx_api_url)
    try:
        yield
    finally:
        for t in _tasks:
            t.cancel()
        for t in _tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        await service.aclose()


app = FastAPI(
    title="BasicSwap Order Book API",
    version=__version__,
    description=(
        "Read-only snapshot of the BasicSwap decentralized order book. "
        "Exposes liquidity (bids/asks) per market plus per-market summary "
        "statistics. A network-wide trades tape / candlestick feed is not "
        "available (see /v1/trades/{market})."
    ),
    lifespan=lifespan,
)


# -- health / readiness ----------------------------------------------------
@app.get("/health", tags=["ops"], summary="Liveness probe")
async def health():
    return {"status": "ok", "version": __version__}


@app.get("/ready", tags=["ops"], summary="Readiness probe")
async def ready():
    if service.is_ready():
        return {"status": "ready"}
    return JSONResponse(
        status_code=503,
        content={"status": "not_ready", "detail": service.status()},
    )


@app.get("/v1/status", tags=["ops"], summary="Adapter and upstream node status")
async def status():
    return service.status()


# -- markets & order book --------------------------------------------------
@app.get("/v1/markets", tags=["orderbook"], summary="List markets with summaries")
async def markets():
    return {
        "ts": service.last_refresh_ts or None,
        "markets": service.book.market_summaries(),
    }


@app.get(
    "/v1/orderbook",
    tags=["orderbook"],
    summary="Summaries for every market (no depth)",
)
async def orderbook_all():
    return {
        "ts": service.last_refresh_ts or None,
        "markets": service.book.market_summaries(),
    }


@app.get(
    "/v1/orderbook/{base}/{quote}",
    tags=["orderbook"],
    summary="Aggregated order book for one market",
)
async def orderbook_market(
    base: str,
    quote: str,
    depth: Optional[int] = Query(
        default=None, ge=1, description="Limit price levels per side"
    ),
):
    market = f"{base.upper()}/{quote.upper()}"
    mb = service.book.markets.get(market)
    if mb is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown or empty market '{market}'. See /v1/markets.",
        )
    return {"ts": service.last_refresh_ts or None, **mb.to_dict(depth=depth)}


@app.get("/v1/offers", tags=["orderbook"], summary="Raw normalized offers")
async def offers(
    market: Optional[str] = Query(default=None, description="Filter, e.g. XMR/BTC"),
    side: Optional[str] = Query(default=None, pattern="^(bid|ask)$"),
):
    want_market = market.upper() if market else None
    out = []
    for m, mb in service.book.markets.items():
        if want_market and m != want_market:
            continue
        for entry in mb.bids + mb.asks:
            if side and entry.side != side:
                continue
            out.append(entry.to_dict())
    return {"ts": service.last_refresh_ts or None, "count": len(out), "offers": out}


# -- trades (explicitly unavailable) --------------------------------------
@app.get(
    "/v1/trades/{base}/{quote}",
    tags=["trades"],
    summary="Executed trades (NOT AVAILABLE)",
    description=(
        "A network-wide trades tape / candlestick feed cannot be provided. "
        "BasicSwap bids and swap execution are point-to-point and encrypted "
        "between maker and taker; a passive observing node never sees swaps it "
        "did not participate in. This endpoint always reports unsupported so "
        "downstream consumers get a clear machine-readable signal."
    ),
)
async def trades(base: str, quote: str):
    return JSONResponse(
        status_code=501,
        content={
            "supported": False,
            "market": f"{base.upper()}/{quote.upper()}",
            "trades": [],
            "reason": (
                "Executed trades are not observable by a passive BasicSwap node. "
                "Bids/swaps are private point-to-point messages. Use /v1/orderbook "
                "for live liquidity and mid-price instead."
            ),
        },
    )


# -- websocket stream ------------------------------------------------------
@app.websocket("/v1/ws")
async def ws_stream(ws: WebSocket):
    await ws.accept()
    queue = service.subscribe()
    try:
        # Send an initial snapshot on connect.
        await ws.send_json(
            {
                "type": "snapshot",
                "ts": service.last_refresh_ts or None,
                "markets": service.book.market_summaries(),
            }
        )
        while True:
            message = await queue.get()
            await ws.send_json(message)
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001
        log.debug("WebSocket client error: %s", e)
    finally:
        service.unsubscribe(queue)
