from __future__ import annotations

import asyncio

import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from backend.features.moderation.auto_reply_common import ensure_message_update, get_match_type_label
from backend.features.moderation.auto_reply_payloads import parse_auto_reply_buttons_input, send_auto_reply_payload
from backend.features.moderation.services.auto_reply_service import create_auto_reply_rule, match_auto_reply, update_auto_reply_rule
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.enums import AutoReplyMatchType, ConversationStateType
from backend.platform.state.state_service import clear_user_state, get_user_state
from backend.shared.async_tasks import spawn_background_task
from backend.shared.ui.button_input import is_clear_button_input
_REPLY_PREVIEW_LENGTH = 50
_MIN_CONFIG_LINES = 4
_TRUE_VALUES = frozenset({"true", "1", "yes"})


log = structlog.get_logger(__name__)

SUPPORTED_AUTO_REPLY_STATES = {
    ConversationStateType.auto_reply_create.value,
    ConversationStateType.auto_reply_edit_keywords.value,
    ConversationStateType.auto_reply_edit_content.value,
    ConversationStateType.auto_reply_edit_cover.value,
    ConversationStateType.auto_reply_edit_buttons.value,
}


async def _process_auto_reply_state(update: Update, session, state, *, text: str) -> None:
    if state is None or state.state_type not in SUPPORTED_AUTO_REPLY_STATES:
        log.info("auto_reply_state_not_match", state_type=state.state_type if state else None)
        await session.commit()
        return
    if state.state_type != ConversationStateType.auto_reply_create.value:
        await _handle_auto_reply_edit_input(update, session, state, text=text)
        return
    if state.state_data.get("step") != "config" or not text:
        await session.commit()
        return
    await _parse_auto_reply_config(update, session, state, text=text)


async def auto_reply_config_handler_impl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.warning(
        "=== AUTO_REPLY_CONFIG_HANDLER ENTRY ===",
        chat_id=update.effective_chat.id if update.effective_chat else None,
        user_id=update.effective_user.id if update.effective_user else None,
        chat_type=update.effective_chat.type if update.effective_chat else None,
    )

    try:
        if not ensure_message_update(update, require_user=True):
            return

        chat = update.effective_chat
        user = update.effective_user
        text = update.effective_message.text or ""

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            state = await get_user_state(session, chat_id=chat.id, user_id=user.id)
            log.info(
                "auto_reply_config_state_check",
                chat_id=chat.id,
                user_id=user.id,
                state_chat_id=chat.id,
                state_found=state is not None,
                state_type=state.state_type if state else None,
                expected_state=ConversationStateType.auto_reply_create.value,
            )
            await _process_auto_reply_state(update, session, state, text=text)
            log.info("auto_reply_handler_done")
    except Exception as exc:
        log.exception(
            "auto_reply_config_handler_error",
            error=str(exc),
            error_type=type(exc).__name__,
            traceback=True,
        )


async def _send_matched_rules(update: Update, context: ContextTypes.DEFAULT_TYPE, rules: list) -> list:
    message = update.effective_message
    return [
        await send_auto_reply_payload(
            context,
            chat_id=update.effective_chat.id,
            text=rule.reply_content,
            rule=rule,
            reply_to_message_id=message.message_id,
            message_thread_id=getattr(message, "message_thread_id", None),
        )
        for rule in rules
    ]


async def _delete_source_message(update: Update, rules: list) -> None:
    if not any(getattr(rule, "delete_source", False) for rule in rules):
        return
    try:
        await update.effective_message.delete()
    except Exception as exc:
        log.debug("auto_reply_delete_source_failed", error=str(exc))


def _schedule_reply_deletions(context: ContextTypes.DEFAULT_TYPE, rules: list, sent_messages: list) -> None:
    for rule, sent_message in zip(rules, sent_messages, strict=False):
        delete_after = getattr(rule, "delete_reply_delay_seconds", 0) or 0
        if delete_after <= 0:
            continue
        spawn_background_task(
            context,
            _delete_later(sent_message, delete_after),
            name="auto_reply_runtime.delete_later",
        )


async def _deliver_auto_replies(update: Update, context: ContextTypes.DEFAULT_TYPE, result) -> None:
    rules = result.matched_rules or [result.rule]
    sent_messages = await _send_matched_rules(update, context, rules)
    await _delete_source_message(update, rules)
    _schedule_reply_deletions(context, rules, sent_messages)


async def auto_reply_message_handler_impl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not ensure_message_update(update, require_user=False):
        return
    chat = update.effective_chat
    message_text = update.effective_message.text or ""
    if chat.type == "private" or not message_text:
        return
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        result = await match_auto_reply(session, chat.id, message_text)
        await session.commit()
    if not (result.success and result.reply_content and result.rule is not None):
        return
    try:
        await _deliver_auto_replies(update, context, result)
    except Exception as exc:
        log.warning("auto_reply_send_failed", error=str(exc))


async def _parse_auto_reply_config(update: Update, session, state: object, *, text: str) -> None:
    try:
        config = _parse_auto_reply_config_text(text)
        target_chat_id = state.state_data.get("target_chat_id") or update.effective_chat.id
        result = await create_auto_reply_rule(
            session,
            chat_id=target_chat_id,
            created_by_user_id=update.effective_user.id,
            **config,
        )
        if not result.success:
            raise ValueError(
                {
                    "invalid_keywords": "关键词格式无效",
                    "invalid_reply": "回复内容无效",
                    "invalid_match_type": "匹配类型无效",
                    "invalid_delete_delay": "延迟删除必须是大于等于 0 的整数",
                }.get(result.reason, "创建失败")
            )

        state_chat_id = update.effective_chat.id if update.effective_chat.type == "private" else target_chat_id
        await clear_user_state(session, chat_id=state_chat_id, user_id=update.effective_user.id)
        await session.commit()
        await update.effective_message.reply_text(
            _build_create_success_text(config, result),
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("📄 规则详情", callback_data=f"auto_reply:detail:{target_chat_id}:{result.entity.id}")],
                    [InlineKeyboardButton("🔙 返回自动回复管理", callback_data=f"adm:menu:autoreply:{target_chat_id}")],
                    [InlineKeyboardButton("🏠 返回主菜单", callback_data=f"adm:menu:main:{target_chat_id}")],
                ]
            ),
        )
    except ValueError as exc:
        await update.effective_message.reply_text(f"❌ 配置错误: {exc}\n\n请重新发送配置，或使用 /cancel 取消。")
        await session.commit()
    except Exception as exc:
        await update.effective_message.reply_text(f"❌ 解析失败: {exc}\n\n请检查格式后重新发送。")
        await session.commit()


def _auto_reply_defaults(keywords: list[str]) -> dict:
    return {
        "keywords": keywords,
        "match_type": AutoReplyMatchType.contains.value,
        "case_sensitive": False,
        "stop_after_match": True,
        "delete_source": False,
        "delete_reply_delay_seconds": 0,
    }


def _truth_value(value: str) -> bool:
    return value.lower() in _TRUE_VALUES


def _continue_matching_value(value: str) -> bool:
    return not _truth_value(value)


def _delay_value(value: str) -> int:
    return int(value.rstrip("秒sS") or "0")


_AUTO_REPLY_CONFIG_RULES = (
    ("匹配类型:", "match_type", str),
    ("区分大小写:", "case_sensitive", _truth_value),
    ("停止继续匹配:", "stop_after_match", _truth_value),
    ("继续匹配:", "stop_after_match", _continue_matching_value),
    ("删除来源:", "delete_source", _truth_value),
    ("延迟删除:", "delete_reply_delay_seconds", _delay_value),
)


def _line_value(line: str) -> str:
    return line.split(":", 1)[1].strip()


def _apply_config_option(config: dict, line: str) -> dict:
    for prefix, key, converter in _AUTO_REPLY_CONFIG_RULES:
        if line.startswith(prefix):
            return {**config, key: converter(_line_value(line))}
    return dict(config)


def _parse_config_options(lines: list[str], keywords: list[str]) -> dict:
    config = _auto_reply_defaults(keywords)
    for raw_line in lines:
        line = raw_line.strip()
        if line.startswith("回复内容:"):
            return config
        config = _apply_config_option(config, line)
    return config


def _parse_reply_content(lines: list[str]) -> str:
    reply_lines: list[str] = []
    start_index = next((index for index, line in enumerate(lines) if line.strip().startswith("回复内容:")), None)
    if start_index is None:
        raise ValueError("回复内容不能为空")
    first_line = lines[start_index]
    first_content = first_line.split(":", 1)[1].strip() if ":" in first_line else ""
    if first_content:
        reply_lines.append(first_content)
    reply_lines.extend(lines[start_index + 1 :])
    reply_content = "\n".join(reply_lines).strip()
    if not reply_content:
        raise ValueError("回复内容不能为空")
    return reply_content


def _parse_auto_reply_config_text(text: str) -> dict:
    lines = text.strip().splitlines()
    if len(lines) < _MIN_CONFIG_LINES:
        raise ValueError("配置格式不完整")
    keywords = [item.strip() for item in lines[0].strip().split(",") if item.strip()]
    if not keywords:
        raise ValueError("关键词不能为空")
    return {**_parse_config_options(lines[1:], keywords), "reply_content": _parse_reply_content(lines[1:])}


def _build_create_success_text(config: dict, result) -> str:
    reply_content = config["reply_content"]
    delete_reply_delay_seconds = config["delete_reply_delay_seconds"]
    return (
        "✅ 自动回复规则创建成功！\n\n"
        f"🔑 关键词: {', '.join(config['keywords'])}\n"
        f"🔢 顺序: #{result.entity.sort_order}\n"
        f"📋 匹配类型: {get_match_type_label(config['match_type'])}\n"
        f"🔤 区分大小写: {'是' if config['case_sensitive'] else '否'}\n"
        f"🧱 命中后停止继续匹配: {'是' if config['stop_after_match'] else '否'}\n"
        f"🧹 删除来源: {'是' if config['delete_source'] else '否'}\n"
        + (
            f"⏱️ 延迟删除: {delete_reply_delay_seconds} 秒\n"
            if delete_reply_delay_seconds
            else "⏱️ 延迟删除: 不删除\n"
        )
        + f"💬 回复: {reply_content[:_REPLY_PREVIEW_LENGTH]}{'...' if len(reply_content) > _REPLY_PREVIEW_LENGTH else ''}\n"
        + f"\n规则ID: {result.entity.id}\n\n可继续进入详情页补充封面和按钮。"
    )


async def _handle_auto_reply_edit_input(update: Update, session, state: object, *, text: str) -> None:
    state_data = state.state_data or {}
    target_chat_id = state_data.get("target_chat_id")
    rule_id = state_data.get("rule_id")
    if not target_chat_id or not rule_id:
        await update.effective_message.reply_text("❌ 自动回复状态异常，请重新进入规则详情页。")
        await clear_user_state(session, chat_id=update.effective_chat.id, user_id=update.effective_user.id)
        await session.commit()
        return

    updated_rule = await _apply_auto_reply_edit(update, session, state.state_type, target_chat_id=target_chat_id, rule_id=rule_id, text=text)
    if updated_rule is None:
        await update.effective_message.reply_text("❌ 自动回复规则不存在或不属于当前群组。")
        await session.commit()
        return

    await clear_user_state(session, chat_id=update.effective_chat.id, user_id=update.effective_user.id)
    await session.commit()
    await update.effective_message.reply_text(
        "✅ 自动回复规则已更新。",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 返回规则详情", callback_data=f"auto_reply:detail:{target_chat_id}:{rule_id}")]]
        ),
    )


async def _apply_cover_edit(update: Update, session, *, target_chat_id: int, rule_id: int, text: str):
    message = update.effective_message
    if text.strip() == "清空":
        return await update_auto_reply_rule(
            session, rule_id, chat_id=target_chat_id, cover_media_type=None, cover_media_file_id=None
        )
    if message.photo:
        media_type, file_id = "photo", message.photo[-1].file_id
    elif message.video:
        media_type, file_id = "video", message.video.file_id
    else:
        await message.reply_text("❌ 请发送图片、视频，或发送“清空”。")
        await session.commit()
        return None
    return await update_auto_reply_rule(
        session,
        rule_id,
        chat_id=target_chat_id,
        cover_media_type=media_type,
        cover_media_file_id=file_id,
    )


async def _apply_auto_reply_edit(update: Update, session, state_type: str, *, target_chat_id: int, rule_id: int, text: str):
    if state_type == ConversationStateType.auto_reply_edit_keywords.value:
        keywords = [item.strip() for item in text.split(",") if item.strip()]
        return await update_auto_reply_rule(session, rule_id, chat_id=target_chat_id, keywords=keywords)
    if state_type == ConversationStateType.auto_reply_edit_content.value:
        return await update_auto_reply_rule(session, rule_id, chat_id=target_chat_id, reply_content=text.strip())
    if state_type == ConversationStateType.auto_reply_edit_cover.value:
        return await _apply_cover_edit(update, session, target_chat_id=target_chat_id, rule_id=rule_id, text=text)
    if state_type == ConversationStateType.auto_reply_edit_buttons.value:
        buttons = [] if is_clear_button_input(text) else parse_auto_reply_buttons_input(text)
        return await update_auto_reply_rule(session, rule_id, chat_id=target_chat_id, buttons=buttons)
    return None


async def _delete_later(message, delay_seconds: int) -> None:
    try:
        await asyncio.sleep(max(delay_seconds, 1))
    except asyncio.CancelledError:
        raise
    try:
        await message.delete()
    except Exception as exc:
        log.warning("auto_reply_message_delete_failed", chat_id=message.chat_id, message_id=message.message_id, error=str(exc))
        return
