from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "docs-site/scripts/audit_flow_experience.py"


def run_experience_audit(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_flow_experience_audit_reports_completion_and_recovery_gaps() -> None:
    result = run_experience_audit()

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    assert payload["flows"] == len(list((ROOT / "docs-site/src/content/flows").glob("*.json")))
    assert set(payload["counts"]) <= {"input_hint", "recovery", "completion", "test_loop"}
    assert "byCategory" in payload
    assert "findings" in payload


def test_flow_experience_audit_can_print_markdown_report() -> None:
    result = run_experience_audit("--format", "markdown")

    assert result.returncode == 0, result.stderr
    assert "# 功能使用流程体验审计报告" in result.stdout
    assert "## 按分类统计" in result.stdout
    assert "## Findings" in result.stdout
