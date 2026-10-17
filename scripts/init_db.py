"""Apply TimescaleDB migration SQL files.

Idempotent: each migration file's name is recorded in ``schema_migrations`` and
skipped on subsequent runs. Runs directly over asyncpg (no ORM needed).

Usage:
    python scripts/init_db.py            # apply pending migrations
    python scripts/init_db.py --status   # show applied versions
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import asyncpg

# Allow running as a script from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.logging import configure_logging, get_logger  # noqa: E402
from config.settings import settings  # noqa: E402
from data.db import migration_files  # noqa: E402

log = get_logger("scripts.init_db")


async def _ensure_tracking_table(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version     TEXT PRIMARY KEY,
            applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


async def _applied_versions(conn: asyncpg.Connection) -> set[str]:
    rows = await conn.fetch("SELECT version FROM schema_migrations")
    return {r["version"] for r in rows}


async def apply_migrations() -> int:
    """Apply pending migrations; return number applied."""
    files = migration_files()
    if not files:
        log.warning("no migration files found")
        return 0

    conn = await asyncpg.connect(settings.db_dsn)
    try:
        # Ensure TimescaleDB and pgcrypto exist before migration 001 references them.
        await _ensure_tracking_table(conn)
        applied = await _applied_versions(conn)

        count = 0
        for path in files:
            version = path.stem
            if version in applied:
                log.info("skip %s (already applied)", version)
                continue
            log.info("applying %s", version)
            sql = path.read_text(encoding="utf-8")
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO schema_migrations (version) VALUES ($1)", version
                )
            count += 1
            log.info("applied %s", version)
        log.info("migrations complete (%d applied)", count)
        return count
    finally:
        await conn.close()


async def show_status() -> None:
    conn = await asyncpg.connect(settings.db_dsn)
    try:
        await _ensure_tracking_table(conn)
        applied = await _applied_versions(conn)
        for path in migration_files():
            mark = "applied" if path.stem in applied else "PENDING"
            print(f"[{mark}] {path.name}")
    finally:
        await conn.close()


async def _wait_for_db(retries: int = 30, delay: float = 2.0) -> None:
    """Wait for the DB to accept connections (container startup race)."""
    for attempt in range(1, retries + 1):
        try:
            conn = await asyncpg.connect(settings.db_dsn)
            await conn.close()
            log.info("database reachable")
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("db not ready (%d/%d): %s", attempt, retries, exc)
            await asyncio.sleep(delay)
    raise RuntimeError("database unreachable after retries")


async def _run_migrations() -> None:
    await _wait_for_db()
    await apply_migrations()


def main() -> None:
    parser = argparse.ArgumentParser(description="GoldScalper DB migrations")
    parser.add_argument("--status", action="store_true", help="show migration status")
    args = parser.parse_args()

    configure_logging()
    if args.status:
        asyncio.run(show_status())
        return
    asyncio.run(_run_migrations())


if __name__ == "__main__":
    main()
