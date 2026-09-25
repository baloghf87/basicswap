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

# 2. Start the BasicSwap node. It manages the Particl daemon itself and serves
#    the internal JSON API (:12700) and WebSocket (:11700) on localhost.
log "Starting BasicSwap node"
basicswap-run -datadir="${DATADIR}" &
NODE_PID=$!

# 3. Start the adapter API (public interface, default :8080).
log "Starting order-book adapter"
python -m orderbook_api &
ADAPTER_PID=$!

terminate() {
    log "Shutting down"
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
