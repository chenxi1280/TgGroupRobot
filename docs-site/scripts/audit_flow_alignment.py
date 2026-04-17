from __future__ import annotations

import ast
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOCS_SITE = ROOT / "docs-site"
FLOWS_DIR = DOCS_SITE / "src/content/flows"
CATALOG_PATH = DOCS_SITE / "src/content/features/catalog.json"
MENU_DISPATCH_PATH = ROOT / "backend/features/admin/core/menu_dispatch.py"
RUNTIME_PATH = ROOT / "backend/features/admin/runtime.py"
PRIVATE_REGISTRY_PATH = ROOT / "backend/platform/telegram/private_config_registry.py"
ENUMS_PATH = ROOT / "backend/platform/db/schema/models/enums.py"
BACKEND_DIR = ROOT / "backend"

STATIC_CALLBACK_ROOTS = {
    "_noop",
    "ads",
    "afcfg",
    "ascfg",
    "auto_reply",
    "autoreply",
    "autodel",
    "banned_word",
    "banned_word_delete_",
    "banned_word_toggle_",
    "btmrun",
    "btned",
    "gg",
    "gmrun",
    "group",
    "inh",
    "inv",
    "join_lottery_",
    "join_solitaire",
    "keywords",
    "lbs",
    "lot",
    "pts",
    "renew",
    "sm",
    "sol",
    "solitaire",
    "sub",
    "verification",
    "vfy",
    "vfy_help",
}


@dataclass(frozen=True)
class Finding:
    severity: str
    slug: str
    screen: str
    button: str
    message: str


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dict_keys_from_assignment(path: Path, assignment: str) -> set[str]:
    module = ast.parse(path.read_text(encoding="utf-8"))
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == assignment and isinstance(node.value, ast.Dict):
                    return {key.value for key in node.value.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)}
    return set()


def registered_states() -> set[str]:
    text = PRIVATE_REGISTRY_PATH.read_text(encoding="utf-8")
    states = set(re.findall(r'"([A-Za-z0-9_]+)"', text))
    states.update(re.findall(r'=\s*"([A-Za-z0-9_]+)"\s*(?:#|$)', ENUMS_PATH.read_text(encoding="utf-8"), flags=re.MULTILINE))
    return states


def backend_source_text() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in BACKEND_DIR.rglob("*.py")
        if path.is_file()
    )


def callback_roots_from_backend(source_text: str, prefix_handlers: set[str]) -> set[str]:
    roots = set(STATIC_CALLBACK_ROOTS)
    roots.update(prefix_handlers)

    for pattern in re.findall(r'pattern\s*=\s*r?["\']([^"\']+)["\']', source_text):
        stripped = pattern.lstrip("^")
        group_match = re.match(r"\(([^)]+)\):", stripped)
        if group_match:
            roots.update(part for part in group_match.group(1).split("|") if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", part))
        root_match = re.match(r"([A-Za-z_][A-Za-z0-9_]*)(?::|_|\\|\$|\[|$)", stripped)
        if root_match:
            root = root_match.group(1)
            if "_" in stripped and not stripped.startswith(root + ":"):
                underscore_root = re.match(r"([A-Za-z_][A-Za-z0-9_]*_)", stripped)
                if underscore_root:
                    roots.add(underscore_root.group(1))
            roots.add(root)

    for raw in re.findall(r'callback_data\s*=\s*f?["\']([^"\']+)["\']', source_text):
        if not raw or raw.startswith("{"):
            continue
        if raw.startswith("_noop"):
            roots.add("_noop")
            continue
        before_placeholder = raw.split("{", 1)[0]
        if ":" in before_placeholder:
            root = before_placeholder.split(":", 1)[0]
        else:
            root = before_placeholder
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*_?$", root):
            roots.add(root)

    return {root for root in roots if len(root) >= 2 or root == "gm"}


def normalize_callback(callback_data: str) -> str:
    replacements = {
        "{auction_id}": "9001",
        "{chat_id}": "-100123456",
        "{event_id}": "9001",
        "{item_id}": "9001",
        "{level_id}": "9001",
        "{link_id}": "9001",
        "{lottery_id}": "9001",
        "{order_id}": "9001",
        "{product_id}": "9001",
        "{rule_id}": "9001",
        "{solitaire_id}": "9001",
        "{task_id}": "A1B2C3",
        "{type_id}": "9001",
        "{welcome_id}": "9001",
        "{page}": "0",
    }
    for source, target in replacements.items():
        callback_data = callback_data.replace(source, target)
    return callback_data


def callback_root(callback_data: str) -> str:
    callback = normalize_callback(callback_data)
    if ":" in callback:
        return callback.split(":", 1)[0]
    return callback


def callback_matches_known_root(callback_data: str, known_roots: set[str]) -> bool:
    callback = normalize_callback(callback_data)
    root = callback_root(callback)
    return root in known_roots or any(callback.startswith(known_root) for known_root in known_roots if known_root.endswith("_"))


def coverage_prefix_is_known(prefix: str, menu_keys: set[str], adm_actions: set[str], known_roots: set[str], source_text: str) -> bool:
    normalized = normalize_callback(prefix)
    parts = normalized.split(":")
    if parts[0] == "adm":
        if len(parts) < 2:
            return False
        action = parts[1]
        if action not in adm_actions:
            return False
        if action == "menu" and len(parts) >= 3:
            return parts[2] in menu_keys
        return True
    if callback_matches_known_root(prefix, known_roots):
        return True
    return prefix in source_text


def audit_flow(flow: dict, menu_keys: set[str], adm_actions: set[str], prefix_handlers: set[str], states: set[str], known_roots: set[str], source_text: str) -> list[Finding]:
    findings: list[Finding] = []
    slug = flow.get("slug", "<unknown>")
    coverage = flow.get("coverage") or {}
    callbacks = [
        button.get("callbackData", "")
        for screen in flow.get("screens", [])
        for row in screen.get("keyboard", [])
        for button in row
        if button.get("callbackData") and not button.get("callbackData", "").startswith(("http://", "https://", "tg://"))
    ]

    if coverage.get("alignmentStatus") != "ok":
        findings.append(
            Finding("P2", slug, "coverage", "alignmentStatus", "coverage.alignmentStatus 必须为 ok，不能保留 needsReview。")
        )

    callback_prefixes = coverage.get("callbackPrefixes") or []
    if coverage.get("mode") == "complete" and callback_prefixes == ["adm:menu:"]:
        findings.append(
            Finding(
                "P2",
                slug,
                "coverage",
                "callbackPrefixes",
                "完整复刻页面只声明了宽泛 adm:menu:，无法证明该功能的真实二级回调已覆盖。",
            )
        )

    for prefix in callback_prefixes:
        if prefix == "adm:menu:":
            findings.append(Finding("P2", slug, "coverage", prefix, "coverage.callbackPrefixes 不能使用宽泛 adm:menu:。"))
            continue
        if not coverage_prefix_is_known(prefix, menu_keys, adm_actions, known_roots, source_text):
            findings.append(Finding("P2", slug, "coverage", prefix, "coverage.callbackPrefixes 未能在后端路由、菜单或 callback 前缀中确认。"))
        if not any(callback.startswith(prefix) for callback in callbacks):
            findings.append(Finding("P2", slug, "coverage", prefix, "coverage.callbackPrefixes 未被该 flow 中任何按钮实际使用。"))

    for state in coverage.get("inputStates") or []:
        if state not in states:
            findings.append(
                Finding("P1", slug, "coverage", state, "声明的 input state 在私聊配置注册表或 ConversationStateType 中不存在。")
            )

    for screen in flow.get("screens", []):
        screen_id = screen.get("id", "<screen>")
        for row in screen.get("keyboard", []):
            for button in row:
                label = button.get("label", "<button>")
                callback_data = button.get("callbackData", "")
                flow_action = button.get("action", "")
                if callback_data.startswith(("http://", "https://", "tg://")):
                    continue
                callback = normalize_callback(callback_data)
                parts = callback.split(":")
                prefix = parts[0] if parts else ""

                if prefix == "adm":
                    if len(parts) < 2 or parts[1] not in adm_actions:
                        findings.append(
                            Finding(
                                "P1",
                                slug,
                                screen_id,
                                label,
                                f"callback `{callback_data}` 的 adm action 未注册；真实入口需要是 {sorted(adm_actions)} 之一。",
                            )
                        )
                        continue

                    if parts[1] == "menu":
                        menu_key = parts[2] if len(parts) > 2 else ""
                        if menu_key and menu_key not in menu_keys:
                            findings.append(
                                Finding("P1", slug, screen_id, label, f"菜单 key `{menu_key}` 不在 ADMIN_MENU_HANDLERS 中。")
                            )
                        if flow_action in {"toggle", "input", "confirm"}:
                            findings.append(
                                Finding(
                                    "P1",
                                    slug,
                                    screen_id,
                                    label,
                                    f"`{callback_data}` 只是菜单入口，但 flow action 写成 `{flow_action}`，真实后端不会执行该动作。",
                                )
                            )
                        if len(parts) > 4:
                            findings.append(
                                Finding(
                                    "P2",
                                    slug,
                                    screen_id,
                                    label,
                                    f"`{callback_data}` 在 `adm:menu` 后追加了额外段；_handle_menu 只按菜单 key 分发，额外段不会按文档语义处理。",
                                )
                            )
                    continue

                if prefix in prefix_handlers or callback_matches_known_root(callback_data, known_roots):
                    continue

                findings.append(
                    Finding("P2", slug, screen_id, label, f"callback 前缀 `{prefix}` 未在本轮已知路由中确认。")
                )

    return findings


def main() -> int:
    catalog = load_json(CATALOG_PATH)["features"]
    expected_slugs = {feature["slug"] for feature in catalog}
    menu_keys = dict_keys_from_assignment(MENU_DISPATCH_PATH, "ADMIN_MENU_HANDLERS")
    adm_actions = dict_keys_from_assignment(RUNTIME_PATH, "ADM_ACTION_HANDLERS")
    prefix_handlers = dict_keys_from_assignment(RUNTIME_PATH, "PREFIX_HANDLERS")
    states = registered_states()
    source_text = backend_source_text()
    known_roots = callback_roots_from_backend(source_text, prefix_handlers)

    findings: list[Finding] = []
    for flow_path in sorted(FLOWS_DIR.glob("*.json")):
        flow = load_json(flow_path)
        if flow.get("slug") not in expected_slugs:
            findings.append(Finding("P2", flow.get("slug", flow_path.stem), "file", flow_path.name, "flow slug 不在 catalog 中。"))
        findings.extend(audit_flow(flow, menu_keys, adm_actions, prefix_handlers, states, known_roots, source_text))

    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1

    print(json.dumps({
        "flows": len(list(FLOWS_DIR.glob("*.json"))),
        "findings": len(findings),
        "counts": counts,
        "sample": [finding.__dict__ for finding in findings[:80]],
    }, ensure_ascii=False, indent=2))
    return 1 if any(finding.severity in {"P1", "P2"} for finding in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
