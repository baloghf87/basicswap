# BasicSwap DEX (BSX)

![BasicswapDEX Preview](.github-readme/basicswap_header.jpg)

**[Official Website](https://basicswapdex.com)** | **[News](https://particl.news)** | **[Tutorials](https://academy.particl.io)** | **[Chat]( https://matrix.to/#/#basicswap:matrix.org )**

Table of Contents

* [About](#about)
* [Features](#features)
* [Available Assets](#available-assets)
* [Participate](#participate)
* [Tutorials](#tutorials)
* [License](#license)

## About

**BasicSwap** is the world’s most secure and decentralized DEX. It facilitates cross-chain atomic swaps by enabling peers to interact directly with each other within a free and open environment without central points of failure.

This DEX is fully non-custodial and features a decentralized order book, letting you create or accept swap offers without any fees, counterparties, or the need for accounts.

Built as a low-friction, highly secure solution to the frequent losses of funds on centralized exchanges (e.g., FTX, BitFinex, MtGox), **BasicSwap** aims to provide more reliable and secure cryptocurrency trading conditions for everyone.

**BasicSwap** is currently in active development by the community. While it already offers some of the essential trading features you'd expect from an exchange, more features and quality-of-life improvements are being worked on with the goal to provide a smoother user experience.

## Features

* **True cross-chain support** — Swap cryptocurrencies that live on entirely different blockchain environments, like Bitcoin and Monero.
* **Decentralized order book** — Make or take swap offers on a completely decentralized order book system.
* **No third-party or middleman** — Trade crypto with no intermediaries, completely eliminating central points of failure.
* **No trading fees** — Only pay the typical cryptocurrency network fee.
* **Superior financial privacy** — Protect your financial information from unauthorized access with BasicSwap’s privacy-conscious technology.
* **Full Monero support** — Swap Monero with a variety of other cryptocurrencies like Bitcoin or Particl. No wrapped assets or layer-2 involved.
* **User-friendly interface** — Enjoy all these features within a user-friendly and intuitive interface that handles all the complicated parts for you.

## Under the Hood

**BasicSwap** can be best understood as the decentralized version of the SWIFT messaging network; providing a decentralized messaging protocol that allows for peers to connect directly with each other with the purpose of executing atomic swaps without central points of failure and using official core wallets (Bitcoin Core, Litecoin Core, etc).

**BasicSwap** does not process, initiate, or execute swaps; it merely enables peers to communicate with each other and exchange the required information to simplify the process of using atomic swaps on the respective blockchains of the coins being swapped.

In essence, **BasicSwap** operates merely as a decentralized messaging protocol supplemented by a user-friendly interface.

## Available Assets

BasicSwap is compatible with the following digital assets.

<table>
  <tr>
   <td><strong>Coin Name</strong>
   </td>
   <td><strong>Ticker</strong>
   </td>
  </tr>
  <tr>
   <td>Bitcoin
   </td>
   <td>BTC
   </td>
  </tr>
  <tr>
   <td>Monero
   </td>
   <td>XMR
   </td>
  </tr>
  <tr>
   <td>Bitcoin Cash
   </td>
   <td>BCH
   </td>
  </tr>
  <tr>
   <td>Dash
   </td>
   <td>DASH
   </td>
  </tr>
  <tr>
   <td>Litecoin
   </td>
   <td>LTC
   </td>
  </tr>
  <tr>
   <td>Firo
   </td>
   <td>FIRO
   </td>
  </tr>
  <tr>
   <td>PIVX
   </td>
   <td>PIVX
   </td>
  </tr>
  <tr>
   <td>Decred
   </td>
   <td>DCR
   </td>
  </tr>
  <tr>
   <td>Wownero
   </td>
   <td>WOW
   </td>
  </tr>
  <tr>
   <td>Particl
   </td>
   <td>PART
   </td>
  </tr>
  <tr>
   <td>Dogecoin
   </td>
   <td>DOGE
   </td>
  </tr>
  <tr>
   <td>Namecoin
   </td>
   <td>NMC
   </td>
  </tr>
</table>

If you’d like to add a cryptocurrency to BasicSwap, refer to how other cryptocurrencies have been integrated to the DEX by following [this link](https://academy.particl.io/en/latest/basicswap-guides/basicswapguides_apply.html).

# Participate

### Chats

* **For support** Join the community on [#basicswap:matrix.org](https://matrix.to/#/#basicswap:matrix.org) using a Matrix client.

[![Twitter Follow](https://img.shields.io/twitter/follow/BasicSwapDEX?label=follow%20us&style=social)](http://twitter.com/BasicSwapDEX)

### Documentation, installation

Follow the guides on [Particl Academy](https://academy.particl.io) for tutorials and guides on how BasicSwap works.

* [Download BasicSwapDEX](https://github.com/basicswap/basicswap/tree/master/doc)

#### Community chat support

* [Matrix](https://matrix.to/#/#basicswap:matrix.org)

# Tutorials

You can find a wide variety of tutorials and step-by-step guides about BasicSwap on the [Particl Academy](https://academy.particl.io) or on Particl’s Youtube channel.

If you encounter an issue or try to accomplish something not mentioned in any of the tutorials included in the links above, please join the community chat support channel; you’ll be sure to find help and support from current contributors there!

# Network Order Book API (fork addition)

This fork adds a **read-only HTTP + WebSocket API that exposes a live snapshot of
the BasicSwap decentralized order book** (liquidity per market), packaged as a
container image that runs autonomously in Docker or Kubernetes.

- **Feasibility study:** [`FEASIBILITY_orderbook_api.md`](FEASIBILITY_orderbook_api.md)
- **Full API contract (for integrators):** [`docs/ORDERBOOK_API.md`](docs/ORDERBOOK_API.md)
- **Operator guide:** [`orderbook_api/README.md`](orderbook_api/README.md)

## What was built and why

BasicSwap has no central order book or trade feed — it is a decentralized
message board for atomic-swap offers, layered on the Particl **SMSG** secure
messaging network. A feasibility study (see the doc above) established two facts
that shape this work:

1. **The order book is fully observable.** Every install ships with a shared,
   well-known network keypair (`basicswap/bin/prepare.py`), and all public
   offers are broadcast to the SMSG address derived from it. Any node therefore
   decrypts every offer on the network — no funds, wallet, or swap participation
   required. This makes a live order-book snapshot straightforward.
2. **A network-wide trades tape / candlestick feed is _not_ possible from a
   passive node.** Bids and swap execution are point-to-point and encrypted
   between maker and taker (`processBid` rejects any bid for an offer the node
   did not itself create). Completed swaps are never rebroadcast, so an observer
   only ever sees trades it participated in. This is an architectural property
   of the network, not a gap to be engineered around.

The delivered scope ("Option A") is therefore the **order-book / liquidity API**,
with the trades endpoint explicitly reporting that it is unsupported.

## Components added

| Path | Purpose |
|------|---------|
| `orderbook_api/` | The adapter service (FastAPI): consumes a listen-only node's `/json/offers` + WebSocket and re-exposes a clean API. |
| `orderbook_api/Dockerfile` | Combined image: a Particl-only BasicSwap node **plus** the adapter in one container. |
| `orderbook_api/run-node-and-adapter.sh` | In-container supervisor (prepare-on-first-run → node → adapter). |
| `orderbook_api/tests/` | Unit tests for market mapping / price derivation. |
| `deploy/k8s/orderbook-api.yaml` | StatefulSet + Service + ConfigMap + optional Secret + PVC. |
| `docs/ORDERBOOK_API.md` | The public API contract. |
| `FEASIBILITY_orderbook_api.md` | The feasibility study. |

## Architecture

```
        ┌──────────────────────── container / pod ────────────────────────┐
        │                                                                  │
        │   particld  ◄── SMSG/ZMQ/RPC ──►  basicswap-run                  │
        │  (Particl full node)             (JSON API :12700, WS :11700)    │
        │                                        ▲                         │
        │                                        │ read-only               │
        │                                   orderbook_api  ── HTTP/WS :8080 ├──► consumers
        │                                                                  │
        └──────────────────────────────────────────────────────────────────┘
                         one PersistentVolumeClaim (/coindata)
```

The adapter folds one-directional BasicSwap offers into canonical `BASE/QUOTE`
markets (quote currency chosen by a deterministic preference order), classifies
each as a bid or ask, and expresses all prices as quote-per-base. It holds only
the latest snapshot in memory and rebuilds it atomically on each refresh (interval
poll + WebSocket-triggered refresh); it has no database and never mutates swap
state.

## API summary

Base path `/v1`; interactive schema at `/docs`, OpenAPI at `/openapi.json`.

| Endpoint | Description |
|----------|-------------|
| `GET /health`, `GET /ready` | Liveness / readiness probes. |
| `GET /v1/status` | Adapter + upstream node status (offer count, lock state, last refresh). |
| `GET /v1/markets`, `GET /v1/orderbook` | All markets with summary stats (best bid/ask, mid, spread). |
| `GET /v1/orderbook/{base}/{quote}?depth=N` | Aggregated bid/ask ladder for one market. |
| `GET /v1/offers?market=&side=` | Raw normalized offers. |
| `GET /v1/ws` | WebSocket: snapshot on connect, then push updates. |
| `GET /v1/trades/{base}/{quote}` | **Always HTTP 501** (`supported: false`) — see limitations. |

See [`docs/ORDERBOOK_API.md`](docs/ORDERBOOK_API.md) for full request/response
schemas and the configuration (environment-variable) reference.

## Build and run

```bash
# From the repository root:
docker build -t basicswap:latest .                                   # base node image
docker build -f orderbook_api/Dockerfile -t basicswap-orderbook:latest .

# Kubernetes: push basicswap-orderbook:latest to your registry, set image: in the
# manifest, then:
kubectl apply -f deploy/k8s/orderbook-api.yaml
kubectl port-forward svc/orderbook-api 8080:80

# Or a single local container:
docker run --rm -p 8080:8080 -v bsx-data:/coindata basicswap-orderbook:latest
```

To run only the adapter against an existing BasicSwap node:

```bash
pip install -r orderbook_api/requirements.txt
BSX_API_URL=http://127.0.0.1:12700 BSX_WS_URL=ws://127.0.0.1:11700 python -m orderbook_api
```

## Testing against the main (live) network

The node connects to the **Particl mainnet by default**, which is where the live
BasicSwap order book lives — no testnet or extra flags are needed. To validate
end-to-end against the real network:

1. **Start the container with a persistent volume** (the volume keeps the synced
   chain across restarts, so you only sync once):
   ```bash
   docker run -d --name bsx-ob -p 8080:8080 -v bsx-data:/coindata basicswap-orderbook:latest
   docker logs -f bsx-ob
   ```
   On first boot the container runs `basicswap-prepare` (downloads Particl Core,
   initialises the PART wallet) and then begins syncing the Particl mainnet
   chain. Particl runs as a full node with `txindex` and **no prune option**, so
   allow for a full chain download (single-digit GB, plus time). The order book
   is incomplete until the node is caught up.

   > If you prepared the node with an encrypted wallet (`WALLET_ENCRYPTION_PWD`),
   > also pass `BSX_UNLOCK_PASSWORD` so the adapter can unlock it — the PART
   > wallet must be unlocked for the node to serve offers. For a pure listen-only
   > node you can leave the wallet unencrypted and skip both.

2. **Wait for readiness.** `/ready` returns `503` until the adapter has fetched
   the book at least once (node up, wallet unlocked):
   ```bash
   curl -s localhost:8080/ready
   curl -s localhost:8080/v1/status | jq
   ```
   `offer_count` starts near zero and **grows over the first minutes** as offers
   arrive over SMSG (offers have a limited validity window and are rebroadcast,
   so the book fills in continuously — expect a usable snapshot within minutes of
   the node being synced, not instantly).

3. **Inspect the live order book:**
   ```bash
   curl -s localhost:8080/v1/markets | jq              # real markets, e.g. XMR/BTC, PART/BTC, LTC/BTC
   curl -s localhost:8080/v1/orderbook/XMR/BTC | jq    # aggregated bids/asks + mid/spread
   curl -s 'localhost:8080/v1/offers?market=XMR/BTC' | jq
   ```

4. **Watch the real-time stream** (any WebSocket client):
   ```bash
   websocat ws://localhost:8080/v1/ws        # snapshot on connect, then push updates
   ```

5. **Cross-check against the node directly** (from inside the container) to
   confirm the adapter mirrors the node's own view:
   ```bash
   docker exec bsx-ob curl -s -X POST 127.0.0.1:12700/json/offers -d '{}' | jq 'length'
   ```

6. **Confirm the trades limitation** is reported honestly on the live network:
   ```bash
   curl -s -o /dev/null -w '%{http_code}\n' localhost:8080/v1/trades/XMR/BTC   # 501
   ```

Sanity signs of a healthy live deployment: `/v1/status` shows `ready: true`,
`node_locked: false`, a non-zero and generally increasing `offer_count`, and
`/v1/markets` lists real coin pairs with populated bid/ask sides.

## Local (offline) testing

No network is needed for the unit tests of the mapping/pricing logic:

```bash
python -m pytest orderbook_api/tests/     # or, without pytest:
python -c "from orderbook_api.tests import test_markets as t; \
[getattr(t,n)() for n in dir(t) if n.startswith('test_')]; print('ok')"
```

## Limitations

- **No trades tape or candlesticks.** Executed swaps are private and never
  broadcast; a passive node cannot observe them. `/v1/trades/*` returns `501` by
  design. Do not attempt to synthesise trades from offers disappearing — that
  signal is unreliable and easily mistaken for real market data.
- **Snapshot only, no history.** Only the current order book is served; a freshly
  started node's book fills in as offers arrive.
- **Permissionless order book.** Anyone can post offers (including spam). Each
  offer exposes its maker address, amounts, and expiry so consumers can filter.
- **Particl full-node cost.** The main operational cost is the Particl chain sync
  and its disk footprint; there is no pruned/SPV mode for Particl.

# License

BasicSwap is released under MIT software license.
