"""BasicSwap order-book adapter API.

A thin, read-only service that runs alongside a listen-only BasicSwap node,
consumes its internal JSON API and WebSocket, and re-exposes the network
order book as a clean, documented REST + WebSocket API suitable for running
in Kubernetes.

See docs/ORDERBOOK_API.md for the public API contract.
"""

__version__ = "0.1.0"
