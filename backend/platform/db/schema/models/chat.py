from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.platform.db.runtime.base import Base
from backend.platform.db.schema.models.enums import (
    ChatType,
    ControlPermissionPolicy,
    ForceSubscribeAction,
    ForceSubscribeCheckMode,
    GroupLockDeleteNoticeMode,
    MemberRole,
    ModerationAction,
    VerificationMode,
)


class TgUser(Base):
    __tablename__ = "tg_users"
    __table_args__ = {"schema": "bot"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    language_code: Mapped[str | None] = mapped_column(String(16), nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class TgChat(Base):
    __tablename__ = "tg_chats"
    __table_args__ = {"schema": "bot"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    type: Mapped[str] = mapped_column(String(32), default=ChatType.supergroup.value)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )

    settings: Mapped["ChatSettings"] = relationship(back_populates="chat", uselist=False)


class ChatSettings(Base):
    __tablename__ = "chat_settings"
    __table_args__ = {"schema": "bot"}

    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), primary_key=True)

    language: Mapped[str] = mapped_column(String(16), default="zh-CN")
    sign_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sign_points: Mapped[int] = mapped_column(Integer, default=5)
    sign_cooldown_hours: Mapped[int] = mapped_column(Integer, default=20)
    sign_consecutive_days: Mapped[int] = mapped_column(Integer, default=0)
    sign_consecutive_bonus: Mapped[int] = mapped_column(Integer, default=0)

    message_points_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    message_points: Mapped[int] = mapped_column(Integer, default=1)
    message_points_daily_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message_min_length: Mapped[int | None] = mapped_column(Integer, nullable=True)

    invite_points_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    invite_points: Mapped[int] = mapped_column(Integer, default=1)
    invite_points_daily_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)

    invite_link_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    invite_link_notify: Mapped[bool] = mapped_column(Boolean, default=True)
    invite_link_expire_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    invite_link_max_joins: Mapped[int | None] = mapped_column(Integer, nullable=True)
    invite_link_user_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    invite_link_mode: Mapped[str] = mapped_column(String(16), default="direct")
    invite_link_cover_media_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    invite_link_cover_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    invite_link_text_template: Mapped[str] = mapped_column(
        Text,
        default="🔗 邀请好友加入 {group}\n邀请人：{inviter}\n新成员：{invitee}",
    )
    invite_link_buttons: Mapped[list[dict]] = mapped_column(JSONB, default=list)

    auto_delete_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_delete_join: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_delete_left: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_delete_pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_delete_avatar: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_delete_title: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_delete_anonymous: Mapped[bool] = mapped_column(Boolean, default=False)

    points_display_rule_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    points_speech_rank_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    points_personal_speech_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    points_alias: Mapped[str] = mapped_column(String(32), default="积分")
    points_rank_alias: Mapped[str] = mapped_column(String(32), default="积分排行")

    verification_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    verification_mode: Mapped[str] = mapped_column(String(16), default=VerificationMode.button.value)
    verification_timeout_seconds: Mapped[int] = mapped_column(Integer, default=180)
    verification_restrict_can_send: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_timeout_action: Mapped[str] = mapped_column(String(16), default="mute")
    verification_mute_duration: Mapped[int] = mapped_column(Integer, default=86400)
    join_spam_guard_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    join_spam_detect_rules_count: Mapped[int] = mapped_column(Integer, default=2)
    join_spam_send_invalid_msg_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    join_spam_mute_member_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    join_spam_kick_member_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    join_spam_tip_delete_after_seconds: Mapped[int] = mapped_column(Integer, default=60)
    join_self_review_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    join_self_review_timeout_seconds: Mapped[int] = mapped_column(Integer, default=300)
    join_self_review_timeout_action: Mapped[str] = mapped_column(String(32), default="reject_allow_retry")
    join_self_review_wrong_action: Mapped[str] = mapped_column(String(32), default="reject_block")
    join_burst_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    join_burst_window_seconds: Mapped[int] = mapped_column(Integer, default=30)
    join_burst_threshold_count: Mapped[int] = mapped_column(Integer, default=10)
    join_burst_mute_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    join_burst_kick_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    join_burst_tip_mode: Mapped[str] = mapped_column(String(16), default="tip_and_delete")

    new_member_limit_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    new_member_limit_window_seconds: Mapped[int] = mapped_column(Integer, default=3600)
    new_member_limit_block_media: Mapped[bool] = mapped_column(Boolean, default=True)
    new_member_limit_block_links: Mapped[bool] = mapped_column(Boolean, default=True)
    new_member_limit_text_only: Mapped[bool] = mapped_column(Boolean, default=False)
    new_member_limit_delete_message: Mapped[bool] = mapped_column(Boolean, default=True)
    new_member_limit_warn_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    new_member_limit_warn_text: Mapped[str] = mapped_column(Text, default="新成员需等待 {duration} 才可发送媒体/链接。")
    new_member_limit_warn_delete_after_seconds: Mapped[int] = mapped_column(Integer, default=60)

    night_mode_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    night_mode_start_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    night_mode_end_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    night_mode_exempt_admin: Mapped[bool] = mapped_column(Boolean, default=True)
    night_mode_whitelist_user_ids: Mapped[list[int]] = mapped_column(JSONB, default=list)
    night_mode_delete_message: Mapped[bool] = mapped_column(Boolean, default=True)
    night_mode_warn_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    night_mode_warn_text: Mapped[str] = mapped_column(Text, default="🌙 夜间模式生效中，请稍后再试。")
    night_mode_warn_delete_after_seconds: Mapped[int] = mapped_column(Integer, default=60)

    command_config_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    command_config: Mapped[dict] = mapped_column(JSONB, default=dict)

    moderation_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    moderation_block_links: Mapped[bool] = mapped_column(Boolean, default=True)
    moderation_action: Mapped[str] = mapped_column(String(32), default=ModerationAction.delete.value)
    moderation_keywords: Mapped[list[str]] = mapped_column(JSONB, default=list)

    ads_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    monetization_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    control_permission_policy: Mapped[str] = mapped_column(
        String(32),
        default=ControlPermissionPolicy.can_promote_members.value,
    )

    group_lock_phrase_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    group_lock_open_phrase: Mapped[str | None] = mapped_column(Text, nullable=True)
    group_lock_close_phrase: Mapped[str | None] = mapped_column(Text, nullable=True)
    group_lock_schedule_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    group_lock_open_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    group_lock_close_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    group_lock_delete_notice_mode: Mapped[str] = mapped_column(
        String(16),
        default=GroupLockDeleteNoticeMode.keep.value,
    )

    name_change_monitor_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    name_change_monitor_template_text: Mapped[str] = mapped_column(
        Text,
        default="检测到用户{userId}修改{changeType}\n原{changeType}: {oldContent}\n新{changeType}: {newContent}\n\n请注意规避风险",
    )
    name_change_monitor_delete_after_seconds: Mapped[int] = mapped_column(Integer, default=60)

    force_subscribe_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    force_subscribe_bound_channel_1: Mapped[str | None] = mapped_column(Text, nullable=True)
    force_subscribe_bound_channel_2: Mapped[str | None] = mapped_column(Text, nullable=True)
    force_subscribe_cover_media_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    force_subscribe_cover_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    force_subscribe_guide_text: Mapped[str] = mapped_column(
        Text,
        default="{member}，您需要关注我们的频道才能发言。",
    )
    force_subscribe_custom_buttons_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    force_subscribe_check_mode: Mapped[str] = mapped_column(String(8), default=ForceSubscribeCheckMode.all.value)
    force_subscribe_not_subscribed_action: Mapped[str] = mapped_column(
        String(32),
        default=ForceSubscribeAction.delete_and_warn.value,
    )
    force_subscribe_delete_warn_after_seconds: Mapped[int] = mapped_column(Integer, default=60)
    force_subscribe_buttons: Mapped[list[dict]] = mapped_column(JSONB, default=list)

    welcome_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    welcome_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    garage_auth_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    garage_auth_badge: Mapped[str] = mapped_column(String(16), default="🤝")
    garage_limit_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    garage_limit_mode: Mapped[str] = mapped_column(String(16), default="none")
    garage_limit_interval_sec: Mapped[int] = mapped_column(Integer, default=3600)
    garage_limit_max_count: Mapped[int] = mapped_column(Integer, default=1)
    garage_summary_partition_by: Mapped[str] = mapped_column(String(16), default="region")
    garage_summary_only_open_course: Mapped[bool] = mapped_column(Boolean, default=False)

    anti_flood_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    anti_flood_messages: Mapped[int] = mapped_column(Integer, default=5)
    anti_flood_seconds: Mapped[int] = mapped_column(Integer, default=5)
    anti_flood_action: Mapped[str] = mapped_column(String(32), default="mute")
    anti_flood_mute_duration: Mapped[int] = mapped_column(Integer, default=3600)
    anti_flood_exempt_admin: Mapped[bool] = mapped_column(Boolean, default=True)
    anti_flood_cleanup_messages: Mapped[bool] = mapped_column(Boolean, default=False)
    anti_flood_delete_notify: Mapped[bool] = mapped_column(Boolean, default=False)
    anti_flood_delete_notify_seconds: Mapped[int] = mapped_column(Integer, default=600)

    anti_spam_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    anti_spam_action: Mapped[str] = mapped_column(String(32), default="mute")
    anti_spam_mute_duration: Mapped[int] = mapped_column(Integer, default=3600)
    anti_spam_exempt_admin: Mapped[bool] = mapped_column(Boolean, default=True)
    anti_spam_delete_notify: Mapped[bool] = mapped_column(Boolean, default=False)
    anti_spam_delete_notify_seconds: Mapped[int] = mapped_column(Integer, default=600)
    anti_spam_repeat_messages: Mapped[int] = mapped_column(Integer, default=3)
    anti_spam_repeat_seconds: Mapped[int] = mapped_column(Integer, default=15)
    anti_spam_rules: Mapped[dict] = mapped_column(JSONB, default=dict)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )

    chat: Mapped[TgChat] = relationship(back_populates="settings")


class ChatMember(Base):
    __tablename__ = "chat_members"
    __table_args__ = (
        UniqueConstraint("chat_id", "user_id", name="uq_chat_member"),
        {"schema": "bot"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16), default=MemberRole.member.value)
    joined_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class NearbyProfile(Base):
    __tablename__ = "nearby_profiles"
    __table_args__ = (
        UniqueConstraint("chat_id", "user_id", name="uq_nearby_profile_chat_user"),
        {"schema": "bot"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="CASCADE"), index=True)
    latitude: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    longitude: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    price_text: Mapped[str | None] = mapped_column(String(128), nullable=True)
    method_text: Mapped[str | None] = mapped_column(String(128), nullable=True)
    address_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_visible: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    fuzzy_distance: Mapped[bool] = mapped_column(Boolean, default=True)
    last_location_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class ConversationState(Base):
    __tablename__ = "conversation_states"
    __table_args__ = (
        UniqueConstraint("chat_id", "user_id", name="uq_conversation_state"),
        {"schema": "bot"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="CASCADE"), index=True)
    state_type: Mapped[str] = mapped_column(String(32), index=True)
    state_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )
