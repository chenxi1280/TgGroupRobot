from __future__ import annotations

from dataclasses import dataclass, field

import pytest

import backend.app.bootstrap as app_main
from backend.platform.db.runtime.startup_migrations import run_startup_schema_migrations


@dataclass
class FakeInspector:
    tables: set[str]

    def has_table(self, table_name: str, schema: str | None = None) -> bool:
        return table_name in self.tables


@dataclass
class FakeBeginContext:
    inspector: FakeInspector
    executed_sql: list[str] = field(default_factory=list)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def run_sync(self, fn):
        return fn(object())

    async def exec_driver_sql(self, sql: str):
        self.executed_sql.append(" ".join(sql.split()))


class FakeEngine:
    def __init__(self, inspector: FakeInspector) -> None:
        self.context = FakeBeginContext(inspector=inspector)

    def begin(self) -> FakeBeginContext:
        return self.context


@pytest.mark.asyncio
async def test_run_startup_schema_migrations_executes_known_compat_patches(monkeypatch) -> None:
    inspector = FakeInspector(tables={
        "chat_settings",
        "garage_forward_settings",
        "teacher_search_settings",
        "scheduled_message_tasks",
        "ad_campaigns",
    })
    engine = FakeEngine(inspector)

    monkeypatch.setattr("backend.platform.db.runtime.startup_migrations.inspect", lambda _: inspector)
    monkeypatch.setattr("backend.platform.db.runtime.startup_migrations.Base.metadata.create_all", lambda sync_conn, checkfirst=True: None)

    await run_startup_schema_migrations(engine)  # type: ignore[arg-type]

    executed_sql = engine.context.executed_sql

    assert any("CREATE SCHEMA IF NOT EXISTS bot" in sql for sql in executed_sql)
    assert any("ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS command_config_enabled" in sql for sql in executed_sql)
    assert any("ALTER TABLE bot.garage_forward_settings ADD COLUMN IF NOT EXISTS button_template_enabled" in sql for sql in executed_sql)
    assert any("ALTER TABLE bot.teacher_search_settings ADD COLUMN IF NOT EXISTS footer_button_url" in sql for sql in executed_sql)
    assert any("CREATE UNIQUE INDEX IF NOT EXISTS uq_smt_short_id ON bot.scheduled_message_tasks(short_id)" in sql for sql in executed_sql)
    assert any("ALTER TABLE bot.ad_campaigns ADD COLUMN IF NOT EXISTS sort_order" in sql for sql in executed_sql)


@pytest.mark.asyncio
async def test_validate_schema_or_exit_runs_migrations_before_schema_gate(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []
    engine = object()
    app = type("App", (), {"bot_data": {"db": type("DB", (), {"engine": engine})()}})()

    async def fake_run_startup_schema_migrations(arg) -> None:
        calls.append(("migrate", arg))

    async def fake_validate_database_schema(arg) -> None:
        calls.append(("validate", arg))

    monkeypatch.setattr(app_main, "run_startup_schema_migrations", fake_run_startup_schema_migrations)
    monkeypatch.setattr(app_main, "validate_database_schema", fake_validate_database_schema)

    await app_main._validate_schema_or_exit(app)

    assert calls == [("migrate", engine), ("validate", engine)]
