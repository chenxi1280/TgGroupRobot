from __future__ import annotations

import ast
import argparse
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from re import Pattern


ROOT = Path(__file__).resolve().parents[2]
DOCS_SITE = ROOT / "docs-site"
FLOWS_DIR = DOCS_SITE / "src/content/flows"
CATALOG_PATH = DOCS_SITE / "src/content/features/catalog.json"
MENU_DISPATCH_PATH = ROOT / "backend/features/admin/core/menu_dispatch.py"
RUNTIME_PATH = ROOT / "backend/features/admin/runtime.py"
PRIVATE_REGISTRY_PATH = ROOT / "backend/platform/telegram/private_config_registry.py"
ROUTER_REGISTRY_PATH = ROOT / "backend/app/router_registry.py"
GROUP_PIPELINE_PATH = ROOT / "backend/platform/telegram/group_pipeline.py"
ENUMS_PATH = ROOT / "backend/platform/db/schema/models/enums.py"
BACKEND_DIR = ROOT / "backend"
TESTS_DIR = ROOT / "tests"
TRUTH_TABLE_PATH = ROOT / "docs/setup/06_feature_truth_table.md"

DUPLICATE_CATEGORIES = (
    "同一能力多入口",
    "旧入口兼容",
    "真实重复实现",
)

GENERIC_TEST_TOKENS = {
    "action",
    "actions",
    "activity",
    "admin",
    "backend",
    "callback",
    "callbacks",
    "config",
    "controller",
    "core",
    "create",
    "detail",
    "dispatch",
    "edit",
    "feature",
    "features",
    "group",
    "handler",
    "handlers",
    "helper",
    "helpers",
    "home",
    "hooks",
    "input",
    "inputs",
    "keyboards",
    "list",
    "main",
    "menu",
    "menus",
    "message",
    "messages",
    "module",
    "ops",
    "page",
    "panel",
    "router",
    "runtime",
    "service",
    "services",
    "setting",
    "settings",
    "shared",
    "telegram",
    "test",
    "tests",
    "toggle",
    "ui",
    "view",
    "views",
}

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


@dataclass(frozen=True)
class CallbackEvidence:
    kind: str
    raw: str
    path: str
    regex: Pattern[str]
    broad: bool = False


@dataclass
class AuditStats:
    callbacks: int = 0
    template_matches: int = 0
    route_matches: int = 0
    broad_route_only: int = 0
    input_buttons: int = 0
    toggle_buttons: int = 0
    confirm_buttons: int = 0


@dataclass(frozen=True)
class GroupListener:
    name: str
    handler: str
    path: str


@dataclass(frozen=True)
class DuplicateCandidate:
    category: str
    slugs: list[str]
    reason: str
    evidence: list[str]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_flows() -> list[dict]:
    return [load_json(path) for path in sorted(FLOWS_DIR.glob("*.json"))]


def dict_keys_from_assignment(path: Path, assignment: str) -> set[str]:
    module = ast.parse(path.read_text(encoding="utf-8"))
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == assignment and isinstance(node.value, ast.Dict):
                    return {key.value for key in node.value.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)}
    return set()


def truth_table_statuses() -> dict[str, str]:
    if not TRUTH_TABLE_PATH.exists():
        return {}
    statuses: dict[str, str] = {}
    for line in TRUTH_TABLE_PATH.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or "---" in line or "模块" in line:
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) >= 2 and cells[0] and cells[1]:
            statuses[cells[0]] = cells[1]
    return statuses


def callback_values(flow: dict) -> list[str]:
    return [
        button.get("callbackData", "")
        for screen in flow.get("screens", [])
        for row in screen.get("keyboard", [])
        for button in row
        if button.get("callbackData") and not button.get("callbackData", "").startswith(("http://", "https://", "tg://"))
    ]


def callback_match_paths(callbacks: list[str], callback_evidence: list[CallbackEvidence]) -> list[str]:
    paths: set[str] = set()
    for callback_data in callbacks:
        for evidence in callback_evidence_matches(callback_data, callback_evidence):
            paths.add(evidence.path)
    return sorted(paths)


def router_names() -> list[str]:
    text = ROUTER_REGISTRY_PATH.read_text(encoding="utf-8")
    return sorted(set(re.findall(r"\b([A-Z][A-Za-z0-9]+Router)\(", text)))


def group_listener_inventory() -> list[GroupListener]:
    text = GROUP_PIPELINE_PATH.read_text(encoding="utf-8")
    imports: dict[str, str] = {}
    module = ast.parse(text)
    for node in ast.walk(module):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                imports[alias.asname or alias.name] = node.module.replace(".", "/") + ".py"

    listeners: list[GroupListener] = []
    for name, handler in re.findall(r'\("([^"]+)",\s*([A-Za-z_][A-Za-z0-9_]*)\)', text):
        listeners.append(GroupListener(name=name, handler=handler, path=imports.get(handler, "")))
    return listeners


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


def expression_to_pattern(node: ast.AST) -> tuple[str, str] | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return re.escape(node.value), node.value

    if isinstance(node, ast.JoinedStr):
        pattern = ""
        raw = ""
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                pattern += re.escape(value.value)
                raw += value.value
            elif isinstance(value, ast.FormattedValue):
                pattern += r"[^:]+"
                raw += "{expr}"
        return pattern, raw

    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = expression_to_pattern(node.left)
        right = expression_to_pattern(node.right)
        if left is None or right is None:
            return None
        return left[0] + right[0], left[1] + right[1]

    if isinstance(node, ast.IfExp):
        return expression_to_pattern(node.body)

    if isinstance(node, ast.Lambda):
        return expression_to_pattern(node.body)

    return None


def expression_to_patterns(node: ast.AST) -> list[tuple[str, str]]:
    if isinstance(node, ast.IfExp):
        return [
            pattern
            for branch in (node.body, node.orelse)
            if (pattern := expression_to_pattern(branch)) is not None
        ]
    pattern = expression_to_pattern(node)
    return [pattern] if pattern is not None else []


def string_constant(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def is_broad_route_pattern(pattern: str) -> bool:
    stripped = pattern.lstrip("^")
    if stripped.startswith("(adm|ali|gfw|grg|tsearch|crv|auc|btm|gm|guess|act|qpub):"):
        return True
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?::|_).*", stripped))


def callback_evidence_from_backend() -> list[CallbackEvidence]:
    evidence: list[CallbackEvidence] = []
    for path in BACKEND_DIR.rglob("*.py"):
        if not path.is_file():
            continue
        try:
            module = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue

        rel_path = str(path.relative_to(ROOT))
        for node in ast.walk(module):
            if isinstance(node, ast.Assign):
                for pattern, raw in expression_to_patterns(node.value):
                    if ":" in raw:
                        evidence.append(
                            CallbackEvidence(
                                kind="template",
                                raw=raw,
                                path=rel_path,
                                regex=re.compile(f"^{pattern}$"),
                            )
                        )

            if isinstance(node, ast.keyword) and node.arg == "callback_data":
                for pattern, raw in expression_to_patterns(node.value):
                    evidence.append(
                        CallbackEvidence(
                            kind="template",
                            raw=raw,
                            path=rel_path,
                            regex=re.compile(f"^{pattern}$"),
                        )
                    )

            if isinstance(node, ast.Call):
                if call_name(node) == "action_button" and len(node.args) >= 2:
                    for pattern, raw in expression_to_patterns(node.args[1]):
                        evidence.append(
                            CallbackEvidence(
                                kind="template",
                                raw=raw,
                                path=rel_path,
                                regex=re.compile(f"^{pattern}$"),
                            )
                        )

                for keyword in node.keywords:
                    if keyword.arg in {"back_callback", "callback_factory", "custom_callback"}:
                        for pattern, raw in expression_to_patterns(keyword.value):
                            evidence.append(
                                CallbackEvidence(
                                    kind="template",
                                    raw=raw,
                                    path=rel_path,
                                    regex=re.compile(f"^{pattern}$"),
                                )
                            )
                        continue

                    if keyword.arg != "pattern":
                        continue
                    raw_pattern = string_constant(keyword.value)
                    if not raw_pattern:
                        continue
                    try:
                        regex = re.compile(raw_pattern)
                    except re.error:
                        continue
                    evidence.append(
                        CallbackEvidence(
                            kind="route",
                            raw=raw_pattern,
                            path=rel_path,
                            regex=regex,
                            broad=is_broad_route_pattern(raw_pattern),
                        )
                    )

    return evidence


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


def callback_evidence_matches(callback_data: str, evidence: list[CallbackEvidence]) -> list[CallbackEvidence]:
    callback = normalize_callback(callback_data)
    return [item for item in evidence if item.regex.search(callback)]


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


def audit_flow(
    flow: dict,
    menu_keys: set[str],
    adm_actions: set[str],
    prefix_handlers: set[str],
    states: set[str],
    known_roots: set[str],
    source_text: str,
    callback_evidence: list[CallbackEvidence],
    stats: AuditStats,
) -> list[Finding]:
    findings: list[Finding] = []
    slug = flow.get("slug", "<unknown>")
    coverage = flow.get("coverage") or {}
    screens = flow.get("screens", [])
    reachable_screens = {flow.get("entryScreen")}
    callbacks = [
        button.get("callbackData", "")
        for screen in screens
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

    for screen in screens:
        screen_id = screen.get("id", "<screen>")
        for row in screen.get("keyboard", []):
            for button in row:
                label = button.get("label", "<button>")
                callback_data = button.get("callbackData", "")
                flow_action = button.get("action", "")
                if callback_data.startswith(("http://", "https://", "tg://")):
                    continue
                target = button.get("target")
                if target:
                    reachable_screens.add(target)
                if flow_action == "input":
                    stats.input_buttons += 1
                    target_screen = next((item for item in screens if item.get("id") == target), None)
                    if not isinstance(target_screen, dict) or not target_screen.get("input"):
                        findings.append(
                            Finding(
                                "P2",
                                slug,
                                screen_id,
                                label,
                                f"flow action 为 input，但目标 screen `{target}` 没有 input 配置，手册输入流程不能闭环。",
                            )
                        )
                elif flow_action == "toggle":
                    stats.toggle_buttons += 1
                elif flow_action == "confirm":
                    stats.confirm_buttons += 1

                stats.callbacks += 1
                evidence_matches = callback_evidence_matches(callback_data, callback_evidence)
                template_matches = [item for item in evidence_matches if item.kind == "template"]
                route_matches = [item for item in evidence_matches if item.kind == "route"]
                if template_matches:
                    stats.template_matches += 1
                elif route_matches:
                    stats.route_matches += 1
                    if any(item.broad for item in route_matches):
                        stats.broad_route_only += 1
                        match = next(item for item in route_matches if item.broad)
                        findings.append(
                            Finding(
                                "P3",
                                slug,
                                screen_id,
                                label,
                                f"`{callback_data}` 只能匹配宽路由 `{match.raw}`（{match.path}），未找到后端生成的同形 callback 模板；需要人工确认分支语义。",
                            )
                        )
                else:
                    findings.append(
                        Finding(
                            "P2",
                            slug,
                            screen_id,
                            label,
                            f"`{callback_data}` 未匹配到后端生成模板或 CallbackQueryHandler pattern。",
                        )
                    )

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

    input_screens = [screen.get("id") for screen in screens if screen.get("input")]
    for input_screen in input_screens:
        if input_screen not in reachable_screens:
            findings.append(
                Finding("P3", slug, str(input_screen), "input", "该输入 screen 没有被任何按钮或输入示例 target 引用，手册可能存在孤立步骤。")
            )

    for screen in screens:
        if not screen.get("input"):
            continue
        screen_id = screen.get("id", "<screen>")
        buttons = [
            button
            for row in screen.get("keyboard", [])
            for button in row
        ]
        if not any(button.get("action") == "back" or "返回" in str(button.get("label", "")) for button in buttons):
            findings.append(Finding("P3", slug, screen_id, "input", "输入 screen 缺少返回按钮，管理员输错或放弃时闭环不清晰。"))

    return findings


def findings_by_severity(findings: list[Finding]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1
    return counts


def tokenize(value: str) -> set[str]:
    tokens = {
        token
        for token in re.split(r"[^A-Za-z0-9]+", value.lower())
        if len(token) >= 3 and token not in GENERIC_TEST_TOKENS
    }
    return tokens


def test_index() -> dict[str, str]:
    return {
        str(path.relative_to(ROOT)): path.read_text(encoding="utf-8", errors="ignore").lower()
        for path in sorted(TESTS_DIR.glob("test_*.py"))
    }


def source_file_tokens(source_files: list[str]) -> set[str]:
    tokens: set[str] = set()
    for source_file in source_files:
        path = Path(source_file)
        tokens.update(tokenize(path.stem))
        for parent in path.parts:
            if parent not in {"backend", "features", "docs-site", "src", "content"}:
                tokens.update(tokenize(parent))
    return tokens


def callback_tokens(callback_prefixes: list[str]) -> set[str]:
    tokens: set[str] = set()
    for prefix in callback_prefixes:
        callback = normalize_callback(prefix).strip(":")
        parts = re.split(r"[:_]+", callback)
        tokens.update(part.lower() for part in parts if len(part) >= 3 and part.lower() not in GENERIC_TEST_TOKENS)
    return tokens


def matched_test_files(flow: dict, tests: dict[str, str]) -> list[str]:
    coverage = flow.get("coverage") or {}
    source_files = coverage.get("sourceFiles") or []
    callback_prefixes = coverage.get("callbackPrefixes") or []
    states = coverage.get("inputStates") or []
    tokens = set()
    tokens.update(tokenize(flow.get("slug", "")))
    tokens.update(source_file_tokens(source_files))
    tokens.update(callback_tokens(callback_prefixes))
    tokens.update(tokenize(" ".join(states)))

    exact_needles = {flow.get("slug", "")}
    exact_needles.update(source_files)
    exact_needles.update(states)
    exact_needles.update(prefix for prefix in callback_prefixes if prefix and not prefix.startswith("adm:menu"))
    exact_needles = {needle.lower() for needle in exact_needles if needle}

    matches: list[tuple[int, str]] = []
    for path, text in tests.items():
        basename = Path(path).stem.lower()
        score = 0
        for token in tokens:
            if token in basename:
                score += 3
            elif token in text:
                score += 1
        for needle in exact_needles:
            if needle and needle in text:
                score += 4
        if score >= 3:
            matches.append((score, path))

    return [path for _, path in sorted(matches, key=lambda item: (-item[0], item[1]))[:8]]


def listener_matches_for_flow(flow: dict, listeners: list[GroupListener]) -> list[dict]:
    coverage = flow.get("coverage") or {}
    source_files = " ".join(coverage.get("sourceFiles") or []).lower()
    tokens = tokenize(flow.get("slug", ""))
    tokens.update(source_file_tokens(coverage.get("sourceFiles") or []))
    result: list[dict] = []
    for listener in listeners:
        haystack = f"{listener.name} {listener.handler} {listener.path}".lower()
        if listener.path and listener.path.lower() in source_files:
            result.append(listener.__dict__)
            continue
        if tokens and (tokens & tokenize(haystack)):
            result.append(listener.__dict__)
    return result


def risk_for_flow(flow: dict, findings: list[Finding], tests: list[str]) -> tuple[str, list[str]]:
    slug = flow.get("slug", "")
    slug_findings = [finding for finding in findings if finding.slug == slug]
    counts = findings_by_severity(slug_findings)
    reasons: list[str] = []
    if counts.get("P1") or counts.get("P2"):
        reasons.append(f"P1/P2 阻断项：{counts.get('P1', 0) + counts.get('P2', 0)}")
        return "high", reasons
    if counts.get("P3"):
        reasons.append(f"P3 分支复核项：{counts['P3']}")
    if not tests:
        reasons.append("未匹配到测试文件")
    if flow.get("status") != "已闭环":
        reasons.append(f"状态不是已闭环：{flow.get('status')}")
    if counts.get("P3") or not tests:
        return "medium", reasons
    return "low", ["已匹配路由、文档和测试基线"]


def feature_matrix(
    flows: list[dict],
    catalog: list[dict],
    findings: list[Finding],
    callback_evidence: list[CallbackEvidence],
    tests: dict[str, str],
    truth_status: dict[str, str],
    menu_keys: set[str],
    routers: list[str],
    listeners: list[GroupListener],
) -> list[dict]:
    catalog_by_slug = {feature["slug"]: feature for feature in catalog}
    rows: list[dict] = []
    for flow in flows:
        slug = flow.get("slug", "")
        catalog_feature = catalog_by_slug.get(slug, {})
        coverage = flow.get("coverage") or {}
        source_files = sorted(set(coverage.get("sourceFiles") or []))
        tests_for_flow = matched_test_files(flow, tests)
        risk_level, risk_reasons = risk_for_flow(flow, findings, tests_for_flow)
        truth_names = flow.get("truthTableNames") or catalog_feature.get("truthTableNames") or []
        callback_prefixes = coverage.get("callbackPrefixes") or []
        callback_paths = callback_match_paths(callback_values(flow), callback_evidence)
        entry = catalog_feature.get("entry") or {}

        rows.append(
            {
                "slug": slug,
                "title": flow.get("title") or catalog_feature.get("title"),
                "category": flow.get("category") or catalog_feature.get("category"),
                "status": flow.get("status") or catalog_feature.get("status"),
                "truthTableNames": truth_names,
                "truthTableStatuses": {name: truth_status.get(name, "未在真值表中找到") for name in truth_names},
                "entry": {
                    "label": entry.get("label"),
                    "command": entry.get("command"),
                    "menuKeys": entry.get("menuKeys", []),
                    "registeredMenuKeys": sorted(set(entry.get("menuKeys", [])) & menu_keys),
                },
                "callbackRoutes": {
                    "prefixes": callback_prefixes,
                    "matchedPaths": callback_paths,
                    "sourceFiles": source_files,
                },
                "groupListeners": listener_matches_for_flow(flow, listeners),
                "privateInputStates": coverage.get("inputStates") or [],
                "runtimeServices": source_files,
                "routerRegistry": routers,
                "testFiles": tests_for_flow,
                "riskLevel": risk_level,
                "riskReasons": risk_reasons,
            }
        )
    return rows


def duplicate_signature(flow: dict) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    coverage = flow.get("coverage") or {}
    return (
        tuple(sorted(coverage.get("callbackPrefixes") or [])),
        tuple(sorted(coverage.get("inputStates") or [])),
        tuple(sorted(coverage.get("sourceFiles") or [])),
    )


def legacy_compat_candidates(flows: list[dict]) -> list[DuplicateCandidate]:
    candidates: list[DuplicateCandidate] = []
    for flow in flows:
        callbacks = callback_values(flow)
        legacy_callbacks = [
            callback
            for callback in callbacks
            if "back_to_menu" in callback or ":todo:" in callback or callback.startswith(("pts:todo:", "adm:todo:"))
        ]
        if legacy_callbacks:
            candidates.append(
                DuplicateCandidate(
                    category="旧入口兼容",
                    slugs=[flow.get("slug", "")],
                    reason="flow 中仍有旧式 callback，当前仅作为兼容入口审计，不在本轮删除。",
                    evidence=legacy_callbacks,
                )
            )

    source_text = backend_source_text()
    redirect_features = sorted(set(re.findall(r'"([A-Za-z_]+)":\s*self\._show_[A-Za-z0-9_]+', source_text)))
    if redirect_features:
        candidates.append(
            DuplicateCandidate(
                category="旧入口兼容",
                slugs=redirect_features,
                reason="admin todo/旧入口会重定向到新版工作台，属于保留兼容路径。",
                evidence=["backend/features/admin/core/menu_dispatch.py"],
            )
        )
    return candidates


def implementation_duplicate_candidates(flows: list[dict]) -> list[DuplicateCandidate]:
    groups: dict[tuple[str, ...], list[dict]] = defaultdict(list)
    for flow in flows:
        service_files = tuple(
            sorted(
                source_file
                for source_file in (flow.get("coverage") or {}).get("sourceFiles", [])
                if "/services/" in source_file or source_file.endswith("_service.py")
            )
        )
        if service_files:
            groups[service_files].append(flow)

    candidates: list[DuplicateCandidate] = []
    for service_files, grouped_flows in groups.items():
        slugs = [flow.get("slug", "") for flow in grouped_flows]
        if len(slugs) > 1:
            candidates.append(
                DuplicateCandidate(
                    category="真实重复实现",
                    slugs=slugs,
                    reason="多个 flow 共享同一组 service 文件，后续合并前需确认是复用还是重复实现。",
                    evidence=list(service_files),
                )
            )
    return candidates


def duplicate_candidates(flows: list[dict]) -> list[DuplicateCandidate]:
    candidates: list[DuplicateCandidate] = []
    groups: dict[tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]], list[dict]] = defaultdict(list)
    for flow in flows:
        groups[duplicate_signature(flow)].append(flow)

    for signature, grouped_flows in groups.items():
        slugs = [flow.get("slug", "") for flow in grouped_flows]
        if len(slugs) <= 1:
            continue
        callbacks, states, source_files = signature
        candidates.append(
            DuplicateCandidate(
                category="同一能力多入口",
                slugs=slugs,
                reason="多个用户入口共用同一组 callback、私聊状态和 sourceFiles，应保留入口并按同一能力测试。",
                evidence=[
                    f"callbackPrefixes={list(callbacks)}",
                    f"inputStates={list(states)}",
                    f"sourceFiles={list(source_files)}",
                ],
            )
        )

    candidates.extend(legacy_compat_candidates(flows))
    candidates.extend(implementation_duplicate_candidates(flows))
    return candidates


def duplicate_summary(candidates: list[DuplicateCandidate]) -> dict[str, int]:
    counts = {category: 0 for category in DUPLICATE_CATEGORIES}
    for candidate in candidates:
        counts[candidate.category] = counts.get(candidate.category, 0) + 1
    return counts


def matrix_counts(matrix: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in matrix:
        risk_level = row["riskLevel"]
        counts[risk_level] = counts.get(risk_level, 0) + 1
    return counts


def p3_branch_review_items(findings: list[Finding]) -> list[dict]:
    return [
        finding.__dict__
        for finding in findings
        if finding.severity == "P3" and "宽路由" in finding.message
    ]


def build_payload(
    findings: list[Finding],
    stats: AuditStats,
    matrix: list[dict],
    duplicates: list[DuplicateCandidate],
) -> dict:
    return {
        "flows": len(list(FLOWS_DIR.glob("*.json"))),
        "callbacks": stats.callbacks,
        "templateMatches": stats.template_matches,
        "routeOnlyMatches": stats.route_matches,
        "broadRouteOnlyMatches": stats.broad_route_only,
        "inputButtons": stats.input_buttons,
        "toggleButtons": stats.toggle_buttons,
        "confirmButtons": stats.confirm_buttons,
        "findings": len(findings),
        "counts": findings_by_severity(findings),
        "matrixCounts": matrix_counts(matrix),
        "coverageMatrix": matrix,
        "duplicateSummary": duplicate_summary(duplicates),
        "duplicateCandidates": [candidate.__dict__ for candidate in duplicates],
        "p3BranchReview": p3_branch_review_items(findings),
        "sample": [finding.__dict__ for finding in findings[:80]],
    }


def print_markdown_report(
    findings: list[Finding],
    stats: AuditStats,
    matrix: list[dict],
    duplicates: list[DuplicateCandidate],
) -> None:
    payload = build_payload(findings, stats, matrix, duplicates)
    print("# 用户手册键盘流程反向审计报告")
    print()
    print("## 摘要")
    print(f"- Flow 文件：{payload['flows']}")
    print(f"- 手册按钮 callback：{payload['callbacks']}")
    print(f"- 后端同形 callback 模板匹配：{payload['templateMatches']}")
    print(f"- 仅路由 pattern 匹配：{payload['routeOnlyMatches']}")
    print(f"- 仅宽路由兜底匹配：{payload['broadRouteOnlyMatches']}")
    print(f"- 输入按钮：{payload['inputButtons']}")
    print(f"- 开关按钮：{payload['toggleButtons']}")
    print(f"- 确认按钮：{payload['confirmButtons']}")
    print(f"- Findings：{payload['findings']}，分布：{payload['counts']}")
    print(f"- 功能覆盖矩阵：{len(payload['coverageMatrix'])} 项，风险分布：{payload['matrixCounts']}")
    print(f"- 重复功能候选：{len(payload['duplicateCandidates'])} 项，分类：{payload['duplicateSummary']}")
    print()
    print("## 结论")
    if any(finding.severity in {"P1", "P2"} for finding in findings):
        print("- 存在 P1/P2 问题，需要修复后再认为手册流程与真实功能对齐。")
    else:
        print("- 未发现 P1/P2 阻断项；所有手册 callback 都能进入真实模板或后端路由。")
    if payload["broadRouteOnlyMatches"]:
        print("- 仍有按钮只能证明到达宽路由入口，已作为 P3 标出，适合下一轮人工沿 handler 分支复核。")
    print()
    print("## 功能覆盖矩阵")
    print("| 功能 | 入口 | callback/source | 私聊状态 | 群监听 | 测试 | 风险 |")
    print("|---|---|---:|---:|---:|---:|---|")
    for row in matrix:
        entry_label = row["entry"].get("label") or "-"
        source_count = len(set(row["callbackRoutes"]["matchedPaths"]) | set(row["callbackRoutes"]["sourceFiles"]))
        print(
            "| {title} (`{slug}`) | {entry} | {sources} | {states} | {listeners} | {tests} | {risk} |".format(
                title=row["title"],
                slug=row["slug"],
                entry=entry_label,
                sources=source_count,
                states=len(row["privateInputStates"]),
                listeners=len(row["groupListeners"]),
                tests=len(row["testFiles"]),
                risk=row["riskLevel"],
            )
        )
    print()
    print("## 重复功能候选")
    if duplicates:
        for candidate in duplicates:
            print(f"- {candidate.category}：{', '.join(candidate.slugs)}。{candidate.reason}")
    else:
        print("- 无")
    print()
    print("## P3 分支复核清单")
    p3_items = payload["p3BranchReview"]
    if p3_items:
        for item in p3_items:
            print(f"- `{item['slug']}` / `{item['screen']}` / `{item['button']}`：{item['message']}")
    else:
        print("- 无")
    print()
    print("## Findings")
    if not findings:
        print("- 无")
        return
    for finding in findings:
        print(f"- {finding.severity} `{finding.slug}` / `{finding.screen}` / `{finding.button}`：{finding.message}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit docs-site flow callbacks against real backend routes.")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--all-findings", action="store_true", help="Print all findings in JSON output instead of the first 80.")
    args = parser.parse_args()

    catalog = load_json(CATALOG_PATH)["features"]
    flows = load_flows()
    expected_slugs = {feature["slug"] for feature in catalog}
    menu_keys = dict_keys_from_assignment(MENU_DISPATCH_PATH, "ADMIN_MENU_HANDLERS")
    adm_actions = dict_keys_from_assignment(RUNTIME_PATH, "ADM_ACTION_HANDLERS")
    prefix_handlers = dict_keys_from_assignment(RUNTIME_PATH, "PREFIX_HANDLERS")
    states = registered_states()
    source_text = backend_source_text()
    known_roots = callback_roots_from_backend(source_text, prefix_handlers)
    callback_evidence = callback_evidence_from_backend()
    truth_status = truth_table_statuses()
    tests = test_index()
    routers = router_names()
    listeners = group_listener_inventory()
    stats = AuditStats()

    findings: list[Finding] = []
    for flow in flows:
        if flow.get("slug") not in expected_slugs:
            flow_slug = flow.get("slug", "<unknown>")
            findings.append(Finding("P2", flow_slug, "file", f"{flow_slug}.json", "flow slug 不在 catalog 中。"))
        findings.extend(audit_flow(flow, menu_keys, adm_actions, prefix_handlers, states, known_roots, source_text, callback_evidence, stats))

    matrix = feature_matrix(
        flows,
        catalog,
        findings,
        callback_evidence,
        tests,
        truth_status,
        menu_keys,
        routers,
        listeners,
    )
    duplicates = duplicate_candidates(flows)

    if args.format == "markdown":
        print_markdown_report(findings, stats, matrix, duplicates)
    else:
        payload = build_payload(findings, stats, matrix, duplicates)
        if args.all_findings:
            payload["findingsDetail"] = [finding.__dict__ for finding in findings]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if any(finding.severity in {"P1", "P2"} for finding in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
