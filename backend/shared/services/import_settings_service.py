from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.core import AutoReplyRule, BannedWord, ChatSettings, TgChat
from backend.platform.db.schema.models.welcome import WelcomeMessage
from backend.shared.services.base import ValidationError


MODULE_DEFINITIONS: list[dict[str, Any]] = [
    {"key": "base", "label": "基础开关", "detail": "语言、广告、自动删除等"},
    {"key": "points", "label": "积分配置", "detail": "签到/发言/邀请规则"},
    {"key": "points_level", "label": "积分等级与标签", "detail": "覆盖等级、媒体权限与标签配置，不复制余额或已有标签所有权"},
    {"key": "verification", "label": "入群验证", "detail": "验证/刷号/自助审核"},
    {"key": "force_subscribe", "label": "强制关注", "detail": "发言前关注校验与提示"},
    {"key": "new_member_limit", "label": "新成员限制", "detail": "入群窗口限制"},
    {"key": "night_mode", "label": "夜间管控", "detail": "时段限制、提示、全员禁言和口令"},
    {"key": "anti_spam", "label": "反垃圾配置", "detail": "规则/动作/白名单"},
    {"key": "anti_flood", "label": "防刷屏配置", "detail": "阈值/动作"},
    {"key": "moderation", "label": "内容审核", "detail": "关键词与动作"},
    {"key": "welcome", "label": "欢迎消息", "detail": "欢迎模板与列表"},
    {"key": "auto_reply", "label": "自动回复", "detail": "规则与回复内容"},
    {"key": "banned_words", "label": "违禁词", "detail": "词库与处罚"},
    {"key": "rename_monitor", "label": "改名监控", "detail": "模板与删除策略"},
    {"key": "command_config", "label": "命令配置", "detail": "启停与别名"},
]


CHAT_SETTINGS_FIELDS: dict[str, list[str]] = {
    "base": [
        "language",
        "ads_enabled",
        "monetization_enabled",
        "auto_delete_enabled",
        "auto_delete_join",
        "auto_delete_left",
        "auto_delete_pinned",
        "auto_delete_avatar",
        "auto_delete_title",
        "auto_delete_anonymous",
        "control_permission_policy",
    ],
    "points": [
        "sign_enabled",
        "sign_points",
        "sign_cooldown_hours",
        "sign_consecutive_days",
        "sign_consecutive_bonus",
        "message_points_enabled",
        "message_points",
        "message_points_daily_limit",
        "message_min_length",
        "invite_points_enabled",
        "invite_points",
        "invite_points_daily_limit",
        "points_display_rule_enabled",
        "points_speech_rank_enabled",
        "points_personal_speech_enabled",
        "points_alias",
        "points_rank_alias",
    ],
    "verification": [
        "verification_enabled",
        "verification_mode",
        "verification_timeout_seconds",
        "verification_restrict_can_send",
        "verification_timeout_action",
        "verification_mute_duration",
        "verification_cover_media_type",
        "verification_cover_file_id",
        "verification_agreement_text",
        "verification_math_prompt_text",
        "verification_wrong_action",
        "verification_direct_mute_duration",
        "join_spam_guard_enabled",
        "join_spam_detect_rules_count",
        "join_spam_send_invalid_msg_enabled",
        "join_spam_mute_member_enabled",
        "join_spam_kick_member_enabled",
        "join_spam_tip_delete_after_seconds",
        "join_self_review_enabled",
        "join_self_review_timeout_seconds",
        "join_self_review_timeout_action",
        "join_self_review_wrong_action",
        "join_burst_enabled",
        "join_burst_window_seconds",
        "join_burst_threshold_count",
        "join_burst_mute_enabled",
        "join_burst_kick_enabled",
        "join_burst_tip_mode",
    ],
    "force_subscribe": [
        "force_subscribe_enabled",
        "force_subscribe_bound_channel_1",
        "force_subscribe_bound_channel_2",
        "force_subscribe_cover_media_type",
        "force_subscribe_cover_file_id",
        "force_subscribe_guide_text",
        "force_subscribe_custom_buttons_enabled",
        "force_subscribe_check_mode",
        "force_subscribe_not_subscribed_action",
        "force_subscribe_delete_warn_after_seconds",
        "force_subscribe_buttons",
    ],
    "new_member_limit": [
        "new_member_limit_enabled",
        "new_member_limit_window_seconds",
        "new_member_limit_block_media",
        "new_member_limit_block_links",
        "new_member_limit_text_only",
        "new_member_limit_delete_message",
        "new_member_limit_warn_enabled",
        "new_member_limit_warn_text",
        "new_member_limit_warn_delete_after_seconds",
    ],
    "night_mode": [
        "night_mode_enabled",
        "night_mode_start_time",
        "night_mode_end_time",
        "night_mode_exempt_admin",
        "night_mode_whitelist_user_ids",
        "night_mode_delete_message",
        "night_mode_warn_enabled",
        "night_mode_warn_text",
        "night_mode_warn_delete_after_seconds",
        "group_lock_phrase_enabled",
        "group_lock_open_phrase",
        "group_lock_close_phrase",
        "group_lock_schedule_enabled",
        "group_lock_open_time",
        "group_lock_close_time",
        "group_lock_delete_notice_mode",
    ],
    "anti_spam": [
        "anti_spam_enabled",
        "anti_spam_action",
        "anti_spam_mute_duration",
        "anti_spam_exempt_admin",
        "anti_spam_delete_notify",
        "anti_spam_delete_notify_seconds",
        "anti_spam_repeat_messages",
        "anti_spam_repeat_seconds",
        "anti_spam_rules",
    ],
    "anti_flood": [
        "anti_flood_enabled",
        "anti_flood_messages",
        "anti_flood_seconds",
        "anti_flood_action",
        "anti_flood_mute_duration",
        "anti_flood_exempt_admin",
        "anti_flood_cleanup_messages",
        "anti_flood_delete_notify",
        "anti_flood_delete_notify_seconds",
    ],
    "moderation": [
        "moderation_enabled",
        "moderation_block_links",
        "moderation_action",
        "moderation_keywords",
    ],
    "welcome": [
        "welcome_enabled",
        "welcome_message",
    ],
    "group_lock": [
        "group_lock_phrase_enabled",
        "group_lock_open_phrase",
        "group_lock_close_phrase",
        "group_lock_schedule_enabled",
        "group_lock_open_time",
        "group_lock_close_time",
        "group_lock_delete_notice_mode",
    ],
    "rename_monitor": [
        "name_change_monitor_enabled",
        "name_change_monitor_template_text",
        "name_change_monitor_delete_after_seconds",
    ],
    "command_config": [
        "command_config_enabled",
        "command_config",
    ],
}


def list_import_modules() -> list[dict[str, Any]]:
    return MODULE_DEFINITIONS


def _filter_fields_for_modules(modules: list[str]) -> list[str]:
    fields: list[str] = []
    for key in modules:
        fields.extend(CHAT_SETTINGS_FIELDS.get(key, []))
    return list(dict.fromkeys(fields))


async def apply_import(
    session: AsyncSession,
    *,
    source_chat_id: int,
    target_chat_id: int,
    modules: list[str],
    context=None,
    actor_user_id: int | None = None,
) -> None:
    _validate_import(source_chat_id, target_chat_id, modules=modules)
    await session.execute(select(TgChat.id).where(TgChat.id.in_([source_chat_id,target_chat_id]))
        .order_by(TgChat.id).with_for_update())
    rows = (await session.scalars(select(ChatSettings).where(ChatSettings.chat_id.in_([source_chat_id,target_chat_id]))
        .order_by(ChatSettings.chat_id).with_for_update().execution_options(populate_existing=True))).all()
    settings = {item.chat_id:item for item in rows}
    source, target = settings.get(source_chat_id), settings.get(target_chat_id)
    if source is None or target is None:
        raise ValidationError("来源或目标配置已不存在，未执行覆盖。")

    fields = _filter_fields_for_modules(modules)
    for field in fields:
        setattr(target, field, getattr(source, field))

    from backend.shared.services.config_imports import copy_module_configuration
    await copy_module_configuration(session,source=source,target=target,modules=modules,
        context=context,actor_user_id=actor_user_id)

    if "welcome" in modules:
        await _copy_welcome_messages(session, source_chat_id, target_chat_id)
    if "auto_reply" in modules:
        await _copy_auto_reply_rules(session, source_chat_id, target_chat_id)
    if "banned_words" in modules:
        await _copy_banned_words(session, source_chat_id, target_chat_id)


def _validate_import(source_chat_id, target_chat_id, *, modules):
    allowed = CHAT_SETTINGS_FIELDS.keys() | {"auto_reply", "banned_words", "points_level"}
    if source_chat_id == target_chat_id or not modules or not set(modules) <= allowed:
        raise ValidationError("来源、目标或所选模块无效。")


async def _copy_welcome_messages(
    session: AsyncSession,
    source_chat_id: int,
    target_chat_id: int,
) -> None:
    await session.execute(
        delete(WelcomeMessage).where(WelcomeMessage.chat_id == target_chat_id)
    )
    result = await session.execute(
        select(WelcomeMessage).where(WelcomeMessage.chat_id == source_chat_id)
    )
    for item in result.scalars().all():
        session.add(
            WelcomeMessage(
                chat_id=target_chat_id,
                title=item.title,
                enabled=item.enabled,
                welcome_mode=item.welcome_mode,
                cover_media_type=item.cover_media_type,
                cover_media_file_id=item.cover_media_file_id,
                text_content=item.text_content,
                buttons=list(item.buttons or []),
                delete_mode=item.delete_mode,
                delete_delay_seconds=item.delete_delay_seconds,
                last_sent_message_id=None,
            )
        )


async def _copy_auto_reply_rules(
    session: AsyncSession,
    source_chat_id: int,
    target_chat_id: int,
) -> None:
    await session.execute(
        delete(AutoReplyRule).where(AutoReplyRule.chat_id == target_chat_id)
    )
    result = await session.execute(
        select(AutoReplyRule).where(AutoReplyRule.chat_id == source_chat_id)
    )
    for rule in result.scalars().all():
        session.add(
            AutoReplyRule(
                chat_id=target_chat_id,
                created_by_user_id=None,
                keywords=list(rule.keywords or []),
                reply_content=rule.reply_content,
                cover_media_type=rule.cover_media_type,
                cover_media_file_id=rule.cover_media_file_id,
                buttons=list(rule.buttons or []),
                match_type=rule.match_type,
                sort_order=rule.sort_order,
                delete_source=rule.delete_source,
                delete_reply_delay_seconds=rule.delete_reply_delay_seconds,
                is_active=rule.is_active,
                match_count=0,
                case_sensitive=rule.case_sensitive,
                stop_after_match=rule.stop_after_match,
            )
        )


async def _copy_banned_words(
    session: AsyncSession,
    source_chat_id: int,
    target_chat_id: int,
) -> None:
    await session.execute(
        delete(BannedWord).where(BannedWord.chat_id == target_chat_id)
    )
    result = await session.execute(
        select(BannedWord).where(BannedWord.chat_id == source_chat_id)
    )
    for word in result.scalars().all():
        session.add(
            BannedWord(
                chat_id=target_chat_id,
                created_by_user_id=None,
                word=word.word,
                match_type=word.match_type,
                action=word.action,
                mute_duration=word.mute_duration,
                notify=word.notify,
                notify_message=word.notify_message,
                is_active=word.is_active,
                trigger_count=0,
                case_sensitive=word.case_sensitive,
            )
        )
