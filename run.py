"""GoldScalper entrypoint.

Boots the API server (and, once implemented, the agent orchestrator).
Optionally applies pending DB migrations first.

Run:
    python run.py
"""

from __future__ import annotations

import asyncio
import os
import sys

import uvicorn

from config.logging import configure_logging, get_logger
from config.settings import settings

log = get_logger("run")


def _run_migrations_enabled() -> bool:
    return os.getenv("RUN_MIGRATIONS", "true").strip().lower() in {"1", "true", "yes"}


async def _apply_migrations() -> None:
    # Imported lazily so a missing asyncpg doesn't break non-migration runs.
    from scripts.init_db import _run_migrations

    try:
        await _run_migrations()
    except Exception as exc:  # noqa: BLE001
        log.error("migration failed: %s", exc)
        raise


def main() -> None:
    configure_logging()
    log.info("booting %s (%s)", settings.app_name, settings.environment)

    if _run_migrations_enabled():
        asyncio.run(_apply_migrations())

    uvicorn.run(
        "api.server:app",
        host=settings.host,
        port=settings.port,
        log_config=None,
        access_log=False,
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
