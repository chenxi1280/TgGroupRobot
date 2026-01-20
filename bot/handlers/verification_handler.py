from __future__ import annotations

import structlog
from telegram import ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.db.session import Database
from bot.i18n.strings import t
from bot.keyboards.common.verification import admin_verify_keyboard, verification_keyboard
from bot.services.core.chat_service import ensure_chat, get_chat_settings
from bot.services.core.user_service import ensure_user
from bot.services.verification_service import (
    create_or_replace_challenge,
    get_challenge,
    solve_by_answer,
    solve_by_token,
)
from bot.services.integration.invite_service import track_and_award_invite


log = structlog.get_logger(__name__)


async def new_members_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.effective_message is None:
        return
    chat = update.effective_chat
    if chat.type == "private":
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
        settings = await get_chat_settings(session, chat.id)

        # 发送欢迎消息（独立于验证功能）
        if settings.welcome_enabled:
            for u in update.effective_message.new_chat_members or []:
                mention = u.mention_html()
                if settings.welcome_message:
                    # 使用自定义欢迎消息
                    welcome_text = settings.welcome_message.format(user=mention, chat=chat.title or "本群")
                else:
                    # 使用默认欢迎消息
                    welcome_text = t(settings.language, "welcome.default", user=mention, chat=chat.title or "本群")
                try:
                    await context.bot.send_message(
                        chat_id=chat.id,
                        text=welcome_text,
                        parse_mode="HTML",
                    )
                except Exception as e:
                    log.warning("send_welcome_message_failed", chat_id=chat.id, error=str(e))

        # 如果未启用验证，直接返回
        if not settings.verification_enabled:
            await session.commit()
            return

        for u in update.effective_message.new_chat_members or []:
            await ensure_user(
                session,
                user_id=u.id,
                username=u.username,
                first_name=u.first_name,
                last_name=u.last_name,
                language_code=u.language_code,
            )

            # 追踪邀请并发放积分
            # 注意：由于 Telegram 的 API 限制，new_chat_members 消息不包含使用的邀请链接信息
            # 需要使用 ChatMemberHandler 来获取 via_invite_link 信息
            # 这里先尝试追踪（如果有 invite_link_id 的上下文）
            # TODO: 实现 ChatMemberHandler 来准确追踪邀请链接
            invite_link_id = context.user_data.get("pending_invite_link_id") if context.user_data else None
            if invite_link_id:
                from bot.models.core import InviteLink
                from sqlalchemy import select

                link_result = await session.execute(
                    select(InviteLink).where(InviteLink.id == invite_link_id)
                )
                link = link_result.scalar_one_or_none()
                if link and link.chat_id == chat.id:
                    is_new, awarded, _ = await track_and_award_invite(
                        session,
                        chat_id=chat.id,
                        inviter_user_id=link.created_by_user_id,
                        invited_user_id=u.id,
                        invite_link_id=link.id,
                    )
                    if is_new:
                        # 更新链接的成员计数
                        link.member_count += 1
                        if awarded and settings.invite_link_notify:
                            try:
                                # 通知邀请人
                                await context.bot.send_message(
                                    chat_id=link.created_by_user_id,
                                    text=f"🎉 恭喜！您邀请的 {u.first_name or u.username or '用户'} 加入了群组 {chat.title}"
                                )
                            except Exception as e:
                                log.warning("invite_notification_failed", inviter_id=link.created_by_user_id, error=str(e))

            ch = await create_or_replace_challenge(
                session,
                chat_id=chat.id,
                user_id=u.id,
                ttl_seconds=settings.verification_timeout_seconds,
                verification_type=settings.verification_mode,
            )

            # 先限制发言（最小限制：不能发消息）
            perms = ChatPermissions(
                can_send_messages=settings.verification_restrict_can_send,
                can_send_audios=False,
                can_send_documents=False,
                can_send_photos=False,
                can_send_videos=False,
                can_send_video_notes=False,
                can_send_voice_notes=False,
                can_send_polls=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
                can_change_info=False,
                can_invite_users=False,
                can_pin_messages=False,
                can_manage_topics=False,
            )
            try:
                await context.bot.restrict_chat_member(chat_id=chat.id, user_id=u.id, permissions=perms)
            except Exception:
                # 权限不足就只能提示
                pass

            # 根据验证类型发送不同的验证消息
            mention = u.mention_html()
            if settings.verification_mode == "button":
                await context.bot.send_message(
                    chat_id=chat.id,
                    text=t(settings.language, "verify.prompt", user=mention, seconds=settings.verification_timeout_seconds),
                    reply_markup=verification_keyboard(ch.token),
                    parse_mode="HTML",
                )
            elif settings.verification_mode == "math":
                await context.bot.send_message(
                    chat_id=chat.id,
                    text=f"🔢 {mention} 请回答以下数学题以完成验证：\n\n<b>{ch.question}</b>\n\n⏱️ {settings.verification_timeout_seconds} 秒内完成",
                    parse_mode="HTML",
                )
            elif settings.verification_mode == "captcha":
                await context.bot.send_message(
                    chat_id=chat.id,
                    text=f"🔢 {mention} 请输入以下验证码以完成验证：\n\n<b>{ch.question}</b>\n\n⏱️ {settings.verification_timeout_seconds} 秒内完成",
                    parse_mode="HTML",
                )
            elif settings.verification_mode == "admin":
                # 管理员确认模式：发送管理员确认请求
                # 管理员确认模式没有超时限制（永久等待管理员审核）
                user_name = u.username or u.first_name or "用户"
                mention_text = f"@{user_name}" if u.username else mention
                await context.bot.send_message(
                    chat_id=chat.id,
                    text=f"👋 {mention_text} 申请加入群组，请管理员确认是否通过。",
                    reply_markup=admin_verify_keyboard(u.id, ch.token),
                    parse_mode="HTML",
                )

        await session.commit()


async def verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None:
        return
    q = update.callback_query
    await q.answer()

    data = q.data or ""
    # vfy:<token>
    token = data.split("vfy:", 1)[-1].strip()
    if not token:
        return

    chat = update.effective_chat
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, chat.id)
        ch = await solve_by_token(session, token)
        await session.commit()

    if ch is None:
        await q.edit_message_text(t("zh-CN", "verify.expired"))
        return

    # 过期：不放行
    if not ch.solved:
        await q.edit_message_text(t(settings.language, "verify.expired"))
        return

    await _unrestrict_and_notify(context, chat.id, ch.user_id, settings.language)
    await q.edit_message_text(t(settings.language, "verify.ok"))


async def verify_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理验证答案消息（数学题/验证码模式）"""
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return

    chat = update.effective_chat
    user = update.effective_user
    message_text = update.effective_message.text or ""

    if chat.type == "private" or not message_text:
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, chat.id)

        # 只处理非按钮模式的验证
        if settings.verification_mode == "button":
            await session.commit()
            return

        # 检查用户是否有待验证的挑战
        ch = await get_challenge(session, chat.id, user.id)
        if ch is None or ch.solved:
            await session.commit()
            return

        # 尝试验证答案
        result = await solve_by_answer(session, chat.id, user.id, message_text)
        await session.commit()

        if result and result.solved:
            # 验证成功
            try:
                await update.effective_message.reply_text("✅ 验证成功！")
            except Exception:
                pass
            await _unrestrict_and_notify(context, chat.id, user.id, settings.language)
        else:
            # 验证失败
            try:
                await update.effective_message.reply_text(f"❌ 答案错误，请重试。\n\n{ch.question}")
            except Exception:
                pass


async def _unrestrict_and_notify(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int, language: str) -> None:
    """解除限制并发送通知"""
    try:
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_audios=True,
                can_send_documents=True,
                can_send_photos=True,
                can_send_videos=True,
                can_send_video_notes=True,
                can_send_voice_notes=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_change_info=False,
                can_invite_users=True,
                can_pin_messages=False,
                can_manage_topics=False,
            ),
        )
    except Exception:
        pass


async def admin_verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """管理员确认验证回调

    处理管理员对用户验证的通过/拒绝操作。

    回调数据格式：adm_vfy:<user_id>:<token>:<action>
    - user_id: 待验证用户 ID
    - token: 验证令牌
    - action: approve（通过）或 reject（拒绝）
    """
    if update.callback_query is None:
        return

    q = update.callback_query
    await q.answer()

    data = q.data or ""
    # 解析回调数据：adm_vfy:<user_id>:<token>:<action>
    parts = data.split(":")
    if len(parts) < 4 or parts[0] != "adm_vfy":
        log.warning("invalid_admin_verify_callback", callback_data=data)
        return

    try:
        user_id = int(parts[1])
        token = parts[2]
        action = parts[3]  # approve 或 reject
    except (ValueError, IndexError) as e:
        log.warning("invalid_admin_verify_callback_format", callback_data=data, error=str(e))
        return

    chat = update.effective_chat
    if chat is None:
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, chat.id)

        if action == "approve":
            # 通过验证
            ch = await solve_by_token(session, token)
            await session.commit()

            if ch and ch.solved:
                # 解除限制并发送通知
                await _unrestrict_and_notify(context, chat.id, user_id, settings.language)
                try:
                    await q.edit_message_text(f"✅ 已通过用户 {user_id} 的验证")
                except Exception as e:
                    log.warning("edit_admin_verify_message_failed", error=str(e))
            else:
                # 验证已过期或不存在
                try:
                    await q.edit_message_text(f"❌ 验证已过期或不存在")
                except Exception as e:
                    log.warning("edit_admin_verify_message_failed", error=str(e))
        else:  # reject
            # 拒绝验证：踢出用户
            try:
                await context.bot.ban_chat_member(chat_id=chat.id, user_id=user_id)
                await q.edit_message_text(f"❌ 已拒绝并踢出用户 {user_id}")
            except Exception as e:
                log.warning("kick_user_failed", user_id=user_id, chat_id=chat.id, error=str(e))
                try:
                    await q.edit_message_text(f"⚠️ 操作失败：{str(e)}")
                except Exception:
                    pass


# ==================== 验证配置相关 ====================

async def verification_config_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理验证配置流程中的消息"""
    # 关键日志 - 使用 critical 确保一定输出
    log.critical(
        "=== VERIFICATION_CONFIG_HANDLER CALLED ===",
        has_update=update is not None,
        has_chat=update.effective_chat is not None if update else False,
        has_user=update.effective_user is not None if update else False,
    )

    # 模块级别的日志，确认 handler 被调用
    import traceback
    log.warning(
        "=== VERIFICATION_CONFIG_HANDLER ENTRY ===",
        chat_id=update.effective_chat.id if update.effective_chat else None,
        user_id=update.effective_user.id if update.effective_user else None,
        chat_type=update.effective_chat.type if update.effective_chat else None,
        traceback=traceback.format_stack()
    )

    try:
        # 基础检查
        if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
            log.info("verification_config_missing_fields", has_chat=update.effective_chat is not None, has_user=update.effective_user is not None, has_message=update.effective_message is not None)
            return

        log.info("verification_config_basic_checks_passed")

        chat = update.effective_chat
        user = update.effective_user
        text = update.effective_message.text or ""

        if not text:
            log.info("verification_config_empty_text")
            return

        log.info("verification_config_getting_db")

        # 获取数据库连接
        db: Database = context.application.bot_data["db"]
        log.info("verification_config_db_obtained", db_instance=str(type(db)))

        async with db.session_factory() as session:
            log.info("verification_config_session_obtained")

            # 获取用户状态
            from bot.services.state.state_service import get_user_state
            from bot.models.enums import ConversationStateType

            state = None
            if chat.type == "private":
                log.info("verification_config_private_chat_mode")

                # 私聊模式：尝试多种方式查找状态
                from bot.services.integration.chat_group_service import get_user_current_chat
                target_chat_id = await get_user_current_chat(db, user.id)

                log.info(
                    "verification_config_state_query",
                    chat_id=chat.id,
                    user_id=user.id,
                    target_chat_id=target_chat_id,
                )

                # 方式1: 通过 get_user_current_chat 获取的 target_chat_id 查询
                if target_chat_id:
                    state = await get_user_state(session, chat_id=target_chat_id, user_id=user.id)
                    log.info("verification_config_state_by_target", state_found=state is not None, target_chat_id=target_chat_id)

                # 方式2: 直接查询用户的所有状态，找到 verification_config 状态
                if state is None:
                    log.info("verification_config_trying_direct_query")
                    from bot.models.core import ConversationState
                    from sqlalchemy import select, desc
                    # 按 ID 倒序排列，获取最新的状态（处理多行情况）
                    stmt = select(ConversationState).where(
                        ConversationState.user_id == user.id,
                        ConversationState.state_type == ConversationStateType.verification_config.value,
                    ).order_by(desc(ConversationState.id))
                    result = await session.execute(stmt)
                    # 使用 first() 获取第一行（最新的状态）
                    row = result.first()
                    state = row[0] if row else None
                    log.info("verification_config_state_by_type", state_found=state is not None)
            else:
                log.info("verification_config_group_chat_mode", chat_id=chat.id)
                state = await get_user_state(session, chat_id=chat.id, user_id=user.id)

            log.info("verification_config_state_check", state_found=state is not None, state_type=state.state_type if state else None)

            if state is None or state.state_type != ConversationStateType.verification_config.value:
                await session.commit()
                log.info("verification_config_state_not_match_returning")
                return

            log.info("verification_config_parsing_config")
            await _parse_verification_config(update, session, state, text)

    except Exception as e:
        log.exception(
            "verification_config_handler_error",
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True
        )


async def _parse_verification_config(update: Update, session, state: object, text: str) -> None:
    """解析验证配置"""
    try:
        lines = text.strip().split("\n")

        # 默认值
        enabled = False
        mode = "button"
        timeout_seconds = 180
        timeout_action = "mute"
        mute_duration = 86400
        restrict_can_send = False

        # 解析配置
        for line in lines:
            line = line.strip()
            if line.startswith("状态:"):
                status_str = line.split(":", 1)[1].strip().lower()
                enabled = status_str in ["开启", "open", "true", "1", "yes", "on"]
            elif line.startswith("验证方式:"):
                mode_str = line.split(":", 1)[1].strip()
                mode_map = {
                    "按钮验证": "button",
                    "button": "button",
                    "数学题": "math",
                    "math": "math",
                    "验证码": "captcha",
                    "captcha": "captcha",
                    "管理员确认": "admin",
                    "admin": "admin",
                    "管理员": "admin",
                }
                mode = mode_map.get(mode_str, mode_str)
            elif line.startswith("超时时间:"):
                try:
                    timeout_seconds = int(line.split(":", 1)[1].strip())
                except ValueError:
                    raise ValueError("超时时间必须是数字")
            elif line.startswith("超时处理:"):
                action_str = line.split(":", 1)[1].strip()
                if action_str in ["禁言", "mute"]:
                    timeout_action = "mute"
                elif action_str in ["踢出", "踢出群聊", "kick"]:
                    timeout_action = "kick"
            elif line.startswith("禁言时长:"):
                try:
                    mute_duration = int(line.split(":", 1)[1].strip())
                except ValueError:
                    raise ValueError("禁言时长必须是数字")
            elif line.startswith("限制发言:"):
                restrict_str = line.split(":", 1)[1].strip().lower()
                restrict_can_send = restrict_str in ["是", "yes", "true", "1", "开启"]

        # 获取目标群组ID
        target_chat_id = state.state_data.get("target_chat_id") or update.effective_chat.id

        # 更新配置
        settings = await get_chat_settings(session, target_chat_id)
        settings.verification_enabled = enabled
        settings.verification_mode = mode
        settings.verification_timeout_seconds = timeout_seconds
        settings.verification_timeout_action = timeout_action
        settings.verification_mute_duration = mute_duration
        settings.verification_restrict_can_send = restrict_can_send

        # 清除状态
        from bot.services.state.state_service import clear_user_state
        await clear_user_state(session, chat_id=target_chat_id, user_id=update.effective_user.id)

        await session.commit()

        # 发送成功消息
        mode_label = {
            "button": "按钮验证",
            "math": "数学题",
            "captcha": "验证码",
            "admin": "管理员确认",
        }.get(mode, mode)

        action_label = "禁言" if timeout_action == "mute" else "踢出"
        status_label = "开启" if enabled else "关闭"

        result_text = f"✅ 验证配置已更新！\n\n"
        result_text += f"📋 配置内容：\n"
        result_text += f"• 状态: {status_label}\n"
        result_text += f"• 验证方式: {mode_label}\n"
        result_text += f"• 超时时间: {timeout_seconds} 秒\n"
        result_text += f"• 超时处理: {action_label}\n"
        if timeout_action == "mute":
            result_text += f"• 禁言时长: {mute_duration} 秒\n"
        result_text += f"• 限制发言: {'是' if restrict_can_send else '否'}\n"

        # 创建返回按钮
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:verification:{target_chat_id}")]
        ])

        await update.effective_message.reply_text(result_text, reply_markup=keyboard)

    except ValueError as e:
        await update.effective_message.reply_text(f"❌ 配置格式错误: {str(e)}\n\n请重新发送配置或使用 /cancel 取消。")
    except Exception as e:
        log.exception("parse_verification_config_error", error=str(e))
        await update.effective_message.reply_text(f"❌ 配置失败: {str(e)}")
