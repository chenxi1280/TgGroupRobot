from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from backend.features.automation.services.scheduled_message_service_validation import ScheduledMessageValidationMixin
from backend.platform.db.runtime.session import Database
from backend.platform.state.conversation_state_service import ConversationStateService
from backend.platform.telegram.errors import answer_callback_query_safely
from backend.shared.callback_parser import CallbackParser
from backend.shared.services.base import ValidationError
from backend.shared.services.permission_service import PermissionPolicyService

MAX_BUTTON_COLS = 4
TEXT_INPUT_STATE = "button_editor_text_input"
URL_INPUT_STATE = "button_editor_url_input"

ButtonCell = dict[str, str] | None
ButtonGrid = list[list[ButtonCell]]


@dataclass(slots=True)
class ButtonEditorContext:
    module_type: str
    target_chat_id: int
    entity_id: int
    row_index: int | None = None
    col_index: int | None = None


class ButtonLayoutEditorService:
    @staticmethod
    def sanitize_button_text(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValidationError("按钮文字不能为空。")
        if len(text) > 16:
            raise ValidationError("按钮文字过长，请控制在 16 个字符以内。")
        return text

    @staticmethod
    def normalize_button_url(value: str) -> str:
        return ScheduledMessageValidationMixin._normalize_button_url(str(value or "").strip())

    @classmethod
    def to_grid(cls, buttons: list | None) -> ButtonGrid:
        normalized = cls._normalize_existing_buttons(buttons or [])
        if not normalized:
            return [[]]
        grid: ButtonGrid = []
        for row in normalized:
            grid.append([{"text": item["text"], "url": item["url"]} for item in row])
        return cls._trim_grid(grid)

    @classmethod
    def add_button(
        cls,
        grid: ButtonGrid,
        row_index: int | None = None,
        col_index: int | None = None,
    ) -> tuple[ButtonGrid, int, int]:
        draft = cls._clone_grid(grid)
        if row_index is None or col_index is None:
            row_index, col_index = cls.first_empty_slot(draft)
        elif row_index < 0 or col_index < 0 or col_index >= MAX_BUTTON_COLS:
            raise ValidationError(f"按钮位置无效，每行最多 {MAX_BUTTON_COLS} 个按钮。")
        elif cls.get_cell(draft, row_index, col_index) is not None:
            raise ValidationError("该位置已经有按钮。")
        cls._set_cell(draft, row_index, col_index, {"text": "", "url": ""})
        return cls._trim_grid(draft), row_index, col_index

    @classmethod
    def clear_buttons(cls) -> ButtonGrid:
        return [[]]

    @classmethod
    def get_cell(cls, grid: ButtonGrid, row_index: int, col_index: int) -> dict[str, str] | None:
        if row_index < 0 or col_index < 0:
            return None
        if row_index >= len(grid):
            return None
        row = grid[row_index]
        if col_index >= len(row):
            return None
        cell = row[col_index]
        if cell is None:
            return None
        return {"text": str(cell.get("text", "")), "url": str(cell.get("url", ""))}

    @classmethod
    def update_button(
        cls,
        grid: ButtonGrid,
        row_index: int,
        col_index: int,
        *,
        text: str | None = None,
        url: str | None = None,
    ) -> ButtonGrid:
        draft = cls._clone_grid(grid)
        cell = cls.get_cell(draft, row_index, col_index)
        if cell is None:
            raise ValidationError("按钮不存在。")
        if text is not None:
            cell["text"] = text
        if url is not None:
            cell["url"] = url
        cls._set_cell(draft, row_index, col_index, cell)
        return cls._trim_grid(draft)

    @classmethod
    def delete_button(cls, grid: ButtonGrid, row_index: int, col_index: int) -> ButtonGrid:
        draft = cls._clone_grid(grid)
        if cls.get_cell(draft, row_index, col_index) is None:
            return cls._trim_grid(draft)
        cls._set_cell(draft, row_index, col_index, None)
        return cls._trim_grid(draft)

    @classmethod
    def move_button(
        cls,
        grid: ButtonGrid,
        row_index: int,
        col_index: int,
        direction: str,
    ) -> tuple[ButtonGrid, int, int, bool]:
        source = cls.get_cell(grid, row_index, col_index)
        if source is None:
            return cls._trim_grid(grid), row_index, col_index, False

        row_delta, col_delta = {
            "up": (-1, 0),
            "down": (1, 0),
            "left": (0, -1),
            "right": (0, 1),
        }.get(direction, (0, 0))
        target_row = row_index + row_delta
        target_col = col_index + col_delta
        if target_row < 0 or target_col < 0 or target_col >= MAX_BUTTON_COLS:
            return cls._trim_grid(grid), row_index, col_index, False

        draft = cls._clone_grid(grid)
        max_target_row = max(target_row, len(draft) - 1)
        while len(draft) <= max_target_row:
            draft.append([])
        target = cls.get_cell(draft, target_row, target_col)
        cls._set_cell(draft, row_index, col_index, target)
        cls._set_cell(draft, target_row, target_col, source)
        trimmed = cls._trim_grid(draft)
        if cls.get_cell(trimmed, target_row, target_col) == source:
            return trimmed, target_row, target_col, True
        return trimmed, row_index, col_index, False

    @classmethod
    def export_complete_buttons(cls, grid: ButtonGrid) -> list[list[dict[str, str]]]:
        rows: list[list[dict[str, str]]] = []
        for row in grid:
            exported_row: list[dict[str, str]] = []
            for cell in row:
                if cell is None:
                    continue
                text = str(cell.get("text", "")).strip()
                raw_url = str(cell.get("url", "")).strip()
                if not text or not raw_url:
                    continue
                exported_row.append({
                    "text": cls.sanitize_button_text(text),
                    "url": cls.normalize_button_url(raw_url),
                })
            if exported_row:
                for index in range(0, len(exported_row), MAX_BUTTON_COLS):
                    rows.append(exported_row[index:index + MAX_BUTTON_COLS])
        return rows

    @classmethod
    def display_rows(cls, grid: ButtonGrid) -> list[list[dict[str, Any]]]:
        draft = cls._trim_grid(grid)
        add_row, add_col = cls.first_empty_slot(draft)
        rows_to_render = max(len(draft), add_row + 1, 1)
        rows: list[list[dict[str, Any]]] = []
        for row_index in range(rows_to_render):
            row: list[dict[str, Any]] = []
            row_cells = draft[row_index] if row_index < len(draft) else []
            occupied_cols = [
                col_index
                for col_index in range(min(len(row_cells), MAX_BUTTON_COLS))
                if cls.get_cell(draft, row_index, col_index) is not None
            ]
            if occupied_cols:
                show_until = min(max(occupied_cols) + 2, MAX_BUTTON_COLS)
            else:
                show_until = 1
            for col_index in range(show_until):
                cell = cls.get_cell(draft, row_index, col_index)
                if cell is not None:
                    label = str(cell.get("text", "")).strip() or "⚠️ 空"
                    row.append({"kind": "cell", "label": label, "row": row_index, "col": col_index})
                    continue
                has_later_button = any(
                    cls.get_cell(draft, row_index, later_col) is not None
                    for later_col in range(col_index + 1, MAX_BUTTON_COLS)
                )
                row.append({
                    "kind": "empty" if has_later_button else "add",
                    "label": "⚠️ 空" if has_later_button else "➕ 按钮",
                    "row": row_index,
                    "col": col_index,
                })
            if row:
                rows.append(row)
        return rows or [[{"kind": "add", "label": "➕ 按钮", "row": 0, "col": 0}]]

    @classmethod
    def first_empty_slot(cls, grid: ButtonGrid) -> tuple[int, int]:
        draft = cls._trim_grid(grid)
        for row_index in range(max(len(draft), 1)):
            for col_index in range(MAX_BUTTON_COLS):
                if cls.get_cell(draft, row_index, col_index) is None:
                    return row_index, col_index
        return len(draft), 0

    @classmethod
    def _normalize_existing_buttons(cls, buttons: list) -> list[list[dict[str, str]]]:
        try:
            normalized = ScheduledMessageValidationMixin.normalize_buttons_config(buttons)
        except ValidationError:
            normalized = []
            for raw_row in buttons if isinstance(buttons, list) else []:
                if not isinstance(raw_row, list):
                    continue
                row: list[dict[str, str]] = []
                for raw_cell in raw_row:
                    if not isinstance(raw_cell, dict):
                        continue
                    text = str(raw_cell.get("text", "")).strip()
                    url = str(raw_cell.get("url", raw_cell.get("link", ""))).strip()
                    if not text or not url:
                        continue
                    try:
                        row.append({"text": text, "url": cls.normalize_button_url(url)})
                    except ValidationError:
                        continue
                if row:
                    normalized.append(row)
        normalized_rows: list[list[dict[str, str]]] = []
        for row in normalized:
            for index in range(0, len(row), MAX_BUTTON_COLS):
                chunk = row[index:index + MAX_BUTTON_COLS]
                if chunk:
                    normalized_rows.append(chunk)
        return normalized_rows

    @staticmethod
    def _clone_grid(grid: ButtonGrid) -> ButtonGrid:
        return [
            [None if cell is None else {"text": str(cell.get("text", "")), "url": str(cell.get("url", ""))} for cell in row]
            for row in grid
        ]

    @classmethod
    def _trim_grid(cls, grid: ButtonGrid) -> ButtonGrid:
        draft = cls._clone_grid(grid)
        while draft and not any(cell is not None for cell in draft[-1]):
            draft.pop()
        return draft or [[]]

    @staticmethod
    def _set_cell(grid: ButtonGrid, row_index: int, col_index: int, value: ButtonCell) -> None:
        while len(grid) <= row_index:
            grid.append([])
        while len(grid[row_index]) <= col_index:
            grid[row_index].append(None)
        grid[row_index][col_index] = value


def _module_title(module_type: str) -> str:
    return {
        "ads": "轮播消息",
        "auto_reply": "自动回复",
        "welcome": "欢迎消息",
        "invite": "邀请链接",
    }.get(module_type, "按钮配置")


def _module_capability(module_type: str) -> str:
    if module_type == "ads":
        return "automation"
    if module_type == "auto_reply":
        return "moderation"
    return "settings"


def _module_return_callback(editor_ctx: ButtonEditorContext) -> str:
    if editor_ctx.module_type == "ads":
        return f"ads:detail:{editor_ctx.target_chat_id}:{editor_ctx.entity_id}"
    if editor_ctx.module_type == "auto_reply":
        return f"auto_reply:detail:{editor_ctx.target_chat_id}:{editor_ctx.entity_id}"
    if editor_ctx.module_type == "welcome":
        return f"adm:wel:{editor_ctx.target_chat_id}:detail:{editor_ctx.entity_id}"
    return f"inv:home:{editor_ctx.target_chat_id}"


def _draft_key(editor_ctx: ButtonEditorContext) -> str:
    return f"{editor_ctx.module_type}:{editor_ctx.target_chat_id}:{editor_ctx.entity_id}"


def _draft_store(context: ContextTypes.DEFAULT_TYPE) -> dict[str, ButtonGrid]:
    return context.user_data.setdefault("button_editor_drafts", {})


async def _load_buttons_for_module(session, editor_ctx: ButtonEditorContext) -> list[list[dict[str, str]]]:
    if editor_ctx.module_type == "ads":
        from backend.features.automation.services.ad_rotation_service import get_rotation_item

        item = await get_rotation_item(session, editor_ctx.entity_id)
        if item is None or item.chat_id != editor_ctx.target_chat_id:
            raise ValidationError("轮播消息不存在。")
        return list(getattr(item, "buttons", None) or [])

    if editor_ctx.module_type == "auto_reply":
        from backend.features.moderation.services.auto_reply_service import get_auto_reply_rule_in_chat

        item = await get_auto_reply_rule_in_chat(session, editor_ctx.target_chat_id, editor_ctx.entity_id)
        if item is None:
            raise ValidationError("自动回复规则不存在。")
        return list(getattr(item, "buttons", None) or [])

    if editor_ctx.module_type == "welcome":
        from backend.features.verification.welcome_service import WelcomeService

        item = await WelcomeService.get_message(session, editor_ctx.target_chat_id, editor_ctx.entity_id)
        return list(getattr(item, "buttons", None) or [])

    if editor_ctx.module_type == "invite":
        from backend.shared.services.chat_service import get_chat_settings

        settings = await get_chat_settings(session, editor_ctx.target_chat_id)
        return list(getattr(settings, "invite_link_buttons", None) or [])

    raise ValidationError("不支持的按钮模块。")


async def _save_buttons_for_module(
    session,
    editor_ctx: ButtonEditorContext,
    buttons: list[list[dict[str, str]]],
) -> None:
    if editor_ctx.module_type == "ads":
        from backend.features.automation.services.ad_rotation_service import update_rotation_item

        await update_rotation_item(session, editor_ctx.entity_id, buttons=buttons)
        return

    if editor_ctx.module_type == "auto_reply":
        from backend.features.moderation.services.auto_reply_service import update_auto_reply_rule

        updated = await update_auto_reply_rule(
            session,
            editor_ctx.entity_id,
            chat_id=editor_ctx.target_chat_id,
            buttons=buttons,
        )
        if updated is None:
            raise ValidationError("自动回复规则不存在。")
        return

    if editor_ctx.module_type == "welcome":
        from backend.features.verification.welcome_service import WelcomeService

        await WelcomeService.update_field(
            session,
            editor_ctx.target_chat_id,
            editor_ctx.entity_id,
            buttons=buttons,
        )
        return

    if editor_ctx.module_type == "invite":
        from backend.shared.services.chat_service import get_chat_settings

        settings = await get_chat_settings(session, editor_ctx.target_chat_id)
        settings.invite_link_buttons = buttons
        await session.flush()
        return

    raise ValidationError("不支持的按钮模块。")


async def _show_module_detail(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    editor_ctx: ButtonEditorContext,
) -> None:
    if editor_ctx.module_type == "ads":
        from backend.features.automation.ads_handler import _ads_handler

        await _ads_handler.show_detail(update, context, editor_ctx.target_chat_id, editor_ctx.entity_id)
        return

    if editor_ctx.module_type == "auto_reply":
        from backend.features.moderation.auto_reply_views import show_auto_reply_rule_detail

        await show_auto_reply_rule_detail(
            update,
            context,
            chat_id=editor_ctx.target_chat_id,
            rule_id=editor_ctx.entity_id,
        )
        return

    if editor_ctx.module_type == "welcome":
        from backend.features.admin.admin_handler import _admin_handler

        await _admin_handler._show_welcome_detail_menu(update, context, editor_ctx.target_chat_id, editor_ctx.entity_id)
        return

    if editor_ctx.module_type == "invite":
        from backend.features.invite.invite_shared import _invite_link_handler

        await _invite_link_handler.show_menu(update, context, editor_ctx.target_chat_id)
        return

    raise ValidationError("不支持的按钮模块。")


async def _ensure_draft(
    session,
    context: ContextTypes.DEFAULT_TYPE,
    editor_ctx: ButtonEditorContext,
) -> ButtonGrid:
    drafts = _draft_store(context)
    key = _draft_key(editor_ctx)
    if key not in drafts:
        buttons = await _load_buttons_for_module(session, editor_ctx)
        drafts[key] = ButtonLayoutEditorService.to_grid(buttons)
    return ButtonLayoutEditorService._clone_grid(drafts[key])


def _save_draft_to_memory(
    context: ContextTypes.DEFAULT_TYPE,
    editor_ctx: ButtonEditorContext,
    grid: ButtonGrid,
) -> None:
    _draft_store(context)[_draft_key(editor_ctx)] = ButtonLayoutEditorService._clone_grid(grid)


async def _persist_draft(
    session,
    context: ContextTypes.DEFAULT_TYPE,
    editor_ctx: ButtonEditorContext,
    grid: ButtonGrid,
) -> None:
    _save_draft_to_memory(context, editor_ctx, grid)
    buttons = ButtonLayoutEditorService.export_complete_buttons(grid)
    await _save_buttons_for_module(session, editor_ctx, buttons)


def build_layout_keyboard(editor_ctx: ButtonEditorContext, grid: ButtonGrid) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for row in ButtonLayoutEditorService.display_rows(grid):
        keyboard_row: list[InlineKeyboardButton] = []
        for item in row:
            kind = item["kind"]
            if kind == "cell":
                callback_data = (
                    f"btned:detail:{editor_ctx.module_type}:{editor_ctx.target_chat_id}:{editor_ctx.entity_id}:"
                    f"{item['row']}:{item['col']}"
                )
            elif kind in {"add", "empty"}:
                callback_data = (
                    f"btned:add:{editor_ctx.module_type}:{editor_ctx.target_chat_id}:{editor_ctx.entity_id}:"
                    f"{item['row']}:{item['col']}"
                )
            else:
                callback_data = "btned:noop"
            keyboard_row.append(InlineKeyboardButton(str(item["label"]), callback_data=callback_data))
        rows.append(keyboard_row)
    rows.append([
        InlineKeyboardButton("♻️ 清空按钮", callback_data=f"btned:clear:{editor_ctx.module_type}:{editor_ctx.target_chat_id}:{editor_ctx.entity_id}"),
        InlineKeyboardButton("🔙 返回", callback_data=_module_return_callback(editor_ctx)),
    ])
    return InlineKeyboardMarkup(rows)


def build_detail_keyboard(editor_ctx: ButtonEditorContext) -> InlineKeyboardMarkup:
    row = editor_ctx.row_index or 0
    col = editor_ctx.col_index or 0
    prefix = f"btned"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "编辑按钮文字",
                callback_data=f"{prefix}:text:{editor_ctx.module_type}:{editor_ctx.target_chat_id}:{editor_ctx.entity_id}:{row}:{col}",
            ),
            InlineKeyboardButton(
                "编辑跳转链接",
                callback_data=f"{prefix}:url:{editor_ctx.module_type}:{editor_ctx.target_chat_id}:{editor_ctx.entity_id}:{row}:{col}",
            ),
        ],
        [InlineKeyboardButton("⬆️ 上移", callback_data=f"{prefix}:move:{editor_ctx.module_type}:{editor_ctx.target_chat_id}:{editor_ctx.entity_id}:{row}:{col}:up")],
        [
            InlineKeyboardButton("⬅️ 左移", callback_data=f"{prefix}:move:{editor_ctx.module_type}:{editor_ctx.target_chat_id}:{editor_ctx.entity_id}:{row}:{col}:left"),
            InlineKeyboardButton("➡️ 右移", callback_data=f"{prefix}:move:{editor_ctx.module_type}:{editor_ctx.target_chat_id}:{editor_ctx.entity_id}:{row}:{col}:right"),
        ],
        [
            InlineKeyboardButton("⬇️ 下移", callback_data=f"{prefix}:move:{editor_ctx.module_type}:{editor_ctx.target_chat_id}:{editor_ctx.entity_id}:{row}:{col}:down"),
            InlineKeyboardButton("❌ 删除按钮", callback_data=f"{prefix}:delete:{editor_ctx.module_type}:{editor_ctx.target_chat_id}:{editor_ctx.entity_id}:{row}:{col}"),
        ],
        [InlineKeyboardButton("🔙 返回", callback_data=f"{prefix}:open:{editor_ctx.module_type}:{editor_ctx.target_chat_id}:{editor_ctx.entity_id}")],
    ])


async def show_layout_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    editor_ctx: ButtonEditorContext,
    *,
    session=None,
) -> None:
    close_session = False
    if session is None:
        db: Database = context.application.bot_data["db"]
        session_cm = db.session_factory()
        session = await session_cm.__aenter__()
        close_session = True
    try:
        draft = await _ensure_draft(session, context, editor_ctx)
        text = (
            f"{_module_title(editor_ctx.module_type)}｜按钮布局\n\n"
            "先配置按钮布局（每行最多4个按钮） 再点击按钮配置文案"
        )
        keyboard = build_layout_keyboard(editor_ctx, draft)
        if update.callback_query is not None:
            await update.callback_query.edit_message_text(text=text, reply_markup=keyboard)
        elif update.effective_message is not None:
            await update.effective_message.reply_text(text=text, reply_markup=keyboard)
    finally:
        if close_session:
            await session.commit()
            await session_cm.__aexit__(None, None, None)


async def show_button_detail(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    editor_ctx: ButtonEditorContext,
    *,
    session=None,
) -> None:
    close_session = False
    if session is None:
        db: Database = context.application.bot_data["db"]
        session_cm = db.session_factory()
        session = await session_cm.__aenter__()
        close_session = True
    try:
        draft = await _ensure_draft(session, context, editor_ctx)
        cell = ButtonLayoutEditorService.get_cell(
            draft,
            int(editor_ctx.row_index or 0),
            int(editor_ctx.col_index or 0),
        )
        if cell is None:
            raise ValidationError("按钮不存在。")
        text = (
            f"{_module_title(editor_ctx.module_type)} | 编辑按钮信息\n\n"
            f"按钮文字：{cell.get('text') or '未配置'}\n"
            f"按钮链接：{cell.get('url') or '未配置'}\n\n"
            "💡 为了按钮美观，建议按钮文字不超过 4 个字\n"
            "🔗 链接请填写完整，自己最好点击访问一下，注意半角全角符号！"
        )
        keyboard = build_detail_keyboard(editor_ctx)
        if update.callback_query is not None:
            await update.callback_query.edit_message_text(text=text, reply_markup=keyboard)
        elif update.effective_message is not None:
            await update.effective_message.reply_text(text=text, reply_markup=keyboard)
    finally:
        if close_session:
            await session.commit()
            await session_cm.__aexit__(None, None, None)


def _parse_editor_context(callback_data: str) -> tuple[str, ButtonEditorContext, str | None]:
    cb = CallbackParser.parse(callback_data)
    action = cb.get(1)
    module_type = cb.get(2)
    target_chat_id = cb.get_int(3)
    entity_id = cb.get_int(4)
    row_index = cb.get_int_optional(5)
    col_index = cb.get_int_optional(6)
    extra = cb.get(7)
    return action, ButtonEditorContext(module_type, target_chat_id, entity_id, row_index, col_index), extra


async def button_layout_editor_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    if q.data == "btned:noop":
        return

    action, editor_ctx, extra = _parse_editor_context(q.data or "")
    allowed, error_text = await PermissionPolicyService.require_manage(
        context,
        editor_ctx.target_chat_id,
        update.effective_user.id,
        capability=_module_capability(editor_ctx.module_type),
    )
    if not allowed:
        await answer_callback_query_safely(update, error_text or "没有权限", show_alert=True)
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        try:
            if action == "open":
                await show_layout_menu(update, context, editor_ctx, session=session)
                await session.commit()
                return

            if action == "add":
                draft = await _ensure_draft(session, context, editor_ctx)
                next_grid, row_index, col_index = ButtonLayoutEditorService.add_button(
                    draft,
                    row_index=editor_ctx.row_index,
                    col_index=editor_ctx.col_index,
                )
                await _persist_draft(session, context, editor_ctx, next_grid)
                await session.commit()
                await show_button_detail(
                    update,
                    context,
                    ButtonEditorContext(
                        editor_ctx.module_type,
                        editor_ctx.target_chat_id,
                        editor_ctx.entity_id,
                        row_index,
                        col_index,
                    ),
                    session=session,
                )
                return

            if action == "clear":
                next_grid = ButtonLayoutEditorService.clear_buttons()
                await _persist_draft(session, context, editor_ctx, next_grid)
                await session.commit()
                await show_layout_menu(update, context, editor_ctx, session=session)
                return

            if action == "detail":
                await show_button_detail(update, context, editor_ctx, session=session)
                await session.commit()
                return

            if action in {"text", "url"}:
                state_type = TEXT_INPUT_STATE if action == "text" else URL_INPUT_STATE
                await ConversationStateService.start(
                    session,
                    chat_id=update.effective_chat.id,
                    user_id=update.effective_user.id,
                    state_type=state_type,
                    state_data={
                        "module_type": editor_ctx.module_type,
                        "target_chat_id": editor_ctx.target_chat_id,
                        "entity_id": editor_ctx.entity_id,
                        "row_index": editor_ctx.row_index,
                        "col_index": editor_ctx.col_index,
                    },
                )
                await session.commit()
                prompt = "👉 请输入按钮文字；发送“清空”可暂时留空。" if action == "text" else "👉 请输入跳转链接；发送“清空”可暂时留空。"
                await q.edit_message_text(
                    text=f"{_module_title(editor_ctx.module_type)} | 编辑按钮信息\n\n{prompt}",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton(
                            "🔙 返回",
                            callback_data=(
                                f"btned:detail:{editor_ctx.module_type}:{editor_ctx.target_chat_id}:{editor_ctx.entity_id}:"
                                f"{editor_ctx.row_index}:{editor_ctx.col_index}"
                            ),
                        )
                    ]]),
                )
                return

            if action == "delete":
                draft = await _ensure_draft(session, context, editor_ctx)
                next_grid = ButtonLayoutEditorService.delete_button(
                    draft,
                    int(editor_ctx.row_index or 0),
                    int(editor_ctx.col_index or 0),
                )
                await _persist_draft(session, context, editor_ctx, next_grid)
                await session.commit()
                await show_layout_menu(update, context, editor_ctx, session=session)
                return

            if action == "move":
                draft = await _ensure_draft(session, context, editor_ctx)
                next_grid, next_row, next_col, changed = ButtonLayoutEditorService.move_button(
                    draft,
                    int(editor_ctx.row_index or 0),
                    int(editor_ctx.col_index or 0),
                    str(extra or ""),
                )
                await _persist_draft(session, context, editor_ctx, next_grid)
                await session.commit()
                if not changed:
                    await answer_callback_query_safely(update, "已经到边界了", show_alert=False)
                await show_button_detail(
                    update,
                    context,
                    ButtonEditorContext(
                        editor_ctx.module_type,
                        editor_ctx.target_chat_id,
                        editor_ctx.entity_id,
                        next_row,
                        next_col,
                    ),
                    session=session,
                )
                return
        except ValidationError as exc:
            await session.commit()
            await answer_callback_query_safely(update, str(exc), show_alert=True)
            return

    await answer_callback_query_safely(update, "无效操作", show_alert=True)


async def handle_button_layout_editor_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state,
    message_text: str,
) -> None:
    if update.effective_user is None or update.effective_message is None:
        return

    editor_ctx = ButtonEditorContext(
        module_type=str((state.state_data or {}).get("module_type") or ""),
        target_chat_id=int((state.state_data or {}).get("target_chat_id") or 0),
        entity_id=int((state.state_data or {}).get("entity_id") or 0),
        row_index=int((state.state_data or {}).get("row_index") or 0),
        col_index=int((state.state_data or {}).get("col_index") or 0),
    )
    if not editor_ctx.module_type or editor_ctx.target_chat_id == 0:
        await update.effective_message.reply_text("按钮配置上下文已失效，请重新进入。")
        return

    allowed, error_text = await PermissionPolicyService.require_manage(
        context,
        editor_ctx.target_chat_id,
        update.effective_user.id,
        capability=_module_capability(editor_ctx.module_type),
    )
    if not allowed:
        await update.effective_message.reply_text(error_text or "没有权限")
        return

    try:
        draft = await _ensure_draft(session, context, editor_ctx)
        cell = ButtonLayoutEditorService.get_cell(
            draft,
            int(editor_ctx.row_index or 0),
            int(editor_ctx.col_index or 0),
        )
        if cell is None:
            raise ValidationError("按钮不存在。")

        normalized_text = (message_text or "").strip()
        if state.state_type == TEXT_INPUT_STATE:
            value = "" if normalized_text in {"清空", "/clear"} else ButtonLayoutEditorService.sanitize_button_text(normalized_text)
            next_grid = ButtonLayoutEditorService.update_button(
                draft,
                int(editor_ctx.row_index or 0),
                int(editor_ctx.col_index or 0),
                text=value,
            )
        elif state.state_type == URL_INPUT_STATE:
            value = "" if normalized_text in {"清空", "/clear"} else ButtonLayoutEditorService.normalize_button_url(normalized_text)
            next_grid = ButtonLayoutEditorService.update_button(
                draft,
                int(editor_ctx.row_index or 0),
                int(editor_ctx.col_index or 0),
                url=value,
            )
        else:
            await update.effective_message.reply_text("当前状态不支持按钮编辑。")
            return

        await _persist_draft(session, context, editor_ctx, next_grid)
        await ConversationStateService.clear(session, state.chat_id, update.effective_user.id)
        if state.chat_id != update.effective_user.id:
            await ConversationStateService.clear(session, update.effective_user.id, update.effective_user.id)
        await session.commit()
    except ValidationError as exc:
        await session.commit()
        await update.effective_message.reply_text(str(exc))
        return

    await show_button_detail(update, context, editor_ctx, session=session)
