from __future__ import annotations

import asyncio
import json
import structlog

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes


log = structlog.get_logger(__name__)

from backend.platform.db.runtime.session import Database
from backend.shared.handlers.base.base_handler import BaseHandler
from backend.shared.handlers.base.chat_resolver import ChatResolver
from backend.platform.db.schema.models.enums import AutoReplyMatchType, ConversationStateType
from backend.features.moderation.services.auto_reply_service import (
    create_auto_reply_rule,
    delete_auto_reply_rule,
    get_auto_reply_rule,
    get_auto_reply_rule_in_chat,
    get_chat_auto_reply_rules,
    get_match_count,
    match_auto_reply,
    move_auto_reply_rule,
    toggle_auto_reply_rule,
    update_auto_reply_rule,
    CreateResult,
)
from backend.shared.services.chat_service import ensure_chat, get_chat_settings
from backend.features.automation.services.scheduled_message_service import ScheduledMessageService
from backend.platform.state.state_service import clear_user_state, get_user_state, set_user_state
from backend.shared.services.permission_service import is_user_admin
from backend.shared.services.user_service import ensure_user
from backend.shared.chat_context import PrivateChatContext
from backend.features.moderation.auto_reply_helpers import (
    _get_match_type_label,
    _parse_auto_reply_buttons_input,
    _send_auto_reply_payload,
)

async def auto_reply_config_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理自动回复创建流程中的消息"""
    # 强制日志 - 必须在最开始输出
    log.warning(
        "=== AUTO_REPLY_CONFIG_HANDLER ENTRY ===",
        chat_id=update.effective_chat.id if update.effective_chat else None,
        user_id=update.effective_user.id if update.effective_user else None,
        chat_type=update.effective_chat.type if update.effective_chat else None,
    )

    try:
        if not _ensure_message_update(update, require_user=True):
            return

        chat = update.effective_chat
        user = update.effective_user
        text = update.effective_message.text or ""

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            # 获取用户状态 - 私聊中使用 chat.id 查询状态（与设置状态时一致）
            state_chat_id = chat.id  # 统一使用 chat.id
            state = await get_user_state(session, chat_id=state_chat_id, user_id=user.id)

            log.info(
                "auto_reply_config_state_check",
                chat_id=chat.id,
                user_id=user.id,
                state_chat_id=state_chat_id,
                state_found=state is not None,
                state_type=state.state_type if state else None,
                expected_state=ConversationStateType.auto_reply_create.value,
            )

            # 静默忽略非自动回复创建状态，避免干扰其他功能
            supported_states = {
                ConversationStateType.auto_reply_create.value,
                ConversationStateType.auto_reply_edit_keywords.value,
                ConversationStateType.auto_reply_edit_content.value,
                ConversationStateType.auto_reply_edit_cover.value,
                ConversationStateType.auto_reply_edit_buttons.value,
            }

            if state is None or state.state_type not in supported_states:
                log.info("auto_reply_state_not_match", state_type=state.state_type if state else None)
                await session.commit()
                # 不 return，让函数自然结束，允许后续 handlers 执行
            else:
                if state.state_type == ConversationStateType.auto_reply_create.value:
                    step = state.state_data.get("step")
                    log.info("auto_reply_step", step=step)

                    if step == "config":
                        if not text:
                            await session.commit()
                            return
                        log.info("auto_reply_calling_parse")
                        await _parse_auto_reply_config(update, session, state, text)
                        log.info("auto_reply_parse_done")
                    else:
                        await session.commit()
                else:
                    await _handle_auto_reply_edit_input(update, context, session, state, text)
                # 注意：各子处理器内部已经 commit 了会话，不需要再次 commit

            log.info("auto_reply_handler_done")
    except Exception as e:
        # 确保异常被记录但不会阻止后续处理器
        log.exception(
            "auto_reply_config_handler_error",
            error=str(e),
            error_type=type(e).__name__,
            traceback=True
        )
        # 明确返回，不重新抛出异常，让后续处理器继续执行
        return


async def _parse_auto_reply_config(update: Update, session, state: object, text: str) -> None:
    """解析自动回复配置"""
    try:
        lines = text.strip().split("\n")
        if len(lines) < 4:
            raise ValueError("配置格式不完整")

        # 解析关键词（第一行）
        keywords_line = lines[0].strip()
        keywords = [k.strip() for k in keywords_line.split(",") if k.strip()]
        if not keywords:
            raise ValueError("关键词不能为空")

        # 解析匹配类型
        match_type = AutoReplyMatchType.contains.value  # 默认
        case_sensitive = False  # 默认
        stop_after_match = True
        delete_source = False
        delete_reply_delay_seconds = 0

        # 解析匹配类型和附加配置
        for i in range(1, len(lines)):
            line = lines[i].strip()
            if line.startswith("回复内容:"):
                break
            if line.startswith("匹配类型:"):
                match_type = line.split(":", 1)[1].strip()
            elif line.startswith("区分大小写:"):
                case_sensitive_str = line.split(":", 1)[1].strip().lower()
                case_sensitive = case_sensitive_str in ["true", "1", "yes"]
            elif line.startswith("停止继续匹配:"):
                stop_after_match_str = line.split(":", 1)[1].strip().lower()
                stop_after_match = stop_after_match_str in ["true", "1", "yes"]
            elif line.startswith("继续匹配:"):
                continue_match_str = line.split(":", 1)[1].strip().lower()
                stop_after_match = continue_match_str not in ["true", "1", "yes"]
            elif line.startswith("删除来源:"):
                delete_source_str = line.split(":", 1)[1].strip().lower()
                delete_source = delete_source_str in ["true", "1", "yes"]
            elif line.startswith("延迟删除:"):
                delay_text = line.split(":", 1)[1].strip().rstrip("秒sS")
                delete_reply_delay_seconds = int(delay_text or "0")

        # 解析回复内容
        reply_start = False
        reply_lines = []
        for i in range(1, len(lines)):
            line = lines[i]
            if line.strip().startswith("回复内容:"):
                reply_start = True
                # 如果同一行有内容，提取冒号后的部分
                if ":" in line:
                    content_after = line.split(":", 1)[1]
                    if content_after.strip():
                        reply_lines.append(content_after.strip())
                continue
            if reply_start:
                reply_lines.append(line)

        reply_content = "\n".join(reply_lines).strip()
        if not reply_content:
            raise ValueError("回复内容不能为空")

        # 获取目标群组ID（从状态数据中获取）
        target_chat_id = state.state_data.get("target_chat_id") or update.effective_chat.id

        # 创建自动回复规则
        result = await create_auto_reply_rule(
            session,
            chat_id=target_chat_id,
            created_by_user_id=update.effective_user.id,
            keywords=keywords,
            reply_content=reply_content,
            match_type=match_type,
            case_sensitive=case_sensitive,
            stop_after_match=stop_after_match,
            delete_source=delete_source,
            delete_reply_delay_seconds=delete_reply_delay_seconds,
        )

        if not result.success:
            error_messages = {
                "invalid_keywords": "关键词格式无效",
                "invalid_reply": "回复内容无效",
                "invalid_match_type": "匹配类型无效",
                "invalid_delete_delay": "延迟删除必须是大于等于 0 的整数",
            }
            raise ValueError(error_messages.get(result.reason, "创建失败"))

        # 清除状态（使用与保存/获取状态相同的 chat_id）
        state_chat_id = update.effective_chat.id if update.effective_chat.type == "private" else target_chat_id
        await clear_user_state(session, chat_id=state_chat_id, user_id=update.effective_user.id)
        await session.commit()

        # 返回成功消息
        reply_text = f"✅ 自动回复规则创建成功！\n\n"
        reply_text += f"🔑 关键词: {', '.join(keywords)}\n"
        reply_text += f"🔢 顺序: #{result.entity.sort_order}\n"
        reply_text += f"📋 匹配类型: {_get_match_type_label(match_type)}\n"
        reply_text += f"🔤 区分大小写: {'是' if case_sensitive else '否'}\n"
        reply_text += f"🧱 命中后停止继续匹配: {'是' if stop_after_match else '否'}\n"
        reply_text += f"🧹 删除来源: {'是' if delete_source else '否'}\n"
        reply_text += (
            f"⏱️ 延迟删除: {delete_reply_delay_seconds} 秒\n"
            if delete_reply_delay_seconds else
            "⏱️ 延迟删除: 不删除\n"
        )
        reply_text += f"💬 回复: {reply_content[:50]}{'...' if len(reply_content) > 50 else ''}\n"
        reply_text += f"\n规则ID: {result.entity.id}\n\n可继续进入详情页补充封面和按钮。"

        # 显示多级返回按钮：返回自动回复管理 / 返回主菜单
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📄 规则详情", callback_data=f"auto_reply:detail:{target_chat_id}:{result.entity.id}")],
            [InlineKeyboardButton("🔙 返回自动回复管理", callback_data=f"adm:menu:autoreply:{target_chat_id}")],
            [InlineKeyboardButton("🏠 返回主菜单", callback_data=f"adm:menu:main:{target_chat_id}")]
        ])

        await update.effective_message.reply_text(reply_text, reply_markup=keyboard)

    except ValueError as e:
        await update.effective_message.reply_text(f"❌ 配置错误: {e}\n\n请重新发送配置，或使用 /cancel 取消。")
        await session.commit()
    except Exception as e:
        await update.effective_message.reply_text(f"❌ 解析失败: {e}\n\n请检查格式后重新发送。")
        await session.commit()


async def _handle_auto_reply_edit_input(update: Update, context: ContextTypes.DEFAULT_TYPE, session, state: object, text: str) -> None:
    state_type = state.state_type
    state_data = state.state_data or {}
    target_chat_id = state_data.get("target_chat_id")
    rule_id = state_data.get("rule_id")
    updated_rule = None
    if not target_chat_id or not rule_id:
        await update.effective_message.reply_text("❌ 自动回复状态异常，请重新进入规则详情页。")
        await clear_user_state(session, chat_id=update.effective_chat.id, user_id=update.effective_user.id)
        await session.commit()
        return

    if state_type == ConversationStateType.auto_reply_edit_keywords.value:
        keywords = [item.strip() for item in text.split(",") if item.strip()]
        updated_rule = await update_auto_reply_rule(session, rule_id, chat_id=target_chat_id, keywords=keywords)
    elif state_type == ConversationStateType.auto_reply_edit_content.value:
        updated_rule = await update_auto_reply_rule(session, rule_id, chat_id=target_chat_id, reply_content=text.strip())
    elif state_type == ConversationStateType.auto_reply_edit_cover.value:
        message = update.effective_message
        if text.strip() == "清空":
            updated_rule = await update_auto_reply_rule(session, rule_id, chat_id=target_chat_id, cover_media_type=None, cover_media_file_id=None)
        elif message.photo:
            updated_rule = await update_auto_reply_rule(session, rule_id, chat_id=target_chat_id, cover_media_type="photo", cover_media_file_id=message.photo[-1].file_id)
        elif message.video:
            updated_rule = await update_auto_reply_rule(session, rule_id, chat_id=target_chat_id, cover_media_type="video", cover_media_file_id=message.video.file_id)
        else:
            await update.effective_message.reply_text("❌ 请发送图片、视频，或发送“清空”。")
            await session.commit()
            return
    elif state_type == ConversationStateType.auto_reply_edit_buttons.value:
        if text.strip() == "清空":
            updated_rule = await update_auto_reply_rule(session, rule_id, chat_id=target_chat_id, buttons=[])
        else:
            buttons = _parse_auto_reply_buttons_input(text)
            updated_rule = await update_auto_reply_rule(session, rule_id, chat_id=target_chat_id, buttons=buttons)

    if updated_rule is None:
        await update.effective_message.reply_text("❌ 自动回复规则不存在或不属于当前群组。")
        await session.commit()
        return

    await clear_user_state(session, chat_id=update.effective_chat.id, user_id=update.effective_user.id)
    await session.commit()
    await update.effective_message.reply_text(
        "✅ 自动回复规则已更新。",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回规则详情", callback_data=f"auto_reply:detail:{target_chat_id}:{rule_id}")]]),
    )


async def auto_reply_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理群组消息，触发自动回复"""
    if not _ensure_message_update(update, require_user=False):
        return

    chat = update.effective_chat
    message_text = update.effective_message.text or ""

    if chat.type == "private" or not message_text:
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        result = await match_auto_reply(session, chat.id, message_text)
        await session.commit()

    if result.success and result.reply_content and result.rule is not None:
        try:
            matched_rules = result.matched_rules or ([result.rule] if result.rule is not None else [])
            sent_messages = []
            for matched_rule in matched_rules:
                sent_messages.append(
                    await _send_auto_reply_payload(
                        context,
                        chat_id=chat.id,
                        text=matched_rule.reply_content,
                        rule=matched_rule,
                        reply_to_message_id=update.effective_message.message_id,
                    )
                )
            if any(getattr(rule, "delete_source", False) for rule in matched_rules):
                try:
                    await update.effective_message.delete()
                except Exception as exc:
                    log.debug("auto_reply_delete_source_failed", error=str(exc))
            for matched_rule, sent_message in zip(matched_rules, sent_messages, strict=False):
                delete_after = getattr(matched_rule, "delete_reply_delay_seconds", 0) or 0
                if delete_after > 0:
                    async def _delete_later(message, delay_seconds: int):
                        await asyncio.sleep(delay_seconds)
                        try:
                            await message.delete()
                        except Exception:
                            return

                    asyncio.create_task(_delete_later(sent_message, delete_after))
        except Exception as e:
            log.debug("auto_reply_send_failed", error=str(e))  # 静默失败，避免循环
