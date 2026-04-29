from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database

log = structlog.get_logger(__name__)

RESERVED_GROUP_TEXT_COMMANDS = frozenset({"签到", "积分", "积分排行"})
INVITE_TEXT_COMMANDS = frozenset({"邀请", "邀请统计", "邀请排行"})
GAME_TEXT_COMMANDS = frozenset({
    "快3",
    "快三",
    "快3规则",
    "快三规则",
    "快3统计",
    "快三统计",
    "黑杰克",
    "黑杰克规则",
    "黑杰克统计",
})


class _MessageTextProxy:
    def __init__(self, message, text: str) -> None:
        self._message = message
        self.text = text
        self.caption = None

    def __getattr__(self, name: str):
        return getattr(self._message, name)


class _UpdateTextProxy:
    def __init__(self, update: Update, text: str) -> None:
        self._update = update
        self.effective_message = _MessageTextProxy(update.effective_message, text)
        self.effective_chat = update.effective_chat
        self.effective_user = update.effective_user
        self.callback_query = getattr(update, "callback_query", None)

    def __getattr__(self, name: str):
        return getattr(self._update, name)


def _with_effective_message_text(update: Update, text: str) -> Update:
    if update.effective_message is None:
        return update
    return _UpdateTextProxy(update, text)  # type: ignore[return-value]


def is_reserved_group_text_command(text: str) -> bool:
    return text.strip() in RESERVED_GROUP_TEXT_COMMANDS


async def get_reserved_group_text_commands(session, chat_id: int) -> set[str]:
    from backend.shared.services.chat_service import get_chat_settings

    commands = set(RESERVED_GROUP_TEXT_COMMANDS)
    settings = await get_chat_settings(session, chat_id)
    for attr in ("points_alias", "points_rank_alias"):
        value = str(getattr(settings, attr, "") or "").strip()
        if value:
            commands.add(value)
    return commands


async def is_reserved_group_text_command_for_chat(session, chat_id: int, text: str) -> bool:
    normalized = text.strip()
    if not normalized:
        return False
    if normalized in RESERVED_GROUP_TEXT_COMMANDS:
        return True
    return normalized in await get_reserved_group_text_commands(session, chat_id)


async def _try_points_text_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE, payload: str) -> bool:
    from backend.features.points.points_handler import points_text_trigger_handler

    return await points_text_trigger_handler(update, context, payload)


async def try_bottom_button_text_trigger(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    button_text: str,
) -> bool:
    if update.effective_message is None:
        return False

    from backend.features.group_ops.services.bottom_button_service import (
        get_enabled_layout_by_button_text,
        resolve_layout_trigger_text,
    )

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        layout = await get_enabled_layout_by_button_text(session, chat_id, button_text)
        if layout is None:
            await session.commit()
            return False
        trigger_text = await resolve_layout_trigger_text(session, chat_id, layout)
        await session.commit()

    if not trigger_text:
        await update.effective_message.reply_text("底部按钮事件未配置，请联系管理员。")
        return True

    handled = await try_group_text_trigger(update, context, chat_id, trigger_text)
    if not handled and layout.action_mode != "event":
        handled = await _try_auto_reply_trigger(update, context, chat_id, trigger_text)
    if not handled:
        await update.effective_message.reply_text("该底部按钮事件当前不可用，请联系管理员检查功能配置。")
    return True


async def _try_garage_text_trigger(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    payload: str,
) -> bool:
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return False
    if update.effective_chat.id != chat_id:
        return False
    if update.effective_chat.type not in {"group", "supergroup"}:
        return False

    from backend.features.garage.services.garage_features_service import (
        CarReviewService,
        GarageAuthService,
        TeacherSearchService,
    )
    from backend.features.group_ops.group_hooks.car_review import _process_car_review_features
    from backend.features.group_ops.group_hooks.teacher_search import (
        _process_teacher_search_features,
        _reply_attendance_checkin,
    )
    from backend.shared.services.permission_service import is_user_admin

    db: Database = context.application.bot_data["db"]
    try:
        is_admin = await is_user_admin(context, chat_id, update.effective_user.id)
    except Exception as exc:
        log.warning(
            "text_trigger_admin_check_failed",
            chat_id=chat_id,
            user_id=update.effective_user.id,
            error=str(exc),
        )
        is_admin = False

    async with db.session_factory() as session:
        teacher_setting = await TeacherSearchService.get_setting(session, chat_id)
        car_review_setting = await CarReviewService.get_setting(session, chat_id)
        is_teacher = await GarageAuthService.is_certified_teacher(session, chat_id, update.effective_user.id)
        is_whitelisted = await GarageAuthService.is_whitelisted(session, chat_id, update.effective_user.id)
        attendance_mode = getattr(teacher_setting, "attendance_mode", "message") or "message"
        if attendance_mode != "external":
            attendance_keywords = {
                "full": getattr(teacher_setting, "attendance_full_keyword", "满课") or "满课",
                "rest": getattr(teacher_setting, "attendance_rest_keyword", "休息") or "休息",
            }
            for status, keyword in attendance_keywords.items():
                if payload == keyword:
                    await _reply_attendance_checkin(
                        context,
                        session,
                        update.effective_chat,
                        update.effective_user,
                        update.effective_message,
                        teacher_setting,
                        is_teacher=is_teacher,
                        status=status,
                    )
                    return True
        if await _process_teacher_search_features(
            context,
            session,
            update.effective_chat,
            update.effective_user,
            update.effective_message,
            payload,
            teacher_setting,
            is_teacher=is_teacher,
            is_admin=is_admin,
            is_whitelisted=is_whitelisted,
        ):
            return True
        handled = await _process_car_review_features(
            context,
            session,
            update.effective_chat,
            update.effective_user,
            update.effective_message,
            payload,
            car_review_setting,
        )
        if not handled:
            await session.commit()
        return handled


async def _try_teacher_search_trigger(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    payload: str,
) -> bool:
    return await _try_garage_text_trigger(update, context, chat_id, payload)


async def _try_invite_trigger(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    payload: str,
) -> bool:
    if payload not in INVITE_TEXT_COMMANDS:
        return False
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return False
    if update.effective_chat.id != chat_id:
        return False
    if payload == "邀请":
        from backend.features.invite.invite_user_callbacks import link_command

        await link_command(update, context)
        return True
    if payload == "邀请统计":
        from backend.features.invite.invite_user_callbacks import link_stat_command

        await link_stat_command(update, context)
        return True

    from backend.features.invite.services.invite_service import get_invite_leaderboard, get_user_rank

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        leaderboard = await get_invite_leaderboard(session, chat_id, limit=10)
        user_rank = await get_user_rank(session, chat_id, update.effective_user.id)
        await session.commit()

    if not leaderboard:
        await update.effective_message.reply_text("🏆 邀请排行榜\n\n暂无邀请数据")
        return True

    lines = ["🏆 邀请排行榜（前10名）", ""]
    for index, (user_id, count, username) in enumerate(leaderboard, start=1):
        lines.append(f"{index}. {username or f'用户{user_id}'} - {count} 人")
    if user_rank:
        lines.append(f"\n你的排名: 第 {user_rank} 名")
    await update.effective_message.reply_text("\n".join(lines))
    return True


async def _try_game_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE, payload: str) -> bool:
    if payload not in GAME_TEXT_COMMANDS:
        return False
    from backend.features.activity.game_message_actions import handle_game_message

    return await handle_game_message(_with_effective_message_text(update, payload), context)


async def _try_guess_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE, payload: str) -> bool:
    if getattr(update, "effective_chat", None) is None or getattr(update, "effective_message", None) is None:
        return False
    if not payload or len(payload) > 32 or " " in payload:
        return False
    from backend.features.activity.guess_handler import guess_message_handler

    return await guess_message_handler(_with_effective_message_text(update, payload), context)


async def _try_engagement_reward_trigger(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    payload: str,
) -> bool:
    if (
        getattr(update, "effective_chat", None) is None
        or getattr(update, "effective_user", None) is None
        or getattr(update, "effective_message", None) is None
    ):
        return False
    if update.effective_chat.id != chat_id or not payload or len(payload) > 32:
        return False

    from backend.features.activity.engagement_handler import engagement_message_handler
    from backend.platform.db.schema.models.expansion import EngagementChatReward

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        reward = await session.get(EngagementChatReward, chat_id)
        command_keyword = str(getattr(reward, "command_keyword", "") or "").strip() if reward is not None else "我爱水群"
        await session.commit()
    if payload != command_keyword:
        return False
    return await engagement_message_handler(_with_effective_message_text(update, payload), context)


async def _try_auto_reply_trigger(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    payload: str,
) -> bool:
    if update.effective_chat is None or update.effective_message is None:
        return False
    if update.effective_chat.id != chat_id:
        return False
    from backend.features.group_ops.group_hooks.moderation import _process_auto_reply

    db: Database = context.application.bot_data["db"]
    return await _process_auto_reply(context, db, update.effective_chat, update.effective_message, payload)


async def try_group_text_trigger(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    payload: str,
) -> bool:
    trigger_text = payload.strip()
    if not trigger_text:
        return False

    handled = await _try_points_text_trigger(update, context, trigger_text)
    if handled:
        return True

    if await _try_invite_trigger(update, context, chat_id, trigger_text):
        return True
    if await _try_game_trigger(update, context, trigger_text):
        return True
    if await _try_guess_trigger(update, context, trigger_text):
        return True
    if await _try_engagement_reward_trigger(update, context, chat_id, trigger_text):
        return True
    return await _try_teacher_search_trigger(update, context, chat_id, trigger_text)
