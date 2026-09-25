#!/bin/bash
# Launch a listen-only BasicSwap node (Particl only) plus the order-book adapter
# in a single container. Runs as swap_user (the base image entrypoint does the
# gosu drop before exec'ing this script).
set -euo pipefail

DATADIR="${BSX_DATADIR:-/coindata}"

log() { echo "[launch] $*"; }

# 1. One-time prepare: writes basicswap.json, fetches particld, inits the PART
#    wallet. Skipped if the datadir is already prepared (persistent volume).
if [ ! -f "${DATADIR}/basicswap.json" ]; then
    log "First run: preparing listen-only node (Particl only) in ${DATADIR}"
    basicswap-prepare -datadir="${DATADIR}" --withcoins=particl --htmlhost=0.0.0.0
else
    log "Existing datadir found; skipping prepare"
fi

# 1b. Optional external Tor proxy (e.g. a shared tor daemon in another k8s
#     namespace). When TOR_PROXY_HOST is set, BasicSwap's own HTTP requests and
#     particld's connections to .onion peers go through that SOCKS proxy. With
#     TOR_PROXY_MODE=all (default: onion) every particld connection is proxied,
#     which makes the initial chain sync much slower. No onion service is
#     published (the node is listen-only, inbound connections are not needed).
#     Re-applied on every start so a changed proxy address takes effect.
#     particld needs an IP, so a host name is resolved here.
configure_tor() {
    local host="${TOR_PROXY_HOST}" port="${TOR_PROXY_PORT:-9050}" ip
    ip=$(getent hosts "${host}" | awk '{print $1; exit}')
    if [ -z "${ip}" ]; then
        log "Cannot resolve TOR_PROXY_HOST=${host}"; exit 1
    fi
    log "Routing through Tor SOCKS proxy ${host} (${ip}):${port}, mode ${TOR_PROXY_MODE:-onion}"
    python - "${DATADIR}" "${ip}" "${port}" "${TOR_PROXY_MODE:-onion}" <<'PY'
import json, os, sys
datadir, ip, port, mode = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
settings_path = os.path.join(datadir, "basicswap.json")
with open(settings_path) as f:
    settings = json.load(f)
settings["use_tor"] = True
settings["tor_proxy_host"] = ip
settings["tor_proxy_port"] = port
with open(settings_path, "w") as f:
    json.dump(settings, f, indent=4)
part = settings["chainclients"]["particl"]
conf_path = os.path.join(part["datadir"], part.get("config_filename", "particl.conf"))
managed = ("proxy=", "onion=", "listenonion=", "torcontrol=", "torpassword=", "listen=")
with open(conf_path) as f:
    lines = [l for l in f if not l.startswith(managed)]
lines += [f"{'proxy' if mode == 'all' else 'onion'}={ip}:{port}\n", "listenonion=0\n", "listen=0\n"]
with open(conf_path, "w") as f:
    f.writelines(lines)
PY
}
if [ -n "${TOR_PROXY_HOST:-}" ]; then
    configure_tor
fi

# 1c. Observe offers of every coin (and wait long enough for particld, see below), not only the active (Particl) one: without this BasicSwap drops
#     each incoming offer involving a coin that has no daemon here ("Ignoring message involving
#     inactive coin XMR"), and a listen-only node would never see an order book.
python - "${DATADIR}" <<'PY'
import json, os, sys
path = os.path.join(sys.argv[1], "basicswap.json")
with open(path) as f:
    settings = json.load(f)
changed = False
if not settings.get("observe_inactive_coin_offers"):
    settings["observe_inactive_coin_offers"] = True
    changed = True
# particld can need a long time before its RPC answers (chainstate replay after an unclean stop);
# BasicSwap's default 15 tries (~10 min) would exit and restart the pod mid-replay, forever.
if settings.get("startup_tries", 15) < 60:
    settings["startup_tries"] = 60
    changed = True
if changed:
    with open(path, "w") as f:
        json.dump(settings, f, indent=4)
PY

# 2. Start the BasicSwap node. It manages the Particl daemon itself and serves
#    the internal JSON API (:12700) and WebSocket (:11700) on localhost.
log "Starting BasicSwap node"
basicswap-run -datadir="${DATADIR}" &
NODE_PID=$!

# 3. Start the adapter API (public interface, default :8080).
log "Starting order-book adapter"
python -m orderbook_api &
ADAPTER_PID=$!

# Stop particld ourselves and wait until it has exited: it must flush its chainstate, or the next
# start replays every block since the last flush (hundreds of thousands on a synced node, tens of
# minutes). Relying on basicswap-run for this was not enough: particld got killed with the container
# (no "Shutdown" in its log). Keep terminationGracePeriodSeconds above the wait below.
stop_particld() {
    local pidfile="${DATADIR}/particl/particl.pid" pid
    [ -f "${pidfile}" ] || return 0
    pid=$(cat "${pidfile}")
    kill -0 "${pid}" 2>/dev/null || return 0
    log "Stopping particld (pid ${pid})"
    "${DATADIR}/bin/particl/particl-cli" -datadir="${DATADIR}/particl" stop >/dev/null 2>&1 \
        || kill -INT "${pid}" 2>/dev/null || true
    for _ in $(seq 1 240); do
        kill -0 "${pid}" 2>/dev/null || { log "particld stopped"; return 0; }
        sleep 1
    done
    log "particld still running after 240 s"
}

TERMINATING=0
terminate() {
    [ "${TERMINATING}" = 1 ] && return
    TERMINATING=1
    log "Shutting down"
    stop_particld
    kill -TERM "${NODE_PID}" "${ADAPTER_PID}" 2>/dev/null || true
}
trap terminate TERM INT

# If either process exits, tear the whole container down so k8s restarts it.
wait -n "${NODE_PID}" "${ADAPTER_PID}"
EXIT_CODE=$?
log "A managed process exited (code ${EXIT_CODE}); stopping the other"
terminate
wait || true
exit "${EXIT_CODE}"
