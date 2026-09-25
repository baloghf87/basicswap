# BasicSwap Order Book API

Version: 0.1.0 · Status: draft for handover

A read-only HTTP + WebSocket API that exposes a **current snapshot of the
BasicSwap decentralized order book** (liquidity per market) plus per-market
summary statistics, derived from a listen-only BasicSwap node.

This document is the contract for downstream consumers and implementers. It is
self-contained: an agent or developer can build a client, a dashboard, or a
data pipeline against it without reading the adapter source.

---

## 1. What this API does and does not provide

**Provides**
- The live set of open swap **offers** across every market, folded into a
  conventional two-sided order book (bids/asks) per canonical market.
- Per-market **summary stats**: best bid, best ask, mid price, spread.
- A **WebSocket** stream that pushes updated market summaries as the book changes.

**Does NOT provide**
- **Executed trades, a trades tape, or candlesticks.** This is a hard property
  of the BasicSwap network, not a roadmap gap: bids and swap execution are
  point-to-point, encrypted between maker and taker, and never broadcast. A
  passive observing node cannot see any swap it did not participate in. The
  `/v1/trades/{base}/{quote}` endpoint therefore always returns HTTP `501` with
  `supported: false`.
- **Historical order-book data.** Only the current snapshot is served. A
  freshly started node's book fills in over the first minutes as offers arrive.

For the full rationale see `FEASIBILITY_orderbook_api.md` at the repo root.

---

## 2. Data model and conventions

### Markets

BasicSwap offers are one-directional (a maker gives `coin_from` and wants
`coin_to`). Both directions of a coin pair are folded into one **canonical
market** written `BASE/QUOTE` (e.g. `XMR/BTC`). The **quote** currency is chosen
deterministically from a fixed preference order (default, strongest first):

```
BTC, LTC, PART, XMR, BCH, DASH, DOGE, FIRO, PIVX, DCR, NMC, WOW, NAV
```

The coin ranked earlier becomes the **quote**; the other becomes the **base**.
Coins not in the list rank last, then alphabetically — so the mapping is stable
for any coin set. The order is configurable via the `QUOTE_PREFERENCE` env var.

- An offer `coin_from = BASE, coin_to = QUOTE` → an **ask** (maker sells base).
- An offer `coin_from = QUOTE, coin_to = BASE` → a **bid** (maker buys base).

### Prices and amounts

- **All prices are quote-per-base** (e.g. for `XMR/BTC`, price is in BTC per XMR).
- **All amounts and prices are decimal strings**, not floats — preserve them as
  arbitrary-precision decimals. Do not parse into binary floating point if you
  care about exactness.
- `base_amount` is denominated in the base coin; `quote_amount` in the quote coin.
- Timestamps (`created_at`, `expire_at`, `ts`) are **Unix seconds** (integers).

### Offer filtering

The adapter already excludes expired, revoked, and the node's own offers. Every
offer returned is a genuine, currently-open counterparty offer on the network.

> **Trust note.** The BasicSwap order book is permissionless: anyone can post
> offers, including spam or unfillable ones. Each offer exposes `maker_addr` and
> its amounts/expiry so consumers can apply their own filtering.

---

## 3. Base URL and versioning

All application endpoints are under `/v1`. Operational endpoints (`/health`,
`/ready`) are unversioned. An OpenAPI 3 schema is served at **`/openapi.json`**
and interactive Swagger UI at **`/docs`** — use these for exact schemas and for
client generation.

Default listen address: `0.0.0.0:8080` (in k8s, reached via the
`orderbook-api` Service on port 80).

No authentication is applied by the adapter itself; run it behind your cluster's
ingress/authz. It is strictly read-only and mutates no swap state.

---

## 4. REST endpoints

### `GET /health` — liveness
Always `200` once the process is up.
```json
{ "status": "ok", "version": "0.1.0" }
```

### `GET /ready` — readiness
`200` once the order book has been successfully fetched at least once (node up
and PART wallet unlocked); otherwise `503` with a `detail` status object. Use
for the Kubernetes readiness probe.

### `GET /v1/status` — adapter + upstream status
```json
{
  "ready": true,
  "node_locked": false,
  "last_refresh_ts": 1790330883.1,
  "last_refresh_age_seconds": 4.2,
  "last_error": null,
  "offer_count": 128,
  "market_count": 9,
  "poll_interval_seconds": 30
}
```
- `node_locked` — true if the node's PART wallet is locked (offers unreadable).
  Set `BSX_UNLOCK_PASSWORD` so the adapter auto-unlocks.
- `last_error` — last refresh error string, or null.

### `GET /v1/markets` — all markets with summaries
Alias of `GET /v1/orderbook`. Returns a summary per market (no depth ladder).
```json
{
  "ts": 1790330883.1,
  "markets": [
    {
      "market": "XMR/BTC", "base": "XMR", "quote": "BTC",
      "best_bid": "0.04", "best_ask": "0.05", "mid": "0.045",
      "spread": "0.01", "spread_pct": "22.2222",
      "bid_count": 1, "ask_count": 1,
      "total_bid_base": "10", "total_ask_base": "10",
      "bid_vwap": "0.04", "ask_vwap": "0.05", "maker_count": 2
    }
  ]
}
```
Any of `best_bid`, `best_ask`, `mid`, `spread`, `spread_pct`, `bid_vwap`, `ask_vwap` may be `null`
when that side of the market is empty. `bid_vwap`/`ask_vwap` are the base-amount-weighted average
prices of each side; `maker_count` is the number of distinct maker addresses with an offer in the market.

### `GET /v1/orderbook` — all markets with summaries
Same shape as `/v1/markets`.

### `GET /v1/orderbook/{base}/{quote}` — one market, aggregated
Path is case-insensitive, e.g. `/v1/orderbook/XMR/BTC`.

Query params:
| Param  | Type | Description |
|--------|------|-------------|
| `depth`| int  | Optional. Max price levels returned per side (top of book first). |

`404` if the market is unknown or currently empty (see `/v1/markets` for the
live list). Response = the market summary plus aggregated `bids`/`asks` ladders:
```json
{
  "ts": 1790330883.1,
  "market": "XMR/BTC", "base": "XMR", "quote": "BTC",
  "best_bid": "0.04", "best_ask": "0.05", "mid": "0.045",
  "spread": "0.01", "spread_pct": "22.2222",
  "bid_count": 1, "ask_count": 1,
  "total_bid_base": "10", "total_ask_base": "10",
  "bids": [ { "price": "0.04", "base_amount": "10", "quote_amount": "0.4", "offer_count": 1 } ],
  "asks": [ { "price": "0.05", "base_amount": "10", "quote_amount": "0.5", "offer_count": 1 } ]
}
```
- `bids` are sorted **highest price first**; `asks` **lowest price first**.
- Each level aggregates all offers at that exact price: `base_amount` and
  `quote_amount` are summed, `offer_count` is how many offers back the level.

### `GET /v1/offers` — raw normalized offers
Every open offer as an individual, canonicalized record (not aggregated).

Query params:
| Param    | Type   | Description |
|----------|--------|-------------|
| `market` | string | Optional, e.g. `XMR/BTC`. Filter to one market. |
| `side`   | string | Optional, `bid` or `ask`. |

```json
{
  "ts": 1790330883.1,
  "count": 2,
  "offers": [
    {
      "offer_id": "aa", "market": "XMR/BTC", "side": "ask",
      "price": "0.05", "base_amount": "10", "quote_amount": "0.5",
      "min_base_amount": "1",
      "created_at": 1, "expire_at": 9999999999,
      "swap_type": 3, "maker_addr": "Pp...",
      "coin_from": "Monero", "coin_to": "Bitcoin"
    }
  ]
}
```
- `offer_id` — the BasicSwap offer id (hex); stable identifier for an offer.
- `min_base_amount` — minimum takeable size, expressed in base units.
- `swap_type` — BasicSwap swap protocol id (e.g. 3 = adaptor-sig/XMR-style). For
  display/filtering only.
- `coin_from`/`coin_to` — the raw wire direction, for traceability.

### `GET /v1/trades/{base}/{quote}` — NOT AVAILABLE
Always returns HTTP `501`:
```json
{
  "supported": false,
  "market": "XMR/BTC",
  "trades": [],
  "reason": "Executed trades are not observable by a passive BasicSwap node. ..."
}
```
This endpoint exists so consumers get a clear, machine-readable signal rather
than a `404`. Do not poll it expecting data.

---

## 5. WebSocket stream

### `GET /v1/ws`
On connect the server sends one `snapshot` message, then an `update` message on
every order-book refresh (interval poll or a change signalled by the node).

Initial message:
```json
{ "type": "snapshot", "ts": 1790330883.1, "markets": [ /* summaries, as in /v1/markets */ ] }
```
Subsequent messages:
```json
{ "type": "update", "ts": 1790330890.7, "markets": [ /* summaries */ ] }
```
- Messages carry **market summaries only** (best bid/ask, mid, counts). Fetch
  `GET /v1/orderbook/{base}/{quote}` for the full ladder of a market you care
  about — treat `update` as an invalidation/refresh signal.
- The server drops stale messages for slow consumers (keeps only the newest), so
  never assume you received every intermediate update; the latest is authoritative.
- The stream is push-only; the server ignores anything the client sends.

---

## 6. Deployment (summary)

The API is delivered as a single container image that runs a listen-only
BasicSwap node (Particl only) plus this adapter. See `orderbook_api/Dockerfile`,
`orderbook_api/run-node-and-adapter.sh`, and `deploy/k8s/orderbook-api.yaml`, and
the operator guide in `orderbook_api/README.md`.

Key operational notes for a consumer/operator:
- First boot syncs the full Particl chain; the book is incomplete until sync
  progresses. Gate rollout on `/ready` and expect it to be empty-ish at first.
- Only the adapter port (`8080`) needs exposing; the node stays pod-internal.
- State (Particl chain, wallet, SQLite) lives on one PersistentVolumeClaim.

---

## 7. Configuration reference (env vars)

| Variable | Default | Purpose |
|----------|---------|---------|
| `BSX_API_URL` | `http://127.0.0.1:12700` | Upstream node JSON API. |
| `BSX_WS_URL` | `ws://127.0.0.1:11700` | Upstream node WebSocket (real-time nudge; optional). |
| `BSX_API_AUTH` | — | `user:password` if the node has `client_auth_hash` set. |
| `BSX_UNLOCK_PASSWORD` | — | If set, the adapter auto-unlocks a locked PART wallet. |
| `ADAPTER_HOST` / `ADAPTER_PORT` | `0.0.0.0` / `8080` | Adapter listen address. |
| `POLL_INTERVAL_SECONDS` | `30` | Full re-fetch interval (safety net). |
| `MIN_REFRESH_INTERVAL_SECONDS` | `2` | Debounce for WS-triggered refreshes. |
| `OFFER_PAGE_LIMIT` | `1000` | Page size when fetching offers. |
| `HTTP_TIMEOUT_SECONDS` | `30` | Upstream request timeout. |
| `QUOTE_PREFERENCE` | (see §2) | Comma-separated quote-currency preference. |
| `LOG_LEVEL` | `INFO` | Adapter log level. |

---

## 8. Notes for the next implementer

- The adapter is intentionally a **thin, stateless read layer**. It holds only
  the latest snapshot in memory and rebuilds it atomically on each refresh;
  there is no database and nothing to migrate.
- Everything the adapter serves derives from the node's `POST /json/offers`
  (all markets, `coin_from=coin_to=-1`) and `GET /json/coins`. If you need a
  field that isn't exposed yet, it almost certainly already exists on the raw
  offer (see `basicswap/js_server.py:js_offers`).
- If a future BasicSwap version emits full offer data over its WebSocket, the
  adapter could apply incremental updates instead of re-fetching; today it
  re-fetches because those events carry only partial data.
- Adding a genuine trades feed would require either running maker/taker bots
  that actually execute swaps (so the node becomes a swap party and records real
  executions), or sourcing trade data from outside the network. Both are out of
  scope for a passive observer — do not attempt to synthesize trades from offers
  disappearing; that signal is unreliable and easily mistaken for market data.
