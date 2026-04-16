from __future__ import annotations

from pathlib import Path

from scripts import dev_reload


def test_changed_paths_reports_created_updated_and_deleted_files():
    before = {
        Path("backend/a.py"): (1, 10),
        Path("backend/deleted.py"): (1, 10),
    }
    after = {
        Path("backend/a.py"): (2, 10),
        Path("backend/created.py"): (1, 10),
    }

    assert dev_reload.changed_paths(before, after) == [
        Path("backend/a.py"),
        Path("backend/created.py"),
        Path("backend/deleted.py"),
    ]


def test_parse_command_uses_default_when_no_command_is_passed():
    assert dev_reload._parse_command([]) == [dev_reload.sys.executable, "main.py"]


def test_should_watch_python_and_env_files_but_skip_cache():
    assert dev_reload._should_watch_file(Path("backend/app/runtime.py"))
    assert dev_reload._should_watch_file(Path(".env"))
    assert not dev_reload._should_watch_file(Path("__pycache__/runtime.pyc"))
