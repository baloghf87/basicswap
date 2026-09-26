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


def test_summary_side_vwaps_and_maker_count():
    from orderbook_api.orderbook import MarketBook

    def offer(oid, give, want, a_from, a_to, addr):
        return normalize_offer(
            {
                "offer_id": oid, "coin_from": give, "coin_to": want,
                "amount_from": a_from, "amount_to": a_to, "min_bid_amount": "0",
                "created_at": 1, "expire_at": 2, "swap_type": 3, "addr_from": addr,
            },
            _registry(), QP,
        )

    book = MarketBook("XMR/BTC", "XMR", "BTC")
    book.add(offer("a1", "Monero", "Bitcoin", "10", "0.05", "m1"))  # ask 10 XMR @ 0.005
    book.add(offer("a2", "Monero", "Bitcoin", "10", "0.07", "m2"))  # ask 10 XMR @ 0.007
    book.add(offer("b1", "Bitcoin", "Monero", "0.004", "1", "m1"))  # bid 1 XMR @ 0.004
    s = book.summary()
    assert Decimal(s["ask_vwap"]) == Decimal("0.006")
    assert Decimal(s["bid_vwap"]) == Decimal("0.004")
    assert s["maker_count"] == 2

    assert MarketBook("PART/BTC", "PART", "BTC").summary()["bid_vwap"] is None


def test_network_signals_and_newest_offer():
    from orderbook_api.orderbook import OrderBook, network_signals

    def offer(oid, created_at):
        return normalize_offer(
            {
                "offer_id": oid, "coin_from": "Monero", "coin_to": "Bitcoin",
                "amount_from": "1", "amount_to": "0.005", "min_bid_amount": "0",
                "created_at": created_at, "expire_at": created_at + 60, "swap_type": 3, "addr_from": "m",
            },
            _registry(), QP,
        )

    assert OrderBook.from_offers([offer("a", 100), offer("b", 250)]).newest_offer_ts == 250
    assert OrderBook.from_offers([]).newest_offer_ts == 0

    signals = network_signals(
        {
            "num_offers_rejected_protocol": 3, "max_rejected_offer_protocol": 11,
            "max_supported_offer_protocol": 10, "num_smsg_messages_received": 42, "particl_peers": 8,
        },
        {"update_available": True, "current_version": "0.18.9", "latest_version": "0.19.0"},
    )
    assert signals == {
        "core_version": "0.18.9", "update_available": True, "latest_version": "0.19.0",
        "offers_rejected_protocol": 3, "max_rejected_offer_protocol": 11,
        "max_supported_offer_protocol": 10, "smsg_messages_received": 42, "particl_peers": 8,
    }
    assert network_signals({}, {})["update_available"] is False
