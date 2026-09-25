# orderbook_api — BasicSwap order-book adapter

A thin, read-only service that runs alongside a **listen-only BasicSwap node**
and re-exposes the network order book as a clean REST + WebSocket API.

- **Public API contract:** [`docs/ORDERBOOK_API.md`](../docs/ORDERBOOK_API.md)
- **Feasibility background:** [`FEASIBILITY_orderbook_api.md`](../FEASIBILITY_orderbook_api.md)

## What it is

BasicSwap has no central order book or trade feed — each node builds its own
view from public offer messages on the Particl SMSG network. This adapter:

1. consumes the node's internal JSON API (`/json/offers`, `/json/coins`) and
   WebSocket (`:11700`), read-only;
2. folds one-directional offers into canonical `BASE/QUOTE` markets with
   bids/asks and quote-per-base prices;
3. serves a stable, documented API (default `:8080`) with per-market summaries,
   aggregated depth, raw offers, and a push WebSocket.

It never creates offers or bids and holds no persistent state of its own.

> **No trades feed.** A network-wide trades tape / candlestick feed is not
> possible from a passive node — swap execution is private and never broadcast.
> `/v1/trades/*` always returns `501`. See the feasibility doc.

## Architecture

```
        ┌──────────────────────── container / pod ────────────────────────┐
        │                                                                  │
        │   particld  ◄── SMSG/ZMQ/RPC ──►  basicswap-run                  │
        │  (Particl full node)             (JSON API :12700, WS :11700)    │
        │                                        ▲                         │
        │                                        │ read-only               │
        │                                   orderbook_api  ── HTTP/WS :8080 ├──►  consumers
        │                                                                  │
        └──────────────────────────────────────────────────────────────────┘
                         one PersistentVolumeClaim (/coindata)
```

## Run it

### Kubernetes (intended target)

```bash
# From the repo root:
docker build -t basicswap:latest .                               # base node image
docker build -f orderbook_api/Dockerfile -t basicswap-orderbook:latest .

# push basicswap-orderbook:latest to your registry, set image: in the manifest, then:
kubectl apply -f deploy/k8s/orderbook-api.yaml
kubectl port-forward svc/orderbook-api 8080:80
curl localhost:8080/v1/markets
```

First boot runs `basicswap-prepare` (downloads Particl Core, inits the PART
wallet) and begins syncing the Particl chain; `/ready` returns `503` until the
first successful order-book fetch, and the book fills in as offers arrive.

### Single container (local)

```bash
docker run --rm -p 8080:8080 -v bsx-data:/coindata basicswap-orderbook:latest
```

### Adapter only (against an existing node)

If you already run a BasicSwap node, run just the adapter:

```bash
pip install -r orderbook_api/requirements.txt
BSX_API_URL=http://127.0.0.1:12700 BSX_WS_URL=ws://127.0.0.1:11700 \
  python -m orderbook_api
```

Configuration is entirely via environment variables — see the table in
`docs/ORDERBOOK_API.md` §7.

## External Tor proxy & mainnet notes (2026-09-25)

- `TOR_PROXY_HOST` (+ `TOR_PROXY_PORT`, default 9050) routes BasicSwap's own HTTP requests and particld's
  **.onion** peers through an existing SOCKS proxy (e.g. a shared tor in another k8s namespace); the host
  name is resolved to an IP on every start (particld needs an IP). `TOR_PROXY_MODE=all` proxies every
  particld connection (much slower initial sync). No onion service is published (listen-only node).
- **Fixed:** the adapter's WebSocket client sent protocol pings with a random binary payload, which
  BasicSwap's bundled websocket server decodes as UTF-8 and crashes on (`UnicodeDecodeError`), dropping the
  connection every 30 s. Client pings are disabled; interval polling covers liveness.
- **Fixed: a listen-only node saw no offers at all.** BasicSwap drops every offer involving a coin it runs
  no daemon for (`Ignoring message involving inactive coin XMR, type OFFER`), and this node only runs
  Particl. New setting `observe_inactive_coin_offers` (set by `run-node-and-adapter.sh`): `ci()` hands out
  a daemon-less interface for inactive coins (built on a copy of the coin's settings, so the coin never
  looks active) that is enough to validate and store offers; fee-rate checks, which need the coin's
  daemon, are skipped for such coins (`isObservedCoin`).
- **Fixed: particld was killed on every container stop** (no clean shutdown → the next start replayed
  hundreds of thousands of blocks, and BasicSwap gave up waiting after 15 RPC tries). The run script now
  stops particld itself and waits for it, and raises `startup_tries` to 60.
- Verified on mainnet (2026-09-25): particld synced (2.25M blocks); the adapter serves 12 markets incl.
  XMR/BTC (e.g. best bid 0.00653 / ask 0.00664) and XMR/LTC.

## Tests

Pure logic (market mapping, price/side derivation) has no dependencies:

```bash
python -m pytest orderbook_api/tests/            # if pytest is available
# or, without pytest:
python -c "from orderbook_api.tests import test_markets as t; \
[getattr(t,n)() for n in dir(t) if n.startswith('test_')]; print('ok')"
```

## Layout

| File | Purpose |
|------|---------|
| `config.py` | Env-var configuration + quote-currency preference. |
| `bsx_client.py` | Async read-only client for the node's JSON API. |
| `markets.py` | Canonical market mapping and offer normalization. |
| `orderbook.py` | In-memory book, aggregation, and the refresh service. |
| `ws_consumer.py` | Consumes the node WS to trigger low-latency refreshes. |
| `server.py` | FastAPI app: REST + WebSocket + OpenAPI. |
| `__main__.py` | `python -m orderbook_api` entry point (uvicorn). |
| `Dockerfile` | Combined node + adapter image. |
| `run-node-and-adapter.sh` | In-container launcher/supervisor. |
