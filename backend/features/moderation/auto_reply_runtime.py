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

log = structlog.get_logger(__name__)

SUPPORTED_AUTO_REPLY_STATES = {
    ConversationStateType.auto_reply_create.value,
    ConversationStateType.auto_reply_edit_keywords.value,
    ConversationStateType.auto_reply_edit_content.value,
    ConversationStateType.auto_reply_edit_cover.value,
    ConversationStateType.auto_reply_edit_buttons.value,
}


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

            if state is None or state.state_type not in SUPPORTED_AUTO_REPLY_STATES:
                log.info("auto_reply_state_not_match", state_type=state.state_type if state else None)
                await session.commit()
            elif state.state_type == ConversationStateType.auto_reply_create.value:
                if state.state_data.get("step") == "config":
                    if not text:
                        await session.commit()
                        return
                    await _parse_auto_reply_config(update, session, state, text)
                else:
                    await session.commit()
            else:
                await _handle_auto_reply_edit_input(update, session, state, text)

            log.info("auto_reply_handler_done")
    except Exception as exc:
        log.exception(
            "auto_reply_config_handler_error",
            error=str(exc),
            error_type=type(exc).__name__,
            traceback=True,
        )


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
        matched_rules = result.matched_rules or [result.rule]
        sent_messages = [
            await send_auto_reply_payload(
                context,
                chat_id=chat.id,
                text=matched_rule.reply_content,
                rule=matched_rule,
                reply_to_message_id=update.effective_message.message_id,
                message_thread_id=getattr(update.effective_message, "message_thread_id", None),
            )
            for matched_rule in matched_rules
        ]
        if any(getattr(rule, "delete_source", False) for rule in matched_rules):
            try:
                await update.effective_message.delete()
            except Exception as exc:
                log.debug("auto_reply_delete_source_failed", error=str(exc))

        for matched_rule, sent_message in zip(matched_rules, sent_messages, strict=False):
            delete_after = getattr(matched_rule, "delete_reply_delay_seconds", 0) or 0
            if delete_after > 0:
                spawn_background_task(
                    context,
                    _delete_later(sent_message, delete_after),
                    name="auto_reply_runtime.delete_later",
                )
    except Exception as exc:
        log.debug("auto_reply_send_failed", error=str(exc))


async def _parse_auto_reply_config(update: Update, session, state: object, text: str) -> None:
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


def _parse_auto_reply_config_text(text: str) -> dict:
    lines = text.strip().split("\n")
    if len(lines) < 4:
        raise ValueError("配置格式不完整")

    keywords = [item.strip() for item in lines[0].strip().split(",") if item.strip()]
    if not keywords:
        raise ValueError("关键词不能为空")

    config = {
        "keywords": keywords,
        "match_type": AutoReplyMatchType.contains.value,
        "case_sensitive": False,
        "stop_after_match": True,
        "delete_source": False,
        "delete_reply_delay_seconds": 0,
    }

    for line in [item.strip() for item in lines[1:]]:
        if line.startswith("回复内容:"):
            break
        if line.startswith("匹配类型:"):
            config["match_type"] = line.split(":", 1)[1].strip()
        elif line.startswith("区分大小写:"):
            config["case_sensitive"] = line.split(":", 1)[1].strip().lower() in {"true", "1", "yes"}
        elif line.startswith("停止继续匹配:"):
            config["stop_after_match"] = line.split(":", 1)[1].strip().lower() in {"true", "1", "yes"}
        elif line.startswith("继续匹配:"):
            config["stop_after_match"] = line.split(":", 1)[1].strip().lower() not in {"true", "1", "yes"}
        elif line.startswith("删除来源:"):
            config["delete_source"] = line.split(":", 1)[1].strip().lower() in {"true", "1", "yes"}
        elif line.startswith("延迟删除:"):
            delay_text = line.split(":", 1)[1].strip().rstrip("秒sS")
            config["delete_reply_delay_seconds"] = int(delay_text or "0")

    reply_lines: list[str] = []
    reply_started = False
    for line in lines[1:]:
        if line.strip().startswith("回复内容:"):
            reply_started = True
            content_after = line.split(":", 1)[1] if ":" in line else ""
            if content_after.strip():
                reply_lines.append(content_after.strip())
            continue
        if reply_started:
            reply_lines.append(line)

    reply_content = "\n".join(reply_lines).strip()
    if not reply_content:
        raise ValueError("回复内容不能为空")
    config["reply_content"] = reply_content
    return config


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
        + f"💬 回复: {reply_content[:50]}{'...' if len(reply_content) > 50 else ''}\n"
        + f"\n规则ID: {result.entity.id}\n\n可继续进入详情页补充封面和按钮。"
    )


async def _handle_auto_reply_edit_input(update: Update, session, state: object, text: str) -> None:
    state_data = state.state_data or {}
    target_chat_id = state_data.get("target_chat_id")
    rule_id = state_data.get("rule_id")
    if not target_chat_id or not rule_id:
        await update.effective_message.reply_text("❌ 自动回复状态异常，请重新进入规则详情页。")
        await clear_user_state(session, chat_id=update.effective_chat.id, user_id=update.effective_user.id)
        await session.commit()
        return

    updated_rule = await _apply_auto_reply_edit(update, session, state.state_type, target_chat_id, rule_id, text)
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


async def _apply_auto_reply_edit(update: Update, session, state_type: str, target_chat_id: int, rule_id: int, text: str):
    if state_type == ConversationStateType.auto_reply_edit_keywords.value:
        keywords = [item.strip() for item in text.split(",") if item.strip()]
        return await update_auto_reply_rule(session, rule_id, chat_id=target_chat_id, keywords=keywords)
    if state_type == ConversationStateType.auto_reply_edit_content.value:
        return await update_auto_reply_rule(session, rule_id, chat_id=target_chat_id, reply_content=text.strip())
    if state_type == ConversationStateType.auto_reply_edit_cover.value:
        message = update.effective_message
        if text.strip() == "清空":
            return await update_auto_reply_rule(session, rule_id, chat_id=target_chat_id, cover_media_type=None, cover_media_file_id=None)
        if message.photo:
            return await update_auto_reply_rule(
                session,
                rule_id,
                chat_id=target_chat_id,
                cover_media_type="photo",
                cover_media_file_id=message.photo[-1].file_id,
            )
        if message.video:
            return await update_auto_reply_rule(
                session,
                rule_id,
                chat_id=target_chat_id,
                cover_media_type="video",
                cover_media_file_id=message.video.file_id,
            )
        await update.effective_message.reply_text("❌ 请发送图片、视频，或发送“清空”。")
        await session.commit()
        return None
    if state_type == ConversationStateType.auto_reply_edit_buttons.value:
        buttons = [] if text.strip() == "清空" else parse_auto_reply_buttons_input(text)
        return await update_auto_reply_rule(session, rule_id, chat_id=target_chat_id, buttons=buttons)
    return None


async def _delete_later(message, delay_seconds: int) -> None:
    try:
        await asyncio.sleep(max(delay_seconds, 1))
    except asyncio.CancelledError:
        raise
    try:
        await message.delete()
    except Exception:
        return
