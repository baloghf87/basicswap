"""Entry point: `python -m orderbook_api`."""

from __future__ import annotations

import uvicorn

from .config import config


def main() -> None:
    uvicorn.run(
        "orderbook_api.server:app",
        host=config.host,
        port=config.port,
        log_level=config.log_level.lower(),
        access_log=False,
    )


if __name__ == "__main__":
    main()
