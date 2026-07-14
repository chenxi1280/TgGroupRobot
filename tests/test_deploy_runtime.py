from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_compose_up_runs_versioned_migrations_in_release_image() -> None:
    script = (PROJECT_ROOT / "deploy" / "compose-up.sh").read_text(encoding="utf-8")

    migration_command = (
        "compose run --rm --no-deps bot "
        "python -m backend.platform.db.init_db"
    )

    assert migration_command in script
    assert "apply-schema.sh" not in script
