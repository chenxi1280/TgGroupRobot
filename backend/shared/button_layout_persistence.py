from __future__ import annotations

import datetime as dt
import hashlib
from sqlalchemy import select
from backend.platform.db.schema.models.core import EditDraft, TgUser
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from backend.shared.button_layout_service import ButtonEditorContext, ButtonGrid, ButtonLayoutEditorService
from backend.shared.services.base import ValidationError

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
    loaders = {
        "ads": _load_ads_buttons,
        "auto_reply": _load_auto_reply_buttons,
        "welcome": _load_welcome_buttons,
        "invite": _load_invite_buttons,
    }
    loader = loaders.get(editor_ctx.module_type)
    if loader is None:
        raise ValidationError("不支持的按钮模块。")
    return await loader(session, editor_ctx)


async def _load_ads_buttons(session, editor_ctx: ButtonEditorContext) -> list[list[dict[str, str]]]:
    from backend.features.automation.services.ad_rotation_service import get_rotation_item

    item = await get_rotation_item(session, editor_ctx.entity_id)
    if item is None or item.chat_id != editor_ctx.target_chat_id:
        raise ValidationError("轮播消息不存在。")
    if item is None:
        raise ValidationError("编辑对象已删除。")
    await session.refresh(item, with_for_update=True)
    return list(getattr(item, "buttons", None) or [])


async def _load_auto_reply_buttons(session, editor_ctx: ButtonEditorContext) -> list[list[dict[str, str]]]:
    from backend.features.moderation.services.auto_reply_service import get_auto_reply_rule_in_chat

    item = await get_auto_reply_rule_in_chat(session, editor_ctx.target_chat_id, editor_ctx.entity_id)
    if item is None:
        raise ValidationError("自动回复规则不存在。")
    if item is None:
        raise ValidationError("编辑对象已删除。")
    await session.refresh(item, with_for_update=True)
    return list(getattr(item, "buttons", None) or [])


async def _load_welcome_buttons(session, editor_ctx: ButtonEditorContext) -> list[list[dict[str, str]]]:
    from backend.features.verification.welcome_service import WelcomeService

    item = await WelcomeService.get_message(session, editor_ctx.target_chat_id, editor_ctx.entity_id)
    if item is None:
        raise ValidationError("编辑对象已删除。")
    await session.refresh(item, with_for_update=True)
    return list(getattr(item, "buttons", None) or [])


async def _load_invite_buttons(session, editor_ctx: ButtonEditorContext) -> list[list[dict[str, str]]]:
    from backend.shared.services.chat_service import get_chat_settings

    settings = await get_chat_settings(session, editor_ctx.target_chat_id)
    await session.refresh(settings, with_for_update=True)
    return list(getattr(settings, "invite_link_buttons", None) or [])


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


async def _show_module_detail(update, context, editor_ctx):
    await update.effective_message.reply_text("按钮配置已保存，请返回功能页面查看。",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("返回功能页面", callback_data=_module_return_callback(editor_ctx))]]))


def _persistent_token(context, editor_ctx):
    user_id = context.user_data.get("button_editor_user_id")
    if not user_id:
        raise ValidationError("编辑身份不可用，请重新打开按钮配置。")
    return hashlib.sha256(f"buttons:{user_id}:{_draft_key(editor_ctx)}".encode()).hexdigest()[:32], user_id


async def _draft_record(session, context, editor_ctx):
    token, user_id = _persistent_token(context, editor_ctx)
    await session.execute(select(TgUser.id).where(TgUser.id == user_id).with_for_update())
    result = await session.execute(select(EditDraft).where(EditDraft.token == token,
        EditDraft.user_id == user_id).with_for_update())
    record = result.scalar_one_or_none()
    if record is not None and record.expires_at <= dt.datetime.now(dt.UTC):
        await session.delete(record)
        await session.flush()
        record = None
    if record is None:
        buttons = await _load_buttons_for_module(session, editor_ctx)
        grid = ButtonLayoutEditorService.to_grid(buttons, module_type=editor_ctx.module_type)
        record = EditDraft(token=token, user_id=user_id, chat_id=editor_ctx.target_chat_id,
            state_chat_id=user_id, state_type="button_layout_draft",
            state_data={"grid": grid, "base_buttons": buttons, "module_type": editor_ctx.module_type, "entity_id": editor_ctx.entity_id},
            expires_at=dt.datetime.now(dt.UTC)+dt.timedelta(days=7))
        session.add(record)
        await session.flush()
    return record


async def save_button_draft(session, context, editor_ctx):
    record = await _draft_record(session, context, editor_ctx)
    current = await _load_buttons_for_module(session, editor_ctx)
    if current != record.state_data["base_buttons"]:
        raise ValidationError("正式按钮已被其他人修改，草稿已保留；请重新载入正式版本后编辑。")
    grid = record.state_data["grid"]
    buttons = ButtonLayoutEditorService.export_complete_buttons(grid, module_type=editor_ctx.module_type)
    # Incomplete cells must be corrected rather than silently dropped at save.
    complete_count = sum(len(row) for row in buttons)
    filled_count = sum(1 for row in grid for cell in row if cell)
    if complete_count < filled_count:
        raise ValidationError("仍有按钮缺少文字或操作，请补齐后保存。")
    if "message" in record.state_data:
        from backend.shared.message_editor_adapter import message_adapter
        adapter = message_adapter(editor_ctx)
        item = await adapter.load(session, editor_ctx)
        if adapter.snapshot(item) != record.state_data["base_message"]:
            raise ValidationError("正式正文或封面已被其他人修改，草稿已保留；请重新载入后编辑。")
        adapter.apply(item, record.state_data["message"])
        record.state_data = {**record.state_data, "base_message": record.state_data["message"]}
    await _save_buttons_for_module(session, editor_ctx, buttons)
    record.state_data = {**record.state_data, "base_buttons": buttons}
    await session.flush()


async def ensure_message_draft(session, context, editor_ctx):
    from backend.shared.message_editor_adapter import message_adapter
    record = await _draft_record(session, context, editor_ctx)
    if "message" not in record.state_data:
        adapter = message_adapter(editor_ctx)
        snapshot = adapter.snapshot(await adapter.load(session, editor_ctx))
        record.state_data = {**record.state_data, "message": snapshot, "base_message": snapshot}
        await session.flush()
    return record


async def discard_button_draft(session, context, editor_ctx):
    record = await _draft_record(session, context, editor_ctx)
    await session.delete(record)
    await session.flush()


async def _ensure_draft(
    session,
    context: ContextTypes.DEFAULT_TYPE,
    editor_ctx: ButtonEditorContext,
) -> ButtonGrid:
    record = await _draft_record(session, context, editor_ctx)
    return ButtonLayoutEditorService._clone_grid(record.state_data["grid"])


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
    *,
    grid: ButtonGrid,
    save_buttons=_save_buttons_for_module,
) -> None:
    record = await _draft_record(session, context, editor_ctx)
    record.state_data = {**record.state_data, "grid": ButtonLayoutEditorService._clone_grid(grid)}
    record.expires_at = dt.datetime.now(dt.UTC)+dt.timedelta(days=7)
    await session.flush()
