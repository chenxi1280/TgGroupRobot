from __future__ import annotations


import structlog
from dataclasses import dataclass
from typing import Awaitable, Callable, Literal
from telegram import Update
from telegram.ext import ContextTypes

from backend.features.automation.ads_parsing import _parse_ads_config
from backend.features.automation.services.ad_rotation_service import (
    UNSET,
    ValidationError,
    create_rotation_item,
    parse_datetime_text,
    parse_delay_seconds_text,
    parse_interval_hours_text,
    update_rotation_item,
    update_rotation_rule,
)
from backend.platform.db.runtime.session import Database
from backend.platform.state.conversation_state_service import ConversationStateService
from backend.shared.services.permission_service import PermissionPolicyService

from backend.features.automation.ads_context import (
    _ads_handler,
    _is_clear_input,
    _resolve_ads_state_chat_id,
    _resolve_ads_target_chat_id,
)

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class _AdsInput:
    update: Update
    context: ContextTypes.DEFAULT_TYPE
    session: object
    state: object
    message: object
    user: object
    chat: object
    target_chat_id: int
    item_id: int | None
    text: str


@dataclass(frozen=True, slots=True)
class _InputDestination:
    view: Literal["none", "rules", "detail"]
    item_id: int | None = None


InputHandler = Callable[[_AdsInput], Awaitable[_InputDestination]]


RULES_DESTINATION = _InputDestination("rules")

async def ads_create_config_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _has_ads_input_context(update):
        return

    message, user, chat = update.effective_message, update.effective_user, update.effective_chat
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state = await ConversationStateService.get(session, chat.id, user.id)
        if not state or not state.state_type.startswith("ads_"):
            await session.commit()
            return
        data = dict(state.state_data or {})
        input_data = _AdsInput(
            update=update,
            context=context,
            session=session,
            state=state,
            message=message,
            user=user,
            chat=chat,
            target_chat_id=data.get("target_chat_id"),
            item_id=data.get("item_id"),
            text=(message.text or message.caption or "").strip(),
        )
        if not await _check_input_permission(input_data):
            return
        destination = await _execute_ads_input_safely(input_data)
        if destination is None:
            return
    await _show_input_destination(input_data, destination)


def _has_ads_input_context(update: Update) -> bool:
    return (
        update.effective_message is not None
        and update.effective_user is not None
        and update.effective_chat is not None
    )


async def _execute_ads_input_safely(data: _AdsInput) -> _InputDestination | None:
    try:
        return await _dispatch_ads_input(data)
    except ValidationError as exc:
        await data.session.commit()
        await data.message.reply_text(str(exc))
        return None
    except Exception as exc:
        log.exception("ads_private_input_failed", error=str(exc), state_type=data.state.state_type)
        await data.session.commit()
        await data.message.reply_text("处理失败，请稍后重试")
        return None


async def _check_input_permission(data: _AdsInput) -> bool:
    allowed, error_text = await PermissionPolicyService.require_manage(
        data.context,
        data.target_chat_id,
        data.user.id,
        capability="automation",
    )
    if allowed:
        return True
    await data.session.commit()
    if error_text:
        await data.message.reply_text(error_text)
    return False


async def _dispatch_ads_input(data: _AdsInput) -> _InputDestination:
    handlers: dict[str, InputHandler] = {
        "ads_create_config": _create_from_config,
        "ads_rule_edit_start": _edit_rule_start,
        "ads_rule_edit_interval": _edit_rule_interval,
        "ads_rule_edit_delay": _edit_rule_delay,
        "ads_item_edit_title": _edit_item_title,
        "ads_item_edit_text": _edit_item_text,
        "ads_item_edit_cover": _edit_item_cover,
        "ads_item_edit_start": _edit_item_start,
        "ads_item_edit_end": _edit_item_end,
        "ads_item_edit_order": _edit_item_order,
    }
    handler = handlers.get(data.state.state_type)
    if handler is None:
        raise ValidationError(f"不支持的轮播编辑状态: {data.state.state_type}")
    return await handler(data)


async def _create_from_config(data: _AdsInput) -> _InputDestination:
    config = _parse_ads_config(data.text)
    item = await create_rotation_item(
        data.session,
        chat_id=data.target_chat_id,
        created_by_user_id=data.user.id,
        title=config["title"],
        content=config["content"],
    )
    await update_rotation_item(
        data.session,
        item.id,
        image_file_id=config.get("image_file_id"),
        start_time=config.get("start_time", UNSET),
    )
    await _apply_config_rule_values(data, config)
    await _finish_ads_input(data)
    return _InputDestination("detail", item.id)


async def _apply_config_rule_values(data: _AdsInput, config: dict) -> None:
    if config.get("interval_hours"):
        await update_rotation_rule(
            data.session,
            data.target_chat_id,
            interval_seconds=int(config["interval_hours"]) * 3600,
        )
    if config.get("start_time"):
        await update_rotation_rule(
            data.session,
            data.target_chat_id,
            start_at=config["start_time"],
        )


async def _edit_rule_start(data: _AdsInput) -> _InputDestination:
    start_at = None if _is_clear_input(data.text) else parse_datetime_text(data.text)
    await update_rotation_rule(data.session, data.target_chat_id, start_at=start_at)
    await _finish_ads_input(data)
    return RULES_DESTINATION


async def _edit_rule_interval(data: _AdsInput) -> _InputDestination:
    interval = parse_interval_hours_text(data.text)
    await update_rotation_rule(data.session, data.target_chat_id, interval_seconds=interval)
    await _finish_ads_input(data)
    return RULES_DESTINATION


async def _edit_rule_delay(data: _AdsInput) -> _InputDestination:
    delay = parse_delay_seconds_text(data.text)
    await update_rotation_rule(
        data.session,
        data.target_chat_id,
        delete_delay_seconds=delay,
        delete_policy="delete_delay",
    )
    await _finish_ads_input(data)
    return RULES_DESTINATION


def _require_item_id(data: _AdsInput) -> int:
    if data.item_id is None:
        raise ValidationError("轮播消息不存在")
    return data.item_id


async def _edit_item_title(data: _AdsInput) -> _InputDestination:
    await update_rotation_item(data.session, _require_item_id(data), title=data.text)
    return await _finish_item_input(data)


async def _edit_item_text(data: _AdsInput) -> _InputDestination:
    await update_rotation_item(data.session, _require_item_id(data), content=data.text)
    return await _finish_item_input(data)


async def _edit_item_cover(data: _AdsInput) -> _InputDestination:
    item_id = _require_item_id(data)
    if _is_clear_input(data.text):
        await update_rotation_item(data.session, item_id, clear_image=True)
    elif data.message.photo:
        await update_rotation_item(data.session, item_id, image_file_id=data.message.photo[-1].file_id)
    else:
        raise ValidationError("请发送图片，或发送“清空”移除封面")
    return await _finish_item_input(data)


async def _edit_item_start(data: _AdsInput) -> _InputDestination:
    value = None if _is_clear_input(data.text) else parse_datetime_text(data.text)
    await update_rotation_item(data.session, _require_item_id(data), start_time=value)
    return await _finish_item_input(data)


async def _edit_item_end(data: _AdsInput) -> _InputDestination:
    value = None if _is_clear_input(data.text) else parse_datetime_text(data.text)
    await update_rotation_item(data.session, _require_item_id(data), end_time=value)
    return await _finish_item_input(data)


async def _edit_item_order(data: _AdsInput) -> _InputDestination:
    if not data.text.isdigit():
        raise ValidationError("请输入有效的顺序数字")
    await update_rotation_item(data.session, _require_item_id(data), sort_order=int(data.text))
    return await _finish_item_input(data)


async def _finish_item_input(data: _AdsInput) -> _InputDestination:
    await _finish_ads_input(data)
    return _InputDestination("detail", _require_item_id(data))


async def _finish_ads_input(data: _AdsInput) -> None:
    await ConversationStateService.clear(data.session, data.chat.id, data.user.id)
    await data.session.commit()


async def _show_input_destination(data: _AdsInput, destination: _InputDestination) -> None:
    if destination.view == "rules":
        await _ads_handler.show_rules(data.update, data.context, data.target_chat_id)
    elif destination.view == "detail" and destination.item_id is not None:
        await _ads_handler.show_detail(
            data.update,
            data.context,
            data.target_chat_id,
            destination.item_id,
        )


async def ads_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    target_chat_id = await _resolve_ads_target_chat_id(update, context)
    if target_chat_id is None:
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state_chat_id = _resolve_ads_state_chat_id(update, target_chat_id)
        await ConversationStateService.clear(session, state_chat_id, update.effective_user.id)
        await session.commit()

    await _ads_handler.show_menu(update, context, target_chat_id)
