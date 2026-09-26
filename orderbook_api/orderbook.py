"""In-memory order-book state and the service that keeps it fresh."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from decimal import Decimal
from typing import Any, Optional

from .bsx_client import BsxClient, BsxLockedError
from .markets import CoinRegistry, OfferEntry, _dstr, normalize_offer

log = logging.getLogger("orderbook_api.orderbook")


def _aggregate_levels(
    offers: list[OfferEntry], side: str
) -> list[dict[str, Any]]:
    """Group same-price offers into price levels."""
    by_price: dict[Decimal, list[OfferEntry]] = defaultdict(list)
    for o in offers:
        by_price[o.price].append(o)
    levels = []
    for price, group in by_price.items():
        base_total = sum((o.base_amount for o in group), Decimal(0))
        quote_total = sum((o.quote_amount for o in group), Decimal(0))
        levels.append(
            {
                "price": _dstr(price),
                "base_amount": _dstr(base_total),
                "quote_amount": _dstr(quote_total),
                "offer_count": len(group),
            }
        )
    # Bids: highest price first. Asks: lowest price first.
    levels.sort(key=lambda lvl: Decimal(lvl["price"]), reverse=(side == "bid"))
    return levels


def _vwap(offers: list[OfferEntry]) -> Optional[str]:
    """Size-weighted (base amount) average price of one book side; None when the side is empty."""
    size = sum((o.base_amount for o in offers), Decimal(0))
    if size <= 0:
        return None
    return _dstr(sum((o.price * o.base_amount for o in offers), Decimal(0)) / size)


class MarketBook:
    def __init__(self, market: str, base: str, quote: str) -> None:
        self.market = market
        self.base = base
        self.quote = quote
        self.bids: list[OfferEntry] = []
        self.asks: list[OfferEntry] = []

    def add(self, entry: OfferEntry) -> None:
        (self.bids if entry.side == "bid" else self.asks).append(entry)

    def _best_bid(self) -> Optional[Decimal]:
        return max((o.price for o in self.bids), default=None)

    def _best_ask(self) -> Optional[Decimal]:
        return min((o.price for o in self.asks), default=None)

    def summary(self) -> dict[str, Any]:
        best_bid = self._best_bid()
        best_ask = self._best_ask()
        mid = None
        spread = None
        spread_pct = None
        if best_bid is not None and best_ask is not None:
            mid = (best_bid + best_ask) / 2
            spread = best_ask - best_bid
            if mid > 0:
                spread_pct = ((spread / mid) * 100).quantize(Decimal("0.0001"))
        return {
            "market": self.market,
            "base": self.base,
            "quote": self.quote,
            "best_bid": _dstr(best_bid) if best_bid is not None else None,
            "best_ask": _dstr(best_ask) if best_ask is not None else None,
            "mid": _dstr(mid) if mid is not None else None,
            "spread": _dstr(spread) if spread is not None else None,
            "spread_pct": _dstr(spread_pct) if spread_pct is not None else None,
            "bid_count": len(self.bids),
            "ask_count": len(self.asks),
            "total_bid_base": _dstr(sum((o.base_amount for o in self.bids), Decimal(0))),
            "total_ask_base": _dstr(sum((o.base_amount for o in self.asks), Decimal(0))),
            "bid_vwap": _vwap(self.bids),
            "ask_vwap": _vwap(self.asks),
            "maker_count": len({o.maker_addr for o in self.bids + self.asks if o.maker_addr}),
        }

    def to_dict(self, depth: Optional[int] = None) -> dict[str, Any]:
        bids = _aggregate_levels(self.bids, "bid")
        asks = _aggregate_levels(self.asks, "ask")
        if depth is not None and depth > 0:
            bids = bids[:depth]
            asks = asks[:depth]
        d = self.summary()
        d["bids"] = bids
        d["asks"] = asks
        return d


class OrderBook:
    """Snapshot of all markets. Rebuilt atomically on each refresh."""

    def __init__(self) -> None:
        self.markets: dict[str, MarketBook] = {}
        self.offer_count: int = 0
        self.newest_offer_ts: int = 0

    @classmethod
    def from_offers(cls, entries: list[OfferEntry]) -> "OrderBook":
        ob = cls()
        for e in entries:
            mb = ob.markets.get(e.market)
            if mb is None:
                mb = MarketBook(e.market, e.base, e.quote)
                ob.markets[e.market] = mb
            mb.add(e)
            ob.newest_offer_ts = max(ob.newest_offer_ts, e.created_at)
        ob.offer_count = len(entries)
        return ob

    def market_summaries(self) -> list[dict[str, Any]]:
        return [self.markets[m].summary() for m in sorted(self.markets)]


def network_signals(summary: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    """The node's "is this build still accepted / still connected?" signals for ``/v1/status``.

    ``offers_rejected_protocol`` counts offers the core dropped for a protocol version it cannot
    handle; ``update_available``/``latest_version`` come from BasicSwap's GitHub release check
    (``latest_version`` is only set while an update is available).
    """
    return {
        "core_version": updates.get("current_version"),
        "update_available": bool(updates.get("update_available")),
        "latest_version": updates.get("latest_version"),
        "offers_rejected_protocol": summary.get("num_offers_rejected_protocol"),
        "max_rejected_offer_protocol": summary.get("max_rejected_offer_protocol"),
        "max_supported_offer_protocol": summary.get("max_supported_offer_protocol"),
        "smsg_messages_received": summary.get("num_smsg_messages_received"),
        "particl_peers": summary.get("particl_peers"),
    }


class OrderBookService:
    """Owns the BasicSwap client, the current OrderBook, and the refresh loop."""

    def __init__(self, config) -> None:
        self.config = config
        self.client = BsxClient(
            config.bsx_api_url,
            auth=config.bsx_api_auth,
            timeout=config.http_timeout_seconds,
        )
        self.registry = CoinRegistry()
        self.book = OrderBook()
        self._lock = asyncio.Lock()
        self._refresh_event = asyncio.Event()
        self._subscribers: set[asyncio.Queue] = set()

        # Observability / readiness state.
        self.last_refresh_ts: float = 0.0
        self.last_refresh_ok: bool = False
        self.last_error: Optional[str] = None
        self.locked: bool = False
        self._registry_loaded = False
        # Network signals from the node (/json summary + /json/updatestatus), best effort.
        self.network: dict[str, Any] = {}

    # -- subscriber management (for the WebSocket fan-out) ------------------
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=8)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def _broadcast(self, message: dict[str, Any]) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                # Slow consumer: drop the oldest, keep the newest.
                try:
                    q.get_nowait()
                    q.put_nowait(message)
                except Exception:  # noqa: BLE001
                    pass

    # -- refresh -----------------------------------------------------------
    def request_refresh(self) -> None:
        """Signal the refresh loop to re-fetch soon (used by the WS consumer)."""
        self._refresh_event.set()

    async def _ensure_registry(self) -> None:
        if self._registry_loaded:
            return
        try:
            coins = await self.client.get_coins()
            self.registry.load(coins)
            self._registry_loaded = True
        except Exception as e:  # noqa: BLE001
            log.warning("Could not load coin registry (using fallback): %s", e)

    async def _refresh_network(self) -> None:
        """Pull the node's network signals; a failure here never fails the book refresh."""
        try:
            summary = await self.client.get_summary()
            updates = await self.client.get_update_status()
            self.network = network_signals(summary, updates)
        except Exception as e:  # noqa: BLE001
            log.warning("Could not read the node's network signals: %s", e)

    async def refresh(self) -> bool:
        """Re-fetch all offers and rebuild the book. Returns True on success."""
        async with self._lock:
            try:
                await self._ensure_registry()
                raw = await self.client.list_all_offers(self.config.offer_page_limit)
                entries: list[OfferEntry] = []
                for o in raw:
                    if o.get("is_expired") or o.get("is_revoked"):
                        continue
                    if o.get("is_own_offer"):
                        continue
                    entry = normalize_offer(
                        o, self.registry, self.config.quote_preference()
                    )
                    if entry is not None:
                        entries.append(entry)
                self.book = OrderBook.from_offers(entries)
                await self._refresh_network()
                self.last_refresh_ts = time.time()
                self.last_refresh_ok = True
                self.last_error = None
                self.locked = False
                log.info(
                    "Order book refreshed: %d offers, %d markets",
                    self.book.offer_count,
                    len(self.book.markets),
                )
                self._broadcast(
                    {
                        "type": "update",
                        "ts": self.last_refresh_ts,
                        "markets": self.book.market_summaries(),
                    }
                )
                return True
            except BsxLockedError as e:
                self.locked = True
                self.last_error = str(e)
                self.last_refresh_ok = False
                log.warning("Node locked: %s", e)
                if self.config.bsx_unlock_password:
                    await self.client.try_unlock(self.config.bsx_unlock_password)
                return False
            except Exception as e:  # noqa: BLE001
                self.last_error = str(e)
                self.last_refresh_ok = False
                log.warning("Refresh failed: %s", e)
                return False

    async def run_forever(self) -> None:
        """Background loop: refresh on interval or when signalled by WS events."""
        while True:
            await self.refresh()
            try:
                await asyncio.wait_for(
                    self._refresh_event.wait(),
                    timeout=self.config.poll_interval_seconds,
                )
            except asyncio.TimeoutError:
                pass
            self._refresh_event.clear()
            # Debounce bursts of WS-triggered refreshes.
            await asyncio.sleep(self.config.min_refresh_interval_seconds)

    async def aclose(self) -> None:
        await self.client.aclose()

    # -- read helpers for the API -----------------------------------------
    def is_ready(self) -> bool:
        return self.last_refresh_ok

    def status(self) -> dict[str, Any]:
        age = (time.time() - self.last_refresh_ts) if self.last_refresh_ts else None
        return {
            "ready": self.is_ready(),
            "node_locked": self.locked,
            "last_refresh_ts": self.last_refresh_ts or None,
            "last_refresh_age_seconds": round(age, 1) if age is not None else None,
            "last_error": self.last_error,
            "offer_count": self.book.offer_count,
            "market_count": len(self.book.markets),
            "poll_interval_seconds": self.config.poll_interval_seconds,
            "newest_offer_age_seconds": (
                round(time.time() - self.book.newest_offer_ts, 1)
                if self.book.newest_offer_ts
                else None
            ),
            **self.network,
        }
