from __future__ import annotations

from collections.abc import Iterable

import structlog
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.platform.db.runtime.base import Base
from backend.platform.db.runtime.schema_gate import REQUIRED_INDEXES

log = structlog.get_logger(__name__)


CHAT_SETTINGS_COMPAT_SQL: tuple[str, ...] = (
    "ALTER TABLE bot.chat_settings ALTER COLUMN anti_flood_mute_duration SET DEFAULT 3600",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS anti_flood_exempt_admin BOOLEAN NOT NULL DEFAULT TRUE",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS anti_flood_cleanup_messages BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS anti_flood_delete_notify BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS anti_flood_delete_notify_seconds INTEGER NOT NULL DEFAULT 600",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS anti_spam_enabled BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS anti_spam_action VARCHAR(32) NOT NULL DEFAULT 'mute'",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS anti_spam_mute_duration INTEGER NOT NULL DEFAULT 3600",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS anti_spam_exempt_admin BOOLEAN NOT NULL DEFAULT TRUE",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS anti_spam_delete_notify BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS anti_spam_delete_notify_seconds INTEGER NOT NULL DEFAULT 600",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS anti_spam_repeat_messages INTEGER NOT NULL DEFAULT 3",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS anti_spam_repeat_seconds INTEGER NOT NULL DEFAULT 15",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS anti_spam_rules JSONB NOT NULL DEFAULT '{}'::jsonb",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS verification_cover_media_type VARCHAR(16)",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS verification_cover_file_id VARCHAR(256)",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS verification_agreement_text TEXT NOT NULL DEFAULT '请阅读并同意本群规则后再发言。'",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS verification_math_prompt_text TEXT NOT NULL DEFAULT '请回答下面的简单算术题完成验证。'",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS verification_wrong_action VARCHAR(16) NOT NULL DEFAULT 'none'",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS verification_direct_mute_duration INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS join_spam_guard_enabled BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS join_spam_detect_rules_count INTEGER NOT NULL DEFAULT 2",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS join_spam_send_invalid_msg_enabled BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS join_spam_mute_member_enabled BOOLEAN NOT NULL DEFAULT TRUE",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS join_spam_kick_member_enabled BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS join_spam_tip_delete_after_seconds INTEGER NOT NULL DEFAULT 60",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS join_self_review_enabled BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS join_self_review_timeout_seconds INTEGER NOT NULL DEFAULT 300",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS join_self_review_timeout_action VARCHAR(32) NOT NULL DEFAULT 'reject_allow_retry'",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS join_self_review_wrong_action VARCHAR(32) NOT NULL DEFAULT 'reject_block'",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS join_burst_enabled BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS join_burst_window_seconds INTEGER NOT NULL DEFAULT 30",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS join_burst_threshold_count INTEGER NOT NULL DEFAULT 10",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS join_burst_mute_enabled BOOLEAN NOT NULL DEFAULT TRUE",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS join_burst_kick_enabled BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS join_burst_tip_mode VARCHAR(16) NOT NULL DEFAULT 'tip_and_delete'",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS new_member_limit_enabled BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS new_member_limit_window_seconds INTEGER NOT NULL DEFAULT 3600",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS new_member_limit_block_media BOOLEAN NOT NULL DEFAULT TRUE",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS new_member_limit_block_links BOOLEAN NOT NULL DEFAULT TRUE",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS new_member_limit_text_only BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS new_member_limit_delete_message BOOLEAN NOT NULL DEFAULT TRUE",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS new_member_limit_warn_enabled BOOLEAN NOT NULL DEFAULT TRUE",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS new_member_limit_warn_text TEXT NOT NULL DEFAULT '新成员需等待 {duration} 才可发送媒体/链接。'",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS new_member_limit_warn_delete_after_seconds INTEGER NOT NULL DEFAULT 60",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS night_mode_enabled BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS night_mode_start_time VARCHAR(5)",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS night_mode_end_time VARCHAR(5)",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS night_mode_exempt_admin BOOLEAN NOT NULL DEFAULT TRUE",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS night_mode_whitelist_user_ids JSONB NOT NULL DEFAULT '[]'::jsonb",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS night_mode_delete_message BOOLEAN NOT NULL DEFAULT TRUE",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS night_mode_warn_enabled BOOLEAN NOT NULL DEFAULT TRUE",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS night_mode_warn_text TEXT NOT NULL DEFAULT '🌙 夜间模式生效中，请稍后再试。'",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS night_mode_warn_delete_after_seconds INTEGER NOT NULL DEFAULT 60",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS command_config_enabled BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS command_config JSONB NOT NULL DEFAULT '{}'::jsonb",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS points_display_rule_enabled BOOLEAN NOT NULL DEFAULT TRUE",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS points_speech_rank_enabled BOOLEAN NOT NULL DEFAULT TRUE",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS points_personal_speech_enabled BOOLEAN NOT NULL DEFAULT TRUE",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS control_permission_policy VARCHAR(32) NOT NULL DEFAULT 'can_promote_members'",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS group_lock_phrase_enabled BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS group_lock_open_phrase TEXT",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS group_lock_close_phrase TEXT",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS group_lock_schedule_enabled BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS group_lock_open_time VARCHAR(5)",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS group_lock_close_time VARCHAR(5)",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS group_lock_delete_notice_mode VARCHAR(16) NOT NULL DEFAULT 'keep'",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS name_change_monitor_enabled BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS name_change_monitor_template_text TEXT NOT NULL DEFAULT E'检测到用户{userId}修改{changeType}\\n原{changeType}: {oldContent}\\n新{changeType}: {newContent}\\n\\n请注意规避风险'",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS name_change_monitor_delete_after_seconds INTEGER NOT NULL DEFAULT 60",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS force_subscribe_enabled BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS force_subscribe_bound_channel_1 TEXT",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS force_subscribe_bound_channel_2 TEXT",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS force_subscribe_cover_media_type VARCHAR(16)",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS force_subscribe_cover_file_id VARCHAR(256)",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS force_subscribe_guide_text TEXT NOT NULL DEFAULT '{member}，您需要关注我们的频道才能发言。'",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS force_subscribe_custom_buttons_enabled BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS force_subscribe_check_mode VARCHAR(8) NOT NULL DEFAULT 'all'",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS force_subscribe_not_subscribed_action VARCHAR(32) NOT NULL DEFAULT 'delete_and_warn'",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS force_subscribe_delete_warn_after_seconds INTEGER NOT NULL DEFAULT 60",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS force_subscribe_buttons JSONB NOT NULL DEFAULT '[]'::jsonb",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS garage_auth_enabled BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS garage_auth_badge VARCHAR(16) NOT NULL DEFAULT '🤝'",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS garage_limit_enabled BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS garage_limit_mode VARCHAR(16) NOT NULL DEFAULT 'none'",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS garage_limit_interval_sec INTEGER NOT NULL DEFAULT 3600",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS garage_limit_max_count INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS garage_summary_partition_by VARCHAR(16) NOT NULL DEFAULT 'region'",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS garage_summary_only_open_course BOOLEAN NOT NULL DEFAULT FALSE",
)

GARAGE_FORWARD_SETTINGS_COMPAT_SQL: tuple[str, ...] = (
    "ALTER TABLE bot.garage_forward_settings ADD COLUMN IF NOT EXISTS button_template_enabled BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE bot.garage_forward_settings ADD COLUMN IF NOT EXISTS button_template JSONB NOT NULL DEFAULT '[]'::jsonb",
)

CAR_REVIEW_SETTINGS_COMPAT_SQL: tuple[str, ...] = (
    "ALTER TABLE bot.car_review_settings ADD COLUMN IF NOT EXISTS auto_refresh_board_enabled BOOLEAN NOT NULL DEFAULT FALSE",
)

TEACHER_SEARCH_SETTINGS_COMPAT_SQL: tuple[str, ...] = (
    "ALTER TABLE bot.teacher_search_settings ADD COLUMN IF NOT EXISTS only_open_course_enabled BOOLEAN NOT NULL DEFAULT TRUE",
    "ALTER TABLE bot.teacher_search_settings ADD COLUMN IF NOT EXISTS attendance_mode VARCHAR(16) NOT NULL DEFAULT 'message'",
    "ALTER TABLE bot.teacher_search_settings ADD COLUMN IF NOT EXISTS attendance_source_chat_id BIGINT",
    "ALTER TABLE bot.teacher_search_settings ADD COLUMN IF NOT EXISTS attendance_open_keyword VARCHAR(32) NOT NULL DEFAULT '开课'",
    "ALTER TABLE bot.teacher_search_settings ADD COLUMN IF NOT EXISTS attendance_full_keyword VARCHAR(32) NOT NULL DEFAULT '满课'",
    "ALTER TABLE bot.teacher_search_settings ADD COLUMN IF NOT EXISTS attendance_rest_keyword VARCHAR(32) NOT NULL DEFAULT '休息'",
    "ALTER TABLE bot.teacher_search_settings ADD COLUMN IF NOT EXISTS footer_button_url VARCHAR(512)",
    "ALTER TABLE bot.teacher_profiles ADD COLUMN IF NOT EXISTS open_course_status VARCHAR(16)",
    "ALTER TABLE bot.teacher_daily_attendance ADD COLUMN IF NOT EXISTS status VARCHAR(16) NOT NULL DEFAULT 'open'",
)

SCHEDULED_MESSAGE_COMPAT_SQL: tuple[str, ...] = (
    "ALTER TABLE bot.scheduled_message_tasks ADD COLUMN IF NOT EXISTS short_id VARCHAR(8)",
    """
    WITH sm_numbered AS (
        SELECT
            task_id,
            LPAD(UPPER(TO_HEX(ROW_NUMBER() OVER (ORDER BY created_at, task_id))), 8, '0') AS sid
        FROM bot.scheduled_message_tasks
        WHERE short_id IS NULL OR short_id = ''
    )
    UPDATE bot.scheduled_message_tasks AS t
    SET short_id = sm_numbered.sid
    FROM sm_numbered
    WHERE t.task_id = sm_numbered.task_id
    """.strip(),
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_smt_short_id ON bot.scheduled_message_tasks(short_id)",
    "ALTER TABLE bot.scheduled_message_tasks ALTER COLUMN short_id SET NOT NULL",
)

AD_CAMPAIGNS_COMPAT_SQL: tuple[str, ...] = (
    "ALTER TABLE bot.ad_campaigns ADD COLUMN IF NOT EXISTS buttons JSONB NOT NULL DEFAULT '[]'::jsonb",
    "ALTER TABLE bot.ad_campaigns ADD COLUMN IF NOT EXISTS sort_order INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE bot.ad_campaigns ADD COLUMN IF NOT EXISTS end_time TIMESTAMPTZ",
    "ALTER TABLE bot.ad_campaigns ADD COLUMN IF NOT EXISTS last_sent_message_id INTEGER",
    "ALTER TABLE bot.ad_campaigns ADD COLUMN IF NOT EXISTS last_sent_cycle_no INTEGER NOT NULL DEFAULT 0",
    """
    WITH ad_numbered AS (
        SELECT
            id,
            ROW_NUMBER() OVER (PARTITION BY chat_id ORDER BY created_at, id) AS row_no
        FROM bot.ad_campaigns
        WHERE sort_order IS NULL OR sort_order <= 0
    )
    UPDATE bot.ad_campaigns AS ad
    SET sort_order = ad_numbered.row_no
    FROM ad_numbered
    WHERE ad.id = ad_numbered.id
    """.strip(),
    "CREATE INDEX IF NOT EXISTS ix_ad_campaigns_sort_order ON bot.ad_campaigns(sort_order)",
)

COMPATIBILITY_MIGRATIONS: dict[str, tuple[str, ...]] = {
    "chat_settings": CHAT_SETTINGS_COMPAT_SQL,
    "garage_forward_settings": GARAGE_FORWARD_SETTINGS_COMPAT_SQL,
    "car_review_settings": CAR_REVIEW_SETTINGS_COMPAT_SQL,
    "teacher_search_settings": TEACHER_SEARCH_SETTINGS_COMPAT_SQL,
    "scheduled_message_tasks": SCHEDULED_MESSAGE_COMPAT_SQL,
    "ad_campaigns": AD_CAMPAIGNS_COMPAT_SQL,
}


def _load_model_metadata() -> None:
    # 导入模型以填充 Base.metadata
    import backend.platform.db.schema.models.alliance  # noqa: F401
    import backend.platform.db.schema.models.activity  # noqa: F401
    import backend.platform.db.schema.models.automation  # noqa: F401
    import backend.platform.db.schema.models.chat  # noqa: F401
    import backend.platform.db.schema.models.expansion  # noqa: F401
    import backend.platform.db.schema.models.garage_features  # noqa: F401
    import backend.platform.db.schema.models.moderation  # noqa: F401
    import backend.platform.db.schema.models.points  # noqa: F401
    import backend.platform.db.schema.models.scheduled_message  # noqa: F401
    import backend.platform.db.schema.models.subscription  # noqa: F401
    import backend.platform.db.schema.models.welcome  # noqa: F401


def _required_index_sql(table_name: str, index_name: str, columns: Iterable[str], unique: bool) -> str:
    unique_sql = "UNIQUE " if unique else ""
    column_sql = ", ".join(columns)
    return f"CREATE {unique_sql}INDEX IF NOT EXISTS {index_name} ON bot.{table_name}({column_sql})"


async def run_startup_schema_migrations(engine: AsyncEngine) -> None:
    """在 schema gate 前执行幂等补丁，兼容历史库结构。"""
    _load_model_metadata()

    async with engine.begin() as conn:
        await conn.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS bot")
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, checkfirst=True))

        def _existing_tables(sync_conn) -> set[str]:
            inspector = inspect(sync_conn)
            return {
                table.name
                for table in Base.metadata.sorted_tables
                if table.schema == "bot" and inspector.has_table(table.name, schema="bot")
            }

        existing_tables = await conn.run_sync(_existing_tables)
        executed = 0

        for table_name, statements in COMPATIBILITY_MIGRATIONS.items():
            if table_name not in existing_tables:
                continue
            for statement in statements:
                await conn.exec_driver_sql(statement)
                executed += 1

        for required in REQUIRED_INDEXES:
            if required.table_name not in existing_tables:
                continue
            await conn.exec_driver_sql(
                _required_index_sql(
                    table_name=required.table_name,
                    index_name=required.index_name,
                    columns=required.columns,
                    unique=required.unique,
                )
            )
            executed += 1

    log.info("startup_schema_migrations_finished", statements_executed=executed)
