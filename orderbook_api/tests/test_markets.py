"""Unit tests for market mapping and offer normalization (pure, no network)."""

from decimal import Decimal

from orderbook_api.config import DEFAULT_QUOTE_PREFERENCE
from orderbook_api.markets import (
    CoinRegistry,
    canonical_pair,
    normalize_offer,
)

QP = DEFAULT_QUOTE_PREFERENCE


def _registry():
    r = CoinRegistry()
    r.load(
        [
            {"name": "Bitcoin", "ticker": "BTC"},
            {"name": "Monero", "ticker": "XMR"},
            {"name": "Particl", "ticker": "PART"},
        ]
    )
    return r


def test_canonical_pair_deterministic():
    # BTC is preferred as quote over XMR, regardless of argument order.
    assert canonical_pair("XMR", "BTC", QP) == ("XMR", "BTC")
    assert canonical_pair("BTC", "XMR", QP) == ("XMR", "BTC")


def test_unknown_coins_alphabetical_quote():
    # Neither listed: quote is alphabetically-first ticker, base the other.
    assert canonical_pair("ZZZ", "AAA", QP) == ("ZZZ", "AAA")
    assert canonical_pair("AAA", "ZZZ", QP) == ("ZZZ", "AAA")


def test_ask_side_and_price():
    # Maker gives XMR (base), wants BTC (quote): an ASK on XMR/BTC.
    # 10 XMR for 0.5 BTC -> price 0.05 BTC/XMR.
    offer = {
        "offer_id": "a1",
        "coin_from": "Monero",
        "coin_to": "Bitcoin",
        "amount_from": "10",
        "amount_to": "0.5",
        "min_bid_amount": "1",
        "created_at": 100,
        "expire_at": 200,
        "swap_type": 3,
        "addr_from": "addrX",
    }
    e = normalize_offer(offer, _registry(), QP)
    assert e is not None
    assert e.market == "XMR/BTC"
    assert e.side == "ask"
    assert e.price == Decimal("0.05")
    assert e.base_amount == Decimal("10")
    assert e.quote_amount == Decimal("0.5")
    assert e.min_base_amount == Decimal("1")


def test_bid_side_and_price():
    # Maker gives BTC (quote), wants XMR (base): a BID on XMR/BTC.
    # 0.5 BTC for 10 XMR -> price 0.05 BTC/XMR, base amount 10 XMR.
    offer = {
        "offer_id": "b1",
        "coin_from": "Bitcoin",
        "coin_to": "Monero",
        "amount_from": "0.5",
        "amount_to": "10",
        "min_bid_amount": "0.05",
        "created_at": 100,
        "expire_at": 200,
        "swap_type": 3,
        "addr_from": "addrY",
    }
    e = normalize_offer(offer, _registry(), QP)
    assert e is not None
    assert e.market == "XMR/BTC"
    assert e.side == "bid"
    assert e.price == Decimal("0.05")
    assert e.base_amount == Decimal("10")
    assert e.quote_amount == Decimal("0.5")
    # min_bid 0.05 BTC / 0.05 price = 1 XMR
    assert e.min_base_amount == Decimal("1")


def test_zero_amounts_rejected():
    offer = {
        "offer_id": "z1",
        "coin_from": "Bitcoin",
        "coin_to": "Monero",
        "amount_from": "0",
        "amount_to": "10",
    }
    assert normalize_offer(offer, _registry(), QP) is None


def test_same_coin_rejected():
    offer = {
        "offer_id": "s1",
        "coin_from": "Bitcoin",
        "coin_to": "Bitcoin",
        "amount_from": "1",
        "amount_to": "1",
    }
    assert normalize_offer(offer, _registry(), QP) is None
