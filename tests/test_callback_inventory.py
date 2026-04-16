from __future__ import annotations

import ast
import re
from pathlib import Path

from backend.features.admin.core.menu_dispatch import ADMIN_MENU_HANDLERS
from backend.features.admin.runtime import admin_runtime
from backend.features.admin.ui.admin_main import admin_main_menu

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"

ADMIN_RUNTIME_PREFIXES = (
    "adm:",
    "ali:",
    "gfw:",
    "grg:",
    "tsearch:",
    "crv:",
    "auc:",
    "btm:",
    "gm:",
    "guess:",
    "act:",
    "qpub:",
)

ALLOWED_DYNAMIC_CALLBACK_BUILDERS = {
    ("backend/shared/ui/base/builders.py", 161),
}

ALLOWED_DYNAMIC_ADMIN_MENU_BUILDERS = {
    ("backend/features/admin/core/navigation.py", 25),
    ("backend/features/admin/ui/admin_main_keyboards.py", 141),
    ("backend/features/admin/ui/admin_main_keyboards.py", 146),
}


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def _sample_expr(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.JoinedStr):
        pieces: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant):
                pieces.append(str(value.value))
            elif isinstance(value, ast.FormattedValue):
                pieces.append(_sample_formatted(value.value))
            else:
                return None
        return "".join(pieces)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _sample_expr(node.left)
        right = _sample_expr(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def _sample_formatted(node: ast.AST) -> str:
    if isinstance(node, ast.Constant):
        return str(node.value)
    if isinstance(node, ast.Name):
        name = node.id.lower()
        if name == "prefix":
            return "btned"
        if name in {"chat_id", "target_chat_id", "source_chat_id"} or name.endswith("chat_id"):
            return "-100123"
        if name.endswith("_id") or name in {"id", "row", "col", "page", "index", "offset", "count", "limit"}:
            return "123"
        if name == "direction":
            return "up"
        if name == "status":
            return "all"
        if name == "mode":
            return "on"
        return "x"
    if isinstance(node, ast.Attribute):
        attr = node.attr.lower()
        if attr == "id" or attr.endswith("_id"):
            return "123"
        if attr == "status":
            return "all"
    return "x"


def _callback_samples() -> list[tuple[str, int, str]]:
    samples: list[tuple[str, int, str]] = []
    for path in BACKEND_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rel_path = str(path.relative_to(PROJECT_ROOT))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _call_name(node) != "InlineKeyboardButton":
                continue
            for keyword in node.keywords:
                if keyword.arg != "callback_data":
                    continue
                sample = _sample_expr(keyword.value)
                if sample and sample != "_noop":
                    samples.append((rel_path, node.lineno, sample))
    return samples


def _callback_query_patterns() -> list[tuple[str, int, str]]:
    patterns: list[tuple[str, int, str]] = []
    for path in BACKEND_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rel_path = str(path.relative_to(PROJECT_ROOT))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _call_name(node) != "CallbackQueryHandler":
                continue
            for keyword in node.keywords:
                if keyword.arg != "pattern":
                    continue
                pattern = _sample_expr(keyword.value)
                if pattern:
                    patterns.append((rel_path, node.lineno, pattern))
    return patterns


def test_inline_keyboard_callbacks_have_registered_receivers() -> None:
    compiled_patterns = [
        (path, line, pattern, re.compile(pattern))
        for path, line, pattern in _callback_query_patterns()
    ]
    unmatched: list[tuple[str, int, str]] = []

    for path, line, callback_data in _callback_samples():
        if (path, line) in ALLOWED_DYNAMIC_CALLBACK_BUILDERS:
            continue
        if callback_data.startswith(ADMIN_RUNTIME_PREFIXES):
            continue
        if not any(regex.match(callback_data) for _, _, _, regex in compiled_patterns):
            unmatched.append((path, line, callback_data))

    assert unmatched == []


def test_known_regression_callbacks_are_now_registered() -> None:
    compiled_patterns = [re.compile(pattern) for _, _, pattern in _callback_query_patterns()]

    for callback_data in [
        "solitaire:cancel:-100123",
        "solitaire:menu:-100123",
        "inv:user:menu:-100123",
    ]:
        assert any(regex.match(callback_data) for regex in compiled_patterns), callback_data

    assert all(not sample.startswith("keywords:menu:") for _, _, sample in _callback_samples())


def test_admin_main_menu_actions_map_to_real_handlers() -> None:
    menu_callbacks = [
        button.callback_data
        for row in admin_main_menu(-100123).inline_keyboard
        for button in row
        if button.callback_data and button.callback_data.startswith("adm:menu:")
    ]
    menu_actions = {callback_data.split(":")[2] for callback_data in menu_callbacks}

    assert menu_actions - set(ADMIN_MENU_HANDLERS) == set()
    assert {
        action
        for action, handler_name in ADMIN_MENU_HANDLERS.items()
        if not hasattr(admin_runtime, handler_name)
    } == set()


def test_adm_menu_callbacks_use_explicit_menu_actions() -> None:
    malformed: list[tuple[str, int, str]] = []

    for path, line, callback_data in _callback_samples():
        if not callback_data.startswith("adm:menu:"):
            continue
        if (path, line) in ALLOWED_DYNAMIC_ADMIN_MENU_BUILDERS:
            continue
        parts = callback_data.split(":")
        menu_action = parts[2] if len(parts) > 2 else ""
        if re.fullmatch(r"-?\d+", menu_action) or menu_action not in ADMIN_MENU_HANDLERS:
            malformed.append((path, line, callback_data))

    assert malformed == []
