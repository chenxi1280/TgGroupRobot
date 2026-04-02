from __future__ import annotations

import asyncio
import datetime as dt
import html
import structlog
from decimal import Decimal

from telegram import ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from sqlalchemy import select

from bot.db.session import Database
from bot.models.core import BannedWord, TgUser
from bot.models.enums import PointsTxnType
from bot.services.activity.points_service import change_points
from bot.services.core.permission_service import is_user_admin
from bot.services.core.module_settings_service import ModuleSettingsService
from bot.services.integration.alliance_service import AllianceService
from bot.services.integration.garage_features_service import (
    CarReviewService,
    GarageAuthService,
    TeacherSearchService,
)
from bot.services.moderation.auto_reply_service import match_auto_reply
from bot.handlers.auto_reply_handler import _send_auto_reply_payload
from bot.services.moderation.banned_word_service import match_banned_words
from bot.services.scheduled_message_service import ScheduledMessageService
from bot.services.shared.action_executor import ActionExecutor
from bot.services.shared.publish_service import PublishService


log = structlog.get_logger(__name__)


async def unified_group_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    统一的群组消息处理入口

    处理顺序：
    1. 权限判断（是否管理员）
    2. 违禁词检测（管理员跳过）
    3. 自动回复（所有人触发，包括管理员）
    """
    # 强制日志 - 必须在最开始输出，用于诊断 handler 是否被调用
    log.warning(
        "=== UNIFIED_GROUP_MESSAGE_HANDLER ENTRY ===",
        chat_id=update.effective_chat.id if update.effective_chat else None,
        user_id=update.effective_user.id if update.effective_user else None,
        message_text=(update.effective_message.text or update.effective_message.caption or "")[:50],
    )

    # 基础检查
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return False

    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message

    # 只处理群组消息
    if chat.type == "private":
        return False

    # 获取消息文本；非文本消息也要允许继续经过订阅/防护链路。
    message_text = message.text or message.caption or ""

    # 检查用户是否是管理员
    is_admin = False
    try:
        is_admin = await is_user_admin(context, chat.id, user.id)
    except Exception as e:
        log.warning("admin_check_failed", chat_id=chat.id, user_id=user.id, error=str(e))

    log.info(
        "unified_handler_admin_check",
        chat_id=chat.id,
        user_id=user.id,
        is_admin=is_admin,
    )

    db: Database = context.application.bot_data["db"]

    async with db.session_factory() as session:
        old_user = await session.get(TgUser, user.id)
        old_username = old_user.username if old_user else None
        old_name = " ".join(part for part in [old_user.first_name if old_user else None, old_user.last_name if old_user else None] if part) if old_user else ""
        settings = await ModuleSettingsService.ensure(
            session,
            chat.id,
            chat_type=chat.type,
            title=chat.title,
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            language_code=user.language_code,
        )
        await session.commit()

    if await _process_rename_monitor(context, chat, user, settings, old_username, old_name):
        log.info("rename_monitor_processed", chat_id=chat.id, user_id=user.id)

    if await _process_group_lock_controls(context, chat, user, message, settings, is_admin, message_text):
        return True

    if is_admin and await _process_alliance_reply_ban(context, db, chat, user, message, message_text):
        return True

    if not is_admin:
        if await _process_alliance_joint_ban(context, db, chat, user, message):
            return True
        subscribed = await _check_force_subscribe(context, chat, user, message, settings)
        if not subscribed:
            return True

    if await _process_garage_features(context, db, chat, user, message, message_text, settings, is_admin):
        return True

    if message_text:
        # 违禁词检测（管理员跳过）
        if not is_admin:
            deleted = await _process_banned_word_check(context, db, chat, user, message, message_text)
            if deleted:
                return True
        else:
            log.info("unified_handler_skip_banned_word_admin", chat_id=chat.id, user_id=user.id)

        # 自动回复（所有人触发，包括管理员）
        await _process_auto_reply(context, db, chat, message, message_text)

    return False


async def _process_alliance_reply_ban(
    context: ContextTypes.DEFAULT_TYPE,
    db: Database,
    chat,
    user,
    message,
    message_text: str,
) -> bool:
    if message_text.strip().lower() != "t" or message.reply_to_message is None:
        return False

    target_user = getattr(message.reply_to_message, "from_user", None)
    if target_user is None:
        return False

    try:
        async with db.session_factory() as session:
            member = await AllianceService.get_member(session, chat.id)
            await session.commit()
        if member is None:
            return False

        await ActionExecutor.execute(
            context,
            action="ban",
            chat_id=chat.id,
            user_id=target_user.id,
            actor_user_id=user.id,
            reason="联盟联合封禁",
            message_id=getattr(message.reply_to_message, "message_id", None),
            sender_chat_id=getattr(getattr(message.reply_to_message, "sender_chat", None), "id", None),
        )
        try:
            async with db.session_factory() as session:
                await AllianceService.add_joint_ban_entry(
                    session,
                    chat_id=chat.id,
                    operator_user_id=user.id,
                    target_user_id=target_user.id,
                    reason="reply_t_command",
                )
                await session.commit()
        except Exception as exc:
            log.warning("alliance_ban_pool_append_failed", chat_id=chat.id, target_user_id=target_user.id, error=str(exc))
            try:
                await message.reply_text("当前群已封禁目标用户，但加入联盟封禁名单失败。")
            except Exception:
                pass
            return True
        try:
            await message.reply_text("已加入联盟联合封禁名单，并在当前群执行封禁。")
        except Exception:
            pass
        return True
    except Exception as exc:
        log.warning("alliance_reply_ban_failed", chat_id=chat.id, user_id=user.id, error=str(exc))
        try:
            await message.reply_text("联合封禁失败，请确认当前群已加入联盟。")
        except Exception:
            pass
        return False


async def _process_alliance_joint_ban(
    context: ContextTypes.DEFAULT_TYPE,
    db: Database,
    chat,
    user,
    message,
) -> bool:
    async with db.session_factory() as session:
        hit = await AllianceService.get_joint_ban_hit(
            session,
            chat_id=chat.id,
            target_user_id=user.id,
        )
        if hit is None:
            await session.commit()
            return False
        _, ban_item = hit
        await session.commit()

    try:
        await ActionExecutor.execute(
            context,
            action="ban",
            chat_id=chat.id,
            user_id=user.id,
            actor_user_id=ban_item.source_operator_user_id,
            reason="联盟联合封禁同步",
            message_id=message.message_id,
            sender_chat_id=getattr(getattr(message, "sender_chat", None), "id", None),
        )
        return True
    except Exception as exc:
        log.warning(
            "alliance_joint_ban_enforce_failed",
            chat_id=chat.id,
            user_id=user.id,
            error=str(exc),
        )
        return False


async def _process_banned_word_check(
    context: ContextTypes.DEFAULT_TYPE,
    db: Database,
    chat,
    user,
    message,
    message_text: str,
) -> bool:
    """
    处理违禁词检测

    Args:
        context: Bot 上下文
        db: 数据库连接
        chat: 群组对象
        user: 用户对象
        message: 消息对象
        message_text: 消息文本
    """
    log.info(
        "unified_handler_banned_word_check_start",
        chat_id=chat.id,
        user_id=user.id,
        message_text_preview=message_text[:50],
    )

    async with db.session_factory() as session:
        matched_words = await match_banned_words(session, chat.id, message_text)
        await session.commit()

    log.info(
        "unified_handler_banned_word_check_result",
        chat_id=chat.id,
        user_id=user.id,
        matched_count=len(matched_words),
    )

    if matched_words:
        # 使用第一个匹配的违禁词的配置
        word = matched_words[0]

        log.info(
            "banned_word_detected",
            chat_id=chat.id,
            user_id=user.id,
            username=user.username,
            word=word.word,
            action=word.action,
        )

        # 删除消息
        try:
            await message.delete()
        except Exception as e:
            log.warning("delete_message_failed", chat_id=chat.id, user_id=user.id, error=str(e))

        # 发送提醒
        if word.notify:
            notify_msg = word.notify_message or f"🚫 您的消息因包含违禁词「{word.word}」已被删除"
            try:
                await context.bot.send_message(chat_id=chat.id, text=notify_msg)
            except Exception as e:
                log.warning("send_notify_failed", chat_id=chat.id, error=str(e))

        # 执行惩罚
        if word.action == "mute":
            try:
                until_date = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=word.mute_duration) if word.mute_duration else None
                await context.bot.restrict_chat_member(
                    chat_id=chat.id,
                    user_id=user.id,
                    permissions={"can_send_messages": False, "can_send_media_messages": False},
                    until_date=until_date,
                )
            except Exception as e:
                log.warning("mute_user_failed", chat_id=chat.id, user_id=user.id, error=str(e))
        elif word.action == "ban":
            try:
                await context.bot.ban_chat_member(chat_id=chat.id, user_id=user.id)
            except Exception as e:
                log.warning("ban_user_failed", chat_id=chat.id, user_id=user.id, error=str(e))

        return True

    return False


async def _process_auto_reply(
    context: ContextTypes.DEFAULT_TYPE,
    db: Database,
    chat,
    message,
    message_text: str,
) -> None:
    """
    处理自动回复

    Args:
        context: Bot 上下文
        db: 数据库连接
        chat: 群组对象
        message_text: 消息文本
    """
    log.info(
        "unified_handler_auto_reply_start",
        chat_id=chat.id,
        message_text_preview=message_text[:50],
    )

    async with db.session_factory() as session:
        result = await match_auto_reply(session, chat.id, message_text)
        await session.commit()

    log.info(
        "unified_handler_auto_reply_result",
        chat_id=chat.id,
        matched=result.success,
        has_reply_content=bool(result.reply_content),
    )

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
                        reply_to_message_id=message.message_id,
                    )
                )
            if any(getattr(rule, "delete_source", False) for rule in matched_rules):
                try:
                    await message.delete()
                except Exception as exc:
                    log.warning("auto_reply_delete_source_failed", chat_id=chat.id, error=str(exc))
            for matched_rule, sent_message in zip(matched_rules, sent_messages, strict=False):
                delete_after = getattr(matched_rule, "delete_reply_delay_seconds", 0) or 0
                if delete_after > 0:
                    asyncio.create_task(_delete_message_later(sent_message, delete_after))
            log.info(
                "unified_handler_auto_reply_sent",
                chat_id=chat.id,
                reply_content_preview=result.reply_content[:50],
                delete_source=any(bool(getattr(rule, "delete_source", False)) for rule in matched_rules),
                delete_reply_delay_seconds=max((getattr(rule, "delete_reply_delay_seconds", 0) or 0) for rule in matched_rules) if matched_rules else 0,
            )
        except Exception as e:
            log.warning("auto_reply_send_failed", chat_id=chat.id, error=str(e))


async def _process_rename_monitor(
    context: ContextTypes.DEFAULT_TYPE,
    chat,
    user,
    settings,
    old_username: str | None,
    old_name: str,
) -> bool:
    if not bool(getattr(settings, "name_change_monitor_enabled", False)):
        return False

    new_username = user.username or ""
    new_name = " ".join(part for part in [user.first_name, user.last_name] if part)
    changes: list[tuple[str, str, str]] = []
    if (old_username or "") != new_username and (old_username or ""):
        changes.append(("用户名", old_username or "空", new_username or "空"))
    if old_name and old_name != new_name:
        changes.append(("昵称", old_name, new_name or "空"))
    if not changes:
        return False

    template = getattr(settings, "name_change_monitor_template_text", None) or (
        "检测到用户{userId}修改{changeType}\n原{changeType}: {oldContent}\n新{changeType}: {newContent}"
    )
    delete_after = int(getattr(settings, "name_change_monitor_delete_after_seconds", 60) or 60)

    for change_type, old_content, new_content in changes:
        text = (
            template
            .replace("{userId}", str(user.id))
            .replace("{changeType}", change_type)
            .replace("{oldContent}", old_content)
            .replace("{newContent}", new_content)
        )
        try:
            sent = await context.bot.send_message(chat.id, text)
            if delete_after > 0:
                asyncio.create_task(_delete_message_later(sent, delete_after))
        except Exception as exc:
            log.warning("rename_monitor_send_failed", chat_id=chat.id, user_id=user.id, error=str(exc))
    return True


def _is_closed_by_schedule(settings) -> bool | None:
    if not bool(getattr(settings, "group_lock_schedule_enabled", False)):
        return None

    open_time = getattr(settings, "group_lock_open_time", None)
    close_time = getattr(settings, "group_lock_close_time", None)
    if not open_time or not close_time:
        return False

    try:
        open_hour, open_minute = [int(x) for x in open_time.split(":", 1)]
        close_hour, close_minute = [int(x) for x in close_time.split(":", 1)]
    except Exception:
        return None

    now = dt.datetime.now().time()
    now_min = now.hour * 60 + now.minute
    open_min = open_hour * 60 + open_minute
    close_min = close_hour * 60 + close_minute
    if open_min == close_min:
        return None
    if close_min < open_min:
        return close_min <= now_min < open_min
    return now_min >= close_min or now_min < open_min


async def _apply_group_lock_permissions(context: ContextTypes.DEFAULT_TYPE, chat_id: int, closed: bool) -> None:
    permissions = ChatPermissions(can_send_messages=not closed)
    await context.bot.set_chat_permissions(chat_id=chat_id, permissions=permissions)


async def _process_group_lock_controls(
    context: ContextTypes.DEFAULT_TYPE,
    chat,
    user,
    message,
    settings,
    is_admin: bool,
    message_text: str,
) -> bool:
    lock_cache: dict[int, bool] = context.application.bot_data.setdefault("group_lock_state", {})
    desired_closed = _is_closed_by_schedule(settings)
    current_closed = lock_cache.get(chat.id)
    if desired_closed is not None and (current_closed is None or current_closed != desired_closed):
        try:
            await _apply_group_lock_permissions(context, chat.id, desired_closed)
            lock_cache[chat.id] = desired_closed
        except Exception as exc:
            log.warning("group_lock_schedule_apply_failed", chat_id=chat.id, error=str(exc))

    if not is_admin or not bool(getattr(settings, "group_lock_phrase_enabled", False)):
        return False

    try:
        member = await context.bot.get_chat_member(chat_id=chat.id, user_id=user.id)
    except Exception as exc:
        log.warning("group_lock_phrase_member_lookup_failed", chat_id=chat.id, user_id=user.id, error=str(exc))
        return False

    if member.status != "creator" and not bool(getattr(member, "can_promote_members", False)):
        return False

    open_phrase = (getattr(settings, "group_lock_open_phrase", None) or "").strip()
    close_phrase = (getattr(settings, "group_lock_close_phrase", None) or "").strip()
    normalized = message_text.strip()
    if not normalized or normalized not in {open_phrase, close_phrase}:
        return False

    close_now = normalized == close_phrase
    try:
        await _apply_group_lock_permissions(context, chat.id, close_now)
        lock_cache[chat.id] = close_now
        if getattr(settings, "group_lock_delete_notice_mode", "keep") == "delete":
            await message.delete()
    except Exception as exc:
        log.warning("group_lock_phrase_apply_failed", chat_id=chat.id, user_id=user.id, error=str(exc))
    return True


def _build_force_subscribe_channel_button(value: str | None) -> InlineKeyboardButton | None:
    if not value:
        return None
    label = value
    url: str | None = None
    if value.startswith("@"):
        url = f"https://t.me/{value[1:]}"
    elif value.startswith("https://t.me/") or value.startswith("http://t.me/"):
        url = value
    if url is None:
        return None
    return InlineKeyboardButton(label, url=url)


def _build_force_subscribe_markup(settings) -> InlineKeyboardMarkup | None:
    custom_enabled = bool(getattr(settings, "force_subscribe_custom_buttons_enabled", False))
    custom_buttons = getattr(settings, "force_subscribe_buttons", None) or []
    if custom_enabled and custom_buttons:
        try:
            normalized = ScheduledMessageService.normalize_buttons_config(custom_buttons)
            keyboard = [
                [InlineKeyboardButton(btn["text"], url=btn["url"]) for btn in row]
                for row in normalized
            ]
            if keyboard:
                return InlineKeyboardMarkup(keyboard)
        except Exception as exc:
            log.warning("force_subscribe_custom_buttons_invalid", error=str(exc))

    buttons = [
        button
        for button in (
            _build_force_subscribe_channel_button(getattr(settings, "force_subscribe_bound_channel_1", None)),
            _build_force_subscribe_channel_button(getattr(settings, "force_subscribe_bound_channel_2", None)),
        )
        if button is not None
    ]
    return InlineKeyboardMarkup([[button] for button in buttons]) if buttons else None


async def _check_force_subscribe(
    context: ContextTypes.DEFAULT_TYPE,
    chat,
    user,
    message,
    settings,
) -> bool:
    if not bool(getattr(settings, "force_subscribe_enabled", False)):
        return True

    channels = [
        getattr(settings, "force_subscribe_bound_channel_1", None),
        getattr(settings, "force_subscribe_bound_channel_2", None),
    ]
    channels = [channel for channel in channels if channel]
    if not channels:
        return True

    subscribed_results: list[bool] = []
    for channel in channels:
        try:
            member = await context.bot.get_chat_member(channel, user.id)
            subscribed_results.append(member.status not in {"left", "kicked"})
        except Exception:
            subscribed_results.append(False)

    check_mode = getattr(settings, "force_subscribe_check_mode", "all")
    subscribed = all(subscribed_results) if check_mode == "all" else any(subscribed_results)
    if subscribed:
        return True

    action = getattr(settings, "force_subscribe_not_subscribed_action", "delete_and_warn")
    if action in {"delete_and_warn", "delete_only"}:
        try:
            await message.delete()
        except Exception as exc:
            log.warning("force_subscribe_delete_failed", chat_id=chat.id, user_id=user.id, error=str(exc))
    if action == "mute":
        try:
            await context.bot.restrict_chat_member(
                chat.id,
                user.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=dt.datetime.now(dt.UTC) + dt.timedelta(minutes=10),
            )
        except Exception as exc:
            log.warning("force_subscribe_mute_failed", chat_id=chat.id, user_id=user.id, error=str(exc))

    if action in {"delete_and_warn", "warn_only", "mute"}:
        guide_text = getattr(settings, "force_subscribe_guide_text", None) or "{member}，您需要关注我们的频道才能发言。"
        text = (
            guide_text
            .replace("{member}", html.escape(user.full_name))
            .replace("{userid}", str(user.id))
            .replace("{nickname}", html.escape(user.full_name))
        )
        markup = _build_force_subscribe_markup(settings)
        try:
            cover_type = getattr(settings, "force_subscribe_cover_media_type", None)
            cover_file_id = getattr(settings, "force_subscribe_cover_file_id", None)
            if cover_type == "photo" and cover_file_id:
                sent = await context.bot.send_photo(
                    chat.id,
                    photo=cover_file_id,
                    caption=text,
                    reply_markup=markup,
                    parse_mode="HTML",
                )
            elif cover_type == "video" and cover_file_id:
                sent = await context.bot.send_video(
                    chat.id,
                    video=cover_file_id,
                    caption=text,
                    reply_markup=markup,
                    parse_mode="HTML",
                )
            else:
                sent = await context.bot.send_message(
                    chat.id,
                    text,
                    reply_markup=markup,
                    parse_mode="HTML",
                )
            delete_after = int(getattr(settings, "force_subscribe_delete_warn_after_seconds", 60) or 60)
            if delete_after > 0:
                asyncio.create_task(_delete_message_later(sent, delete_after))
        except Exception as exc:
            log.warning("force_subscribe_warn_failed", chat_id=chat.id, user_id=user.id, error=str(exc))

    return False


async def _delete_message_later(message, seconds: int) -> None:
    try:
        await asyncio.sleep(seconds)
        await message.delete()
    except Exception:
        return


def _garage_limit_hits_message(message, message_text: str, mode: str) -> bool:
    has_media = any(
        getattr(message, attr, None)
        for attr in ("photo", "video", "document", "animation")
    )
    if mode == "image":
        return bool(has_media)
    if mode == "image_text":
        return bool(has_media or message_text.strip())
    return False


async def _publish_car_review_report(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    report,
    setting,
    teacher_user: TgUser | None,
    author_user: TgUser | None,
) -> int | None:
    score_payload = report.scores or {}
    teacher_name = (
        f"@{teacher_user.username}"
        if teacher_user and teacher_user.username
        else (teacher_user.first_name if teacher_user and teacher_user.first_name else str(report.teacher_user_id))
    )
    author_name = (
        f"@{author_user.username}"
        if author_user and author_user.username
        else (author_user.first_name if author_user and author_user.first_name else str(report.author_user_id))
    )
    text = (
        setting.template_text
        .replace("{time}", report.created_at.astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"))
        .replace("{teacher}", html.escape(teacher_name))
        .replace("{author}", html.escape(author_name))
        .replace("{review}", html.escape(report.review_text or "待审核"))
        .replace("{photo_score}", str(score_payload.get("photo_score", "-")))
        .replace("{face_score}", str(score_payload.get("face_score", "-")))
        .replace("{body_score}", str(score_payload.get("body_score", "-")))
        .replace("{service_score}", str(score_payload.get("service_score", "-")))
        .replace("{attitude_score}", str(score_payload.get("attitude_score", "-")))
        .replace("{env_score}", str(score_payload.get("env_score", "-")))
        .replace("{total_score}", str(score_payload.get("total_score", "-")))
        .replace("{process}", html.escape(report.process_text or report.review_text or "无"))
    )
    published_message_id: int | None = None
    if getattr(setting, "publish_to_main_group", False):
        result = await PublishService.send(context, chat_id=chat_id, text=text, parse_mode="HTML")
        published_message_id = result.message_id
    return published_message_id


async def _process_garage_features(
    context: ContextTypes.DEFAULT_TYPE,
    db: Database,
    chat,
    user,
    message,
    message_text: str,
    settings,
    is_admin: bool,
) -> bool:
    text = (message_text or "").strip()
    lower_text = text.lower()
    async with db.session_factory() as session:
        teacher_setting = await TeacherSearchService.get_setting(session, chat.id)
        car_review_setting = await CarReviewService.get_setting(session, chat.id)
        is_teacher = await GarageAuthService.is_certified_teacher(session, chat.id, user.id)
        is_whitelisted = await GarageAuthService.is_whitelisted(session, chat.id, user.id)

        if getattr(settings, "garage_limit_enabled", False) and not is_admin and is_teacher and not is_whitelisted:
            mode = getattr(settings, "garage_limit_mode", "none")
            if _garage_limit_hits_message(message, text, mode):
                tracker = context.application.bot_data.setdefault("garage_limit_tracker", {})
                key = (chat.id, user.id)
                now_ts = dt.datetime.now(dt.UTC).timestamp()
                interval = max(int(getattr(settings, "garage_limit_interval_sec", 3600) or 3600), 1)
                max_count = max(int(getattr(settings, "garage_limit_max_count", 1) or 1), 1)
                history = [ts for ts in tracker.get(key, []) if now_ts - ts < interval]
                history.append(now_ts)
                tracker[key] = history
                if len(history) > max_count:
                    await session.commit()
                    try:
                        await ActionExecutor.execute(
                            context,
                            action="delete",
                            chat_id=chat.id,
                            user_id=user.id,
                            reason="车库发言限制",
                            actor_user_id=None,
                            message_id=message.message_id,
                            sender_chat_id=getattr(getattr(message, "sender_chat", None), "id", None),
                        )
                    except Exception as exc:
                        log.warning("garage_limit_delete_failed", chat_id=chat.id, user_id=user.id, error=str(exc))
                    await PublishService.send_temporary(
                        context,
                        chat_id=chat.id,
                        text="当前老师发言过于频繁，消息已被限制。",
                        delete_after_seconds=15,
                    )
                    return True

        if getattr(message, "location", None) is not None and teacher_setting.nearby_search_enabled:
            latitude = float(message.location.latitude)
            longitude = float(message.location.longitude)
            await TeacherSearchService.upsert_member_location(
                session,
                chat_id=chat.id,
                user_id=user.id,
                latitude=latitude,
                longitude=longitude,
                operator_user_id=user.id,
            )
            if is_teacher:
                await TeacherSearchService.upsert_teacher_profile_from_location(
                    session,
                    chat_id=chat.id,
                    user_id=user.id,
                    latitude=latitude,
                    longitude=longitude,
                )
            await session.commit()
            await PublishService.send_temporary(
                context,
                chat_id=chat.id,
                text="已记录当前位置。",
                delete_after_seconds=10,
                reply_to_message_id=message.message_id,
            )
            return True

        if teacher_setting.attendance_enabled and is_teacher and text and not text.startswith("/"):
            await TeacherSearchService.mark_attendance(
                session,
                chat_id=chat.id,
                user_id=user.id,
                source_message_id=message.message_id,
            )

        if text == "开课老师":
            rows = await TeacherSearchService.list_open_course_teachers(session, chat.id)
            await session.commit()
            if not rows:
                await PublishService.reply(
                    context,
                    chat_id=chat.id,
                    text="今天还没有开课老师。",
                    reply_to_message_id=message.message_id,
                )
                return True
            lines = ["今日开课老师："]
            for idx, (profile, tg_user) in enumerate(rows[:10], start=1):
                name = f"@{tg_user.username}" if tg_user and tg_user.username else (tg_user.first_name if tg_user and tg_user.first_name else f"用户{profile.user_id}")
                extra = " / ".join(part for part in [profile.region_text, profile.price_text] if part)
                lines.append(f"{idx}. {name}" + (f"  {extra}" if extra else ""))
            await PublishService.reply(
                context,
                chat_id=chat.id,
                text="\n".join(lines),
                reply_to_message_id=message.message_id,
            )
            return True

        if text == "附近":
            if teacher_setting.force_location_enabled:
                location = await TeacherSearchService.get_member_location(session, chat.id, user.id)
                if location is None:
                    await session.commit()
                    await PublishService.reply(
                        context,
                        chat_id=chat.id,
                        text="请先发送位置后再使用附近搜索。",
                        reply_to_message_id=message.message_id,
                    )
                    return True
            else:
                location = await TeacherSearchService.get_member_location(session, chat.id, user.id)

            if location is None:
                await session.commit()
                await PublishService.reply(
                    context,
                    chat_id=chat.id,
                    text="还没有记录到你的位置，请先发送位置。",
                    reply_to_message_id=message.message_id,
                )
                return True

            nearby = await TeacherSearchService.list_nearby_teachers(
                session,
                chat.id,
                float(location.latitude),
                float(location.longitude),
                only_open_course=True,
                limit=10,
            )
            await session.commit()
            if not nearby:
                await PublishService.reply(
                    context,
                    chat_id=chat.id,
                    text="附近暂无开课老师。",
                    reply_to_message_id=message.message_id,
                )
                return True
            lines = ["附近老师："]
            for idx, item in enumerate(nearby, start=1):
                profile = item["profile"]
                extra = " / ".join(part for part in [profile.region_text, profile.price_text] if part)
                lines.append(f"{idx}. {item['display_name']} · {item['distance_text']}" + (f" · {extra}" if extra else ""))
            await PublishService.reply(
                context,
                chat_id=chat.id,
                text="\n".join(lines),
                reply_to_message_id=message.message_id,
            )
            return True

        if text.startswith("老师搜索 "):
            keyword = text.split(" ", 1)[1].strip()
            rows = await TeacherSearchService.search_teachers_by_keyword(
                session,
                chat.id,
                keyword,
                only_open_course=True,
                limit=10,
            )
            await session.commit()
            if not rows:
                await PublishService.reply(
                    context,
                    chat_id=chat.id,
                    text="没有找到匹配的老师。",
                    reply_to_message_id=message.message_id,
                )
                return True
            lines = [f"老师搜索：{keyword}"]
            for idx, (profile, tg_user) in enumerate(rows, start=1):
                name = f"@{tg_user.username}" if tg_user and tg_user.username else (tg_user.first_name if tg_user and tg_user.first_name else f"用户{profile.user_id}")
                labels = " ".join(profile.labels or [])
                extra = " / ".join(part for part in [labels, profile.region_text, profile.price_text] if part)
                lines.append(f"{idx}. {name}" + (f" · {extra}" if extra else ""))
            await PublishService.reply(
                context,
                chat_id=chat.id,
                text="\n".join(lines),
                reply_to_message_id=message.message_id,
            )
            return True

        footer_label = (teacher_setting.footer_button_label or "").strip()
        if footer_label and text == footer_label:
            await session.commit()
            await PublishService.reply(
                context,
                chat_id=chat.id,
                text="请继续发送关键词，或发送“附近”“开课老师”查询。",
                reply_to_message_id=message.message_id,
            )
            return True

        if car_review_setting.enabled and text == car_review_setting.rank_command.strip():
            rankings = await CarReviewService.list_rankings(session, chat.id, limit=10)
            await session.commit()
            if not rankings:
                await PublishService.reply(
                    context,
                    chat_id=chat.id,
                    text="暂无车评排行数据。",
                    reply_to_message_id=message.message_id,
                )
                return True
            lines = ["出击排行："]
            for idx, row in enumerate(rankings, start=1):
                lines.append(f"{idx}. {row['display_name']} · 均分 {row['avg_score']} · {row['count']} 条")
            await PublishService.reply(
                context,
                chat_id=chat.id,
                text="\n".join(lines),
                reply_to_message_id=message.message_id,
            )
            return True

        submit_command = car_review_setting.submit_command.strip()
        if car_review_setting.enabled and submit_command and text.startswith(submit_command):
            replied_user = getattr(getattr(message, "reply_to_message", None), "from_user", None)
            if replied_user is None:
                await session.commit()
                await PublishService.reply(
                    context,
                    chat_id=chat.id,
                    text="提交车评请回复目标老师的消息后再发送指令。",
                    reply_to_message_id=message.message_id,
                )
                return True
            review_text = text[len(submit_command):].strip() or "待补充"
            report = await CarReviewService.create_report(
                session,
                chat_id=chat.id,
                teacher_user_id=replied_user.id,
                author_user_id=user.id,
                review_text=review_text,
                media_file_ids=[],
                scores={"total_score": 0},
            )
            if car_review_setting.approver_user_id:
                await session.commit()
                try:
                    await PublishService.send(
                        context,
                        chat_id=car_review_setting.approver_user_id,
                        text=f"收到新的车评待审核\n群：{chat.title}\n报告ID：{report.report_id}\n提交人：{user.full_name}",
                    )
                except Exception as exc:
                    log.warning("car_review_notify_approver_failed", chat_id=chat.id, report_id=report.report_id, error=str(exc))
                await PublishService.reply(
                    context,
                    chat_id=chat.id,
                    text=f"已提交车评报告，等待审核。报告ID：{report.report_id}",
                    reply_to_message_id=message.message_id,
                )
                return True

            approved = await CarReviewService.approve_report(
                session,
                chat_id=chat.id,
                report_id=report.report_id,
                approver_user_id=user.id,
            )
            teacher_row = await session.get(TgUser, replied_user.id)
            author_row = await session.get(TgUser, user.id)
            if approved is not None:
                published_message_id = await _publish_car_review_report(
                    context,
                    chat_id=chat.id,
                    report=approved,
                    setting=car_review_setting,
                    teacher_user=teacher_row,
                    author_user=author_row,
                )
                if published_message_id is not None:
                    approved.published_message_id = published_message_id
                    approved.report_status = "published"
                if car_review_setting.reward_points > 0:
                    await change_points(
                        session,
                        chat.id,
                        user.id,
                        car_review_setting.reward_points,
                        PointsTxnType.reward.value,
                        reason="车评审核通过奖励",
                    )
            await session.commit()
            await PublishService.reply(
                context,
                chat_id=chat.id,
                text=f"车评已提交并发布。报告ID：{report.report_id}",
                reply_to_message_id=message.message_id,
            )
            return True

        await session.commit()
    return False
