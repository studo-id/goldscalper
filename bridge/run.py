"""Entrypoint for running the bridge on the Windows MT5 host.

    python -m bridge.run

Reads BRIDGE_HOST / BRIDGE_PORT / BRIDGE_LOG_LEVEL from the environment/.env.
"""

from __future__ import annotations

import uvicorn

from bridge.config import BridgeSettings


def main() -> None:
    cfg = BridgeSettings()
    uvicorn.run(
        "bridge.app:app",
        host=cfg.bridge_host,
        port=cfg.bridge_port,
        log_level=cfg.bridge_log_level,
    )


if __name__ == "__main__":
    main()
