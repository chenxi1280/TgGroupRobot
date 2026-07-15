from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.engine import make_url

from backend.platform.db.runtime import database_migrations


ALEMBIC_VERSION_NUM_MAX_LENGTH = 32


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
    ]
    assert [revision.down_revision for revision in revisions] == [
        None,
        "0001_legacy_baseline",
        "0002_verification_reliability",
        "0003_garage_forward_reliability",
        "0004_scheduled_reliability",
    ]
    assert all(callable(revision.downgrade) for revision in revisions)


def test_revision_identifiers_fit_alembic_version_table() -> None:
    revisions = database_migrations.load_revision_modules()

    assert all(
        len(revision.revision) <= ALEMBIC_VERSION_NUM_MAX_LENGTH
        for revision in revisions
    )
