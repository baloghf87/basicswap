"""Canonical market mapping and offer normalization.

BasicSwap offers are one-directional swap intents: the maker gives `coin_from`
and wants `coin_to`, at `rate` = amount of coin_to per 1 unit of coin_from.

To present a conventional two-sided order book we fold both directions of a
coin pair into a single canonical market BASE/QUOTE and classify each offer as
a bid or an ask, with price always expressed as quote-per-base:

  * offer coin_from=BASE, coin_to=QUOTE  -> ASK (maker sells BASE for QUOTE)
  * offer coin_from=QUOTE, coin_to=BASE  -> BID (maker buys BASE with QUOTE)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

log = logging.getLogger("orderbook_api.markets")

# Fallback name->ticker map, used only if /json/coins is unavailable. Keys are
# the display names BasicSwap emits for coin_from/coin_to.
FALLBACK_NAME_TICKER = {
    "Particl": "PART",
    "Particl Blind": "PART",
    "Particl Anon": "PART",
    "Bitcoin": "BTC",
    "Litecoin": "LTC",
    "Litecoin MWEB": "LTC",
    "Monero": "XMR",
    "Wownero": "WOW",
    "Dash": "DASH",
    "Firo": "FIRO",
    "PIVX": "PIVX",
    "Decred": "DCR",
    "Namecoin": "NMC",
    "Navcoin": "NAV",
    "Bitcoin Cash": "BCH",
    "Dogecoin": "DOGE",
}


class CoinRegistry:
    """Maps coin display names to tickers/decimals, from the node's coin table."""

    def __init__(self) -> None:
        self._name_to_ticker: dict[str, str] = dict(FALLBACK_NAME_TICKER)

    def load(self, coins: list[dict[str, Any]]) -> None:
        for c in coins:
            name = c.get("name")
            ticker = c.get("ticker")
            if name and ticker:
                self._name_to_ticker[name] = ticker.upper()
        log.info("Coin registry loaded: %d names", len(self._name_to_ticker))

    def ticker(self, coin_name: str) -> str:
        # Fall back to the name itself (upper-cased) if unknown, so a new coin
        # still produces a stable, if unpretty, market symbol.
        return self._name_to_ticker.get(coin_name, coin_name.upper())


@dataclass(frozen=True)
class OfferEntry:
    offer_id: str
    market: str  # "BASE/QUOTE"
    base: str
    quote: str
    side: str  # "bid" or "ask"
    price: Decimal  # quote per base
    base_amount: Decimal
    quote_amount: Decimal
    min_base_amount: Decimal
    created_at: int
    expire_at: int
    swap_type: int
    maker_addr: str
    # Raw pair as seen on the wire, for traceability.
    coin_from: str
    coin_to: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "offer_id": self.offer_id,
            "market": self.market,
            "side": self.side,
            "price": _dstr(self.price),
            "base_amount": _dstr(self.base_amount),
            "quote_amount": _dstr(self.quote_amount),
            "min_base_amount": _dstr(self.min_base_amount),
            "created_at": self.created_at,
            "expire_at": self.expire_at,
            "swap_type": self.swap_type,
            "maker_addr": self.maker_addr,
            "coin_from": self.coin_from,
            "coin_to": self.coin_to,
        }


def _dstr(d: Decimal) -> str:
    """Serialize a Decimal without scientific notation or trailing noise."""
    return format(d.normalize(), "f") if d == d.to_integral_value() else format(d, "f")


def _dec(v: Any) -> Optional[Decimal]:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None


def market_rank(ticker: str, quote_preference: list[str]) -> tuple[int, str]:
    """Lower rank == stronger preference to be the QUOTE currency."""
    t = ticker.upper()
    try:
        idx = quote_preference.index(t)
    except ValueError:
        idx = len(quote_preference)
    return (idx, t)


def canonical_pair(
    ticker_a: str, ticker_b: str, quote_preference: list[str]
) -> tuple[str, str]:
    """Return (base, quote) deterministically for an unordered coin pair."""
    ra = market_rank(ticker_a, quote_preference)
    rb = market_rank(ticker_b, quote_preference)
    # The stronger-preference (smaller rank) coin is the quote.
    if ra <= rb:
        return ticker_b, ticker_a  # base, quote
    return ticker_a, ticker_b


def normalize_offer(
    offer: dict[str, Any],
    registry: CoinRegistry,
    quote_preference: list[str],
) -> Optional[OfferEntry]:
    """Convert a raw BasicSwap offer dict into a canonical OfferEntry.

    Returns None if the offer cannot be interpreted (missing/zero amounts, etc).
    """
    try:
        coin_from_name = offer["coin_from"]
        coin_to_name = offer["coin_to"]
        amount_from = _dec(offer.get("amount_from"))
        amount_to = _dec(offer.get("amount_to"))
        offer_id = offer["offer_id"]
    except KeyError:
        return None

    if amount_from is None or amount_to is None:
        return None
    if amount_from <= 0 or amount_to <= 0:
        return None

    t_from = registry.ticker(coin_from_name)
    t_to = registry.ticker(coin_to_name)
    if t_from == t_to:
        return None

    base, quote = canonical_pair(t_from, t_to, quote_preference)
    market = f"{base}/{quote}"

    min_bid_from = _dec(offer.get("min_bid_amount")) or Decimal(0)

    if t_from == base:
        # Maker gives base, wants quote -> ASK. price = quote/base.
        side = "ask"
        price = amount_to / amount_from
        base_amount = amount_from
        quote_amount = amount_to
        min_base_amount = min_bid_from  # min_bid is in coin_from == base
    else:
        # Maker gives quote (coin_from), wants base (coin_to) -> BID.
        side = "bid"
        price = amount_from / amount_to
        base_amount = amount_to
        quote_amount = amount_from
        # min_bid is in coin_from == quote; convert to base at this price.
        min_base_amount = (min_bid_from / price) if price > 0 else Decimal(0)

    return OfferEntry(
        offer_id=offer_id,
        market=market,
        base=base,
        quote=quote,
        side=side,
        price=price,
        base_amount=base_amount,
        quote_amount=quote_amount,
        min_base_amount=min_base_amount,
        created_at=int(offer.get("created_at", 0) or 0),
        expire_at=int(offer.get("expire_at", 0) or 0),
        swap_type=int(offer.get("swap_type", 0) or 0),
        maker_addr=offer.get("addr_from", "") or "",
        coin_from=coin_from_name,
        coin_to=coin_to_name,
    )
