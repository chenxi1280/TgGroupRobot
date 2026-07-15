from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import BigInteger
from sqlalchemy.engine import make_url

from backend.platform.db.schema.models.garage_features import CarReviewSetting
from backend.platform.db.schema.models.points import CustomPointLedger, PointsMallOrderLog
from backend.platform.db.runtime import database_migrations


ALEMBIC_VERSION_NUM_MAX_LENGTH = 32


class _FakeConnection:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def run_sync(self, function):
        return function(object())


class _FakeEngine:
    def connect(self) -> _FakeConnection:
        return _FakeConnection()


def test_build_config_accepts_percent_encoded_credentials() -> None:
    url = make_url(
        "postgresql+psycopg://app_user:p%40ssword@postgres:5432/tggrouprobot"
    )
    engine = SimpleNamespace(url=url)

    config = database_migrations._build_config(engine)  # type: ignore[arg-type]

    assert config.get_main_option("sqlalchemy.url") == url.render_as_string(
        hide_password=False
    )


@pytest.mark.asyncio
async def test_version_table_detection_uses_public_schema(monkeypatch) -> None:
    calls: list[tuple[str, str | None]] = []

    class FakeInspector:
        def has_table(self, table_name: str, schema: str | None = None) -> bool:
            calls.append((table_name, schema))
            return True

    monkeypatch.setattr(database_migrations, "inspect", lambda _: FakeInspector())

    assert await database_migrations._has_version_table(_FakeEngine()) is True  # type: ignore[arg-type]
    assert calls == [("alembic_version", "public")]


def test_models_match_production_schema_contract() -> None:
    assert CarReviewSetting.__table__.c.submit_command.type.length == 64
    assert CarReviewSetting.__table__.c.rank_command.type.length == 64
    assert isinstance(CustomPointLedger.__table__.c.id.type, BigInteger)
    assert isinstance(PointsMallOrderLog.__table__.c.id.type, BigInteger)


@pytest.mark.asyncio
async def test_unversioned_database_bootstraps_stamps_and_upgrades(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []
    engine = object()

    async def version_table_exists(arg) -> bool:
        assert arg is engine
        return False

    async def bootstrap(arg) -> None:
        calls.append(("bootstrap", arg))

    async def run_alembic(arg, *, action: str, revision: str) -> None:
        assert arg is engine
        calls.append((action, revision))

    monkeypatch.setattr(database_migrations, "_has_version_table", version_table_exists)
    monkeypatch.setattr(database_migrations, "run_legacy_schema_bootstrap", bootstrap)
    monkeypatch.setattr(database_migrations, "_run_alembic", run_alembic)

    await database_migrations.migrate_database(engine)  # type: ignore[arg-type]

    assert calls == [
        ("bootstrap", engine),
        ("stamp", database_migrations.LEGACY_BASELINE_REVISION),
        ("upgrade", "head"),
    ]


@pytest.mark.asyncio
async def test_versioned_database_only_upgrades_to_head(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    async def version_table_exists(_engine) -> bool:
        return True

    async def reject_bootstrap(_engine) -> None:
        raise AssertionError("legacy bootstrap must not run")

    async def run_alembic(_engine, *, action: str, revision: str) -> None:
        calls.append((action, revision))

    monkeypatch.setattr(database_migrations, "_has_version_table", version_table_exists)
    monkeypatch.setattr(database_migrations, "run_legacy_schema_bootstrap", reject_bootstrap)
    monkeypatch.setattr(database_migrations, "_run_alembic", run_alembic)

    await database_migrations.migrate_database(object())  # type: ignore[arg-type]

    assert calls == [("upgrade", "head")]


@pytest.mark.asyncio
async def test_legacy_bootstrap_failure_is_not_hidden(monkeypatch) -> None:
    async def version_table_exists(_engine) -> bool:
        return False

    async def fail_bootstrap(_engine) -> None:
        raise RuntimeError("bootstrap failed")

    monkeypatch.setattr(database_migrations, "_has_version_table", version_table_exists)
    monkeypatch.setattr(database_migrations, "run_legacy_schema_bootstrap", fail_bootstrap)

    with pytest.raises(RuntimeError, match="bootstrap failed"):
        await database_migrations.migrate_database(object())  # type: ignore[arg-type]


def test_reliability_revisions_form_linear_chain_and_have_downgrades() -> None:
    revisions = database_migrations.load_revision_modules()

    assert [revision.revision for revision in revisions] == [
        "0001_legacy_baseline",
        "0002_verification_reliability",
        "0003_garage_forward_reliability",
        "0004_scheduled_reliability",
        "0005_ad_rotation_reliability",
        "0006_schema_alignment",
    ]
    assert [revision.down_revision for revision in revisions] == [
        None,
        "0001_legacy_baseline",
        "0002_verification_reliability",
        "0003_garage_forward_reliability",
        "0004_scheduled_reliability",
        "0005_ad_rotation_reliability",
    ]
    assert all(callable(revision.downgrade) for revision in revisions)


def test_revision_identifiers_fit_alembic_version_table() -> None:
    revisions = database_migrations.load_revision_modules()

    assert all(
        len(revision.revision) <= ALEMBIC_VERSION_NUM_MAX_LENGTH
        for revision in revisions
    )
