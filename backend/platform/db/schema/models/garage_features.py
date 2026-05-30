from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.platform.db.runtime.base import Base


class GarageCertifiedTeacher(Base):
    __tablename__ = "garage_certified_teachers"
    __table_args__ = (
        UniqueConstraint("chat_id", "user_id", name="uq_garage_certified_teacher_chat_user"),
        {"schema": "bot"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="CASCADE"), index=True)
    certified_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("bot.tg_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class GarageSpeechWhitelist(Base):
    __tablename__ = "garage_speech_whitelist"
    __table_args__ = (
        UniqueConstraint("chat_id", "user_id", name="uq_garage_speech_whitelist_chat_user"),
        {"schema": "bot"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="CASCADE"), index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("bot.tg_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))


class TeacherSearchSetting(Base):
    __tablename__ = "teacher_search_settings"
    __table_args__ = {"schema": "bot"}

    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), primary_key=True)
    tag_search_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    only_open_course_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    nearby_search_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    attendance_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    attendance_mode: Mapped[str] = mapped_column(String(16), default="message", nullable=False)
    attendance_source_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    attendance_open_keyword: Mapped[str] = mapped_column(String(32), default="开课", nullable=False)
    attendance_full_keyword: Mapped[str] = mapped_column(String(32), default="满课", nullable=False)
    attendance_rest_keyword: Mapped[str] = mapped_column(String(32), default="休息", nullable=False)
    force_location_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    delete_mode: Mapped[str] = mapped_column(String(16), default="none")
    footer_button_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    footer_button_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class TeacherProfile(Base):
    __tablename__ = "teacher_profiles"
    __table_args__ = (
        UniqueConstraint("chat_id", "user_id", name="uq_teacher_profile_chat_user"),
        {"schema": "bot"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="CASCADE"), index=True)
    latitude: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    longitude: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    labels: Mapped[list[str]] = mapped_column(JSONB, default=list)
    region_text: Mapped[str | None] = mapped_column(String(128), nullable=True)
    price_text: Mapped[str | None] = mapped_column(String(128), nullable=True)
    open_course_today: Mapped[bool] = mapped_column(Boolean, default=False)
    open_course_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_location_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class TeacherSourcePost(Base):
    __tablename__ = "teacher_source_posts"
    __table_args__ = (
        UniqueConstraint("chat_id", "source_channel_id", "source_message_id", name="uq_teacher_source_post_message"),
        {"schema": "bot"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    source_channel_id: Mapped[int] = mapped_column(BigInteger, index=True)
    source_message_id: Mapped[int] = mapped_column(BigInteger)
    source_channel_username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_channel_title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    username: Mapped[str] = mapped_column(String(64), index=True)
    teacher_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("bot.tg_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    bind_status: Mapped[str] = mapped_column(String(24), default="pending_bind", nullable=False, index=True)
    labels: Mapped[list[str]] = mapped_column(JSONB, default=list)
    region_text: Mapped[str | None] = mapped_column(String(128), nullable=True)
    price_text: Mapped[str | None] = mapped_column(String(128), nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class TeacherDailyAttendance(Base):
    __tablename__ = "teacher_daily_attendance"
    __table_args__ = (
        UniqueConstraint("chat_id", "user_id", "biz_date", name="uq_teacher_attendance_chat_user_date"),
        {"schema": "bot"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="CASCADE"), index=True)
    biz_date: Mapped[dt.date] = mapped_column(Date, index=True, default=lambda: dt.datetime.now(dt.UTC).date())
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False)
    source_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))


class MemberLocation(Base):
    __tablename__ = "member_locations"
    __table_args__ = (
        UniqueConstraint("chat_id", "user_id", name="uq_member_location_chat_user"),
        {"schema": "bot"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="CASCADE"), index=True)
    latitude: Mapped[float] = mapped_column(Numeric(9, 6), nullable=False)
    longitude: Mapped[float] = mapped_column(Numeric(9, 6), nullable=False)
    updated_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("bot.tg_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class CarReviewSetting(Base):
    __tablename__ = "car_review_settings"
    __table_args__ = {"schema": "bot"}

    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    review_mode: Mapped[str] = mapped_column(String(16), default="default")
    teacher_lookup_mode: Mapped[str] = mapped_column(String(16), default="off")
    auto_refresh_board_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    submit_command: Mapped[str] = mapped_column(String(32), default="提交报告")
    rank_command: Mapped[str] = mapped_column(String(32), default="出击排行")
    publish_to_main_group: Mapped[bool] = mapped_column(Boolean, default=True)
    publish_to_comment_group: Mapped[bool] = mapped_column(Boolean, default=False)
    publish_to_bound_channel: Mapped[bool] = mapped_column(Boolean, default=False)
    approver_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("bot.tg_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reward_points: Mapped[int] = mapped_column(Integer, default=100)
    template_text: Mapped[str] = mapped_column(
        Text,
        default=(
            "【时间】：{time}\n"
            "【老师】：{teacher}\n"
            "【留名】：{author}\n"
            "【评价】：{review}\n"
            "【人照】：{photo_score}\n"
            "【颜值】：{face_score}\n"
            "【身材】：{body_score}\n"
            "【服务】：{service_score}\n"
            "【态度】：{attitude_score}\n"
            "【环境】：{env_score}\n"
            "【综合】：{total_score}\n"
            "【过程】：{process}"
        ),
    )
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class CarReviewCustomField(Base):
    __tablename__ = "car_review_custom_fields"
    __table_args__ = (
        UniqueConstraint("chat_id", "field_key", name="uq_car_review_field_chat_key"),
        {"schema": "bot"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    field_key: Mapped[str] = mapped_column(String(64), index=True)
    field_label: Mapped[str] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class CarReviewReport(Base):
    __tablename__ = "car_review_reports"
    __table_args__ = {"schema": "bot"}

    report_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    teacher_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="SET NULL"), index=True, nullable=True)
    author_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="SET NULL"), index=True, nullable=True)
    review_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    scores: Mapped[dict] = mapped_column(JSONB, default=dict)
    process_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_file_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    report_status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    approved_by_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="SET NULL"), nullable=True)
    approved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class CarReviewAuditLog(Base):
    __tablename__ = "car_review_audit_logs"
    __table_args__ = {"schema": "bot"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("bot.car_review_reports.report_id", ondelete="SET NULL"), index=True, nullable=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(32), index=True)
    operator_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="SET NULL"), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
