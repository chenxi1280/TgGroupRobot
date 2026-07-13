from __future__ import annotations

from telegram import Update
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
    return list(getattr(item, "buttons", None) or [])


async def _load_auto_reply_buttons(session, editor_ctx: ButtonEditorContext) -> list[list[dict[str, str]]]:
    from backend.features.moderation.services.auto_reply_service import get_auto_reply_rule_in_chat

    item = await get_auto_reply_rule_in_chat(session, editor_ctx.target_chat_id, editor_ctx.entity_id)
    if item is None:
        raise ValidationError("自动回复规则不存在。")
    return list(getattr(item, "buttons", None) or [])


async def _load_welcome_buttons(session, editor_ctx: ButtonEditorContext) -> list[list[dict[str, str]]]:
    from backend.features.verification.welcome_service import WelcomeService

    item = await WelcomeService.get_message(session, editor_ctx.target_chat_id, editor_ctx.entity_id)
    return list(getattr(item, "buttons", None) or [])


async def _load_invite_buttons(session, editor_ctx: ButtonEditorContext) -> list[list[dict[str, str]]]:
    from backend.shared.services.chat_service import get_chat_settings

    settings = await get_chat_settings(session, editor_ctx.target_chat_id)
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

        await _admin_handler._show_welcome_detail_menu(update, context, editor_ctx.target_chat_id, welcome_id=editor_ctx.entity_id)
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
        drafts[key] = ButtonLayoutEditorService.to_grid(buttons, module_type=editor_ctx.module_type)
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
    *,
    grid: ButtonGrid,
    save_buttons=_save_buttons_for_module,
) -> None:
    _save_draft_to_memory(context, editor_ctx, grid)
    buttons = ButtonLayoutEditorService.export_complete_buttons(grid, module_type=editor_ctx.module_type)
    await save_buttons(session, editor_ctx, buttons)
