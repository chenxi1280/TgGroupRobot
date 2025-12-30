from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import Connection
from sqlalchemy.engine.url import make_url
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from bot.db.base import Base
from bot.models import core  # noqa: F401  # ensure models imported


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL 未设置。请先创建 .env（参考 config/env.example）")
    return url


def _to_sync_url(url: str) -> str:
    u = make_url(url)
    # 对 psycopg dialect，sync/async 使用同一 scheme；保持原样即可。
    return str(u)


def run_migrations_offline() -> None:
    url = _to_sync_url(_get_database_url())
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        version_table_schema="bot",
        include_schemas=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _to_sync_url(_get_database_url())

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args={"options": "-csearch_path=bot"},
    )

    with connectable.connect() as connection:  # type: Connection
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            version_table_schema="bot",
            include_schemas=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()




