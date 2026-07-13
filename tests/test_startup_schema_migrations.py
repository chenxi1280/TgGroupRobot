from __future__ import annotations

from dataclasses import dataclass, field
import re
from pathlib import Path

import pytest

import backend.app.bootstrap as app_main
from backend.platform.db.runtime.startup_migrations import run_startup_schema_migrations

PROJECT_ROOT = Path(__file__).resolve().parents[1]


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
        "garage_forward_sources",
        "garage_forward_retry_queue",
        "teacher_search_settings",
        "scheduled_message_tasks",
        "scheduled_message_logs",
        "ad_campaigns",
        "ad_rotation_rules",
        "ad_rotation_history",
        "game_settings",
        "verification_challenges",
        "verification_timeout_attempts",
    })
    engine = FakeEngine(inspector)

    monkeypatch.setattr("backend.platform.db.runtime.startup_migrations.inspect", lambda _: inspector)
    monkeypatch.setattr("backend.platform.db.runtime.startup_migrations.Base.metadata.create_all", lambda sync_conn, checkfirst=True: None)

    await run_startup_schema_migrations(engine)  # type: ignore[arg-type]

    executed_sql = engine.context.executed_sql

    assert any("CREATE SCHEMA IF NOT EXISTS bot" in sql for sql in executed_sql)
    assert any("ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS command_config_enabled" in sql for sql in executed_sql)
    assert any("ALTER TABLE bot.garage_forward_settings ADD COLUMN IF NOT EXISTS button_template_enabled" in sql for sql in executed_sql)
    assert any("ALTER TABLE bot.garage_forward_sources ADD COLUMN IF NOT EXISTS last_seen_message_id" in sql for sql in executed_sql)
    assert any("ALTER TABLE bot.garage_forward_retry_queue ADD COLUMN IF NOT EXISTS message_map_id" in sql for sql in executed_sql)
    assert any("ALTER TABLE bot.garage_forward_retry_queue ADD COLUMN IF NOT EXISTS reply_markup_snapshot" in sql for sql in executed_sql)
    assert any("ALTER TABLE bot.garage_forward_retry_queue ADD COLUMN IF NOT EXISTS status" in sql for sql in executed_sql)
    assert any("CREATE UNIQUE INDEX IF NOT EXISTS uq_garage_forward_retry_event" in sql for sql in executed_sql)
    assert any("CREATE INDEX IF NOT EXISTS ix_garage_forward_retry_queue_next_retry ON bot.garage_forward_retry_queue(next_retry_at)" in sql for sql in executed_sql)
    assert any("ALTER TABLE bot.teacher_search_settings ADD COLUMN IF NOT EXISTS only_open_course_enabled" in sql for sql in executed_sql)
    assert any("ALTER TABLE bot.teacher_search_settings ADD COLUMN IF NOT EXISTS attendance_mode" in sql for sql in executed_sql)
    assert any("ALTER TABLE bot.teacher_search_settings ADD COLUMN IF NOT EXISTS attendance_source_chat_id" in sql for sql in executed_sql)
    assert any("ALTER TABLE bot.teacher_search_settings ADD COLUMN IF NOT EXISTS attendance_open_keyword" in sql for sql in executed_sql)
    assert any("ALTER TABLE bot.teacher_search_settings ADD COLUMN IF NOT EXISTS footer_button_url" in sql for sql in executed_sql)
    assert any("ALTER TABLE bot.teacher_profiles ADD COLUMN IF NOT EXISTS open_course_status" in sql for sql in executed_sql)
    assert any("ALTER TABLE bot.teacher_daily_attendance ADD COLUMN IF NOT EXISTS status" in sql for sql in executed_sql)
    assert any("CREATE UNIQUE INDEX IF NOT EXISTS uq_smt_short_id ON bot.scheduled_message_tasks(short_id)" in sql for sql in executed_sql)
    assert any("CREATE UNIQUE INDEX IF NOT EXISTS uq_sml_run_key ON bot.scheduled_message_logs(run_key)" in sql for sql in executed_sql)
    assert any("ALTER TABLE bot.scheduled_message_logs ALTER COLUMN sent_at DROP NOT NULL" in sql for sql in executed_sql)
    assert any("ALTER TABLE bot.ad_campaigns ADD COLUMN IF NOT EXISTS sort_order" in sql for sql in executed_sql)
    assert any("ALTER TABLE bot.ad_rotation_rules ADD COLUMN IF NOT EXISTS top_campaign_ids" in sql for sql in executed_sql)
    assert any("ALTER TABLE bot.ad_rotation_rules ADD COLUMN IF NOT EXISTS exclude_campaign_ids" in sql for sql in executed_sql)
    assert any("CREATE INDEX IF NOT EXISTS ix_ad_rotation_history_chat_sent ON bot.ad_rotation_history(chat_id, sent_at DESC)" in sql for sql in executed_sql)
    assert any("CREATE INDEX IF NOT EXISTS ix_ad_rotation_history_campaign_sent ON bot.ad_rotation_history(campaign_id, sent_at DESC)" in sql for sql in executed_sql)
    assert any("ADD COLUMN IF NOT EXISTS dispatch_key VARCHAR(128)" in sql for sql in executed_sql)
    assert any("CREATE UNIQUE INDEX IF NOT EXISTS uq_ad_rotation_history_dispatch_key" in sql for sql in executed_sql)
    assert any("CREATE INDEX IF NOT EXISTS ix_ad_rotation_history_due" in sql for sql in executed_sql)
    assert any("ALTER TABLE bot.game_settings ADD COLUMN IF NOT EXISTS points_source_chat_id" in sql for sql in executed_sql)
    assert any("ALTER TABLE bot.verification_challenges ADD COLUMN IF NOT EXISTS timeout_status" in sql for sql in executed_sql)
    assert any("ADD COLUMN IF NOT EXISTS timeout_replay_of_attempt_id" in sql for sql in executed_sql)
    assert any("UPDATE bot.verification_challenges SET timeout_status = 'succeeded'" in sql for sql in executed_sql)
    assert any("CREATE INDEX IF NOT EXISTS ix_verification_timeout_due" in sql for sql in executed_sql)
    assert any("CREATE UNIQUE INDEX IF NOT EXISTS uq_verification_timeout_attempt_no" in sql for sql in executed_sql)


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


def test_init_sql_adds_compat_columns_before_column_comments() -> None:
    init_sql = (PROJECT_ROOT / "sql" / "init.sql").read_text(encoding="utf-8")

    add_column_pattern = re.compile(
        r"ALTER TABLE(?: IF EXISTS)? bot\.(?P<table>\w+) "
        r"ADD COLUMN IF NOT EXISTS (?P<column>\w+)\b"
    )
    comment_pattern = re.compile(
        r"COMMENT ON COLUMN bot\.(?P<table>\w+)\.(?P<column>\w+) IS"
    )

    added_columns = {
        (match.group("table"), match.group("column")): match.start()
        for match in add_column_pattern.finditer(init_sql)
    }

    checked_columns: list[tuple[str, str]] = []
    for match in comment_pattern.finditer(init_sql):
        table_column = (match.group("table"), match.group("column"))
        add_column_index = added_columns.get(table_column)
        if add_column_index is None:
            continue
        checked_columns.append(table_column)
        assert add_column_index < match.start(), table_column

    assert ("chat_settings", "verification_cover_media_type") in checked_columns
    assert ("ad_campaigns", "buttons") in checked_columns
    assert ("scheduled_message_tasks", "short_id") in checked_columns


def test_init_sql_contains_verification_timeout_state_and_attempt_history() -> None:
    init_sql = (PROJECT_ROOT / "sql" / "init.sql").read_text(encoding="utf-8")

    assert "timeout_status VARCHAR(32) NOT NULL DEFAULT 'pending'" in init_sql
    assert "timeout_replay_of_attempt_id INTEGER" in init_sql
    assert "CREATE TABLE IF NOT EXISTS bot.verification_timeout_attempts" in init_sql
    assert "CONSTRAINT uq_verification_timeout_attempt_no" in init_sql
    assert "CREATE INDEX IF NOT EXISTS ix_verification_timeout_due" in init_sql


def test_init_sql_contains_durable_garage_forward_retry_state() -> None:
    init_sql = (PROJECT_ROOT / "sql" / "init.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS bot.garage_forward_retry_queue" in init_sql
    assert "reply_markup_snapshot JSONB" in init_sql
    assert "status VARCHAR(32) NOT NULL DEFAULT 'pending'" in init_sql
    assert "CONSTRAINT uq_garage_forward_retry_event" in init_sql
    assert "CREATE INDEX IF NOT EXISTS ix_garage_forward_retry_due" in init_sql


def test_init_sql_contains_scheduled_occurrence_state() -> None:
    init_sql = (PROJECT_ROOT / "sql" / "init.sql").read_text(encoding="utf-8")

    assert "run_key VARCHAR(128) NOT NULL" in init_sql
    assert "content_snapshot JSONB NOT NULL" in init_sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_sml_run_key" in init_sql
    assert "CREATE INDEX IF NOT EXISTS ix_sml_due" in init_sql


def test_init_sql_contains_ad_rotation_delivery_state() -> None:
    init_sql = (PROJECT_ROOT / "sql" / "init.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS bot.ad_rotation_history" in init_sql
    assert "dispatch_key VARCHAR(128) NOT NULL" in init_sql
    assert "content_snapshot JSONB NOT NULL" in init_sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_ad_rotation_history_dispatch_key" in init_sql
    assert "CREATE INDEX IF NOT EXISTS ix_ad_rotation_history_due" in init_sql
