"""Async client for a local BasicSwap node's internal JSON API.

Only read endpoints are used (plus an optional unlock). The adapter never
creates offers, bids, or otherwise mutates swap state.
"""

from __future__ import annotations

import base64
import logging
from typing import Any, Optional

import httpx

log = logging.getLogger("orderbook_api.bsx")


class BsxLockedError(RuntimeError):
    """The BasicSwap node reports its wallet is locked."""


class BsxClient:
    def __init__(
        self,
        api_url: str,
        auth: Optional[str] = None,
        timeout: int = 30,
    ) -> None:
        self._api_url = api_url.rstrip("/")
        headers = {}
        if auth:
            token = base64.b64encode(auth.encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {token}"
        # No Origin/Referer header is sent, so BasicSwap's verify-when-present
        # CSRF check treats us as a non-browser client and allows the POST.
        self._client = httpx.AsyncClient(timeout=timeout, headers=headers)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _post_json(self, path: str, body: dict[str, Any]) -> Any:
        url = f"{self._api_url}{path}"
        resp = await self._client.post(url, json=body)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and data.get("locked"):
            raise BsxLockedError(data.get("error", "wallet locked"))
        if isinstance(data, dict) and "error" in data and len(data) == 1:
            raise RuntimeError(f"BasicSwap API error for {path}: {data['error']}")
        return data

    async def _get_json(self, path: str) -> Any:
        url = f"{self._api_url}{path}"
        resp = await self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    async def get_coins(self) -> list[dict[str, Any]]:
        """Return the node's coin table: id, ticker, name, active, decimal_places."""
        return await self._get_json("/json/coins")

    async def get_summary(self) -> dict[str, Any]:
        """Return the node summary (counts, versions, sync state where present)."""
        return await self._get_json("/json")

    async def list_offers_page(
        self, offset: int, limit: int
    ) -> list[dict[str, Any]]:
        """Fetch one page of active public offers across all markets.

        coin_from/coin_to default to -1 (all). Only offers still active and
        unexpired are returned by the node for the un-sent set.
        """
        body = {
            "coin_from": -1,
            "coin_to": -1,
            "offset": offset,
            "limit": limit,
            "sort_by": "created_at",
            "sort_dir": "desc",
            "include_sent": False,
        }
        data = await self._post_json("/json/offers", body)
        if not isinstance(data, list):
            raise RuntimeError(f"Unexpected /json/offers response: {type(data)}")
        return data

    async def list_all_offers(self, page_limit: int) -> list[dict[str, Any]]:
        """Fetch every active offer, paginating until the node returns a short page."""
        all_offers: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = await self.list_offers_page(offset, page_limit)
            all_offers.extend(page)
            if len(page) < page_limit:
                break
            offset += page_limit
            if offset > 1_000_000:  # hard safety stop
                log.warning("Offer pagination exceeded safety limit; truncating")
                break
        return all_offers

    async def try_unlock(self, password: str) -> bool:
        """Best-effort wallet unlock. Returns True if the call succeeded."""
        try:
            await self._post_json("/json/unlock", {"password": password})
            log.info("Wallet unlock request accepted by node")
            return True
        except Exception as e:  # noqa: BLE001 - best effort
            log.warning("Wallet unlock attempt failed: %s", e)
            return False
