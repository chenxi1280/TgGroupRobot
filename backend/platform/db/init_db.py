from __future__ import annotations

import asyncio

import structlog

from backend.platform.config.core.settings import get_settings
from backend.platform.db.runtime.schema_gate import validate_database_schema
from backend.platform.db.runtime.session import create_database
from backend.platform.db.runtime.startup_migrations import run_startup_schema_migrations

log = structlog.get_logger(__name__)


async def init_db() -> None:
    settings = get_settings()
    db = create_database(settings.database_url)

    try:
        await run_startup_schema_migrations(db.engine)
        await validate_database_schema(db.engine)
        log.info("database_initialization_finished")
    finally:
        await db.engine.dispose()


def main() -> None:
    asyncio.run(init_db())


if __name__ == "__main__":
    main()
