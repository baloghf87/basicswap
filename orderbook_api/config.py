"""Runtime configuration, sourced from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


def _get_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _get_int(name: str, default: int) -> int:
    v = os.environ.get(name)
    if v is None or v.strip() == "":
        return default
    try:
        return int(v)
    except ValueError:
        return default


# Canonical quote-currency preference. When an offer's pair is (A, B), the coin
# that appears earliest in this list becomes the QUOTE currency of the canonical
# market and the other becomes the BASE. Price is always expressed as
# quote-per-base. Tickers not listed here rank after all listed ones, then
# alphabetically, so the mapping is fully deterministic for any coin set.
DEFAULT_QUOTE_PREFERENCE = [
    "BTC",
    "LTC",
    "PART",
    "XMR",
    "BCH",
    "DASH",
    "DOGE",
    "FIRO",
    "PIVX",
    "DCR",
    "NMC",
    "WOW",
    "NAV",
]


@dataclass
class Config:
    # Upstream BasicSwap node (its internal JSON API + WebSocket).
    bsx_api_url: str = field(
        default_factory=lambda: os.environ.get(
            "BSX_API_URL", "http://127.0.0.1:12700"
        ).rstrip("/")
    )
    bsx_ws_url: str = field(
        default_factory=lambda: os.environ.get("BSX_WS_URL", "ws://127.0.0.1:11700")
    )
    # Optional HTTP basic-auth credentials for the BasicSwap API, "user:password".
    # Only needed if the node was prepared with client_auth_hash set.
    bsx_api_auth: Optional[str] = field(
        default_factory=lambda: os.environ.get("BSX_API_AUTH") or None
    )
    # Optional wallet password. If set, the adapter will POST /json/unlock when it
    # detects the node is locked (the PART wallet must be unlocked to read offers).
    bsx_unlock_password: Optional[str] = field(
        default_factory=lambda: os.environ.get("BSX_UNLOCK_PASSWORD") or None
    )

    # This adapter's own listener.
    host: str = field(default_factory=lambda: os.environ.get("ADAPTER_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: _get_int("ADAPTER_PORT", 8080))

    # How often to do a full re-fetch of the order book, in seconds. WebSocket
    # events trigger refreshes too; this is the safety-net poll.
    poll_interval_seconds: int = field(
        default_factory=lambda: _get_int("POLL_INTERVAL_SECONDS", 30)
    )
    # Minimum seconds between refreshes, to debounce bursts of WS events.
    min_refresh_interval_seconds: int = field(
        default_factory=lambda: _get_int("MIN_REFRESH_INTERVAL_SECONDS", 2)
    )
    # Page size when fetching offers from the BasicSwap API.
    offer_page_limit: int = field(
        default_factory=lambda: _get_int("OFFER_PAGE_LIMIT", 1000)
    )
    # HTTP request timeout to the BasicSwap API, seconds.
    http_timeout_seconds: int = field(
        default_factory=lambda: _get_int("HTTP_TIMEOUT_SECONDS", 30)
    )

    log_level: str = field(
        default_factory=lambda: os.environ.get("LOG_LEVEL", "INFO").upper()
    )

    def quote_preference(self) -> list[str]:
        override = os.environ.get("QUOTE_PREFERENCE")
        if override:
            return [t.strip().upper() for t in override.split(",") if t.strip()]
        return list(DEFAULT_QUOTE_PREFERENCE)


config = Config()
