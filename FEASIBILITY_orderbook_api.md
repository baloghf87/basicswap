# Feasibility study: BasicSwap network liquidity & trades API

**Goal:** A self-contained Docker image (runnable in k8s) that autonomously
connects to the BasicSwap network and exposes, over a REST/WS API:
1. an **order book** (bids/asks) for all markets, and
2. a **trades tape / candlestick** feed for all markets.

Only a **current snapshot** is required (no historical backfill).

---

## 1. Verdict at a glance

| Deliverable | Feasible? | Why |
|---|---|---|
| **Order book snapshot, all markets** | ✅ **Yes, fully** | Offers are broadcast publicly on a shared, well-known channel that any node can decrypt. An existing API already exposes them. |
| **Live order book updates** | ✅ **Yes** | An in-process WebSocket already emits `new_offer` / `offer_revoked` / `offer_expired` events. |
| **Trades tape (executed swaps), network-wide** | ❌ **No** (fundamental) | Bids and swap execution are private, point-to-point, and encrypted per-offer. A passive node cannot see swaps it did not participate in. Nothing on the network broadcasts completed trades. |
| **Candlestick chart, network-wide** | ❌ **No** (follows from the above) | Candlesticks require a stream of executed trade prices, which does not exist observably. |

**Bottom line:** the *order book / liquidity* half of the request is
cleanly buildable and mostly a matter of packaging what already exists. The
*trades tape / candlestick* half is **not achievable from a passive observer**
— not because of the snapshot-vs-history distinction, but because per-trade
execution data is never disseminated on the network at all. This is an
architectural property of BasicSwap, not a limitation we can engineer around
without either participating in swaps ourselves or getting the data from a
different source. See §4 for options.

---

## 2. How BasicSwap actually works (the relevant parts)

BasicSwap is not a matching engine; it's a **decentralized message board**
for atomic-swap offers, layered on the **Particl SMSG** (secure messaging)
network. There is no central order book and no trade feed — each node keeps
its own SQLite view built from messages it receives.

**Offers are public.** Every install ships with a *hardcoded, shared
network keypair* (`basicswap/bin/prepare.py:2027-2028`):

```
network_key    = "7sW2UEcHXvuqEjkpE5mD584zRaQYs6WXYohue4jLFZPTvMSxwvgs"
network_pubkey = "035758c4...903d2"
```

All public offers are broadcast to the SMSG address derived from that shared
key (`basicswap.py:640-646`, `11486-11495`). Because the *private* key is
public, **any node decrypts every offer on the network** — no funds, no
wallet, no swap participation required. This is what makes an order-book
observer trivially possible.

**Bids and swaps are private.** A bid is sent point-to-point to the offer
maker's per-offer SMSG address, encrypted to a key only that maker holds.
The receive path proves it:

- `processBid` rejects any bid whose offer this node did **not** create:
  `ensure(offer and offer.was_sent, "Unknown offer")` (`basicswap.py:11963`),
  and `ensure(msg["to"] == offer.addr_from, ...)` (`basicswap.py:11966`).
- A completed swap is just the maker's/taker's own `Bid` row reaching
  `BidStates.SWAP_COMPLETED = 8` (`basicswap_util.py:110`). It is **never
  rebroadcast** to the network.

So a node only ever stores bids/completed swaps for offers where it is the
maker or the taker. **A single passive observer therefore has a complete
order book but a trades tape consisting only of its own swaps (i.e. empty,
for a listen-only node).**

**Transport.** The primary/default transport is Particl Core's SMSG, which
BasicSwap consumes from a *local* Particl daemon over ZMQ + RPC
(`bsx_network.py:178-197`, `basicswap.py:14994-15009`). Particl Core itself
does the peer-to-peer gossip; there are no BasicSwap-level seed nodes. A
secondary **Simplex** transport exists (same encrypted payloads relayed over
the Simplex Chat network) that does *not* need Particl Core — see §5.

---

## 3. What we can reuse (a lot)

The codebase already contains almost everything for the order-book half.

- **REST:** `GET/POST /json/offers` (`js_server.py:428-588`) returns all
  active offers across all markets when the coin filters are left at their
  default `-1`. Each row already carries
  `coin_from, coin_to, amount_from, amount_to, rate, min_bid_amount,
  created_at, expire_at, swap_type, is_expired, is_revoked`. Pagination via
  `limit`/`offset`.
- **WebSocket (push):** an in-process WS server (default port **11700**)
  emits `new_offer`, `offer_revoked`, `offer_expired`, `offer_created`
  (`basicswap.py:3824-3826`, `4571-4574`, `14985-14992`). It's push-only
  (invalidation signals); clients re-fetch `/json/offers`.
- **Data model:** offers/bids live in SQLite via a light custom ORM
  (`db.py`); rates are integer, sats-scaled, expressed as *coin_to per unit
  of coin_from* (derived on receipt, not sent on the wire —
  `basicswap.py:11439-11441`).
- **External price context (optional):** `/json/coinprices`,
  `/json/rates`, `/json/coinhistory` pull *external* fiat/market prices
  (CoinGecko etc.) — useful as reference/annotation, but **not** BasicSwap
  trade data.

**Caveats on reuse:**
- The JSON API is coupled to a running instance: most offer/bid endpoints
  call `checkSystemStatus()`, which requires the **Particl wallet present and
  unlocked** (`basicswap.py:1837-1847`) and constructs a coin interface per
  offer. It is not a thin read-only layer over SQLite.
- Auth is **off by default** and binds to `127.0.0.1`; the server has
  Host-allowlist + CSRF checks. For k8s exposure we front it with our own
  thin API rather than exposing `12700` directly.

**Implication:** the cleanest build is a **thin adapter service** that runs
alongside a listen-only BasicSwap node, consuming its `/json/offers` +
WebSocket internally and re-shaping them into a clean, stable, documented
public API (REST snapshot + WS stream) with market-level aggregation
(best bid/ask, mid, depth) that BasicSwap does not itself provide.

---

## 4. The trades-tape problem, and the honest options

Because executed trades are not observable, a real network-wide trades tape
/ candlestick feed cannot be built from a listening node. The options, from
most to least faithful:

- **A. Order-book only (recommended).** Ship the liquidity API: full order
  book per market + live updates + derived best-bid/ask, mid, and depth.
  Drop the trades/candlestick deliverable, or replace the "chart" with an
  **order-book / mid-price snapshot** and (optionally) an externally-sourced
  reference price for context. Clean, honest, fully deliverable.

- **B. Infer "fills" heuristically (low fidelity, not recommended as truth).**
  Watch offers disappear: a one-time/limited offer that vanishes *before* its
  expiry *may* indicate a fill. But offers also expire naturally, get revoked,
  or are cancelled — and we can't see the executed amount or the actual agreed
  rate (bids can negotiate amount/rate). This yields at best a noisy "activity"
  proxy, not real trade prices. Would need to be clearly labelled as an
  estimate; risky if anyone treats it as market data.

- **C. Actively participate to observe (out of scope, capital-heavy).** Only a
  swap counterparty sees real executions. Running maker/taker bots to generate
  observable trades means committing capital and executing real swaps — a
  different project entirely, with financial and operational risk.

- **D. External source.** If a network-wide trade history exists anywhere
  (e.g. an aggregator, or a project-run node with special visibility), it
  would have to come from there, not from a passive node. Not evident in this
  codebase.

My recommendation is **A**: build the liquidity/order-book API properly and
explicitly scope out the trades tape, since it cannot be sourced truthfully
from the network by an observer.

---

## 5. Deployment shape for the Docker image / k8s

**Mandatory:** Particl Core is required for the default SMSG path — it cannot
be disabled (`run.py:736-737`, `prepare.py:1683-1684`). Every *other* coin
daemon can be omitted; a listen-only node needs only Particl. Note Particl
runs as a **full node with `txindex=1` and no prune option**
(`interface/part/core.py:126-128`), so the full Particl chain (single-digit
GB, external estimate) must sync. **There is no pruned/SPV/light mode for
Particl** in this codebase.

Two viable shapes:

1. **Monolithic pod (simplest):** one image running `basicswap-run` +
   a managed `particld` + our adapter. Needs an **init step/init-container**
   running `basicswap-prepare` against the mounted volume first (`run.py`
   refuses to start without `basicswap.json` — `run.py:372-373`), with
   `--withcoins=particl --htmlhost=0.0.0.0`.
2. **Split (mirrors their production compose):** `particl_core` container +
   BasicSwap client (`--nocores --usecontainers`) + adapter. Cleaner
   separation, matches `docker/production/`.

**k8s notes:**
- **1 PVC** for the datadir (Particl chain + txindex + SQLite + wallet).
  Cannot be capped via pruning; size for full chain + headroom.
- **Resources:** rough starting budget ~2–4 GB RAM/pod (particld + Python);
  validate empirically.
- **Ports:** expose only our adapter's API via a Service; keep BasicSwap's
  `12700`/`11700` and Particl RPC/ZMQ pod-internal.
- **Startup is slow:** first boot must sync the Particl chain before the order
  book is complete → use a readiness probe gated on Particl sync height, and a
  generous `terminationGracePeriodSeconds` (shutdown waits up to ~120s/daemon;
  compose uses a 5-minute grace period).
- **Lighter alternative — Simplex-only:** the Simplex transport needs only a
  `simplex-chat` client (no Particl Core, no chain sync) and decrypts offers
  in pure Python. This would make a *much* smaller, faster-starting container.
  **Risk:** Simplex is a newer/secondary transport, requires a
  `SIMPLEX_GROUP_LINK`, and likely carries fewer offers than the primary SMSG
  network — so the order book may be incomplete. Worth a spike to measure
  coverage before committing.

---

## 6. Risks & open questions

- **Order-book completeness on a fresh node.** Offers have a limited SMSG
  validity window (hours to ~48h). A newly started node only sees offers still
  live and being (re)broadcast; there is no "replay all history." For a
  *current snapshot* this is fine, but the book fills in over minutes as
  offers arrive. Acceptable given "current snapshot only."
- **Particl sync time / disk** is the main operational cost and the main
  reason to evaluate the Simplex-only path.
- **Shared network key** is public by design; nothing sensitive is exposed by
  reading offers. But it also means the "network" is permissionless — anyone
  can post spam/fake offers. The API should expose maker address + offer
  state so consumers can filter.
- **Rate semantics** (integer, sats-scaled, coin_to-per-coin_from, per-coin
  decimals) must be converted carefully to human-readable prices in the
  adapter to avoid off-by-decimals bugs.
- **Decision needed:** do we drop the trades/candlestick deliverable
  (Option A), or ship a clearly-labelled heuristic activity signal
  (Option B)?

---

## 7. Recommended next step

Proceed with **Option A**: a listen-only BasicSwap node (Particl-only) +
a thin adapter exposing a clean REST snapshot and WS stream of the order book
with per-market aggregation, packaged as a Docker image with an init-container
prepare step and a single PVC. Optionally run a **Simplex-only spike** first to
see whether we can avoid the Particl full-node weight.

The trades tape / candlestick feed should be **scoped out** (or explicitly
delivered as a labelled estimate) because network-wide execution data is not
observable by a passive node.
