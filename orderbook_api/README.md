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
