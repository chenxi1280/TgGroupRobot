from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "docs-site/scripts/audit_flow_alignment.py"


def load_audit_module():
    spec = importlib.util.spec_from_file_location("audit_flow_alignment", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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
    assert payload["broadRouteOnlyMatches"] == len(payload["p3BranchReview"])
    assert payload["broadRouteOnlyMatches"] == 0
    assert "P1" not in counts
    assert "P2" not in counts
    assert "P3" not in counts
    assert len(payload["coverageMatrix"]) == payload["flows"]
    assert payload["matrixCounts"] == {"low": payload["flows"]}
    assert set(payload["duplicateSummary"]) == {"同一能力多入口", "旧入口兼容", "真实重复实现"}
    if payload["findings"]:
        assert payload["sample"]


def test_flow_alignment_audit_extracts_antispam_two_button_row_templates() -> None:
    audit = load_audit_module()
    evidence = audit.callback_evidence_from_backend()

    callbacks = [
        "gg:toggle:{rule_id}:enabled:{chat_id}",
        "gg:cycle:{rule_id}:messages:{chat_id}",
    ]

    for callback in callbacks:
        matches = audit.callback_evidence_matches(callback, evidence)
        assert any(
            match.kind == "template" and match.path == "backend/features/admin/ui/antispam.py"
            for match in matches
        )


def test_flow_alignment_audit_builds_feature_coverage_matrix() -> None:
    result = run_audit_script()

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    rows = {row["slug"]: row for row in payload["coverageMatrix"]}

    invite_row = rows["invite-link-management"]
    assert invite_row["entry"]["registeredMenuKeys"] == ["invite"]
    assert "inv:home:" in invite_row["callbackRoutes"]["prefixes"]
    assert "invite_link_create" in invite_row["privateInputStates"]
    assert any(path.startswith("tests/") for path in invite_row["testFiles"])
    assert invite_row["riskLevel"] in {"low", "medium"}

    auction_row = rows["auction"]
    assert any(listener["name"] == "auction" for listener in auction_row["groupListeners"])


def test_flow_alignment_audit_reports_duplicate_candidates_by_category() -> None:
    result = run_audit_script()

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    candidates = payload["duplicateCandidates"]

    shared_invite = [
        item
        for item in candidates
        if item["category"] == "同一能力多入口" and "invite-link-management" in item["slugs"]
    ]
    assert shared_invite
    assert {"invite-attribution", "invite-link-management", "invite-rank", "user-invite-link"} <= set(shared_invite[0]["slugs"])
    assert payload["duplicateSummary"]["同一能力多入口"] >= 1
    assert payload["duplicateSummary"]["旧入口兼容"] >= 1


def test_flow_alignment_audit_can_print_markdown_report() -> None:
    result = run_audit_script("--format", "markdown")

    assert result.returncode == 0, result.stderr
    assert "# 用户手册键盘流程反向审计报告" in result.stdout
    assert "未发现 P1/P2 阻断项" in result.stdout
    assert "仅宽路由兜底匹配：0" in result.stdout
    assert "## 功能覆盖矩阵" in result.stdout
    assert "## 重复功能候选" in result.stdout
    assert "## P3 分支复核清单" in result.stdout
