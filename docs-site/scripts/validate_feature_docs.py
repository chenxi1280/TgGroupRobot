from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOCS_SITE = ROOT / "docs-site"
CATALOG_PATH = DOCS_SITE / "src/content/features/catalog.json"
FLOWS_DIR = DOCS_SITE / "src/content/flows"
FEATURE_PAGES_DIR = DOCS_SITE / "src/content/docs/features"
TRUTH_TABLE_PATH = ROOT / "docs/setup/06_feature_truth_table.md"
MENU_KEYBOARD_PATH = ROOT / "backend/features/admin/ui/admin_main_keyboards.py"
MENU_DISPATCH_PATH = ROOT / "backend/features/admin/core/menu_dispatch.py"
RUNTIME_PATH = ROOT / "backend/features/admin/runtime.py"
BACKEND_DIR = ROOT / "backend"

IGNORED_MENU_KEYS = {
    "main": "主菜单本身不是功能页",
    "settings": "早期群设置聚合入口，当前对外功能已拆分",
}

VALID_CATEGORIES = {
    "群组核心",
    "入群风控",
    "内容审核",
    "积分运营",
    "消息自动化",
    "邀请增长",
    "群组扩展",
    "活动互动",
    "频道管理",
    "全局设置",
}

ALLOWED_FLOW_ACTIONS = {
    "goto",
    "back",
    "input",
    "toggle",
    "toast",
    "noop",
    "confirm",
    "external",
}

TARGETLESS_ACTIONS = {"toast", "noop", "external"}

ALLOWED_INPUT_TYPES = {"text", "media", "json", "buttons", "datetime", "number"}

STATIC_CALLBACK_ROOTS = {
    "ads",
    "auto_reply",
    "autodel",
    "banned_word",
    "banned_word_delete_",
    "banned_word_toggle_",
    "btmrun",
    "btned",
    "gg",
    "gmrun",
    "inh",
    "inv",
    "join_lottery_",
    "join_solitaire",
    "keywords",
    "lot",
    "pts",
    "renew",
    "sm",
    "sol",
    "solitaire",
    "sub",
}


def load_features() -> list[dict]:
    with CATALOG_PATH.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload["features"]


def truth_table_rows() -> dict[str, str]:
    rows: dict[str, str] = {}
    with TRUTH_TABLE_PATH.open(encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped.startswith("|"):
                continue
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            if len(cells) < 3:
                continue
            name = cells[0]
            if name in {"模块", "------"} or set(name) == {"-"}:
                continue
            if name:
                rows[name] = cells[1]
    return rows


def menu_keys_from_keyboard() -> set[str]:
    text = MENU_KEYBOARD_PATH.read_text(encoding="utf-8")
    return set(re.findall(r"adm:menu:([a-z_]+)(?::|\"|')", text))


def menu_keys_from_dispatch() -> set[str]:
    text = MENU_DISPATCH_PATH.read_text(encoding="utf-8")
    return set(re.findall(r'^\s+"([a-z_]+)":\s+"_show_', text, flags=re.MULTILINE))


def adm_actions_from_runtime() -> set[str]:
    module = ast.parse(RUNTIME_PATH.read_text(encoding="utf-8"))
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "ADM_ACTION_HANDLERS" and isinstance(node.value, ast.Dict):
                    return {key.value for key in node.value.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)}
    return set()


def backend_source_text() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in BACKEND_DIR.rglob("*.py")
        if path.is_file()
    )


def coverage_prefix_known(prefix: str, source_text: str, menu_keys: set[str], adm_actions: set[str]) -> bool:
    if prefix in source_text:
        return True
    parts = prefix.split(":")
    if parts[0] == "adm" and len(parts) >= 2:
        if parts[1] not in adm_actions:
            return False
        if parts[1] == "menu" and len(parts) >= 3:
            return parts[2] in menu_keys
        return True
    root = parts[0]
    return root in STATIC_CALLBACK_ROOTS or any(prefix.startswith(static_root) for static_root in STATIC_CALLBACK_ROOTS if static_root.endswith("_"))


def validate_flow(feature: dict, source_text: str, menu_keys: set[str], adm_actions: set[str]) -> list[str]:
    errors: list[str] = []
    slug = feature.get("slug", "<unknown>")
    title = feature.get("title", slug)
    mdx_path = FEATURE_PAGES_DIR / f"{slug}.mdx"
    flow_path = FLOWS_DIR / f"{slug}.json"

    if not mdx_path.exists():
        errors.append(f"{title} 缺少 MDX 页面: {mdx_path.relative_to(DOCS_SITE)}")
    if not flow_path.exists():
        errors.append(f"{title} 缺少 flow 数据: {flow_path.relative_to(DOCS_SITE)}")
        return errors

    try:
        flow = json.loads(flow_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"{title} flow JSON 解析失败: {exc}")
        return errors

    if flow.get("slug") != slug:
        errors.append(f"{title} flow slug 不一致: {flow.get('slug')} != {slug}")
    if flow.get("status") != feature.get("status"):
        errors.append(f"{title} flow 状态与 catalog 不一致: {flow.get('status')} != {feature.get('status')}")
    if flow.get("category") != feature.get("category"):
        errors.append(f"{title} flow 分类与 catalog 不一致: {flow.get('category')} != {feature.get('category')}")

    coverage = flow.get("coverage") or {}
    if coverage.get("mode") != "complete":
        errors.append(f"{title} flow coverage.mode 必须为 complete")
    callback_prefixes = coverage.get("callbackPrefixes") or []
    if not callback_prefixes:
        errors.append(f"{title} flow coverage.callbackPrefixes 不能为空")
    for prefix in callback_prefixes:
        if not coverage_prefix_known(prefix, source_text, menu_keys, adm_actions):
            errors.append(f"{title} coverage.callbackPrefixes 在后端源码中找不到: {prefix}")
    source_files = coverage.get("sourceFiles") or []
    if not source_files:
        errors.append(f"{title} flow coverage.sourceFiles 不能为空")
    for source_file in source_files:
        if not (ROOT / source_file).exists():
            errors.append(f"{title} coverage.sourceFiles 不存在: {source_file}")

    screens = flow.get("screens") or []
    if not screens:
        errors.append(f"{title} flow screens 不能为空")
        return errors
    screen_ids = [screen.get("id") for screen in screens]
    duplicate_screen_ids = {screen_id for screen_id in screen_ids if screen_ids.count(screen_id) > 1}
    if duplicate_screen_ids:
        errors.append(f"{title} flow 存在重复 screen id: {', '.join(sorted(duplicate_screen_ids))}")
    screen_id_set = {screen_id for screen_id in screen_ids if screen_id}
    entry_screen = flow.get("entryScreen")
    if entry_screen not in screen_id_set:
        errors.append(f"{title} entryScreen 不存在: {entry_screen}")

    for screen in screens:
        screen_id = screen.get("id", "<missing>")
        if not screen.get("title"):
            errors.append(f"{title}/{screen_id} 缺少 title")
        message = screen.get("message")
        if not isinstance(message, list) or not message:
            errors.append(f"{title}/{screen_id} message 必须是非空数组")
        keyboard = screen.get("keyboard")
        if not isinstance(keyboard, list) or not keyboard:
            errors.append(f"{title}/{screen_id} keyboard 必须是非空二维数组")
            continue
        input_config = screen.get("input")
        if input_config:
            input_type = input_config.get("type")
            if input_type not in ALLOWED_INPUT_TYPES:
                errors.append(f"{title}/{screen_id} input.type 无效: {input_type}")
            for example in input_config.get("examples", []) or []:
                target = example.get("target")
                if target and target not in screen_id_set:
                    errors.append(f"{title}/{screen_id} 输入示例 target 不存在: {target}")
        for row_index, row in enumerate(keyboard, start=1):
            if not isinstance(row, list) or not row:
                errors.append(f"{title}/{screen_id} 第 {row_index} 行按钮为空")
                continue
            for button_index, flow_button in enumerate(row, start=1):
                label = flow_button.get("label")
                action = flow_button.get("action")
                callback_data = flow_button.get("callbackData")
                target = flow_button.get("target")
                marker = f"{title}/{screen_id} 第 {row_index}-{button_index} 个按钮"
                if not label:
                    errors.append(f"{marker} 缺少 label")
                if not callback_data:
                    errors.append(f"{marker} 缺少 callbackData")
                if action not in ALLOWED_FLOW_ACTIONS:
                    errors.append(f"{marker} action 无效: {action}")
                    continue
                if action not in TARGETLESS_ACTIONS and target not in screen_id_set:
                    errors.append(f"{marker} target 不存在: {target}")

    return errors


def validate() -> list[str]:
    errors: list[str] = []
    features = load_features()
    slugs = [feature.get("slug") for feature in features]
    source_text = backend_source_text()
    menu_keys = (menu_keys_from_keyboard() | menu_keys_from_dispatch()) - set(IGNORED_MENU_KEYS)
    adm_actions = adm_actions_from_runtime()

    duplicates = {slug for slug in slugs if slugs.count(slug) > 1}
    if duplicates:
        errors.append(f"重复 slug: {', '.join(sorted(duplicates))}")

    required_fields = {
        "slug",
        "title",
        "category",
        "status",
        "entry",
        "prerequisites",
        "steps",
        "flowchart",
        "qa",
        "logicAudit",
    }
    for feature in features:
        title = feature.get("title", feature.get("slug", "<unknown>"))
        missing = sorted(required_fields - set(feature))
        if missing:
            errors.append(f"{title} 缺少字段: {', '.join(missing)}")
        category = feature.get("category")
        if category not in VALID_CATEGORIES:
            errors.append(f"{title} 分类无效: {category}")
        if len(feature.get("steps", [])) < 3 and not feature.get("singlePage"):
            errors.append(f"{title} 至少需要 3 个步骤，或显式 singlePage=true")
        if not feature.get("flowchart"):
            errors.append(f"{title} 缺少流程图")
        if not feature.get("logicAudit", {}).get("items"):
            errors.append(f"{title} 缺少逻辑检查结论")
        if not feature.get("qa"):
            errors.append(f"{title} 缺少 Q&A")
        errors.extend(validate_flow(feature, source_text, menu_keys, adm_actions))

    truth_rows = truth_table_rows()
    documented_truth: set[str] = set()
    for feature in features:
        feature_status = feature.get("status")
        title = feature.get("title", feature.get("slug", "<unknown>"))
        for name in feature.get("truthTableNames", []):
            documented_truth.add(name)
            truth_status = truth_rows.get(name)
            if truth_status is None:
                errors.append(f"{title} 引用了不存在的真值表条目: {name}")
            elif truth_status != feature_status:
                errors.append(
                    f"{title} 状态与真值表不一致: {name} 为 {truth_status}，页面为 {feature_status}"
                )

    missing_truth = set(truth_rows) - documented_truth
    if missing_truth:
        errors.append("真值表功能缺少页面映射: " + ", ".join(sorted(missing_truth)))

    documented_menu_keys = {
        key
        for feature in features
        for key in feature.get("entry", {}).get("menuKeys", [])
    }
    missing_menu = menu_keys - documented_menu_keys
    if missing_menu:
        errors.append("菜单入口缺少页面映射: " + ", ".join(sorted(missing_menu)))

    return errors


if __name__ == "__main__":
    problems = validate()
    if problems:
        for problem in problems:
            print(f"[docs-site] {problem}", file=sys.stderr)
        sys.exit(1)
    print("[docs-site] feature documentation catalog is complete.")
