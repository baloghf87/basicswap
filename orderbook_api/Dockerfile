# Combined image: a listen-only BasicSwap node (Particl only) + the order-book
# adapter API, in one container.
#
# Build (from the repository root):
#   1. Build the BasicSwap base image:
#        docker build -t basicswap:latest .
#   2. Build this combined image:
#        docker build -f orderbook_api/Dockerfile -t basicswap-orderbook:latest .
#
# The BSX_IMAGE build-arg lets you pin a specific base image tag/digest.
ARG BSX_IMAGE=basicswap:latest
FROM ${BSX_IMAGE}

# Adapter dependencies, installed into the same venv the base image created.
COPY orderbook_api/requirements.txt /tmp/adapter-requirements.txt
RUN pip install --no-cache-dir -r /tmp/adapter-requirements.txt

# Adapter source (kept importable via PYTHONPATH).
COPY orderbook_api /opt/app/orderbook_api
COPY orderbook_api/run-node-and-adapter.sh /usr/local/bin/run-node-and-adapter.sh
RUN chmod +x /usr/local/bin/run-node-and-adapter.sh

ENV PYTHONPATH=/opt/app \
    ADAPTER_HOST=0.0.0.0 \
    ADAPTER_PORT=8080 \
    BSX_API_URL=http://127.0.0.1:12700 \
    BSX_WS_URL=ws://127.0.0.1:11700

# Adapter API port (the only port you need to expose in k8s).
EXPOSE 8080

# The base image's ENTRYPOINT (/entrypoint.sh) chowns the datadir and drops to
# swap_user, then exec's this CMD.
CMD ["run-node-and-adapter.sh"]
