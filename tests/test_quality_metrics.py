from __future__ import annotations

from pathlib import Path

from scripts.quality_metrics import inspect_python_file


def _write_source(tmp_path: Path, source: str) -> Path:
    path = tmp_path / "sample.py"
    path.write_text(source, encoding="utf-8")
    return path


def test_quality_metrics_accept_small_flat_named_code(tmp_path) -> None:
    path = _write_source(
        tmp_path,
        "LIMIT = 5\n\ndef choose(value, minimum=0, *, enabled=True):\n"
        "    if enabled and value > minimum:\n        return value\n    return minimum\n",
    )

    assert inspect_python_file(path) == []


def test_quality_metrics_report_every_structural_rule(tmp_path) -> None:
    padding = "\n".join("    total += 1" for _ in range(45))
    source = (
        "def oversized(a, b, c, d):\n"
        "    total = 0\n"
        "    if a:\n        if b:\n            if c:\n                if d:\n"
        "                    total = 1\n"
        "    if total == 42:\n        total += 1\n"
        f"{padding}\n"
        "    return total\n"
    )

    violations = inspect_python_file(_write_source(tmp_path, source))

    assert {violation.rule for violation in violations} == {
        "QF001",
        "QF002",
        "QF003",
        "QF005",
    }


def test_quality_metrics_report_complexity(tmp_path) -> None:
    branches = "\n".join(
        f"    if value == item_{index}:\n        return {index}"
        for index in range(11)
    )
    source = f"def complex_choice(value, *, items):\n{branches}\n    return -1\n"

    violations = inspect_python_file(_write_source(tmp_path, source))

    assert "QF004" in {violation.rule for violation in violations}
