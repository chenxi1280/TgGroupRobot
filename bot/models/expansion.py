from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from bot.db.base import Base


class AuctionSetting(Base):
    __tablename__ = "auction_settings"
    __table_args__ = {"schema": "bot"}

    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    pin_message_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_extend_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    create_permission: Mapped[str] = mapped_column(String(16), default="admin")
    points_mode: Mapped[str] = mapped_column(String(32), default="none")
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class AuctionItem(Base):
    __tablename__ = "auction_items"
    __table_args__ = {"schema": "bot"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    creator_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("bot.tg_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start_price: Mapped[int] = mapped_column(Integer, default=0)
    current_price: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    start_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    winner_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("bot.tg_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    winner_bid_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_announce_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class AuctionBid(Base):
    __tablename__ = "auction_bids"
    __table_args__ = {"schema": "bot"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    auction_id: Mapped[int] = mapped_column(Integer, ForeignKey("bot.auction_items.id", ondelete="CASCADE"), index=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    bid_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="CASCADE"), index=True)
    bid_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC), index=True)


class BottomButtonSetting(Base):
    __tablename__ = "bottom_button_settings"
    __table_args__ = {"schema": "bot"}

    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    header_text: Mapped[str] = mapped_column(Text, default="⌨️ 底部按钮已生成，点击下方按钮即可使用。")
    generated_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    repeat_generate_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    repeat_interval_seconds: Mapped[int] = mapped_column(Integer, default=3600)
    last_generated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class BottomButtonLayout(Base):
    __tablename__ = "bottom_button_layouts"
    __table_args__ = (
        UniqueConstraint("chat_id", "row_no", "col_no", name="uq_bottom_button_layout_chat_pos"),
        {"schema": "bot"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    row_no: Mapped[int] = mapped_column(Integer, nullable=False)
    col_no: Mapped[int] = mapped_column(Integer, nullable=False)
    button_text: Mapped[str] = mapped_column(String(32), default="按钮")
    payload_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    action_mode: Mapped[str] = mapped_column(String(16), default="send")
    sort_key: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class GameSetting(Base):
    __tablename__ = "game_settings"
    __table_args__ = {"schema": "bot"}

    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), primary_key=True)
    k3_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    blackjack_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    rake_ratio: Mapped[str | None] = mapped_column(String(16), nullable=True)
    rake_owner_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("bot.tg_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    auto_schedule_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_start_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    auto_stop_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    delete_game_message_mode: Mapped[str] = mapped_column(String(16), default="keep")
    k3_panel_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    blackjack_panel_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class GameRound(Base):
    __tablename__ = "game_rounds"
    __table_args__ = {"schema": "bot"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    game_type: Mapped[str] = mapped_column(String(16), index=True)
    creator_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("bot.tg_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    settle_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    announcement_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    result_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class GameParticipant(Base):
    __tablename__ = "game_participants"
    __table_args__ = (
        UniqueConstraint("round_id", "user_id", name="uq_game_participant_round_user"),
        {"schema": "bot"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    round_id: Mapped[int] = mapped_column(Integer, ForeignKey("bot.game_rounds.id", ondelete="CASCADE"), index=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="CASCADE"), index=True)
    bet_points: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    choice_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    payout_points: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class LotterySetting(Base):
    __tablename__ = "lottery_settings"
    __table_args__ = {"schema": "bot"}

    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), primary_key=True)
    publish_pin_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    result_pin_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    delete_join_message_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class GuessSetting(Base):
    __tablename__ = "guess_settings"
    __table_args__ = {"schema": "bot"}

    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), primary_key=True)
    rake_ratio: Mapped[str | None] = mapped_column(String(16), nullable=True)
    rake_owner_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("bot.tg_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    delete_message_mode: Mapped[str] = mapped_column(String(16), default="keep")
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class GuessEvent(Base):
    __tablename__ = "guess_events"
    __table_args__ = {"schema": "bot"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    creator_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("bot.tg_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(128), default="竞猜活动")
    cover_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    mode: Mapped[str] = mapped_column(String(16), default="no_banker")
    banker_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("bot.tg_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    public_pool: Mapped[int] = mapped_column(Integer, default=0)
    options_json: Mapped[list[dict]] = mapped_column(JSONB, default=list)
    command_keyword: Mapped[str] = mapped_column(String(32), default="竞猜")
    deadline_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    allow_repeat_bet: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="running", index=True)
    winner_option: Mapped[str | None] = mapped_column(String(64), nullable=True)
    announcement_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class GuessBet(Base):
    __tablename__ = "guess_bets"
    __table_args__ = {"schema": "bot"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(Integer, ForeignKey("bot.guess_events.id", ondelete="CASCADE"), index=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="CASCADE"), index=True)
    option_key: Mapped[str] = mapped_column(String(64), index=True)
    bet_points: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC), index=True)


class EngagementSetting(Base):
    __tablename__ = "engagement_settings"
    __table_args__ = {"schema": "bot"}

    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), primary_key=True)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class EngagementEgg(Base):
    __tablename__ = "engagement_egg"
    __table_args__ = {"schema": "bot"}

    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    answer: Mapped[str | None] = mapped_column(String(128), nullable=True)
    clues: Mapped[list[str]] = mapped_column(JSONB, default=list)
    clue_rewards: Mapped[list[int]] = mapped_column(JSONB, default=list)
    clue_times: Mapped[list[str]] = mapped_column(JSONB, default=list)
    winner_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("bot.tg_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(16), default="idle")
    published_clue_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class EngagementEggEvent(Base):
    __tablename__ = "engagement_egg_events"
    __table_args__ = {"schema": "bot"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(128), default="彩蛋活动")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    answer: Mapped[str | None] = mapped_column(String(128), nullable=True)
    clues: Mapped[list[str]] = mapped_column(JSONB, default=list)
    clue_rewards: Mapped[list[int]] = mapped_column(JSONB, default=list)
    clue_times: Mapped[list[str]] = mapped_column(JSONB, default=list)
    winner_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("bot.tg_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(16), default="idle", index=True)
    published_clue_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC), index=True)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class EngagementEggHistory(Base):
    __tablename__ = "engagement_egg_history"
    __table_args__ = {"schema": "bot"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    event_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    title: Mapped[str | None] = mapped_column(String(128), nullable=True)
    answer: Mapped[str | None] = mapped_column(String(128), nullable=True)
    winner_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("bot.tg_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reward_points: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="finished")
    published_clue_count: Mapped[int] = mapped_column(Integer, default=0)
    snapshot_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC), index=True)


class EngagementChatReward(Base):
    __tablename__ = "engagement_chat_reward"
    __table_args__ = {"schema": "bot"}

    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    reward_type: Mapped[str] = mapped_column(String(32), default="daily_increment")
    daily_message_target: Mapped[int] = mapped_column(Integer, default=200)
    reward_points_plan: Mapped[list[int]] = mapped_column(JSONB, default=list)
    after_7d_mode: Mapped[str] = mapped_column(String(16), default="continue")
    command_keyword: Mapped[str] = mapped_column(String(32), default="我爱水群")
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class EngagementChatStat(Base):
    __tablename__ = "engagement_chat_stats"
    __table_args__ = (
        UniqueConstraint("chat_id", "user_id", "biz_date", name="uq_engagement_chat_stats_daily"),
        {"schema": "bot"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="CASCADE"), index=True)
    biz_date: Mapped[dt.date] = mapped_column(Date, index=True, default=lambda: dt.datetime.now(dt.UTC).date())
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    streak_days: Mapped[int] = mapped_column(Integer, default=0)
    reward_claimed: Mapped[bool] = mapped_column(Boolean, default=False)
    rewarded_points: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class AccountInheritSetting(Base):
    __tablename__ = "account_inherit_settings"
    __table_args__ = {"schema": "bot"}

    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    token_expire_minutes: Mapped[int] = mapped_column(Integer, default=60)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class AccountInheritToken(Base):
    __tablename__ = "account_inherit_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_account_inherit_token_hash"),
        {"schema": "bot"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    old_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), index=True)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    used: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    used_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("bot.tg_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))


class AccountInheritAudit(Base):
    __tablename__ = "account_inherit_audit"
    __table_args__ = {"schema": "bot"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot.tg_chats.id", ondelete="CASCADE"), index=True)
    old_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("bot.tg_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    new_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("bot.tg_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    asset_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict)
    result: Mapped[str] = mapped_column(String(16), default="success", index=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC), index=True)
