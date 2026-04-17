from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "docs-site/scripts/audit_flow_alignment.py"


def run_audit_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_flow_alignment_audit_reports_reverse_mapping_stats_without_blocking() -> None:
    result = run_audit_script()

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    counts = payload["counts"]

    assert payload["flows"] == len(list((ROOT / "docs-site/src/content/flows").glob("*.json")))
    assert payload["callbacks"] == payload["templateMatches"] + payload["routeOnlyMatches"]
    assert payload["broadRouteOnlyMatches"] == counts.get("P3", 0)
    assert "P1" not in counts
    assert "P2" not in counts
    if payload["findings"]:
        assert payload["sample"]


def test_flow_alignment_audit_can_print_markdown_report() -> None:
    result = run_audit_script("--format", "markdown")

    assert result.returncode == 0, result.stderr
    assert "# 用户手册键盘流程反向审计报告" in result.stdout
    assert "未发现 P1/P2 阻断项" in result.stdout
    assert "仅宽路由兜底匹配" in result.stdout
