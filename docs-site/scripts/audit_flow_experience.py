#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FLOWS_DIR = ROOT / "docs-site/src/content/flows"

INPUT_HINT_TOKENS = {
    "格式",
    "示例",
    "例如",
    "JSON",
    "文本|链接",
    "YYYY",
    "HH:MM",
    "/clear",
    "清空",
    "/skip",
    "每行",
    "逗号",
    "分钟数",
}
RECOVERY_TOKENS = {"请先", "未开启", "启用失败", "权限", "无效", "失败", "不足", "无法", "前置", "依赖"}
COMPLETION_TOKENS = {"步骤", "完成", "必填", "已配置", "未配置", "下一步", "进度"}
TEST_TOKENS = {"预览", "测试", "触发一次", "立即发送", "立即开奖", "发布活动", "去群内", "群内展示"}


def load_flows() -> list[dict]:
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(FLOWS_DIR.glob("*.json"))]


def collect_text(flow: dict) -> tuple[str, list[str]]:
    fragments: list[str] = []
    actions: list[str] = []
    for screen in flow.get("screens", []):
        fragments.extend(str(item) for item in screen.get("message", []))
        fragments.extend(str(item) for item in screen.get("stateLines", []))
        input_config = screen.get("input") or {}
        fragments.append(str(input_config.get("prompt", "")))
        fragments.extend(str(item) for item in input_config.get("examples", []) or [])
        for row in screen.get("keyboard", []):
            for button in row:
                fragments.append(str(button.get("label", "")))
                fragments.append(str(button.get("feedback", "")))
                actions.append(str(button.get("action", "")))
    return " ".join(fragments + actions), actions


def has_any(text: str, tokens: set[str]) -> bool:
    return any(token in text for token in tokens)


def audit_flow(flow: dict) -> list[dict]:
    text, actions = collect_text(flow)
    screens = flow.get("screens", [])
    findings: list[dict] = []

    if "input" in actions and not has_any(text, INPUT_HINT_TOKENS):
        findings.append({
            "code": "input_hint",
            "message": "输入型流程缺少格式、示例或清空方式提示",
        })
    if not has_any(text, RECOVERY_TOKENS):
        findings.append({
            "code": "recovery",
            "message": "流程缺少前置条件失败后的修复指引",
        })
    if len(screens) > 8 and not has_any(text, COMPLETION_TOKENS):
        findings.append({
            "code": "completion",
            "message": "长流程缺少完成度、必填项或下一步提示",
        })
    if not has_any(text, TEST_TOKENS):
        findings.append({
            "code": "test_loop",
            "message": "流程缺少预览、发布或群内测试闭环",
        })
    return findings


def build_report() -> dict:
    flows = load_flows()
    findings: list[dict] = []
    counts = Counter()
    by_category: dict[str, Counter] = defaultdict(Counter)

    for flow in flows:
        flow_findings = audit_flow(flow)
        for finding in flow_findings:
            item = {
                "slug": flow.get("slug"),
                "title": flow.get("title"),
                "category": flow.get("category"),
                **finding,
            }
            findings.append(item)
            counts[finding["code"]] += 1
            by_category[flow.get("category", "未分类")][finding["code"]] += 1

    return {
        "flows": len(flows),
        "findings": findings,
        "counts": dict(counts),
        "byCategory": {key: dict(value) for key, value in sorted(by_category.items())},
    }


def print_markdown(report: dict) -> None:
    print("# 功能使用流程体验审计报告")
    print()
    print(f"- Flow 文件：{report['flows']}")
    print(f"- Findings：{len(report['findings'])}")
    print(f"- 分类统计：{report['counts']}")
    print()
    print("## 按分类统计")
    for category, counts in report["byCategory"].items():
        print(f"- {category}: {counts}")
    print()
    print("## Findings")
    if not report["findings"]:
        print("- 无")
        return
    for item in report["findings"]:
        print(f"- {item['category']} / {item['title']} (`{item['slug']}`): {item['message']} [{item['code']}]")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit feature flows from a user-experience completion perspective.")
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    args = parser.parse_args()

    report = build_report()
    if args.format == "markdown":
        print_markdown(report)
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
