from __future__ import annotations


import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from backend.features.automation.services.ad_rotation_service import (
    format_local_datetime,
    get_or_create_rotation_rule,
    update_rotation_rule,
)
from backend.features.automation.ui.ads import (
    ads_copy_time_keyboard,
    ads_rules_interval_keyboard,
)
from backend.platform.db.runtime.session import Database
from backend.platform.state.conversation_state_service import ConversationStateService
from backend.shared.callback_parser import CallbackParser
from backend.shared.time_ui import build_datetime_prompt_text, next_top_of_hour
from backend.platform.telegram.errors import (
    answer_callback_query_safely,
)

from backend.features.automation.ads_context import (
    _ads_handler,
    _resolve_ads_target_chat_id,
)

log = structlog.get_logger(__name__)

async def ads_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    await update.callback_query.answer()

    target_chat_id = await _resolve_ads_target_chat_id(update, context)
    if target_chat_id is None:
        return
    await _ads_handler.show_menu(update, context, target_chat_id)


async def ads_rules_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    cb = CallbackParser.parse(update.callback_query.data or "")
    if cb.get(2) == "hint":
        hint_key = cb.get(4)
        hint_text = {
            "unpin_previous": "这是说明栏，请点击下方「开启」或「关闭」按钮来切换取消上一条置顶。",
        }.get(hint_key, "这是说明栏，请点击旁边可操作的按钮。")
        await answer_callback_query_safely(update, hint_text, show_alert=False)
        return

    await update.callback_query.answer()
    target_chat_id = await _resolve_ads_target_chat_id(update, context)
    if target_chat_id is None:
        return
    await _ads_handler.show_rules(update, context, target_chat_id)


async def ads_rules_set_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    q = update.callback_query
    await q.answer()

    cb = CallbackParser.parse(q.data or "")
    chat_id = cb.require_int(3, label="chat_id")
    field = cb.get(4)
    value = cb.get(5)

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        rule = await get_or_create_rotation_rule(session, chat_id)
        kwargs = _rule_update_kwargs(field, value)
        if kwargs is None:
            await session.commit()
            await answer_callback_query_safely(update, "无效配置项", show_alert=True)
            return
        if await _start_existing_delay_edit(update, session, rule, chat_id=chat_id, field=field, value=value):
            return
        if field == "delete_policy" and value == "delete_delay":
            kwargs["delete_delay_seconds"] = DEFAULT_DELETE_DELAY_SECONDS
        await update_rotation_rule(session, chat_id, **kwargs)
        await session.commit()
    await _ads_handler.show_rules(update, context, chat_id)


DEFAULT_DELETE_DELAY_SECONDS = 60


def _rule_update_kwargs(field: str | None, value: str | None) -> dict[str, object] | None:
    factories = {
        "enabled": lambda: {"enabled": value == "1"},
        "mode": lambda: {"mode": value},
        "interval_minutes": lambda: {"interval_seconds": int(value) * 60},
        "delete_policy": lambda: {"delete_policy": value},
        "unpin_previous": lambda: {"unpin_previous": value == "1"},
    }
    factory = factories.get(field)
    return factory() if factory else None


async def _start_existing_delay_edit(update: Update, session, rule, *, chat_id: int, field, value) -> bool:
    if field != "delete_policy" or value != "delete_delay" or rule.delete_policy != "delete_delay":
        return False
    await ConversationStateService.start(
        session,
        chat_id=update.effective_chat.id,
        user_id=update.effective_user.id,
        state_type="ads_rule_edit_delay",
        state_data={"target_chat_id": chat_id},
    )
    await session.commit()
    await update.callback_query.edit_message_text(
        "👉 请输入延迟删除秒数，例如 60。",
        reply_markup=_rules_back_keyboard(chat_id),
    )
    return True


def _rules_back_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔙 返回", callback_data=f"ads:rules:{chat_id}")]]
    )


async def ads_rules_input_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    cb = CallbackParser.parse(q.data or "")
    chat_id = cb.require_int(3, label="chat_id")
    field = cb.get(4)

    if field == "interval":
        await _show_interval_choices(context, q, chat_id=chat_id)
        return
    state_type = {
        "start": "ads_rule_edit_start",
        "interval_custom": "ads_rule_edit_interval",
        "delay": "ads_rule_edit_delay",
    }.get(field)
    if state_type is None:
        await answer_callback_query_safely(update, "无效配置项", show_alert=True)
        return
    await _start_rule_input_state(update, context, chat_id=chat_id, state_type=state_type)
    await _show_rule_input_prompt(q, chat_id=chat_id, field=field)


async def _show_interval_choices(context, query, *, chat_id: int) -> None:
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        rule = await get_or_create_rotation_rule(session, chat_id)
        await session.commit()
    await query.edit_message_text(
        "请选择轮播间隔",
        reply_markup=ads_rules_interval_keyboard(chat_id, getattr(rule, "interval_seconds", None)),
    )


async def _start_rule_input_state(update: Update, context, *, chat_id: int, state_type: str) -> None:
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await ConversationStateService.start(
            session,
            chat_id=update.effective_chat.id,
            user_id=update.effective_user.id,
            state_type=state_type,
            state_data={"target_chat_id": chat_id},
        )
        await session.commit()


async def _show_rule_input_prompt(query, *, chat_id: int, field: str) -> None:
    if field == "start":
        sample_time = next_top_of_hour()
        sample_label = format_local_datetime(sample_time, empty="")
        await query.edit_message_text(
            build_datetime_prompt_text(
                title="🎠 轮播规则 | 编辑开始时间",
                sample_time_text=sample_label,
                sample_time_unix=int(sample_time.timestamp()),
                show_copy_hint=False,
                input_hint="👉🏻 现在输入定时开始时间:",
            ),
            parse_mode="HTML",
            reply_markup=ads_copy_time_keyboard(f"ads:rules:{chat_id}", sample_label),
        )
        return
    prompt = {
        "interval_custom": "👉 请输入自定义间隔时间（分钟）：",
        "delay": "👉 请输入延迟删除秒数，例如 60。",
    }[field]
    await query.edit_message_text(
        prompt,
        reply_markup=_rules_back_keyboard(chat_id),
    )
