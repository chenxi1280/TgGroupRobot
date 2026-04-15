from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.shared import button_layout_editor
from backend.shared.button_layout_editor import (
    ButtonEditorContext,
    ButtonLayoutEditorService,
    build_layout_keyboard,
    handle_button_layout_editor_input,
)


def test_button_layout_editor_round_trip_and_compact_holes() -> None:
    grid = ButtonLayoutEditorService.to_grid([
        [{"text": "A", "url": "https://a.com"}, {"text": "B", "url": "https://b.com"}],
        [{"text": "C", "url": "https://c.com"}],
    ])

    grid = ButtonLayoutEditorService.delete_button(grid, 0, 1)
    exported = ButtonLayoutEditorService.export_complete_buttons(grid)

    assert exported == [[
        {"text": "A", "url": "https://a.com"},
        {"text": "C", "url": "https://c.com"},
    ]]


def test_button_layout_editor_add_button_uses_first_empty_slot() -> None:
    grid = ButtonLayoutEditorService.to_grid([
        [{"text": "A", "url": "https://a.com"}, {"text": "B", "url": "https://b.com"}],
    ])
    grid = ButtonLayoutEditorService.delete_button(grid, 0, 0)

    next_grid, row_index, col_index = ButtonLayoutEditorService.add_button(grid)

    assert (row_index, col_index) == (0, 0)
    assert ButtonLayoutEditorService.get_cell(next_grid, 0, 0) == {"text": "", "url": ""}


def test_button_layout_editor_move_supports_horizontal_and_vertical() -> None:
    grid = ButtonLayoutEditorService.to_grid([
        [{"text": "A", "url": "https://a.com"}, {"text": "B", "url": "https://b.com"}],
        [{"text": "C", "url": "https://c.com"}],
    ])

    grid, row_index, col_index, changed = ButtonLayoutEditorService.move_button(grid, 0, 1, "down")
    assert changed is True
    assert (row_index, col_index) == (1, 1)

    grid, row_index, col_index, changed = ButtonLayoutEditorService.move_button(grid, 1, 1, "left")
    assert changed is True
    assert (row_index, col_index) == (1, 0)
    assert ButtonLayoutEditorService.get_cell(grid, 1, 0) == {"text": "B", "url": "https://b.com"}


def test_button_layout_editor_move_boundary_is_noop() -> None:
    grid = ButtonLayoutEditorService.to_grid([[{"text": "A", "url": "https://a.com"}]])

    next_grid, row_index, col_index, changed = ButtonLayoutEditorService.move_button(grid, 0, 0, "left")

    assert changed is False
    assert (row_index, col_index) == (0, 0)
    assert ButtonLayoutEditorService.export_complete_buttons(next_grid) == [[{"text": "A", "url": "https://a.com"}]]


def test_build_layout_keyboard_shows_add_and_existing_buttons() -> None:
    keyboard = build_layout_keyboard(
        ButtonEditorContext("ads", -1001, 9),
        ButtonLayoutEditorService.to_grid([[{"text": "关注", "url": "https://t.me/demo"}]]),
    )

    first_row = keyboard.inline_keyboard[0]
    assert first_row[0].text == "关注"
    assert first_row[1].text == "➕ 按钮"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module_type", "entity_id"),
    [("ads", 9), ("auto_reply", 10), ("welcome", 12), ("invite", 0)],
)
async def test_button_layout_editor_input_persists_complete_buttons(monkeypatch, module_type: str, entity_id: int) -> None:
    saved: list[list[dict[str, str]]] = []
    shown: list[ButtonEditorContext] = []

    async def fake_save_buttons(session, editor_ctx, buttons):
        saved[:] = buttons

    async def fake_clear(session, chat_id: int, user_id: int):
        return None

    async def fake_commit():
        return None

    async def fake_show_button_detail(update, context, editor_ctx, *, session=None):
        shown.append(editor_ctx)

    monkeypatch.setattr(button_layout_editor, "_save_buttons_for_module", fake_save_buttons)
    monkeypatch.setattr(button_layout_editor.ConversationStateService, "clear", fake_clear)
    monkeypatch.setattr(button_layout_editor, "show_button_detail", fake_show_button_detail)

    state = SimpleNamespace(
        state_type="button_editor_text_input",
        chat_id=10001,
        state_data={
            "module_type": module_type,
            "target_chat_id": -1001,
            "entity_id": entity_id,
            "row_index": 0,
            "col_index": 0,
        },
    )
    context = SimpleNamespace(
        user_data={
            "button_editor_drafts": {
                f"{module_type}:-1001:{entity_id}": [[{"text": "", "url": "https://t.me/demo"}]],
            }
        },
    )
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=42),
        effective_message=SimpleNamespace(reply_text=lambda text: None),
    )
    session = SimpleNamespace(commit=fake_commit)

    async def fake_require_manage(_context, chat_id: int, user_id: int, capability: str = "manage"):
        return True, None

    monkeypatch.setattr(button_layout_editor.PermissionPolicyService, "require_manage", fake_require_manage)

    await handle_button_layout_editor_input(update, context, session, state, "新按钮")

    assert saved == [[{"text": "新按钮", "url": "https://t.me/demo"}]]
    assert shown and shown[0].module_type == module_type
