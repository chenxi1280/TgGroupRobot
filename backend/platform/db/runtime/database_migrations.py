"""数据库版本迁移编排。"""
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import ModuleType

import structlog
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.platform.db.runtime.startup_migrations import run_legacy_schema_bootstrap

LEGACY_BASELINE_REVISION = "0001_legacy_baseline"
ALEMBIC_VERSION_TABLE_SCHEMA = "public"
PROJECT_ROOT = Path(__file__).resolve().parents[4]
REVISION_FILES = (
    "0001_legacy_baseline.py",
    "0002_verification_reliability.py",
    "0003_garage_forward_reliability.py",
    "0004_scheduled_message_reliability.py",
    "0005_ad_rotation_reliability.py",
    "0006_schema_alignment.py",
)

log = structlog.get_logger(__name__)


def load_revision_modules() -> tuple[ModuleType, ...]:
    """加载 revision，供迁移链自检和测试使用。"""
    return tuple(_load_revision(filename) for filename in REVISION_FILES)


def _load_revision(filename: str) -> ModuleType:
    path = PROJECT_ROOT / "alembic" / "versions" / filename
    module_name = f"tggrouprobot_revision_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载迁移 revision: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _has_version_table(engine: AsyncEngine) -> bool:
    async with engine.connect() as conn:
        return await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).has_table(
                "alembic_version",
                schema=ALEMBIC_VERSION_TABLE_SCHEMA,
            )
        )


def _build_config(engine: AsyncEngine) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    database_url = engine.url.render_as_string(hide_password=False)
    # Alembic uses ConfigParser, where literal percent signs must be doubled.
    config.set_main_option(
        "sqlalchemy.url",
        database_url.replace("%", "%%"),
    )
    return config


async def _run_alembic(
    engine: AsyncEngine,
    *,
    action: str,
    revision: str,
) -> None:
    config = _build_config(engine)
    actions = {"stamp": command.stamp, "upgrade": command.upgrade}
    await asyncio.to_thread(actions[action], config, revision)


async def migrate_database(engine: AsyncEngine) -> None:
    """引导未纳管库，并将所有数据库无条件升级到 head。"""
    if not await _has_version_table(engine):
        log.info("database_legacy_bootstrap_required")
        await run_legacy_schema_bootstrap(engine)
        await _run_alembic(
            engine,
            action="stamp",
            revision=LEGACY_BASELINE_REVISION,
        )
        log.info("database_legacy_baseline_stamped", revision=LEGACY_BASELINE_REVISION)

    await _run_alembic(engine, action="upgrade", revision="head")
    log.info("database_migrations_finished", revision="head")
