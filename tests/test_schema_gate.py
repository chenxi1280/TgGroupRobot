from __future__ import annotations

from dataclasses import dataclass

import pytest

import backend.platform.db.schema.models.alliance  # noqa: F401
import backend.platform.db.schema.models.core  # noqa: F401
import backend.platform.db.schema.models.garage_features  # noqa: F401
import backend.platform.db.schema.models.scheduled_message  # noqa: F401
import backend.platform.db.schema.models.welcome  # noqa: F401
from backend.platform.db.runtime.schema_gate import SchemaValidationError, validate_database_schema


@dataclass
class FakeInspector:
    schemas: list[str]
    tables: dict[str, dict]

    def get_schema_names(self) -> list[str]:
        return self.schemas

    def has_table(self, table_name: str, schema: str | None = None) -> bool:
        return table_name in self.tables

    def get_columns(self, table_name: str, schema: str | None = None) -> list[dict]:
        return [{"name": name} for name in self.tables[table_name]["columns"]]

    def get_indexes(self, table_name: str, schema: str | None = None) -> list[dict]:
        return self.tables[table_name].get("indexes", [])

    def get_unique_constraints(self, table_name: str, schema: str | None = None) -> list[dict]:
        return self.tables[table_name].get("uniques", [])


class FakeBeginContext:
    def __init__(self, inspector: FakeInspector) -> None:
        self.inspector = inspector

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def run_sync(self, fn):
        return fn(object())


class FakeEngine:
    def __init__(self, inspector: FakeInspector) -> None:
        self.inspector = inspector

    def begin(self) -> FakeBeginContext:
        return FakeBeginContext(self.inspector)


def _full_tables() -> dict[str, dict]:
    return {
        "tg_users": {"columns": {"id", "username", "first_name", "last_name", "language_code", "created_at", "updated_at"}},
        "tg_chats": {"columns": {"id", "type", "title", "created_at", "updated_at"}},
        "chat_settings": {
            "columns": {
                "chat_id", "language", "sign_enabled", "sign_points", "sign_cooldown_hours",
                "sign_consecutive_days", "sign_consecutive_bonus", "message_points_enabled",
                "message_points", "message_points_daily_limit", "message_min_length",
                "invite_points_enabled", "invite_points", "invite_points_daily_limit",
                "invite_link_enabled", "invite_link_notify", "invite_link_expire_days",
                "invite_link_max_joins", "invite_link_user_limit", "invite_link_mode",
                "invite_link_cover_media_type", "invite_link_cover_file_id",
                "invite_link_text_template", "invite_link_buttons", "auto_delete_enabled",
                "auto_delete_join", "auto_delete_left", "auto_delete_pinned", "auto_delete_avatar",
                "auto_delete_title", "auto_delete_anonymous",
                "points_display_rule_enabled", "points_speech_rank_enabled",
                "points_personal_speech_enabled", "points_alias", "points_rank_alias",
                "verification_enabled", "verification_mode", "verification_timeout_seconds",
                "verification_restrict_can_send", "verification_timeout_action", "verification_mute_duration",
                "verification_cover_media_type", "verification_cover_file_id", "verification_agreement_text",
                "verification_math_prompt_text", "verification_wrong_action", "verification_direct_mute_duration",
                "join_spam_guard_enabled", "join_spam_detect_rules_count", "join_spam_send_invalid_msg_enabled",
                "join_spam_mute_member_enabled", "join_spam_kick_member_enabled", "join_spam_tip_delete_after_seconds",
                "join_self_review_enabled", "join_self_review_timeout_seconds", "join_self_review_timeout_action",
                "join_self_review_wrong_action", "join_burst_enabled", "join_burst_window_seconds",
                "join_burst_threshold_count", "join_burst_mute_enabled", "join_burst_kick_enabled",
                "join_burst_tip_mode",
                "new_member_limit_enabled", "new_member_limit_window_seconds", "new_member_limit_block_media",
                "new_member_limit_block_links", "new_member_limit_text_only", "new_member_limit_delete_message",
                "new_member_limit_warn_enabled", "new_member_limit_warn_text", "new_member_limit_warn_delete_after_seconds",
                "night_mode_enabled", "night_mode_start_time", "night_mode_end_time", "night_mode_exempt_admin",
                "night_mode_whitelist_user_ids", "night_mode_delete_message", "night_mode_warn_enabled",
                "night_mode_warn_text", "night_mode_warn_delete_after_seconds",
                "command_config_enabled", "command_config",
                "moderation_enabled", "moderation_block_links", "moderation_action", "moderation_keywords",
                "ads_enabled", "monetization_enabled", "welcome_enabled", "welcome_message",
                "anti_flood_enabled", "anti_flood_messages", "anti_flood_seconds", "anti_flood_action",
                "anti_flood_mute_duration", "anti_flood_exempt_admin", "anti_flood_cleanup_messages",
                "anti_flood_delete_notify", "anti_flood_delete_notify_seconds", "anti_spam_enabled",
                "anti_spam_action", "anti_spam_mute_duration", "anti_spam_exempt_admin",
                "anti_spam_delete_notify", "anti_spam_delete_notify_seconds", "anti_spam_repeat_messages",
                "anti_spam_repeat_seconds", "anti_spam_rules",
                "control_permission_policy",
                "group_lock_phrase_enabled", "group_lock_open_phrase", "group_lock_close_phrase",
                "group_lock_schedule_enabled", "group_lock_open_time", "group_lock_close_time",
                "group_lock_delete_notice_mode",
                "name_change_monitor_enabled", "name_change_monitor_template_text",
                "name_change_monitor_delete_after_seconds",
                "force_subscribe_enabled", "force_subscribe_bound_channel_1", "force_subscribe_bound_channel_2",
                "force_subscribe_cover_media_type", "force_subscribe_cover_file_id",
                "force_subscribe_guide_text", "force_subscribe_custom_buttons_enabled",
                "force_subscribe_check_mode", "force_subscribe_not_subscribed_action",
                "force_subscribe_delete_warn_after_seconds", "force_subscribe_buttons",
                "garage_auth_enabled", "garage_auth_badge", "garage_limit_enabled",
                "garage_limit_mode", "garage_limit_interval_sec", "garage_limit_max_count",
                "garage_summary_partition_by", "garage_summary_only_open_course",
                "created_at", "updated_at",
            },
        },
        "chat_members": {"columns": {"id", "chat_id", "user_id", "role", "joined_at", "updated_at"}},
        "group_daily_stats": {
            "columns": {
                "id", "chat_id", "stat_date", "join_count", "leave_count",
                "created_at", "updated_at",
            },
        },
        "nearby_profiles": {"columns": {"id", "chat_id", "user_id", "latitude", "longitude", "price_text", "method_text", "address_text", "is_visible", "fuzzy_distance", "last_location_at", "created_at", "updated_at"}},
        "points_accounts": {"columns": {"id", "chat_id", "user_id", "balance", "updated_at"}},
        "points_transactions": {"columns": {"id", "chat_id", "user_id", "txn_type", "amount", "reason", "created_at"}},
        "sign_in_logs": {"columns": {"id", "chat_id", "user_id", "sign_date", "points_awarded", "created_at"}},
        "user_daily_stats": {"columns": {"id", "chat_id", "user_id", "stat_date", "message_points_earned", "invite_points_earned", "invites_count", "consecutive_sign_days", "created_at", "updated_at"}},
        "custom_point_types": {
            "columns": {
                "id", "chat_id", "type_no", "name", "rank_command", "enabled", "created_by_user_id", "created_at", "updated_at",
            },
            "uniques": [
                {"name": "uq_custom_point_type_chat_no", "column_names": ["chat_id", "type_no"]},
                {"name": "uq_custom_point_type_chat_name", "column_names": ["chat_id", "name"]},
            ],
        },
        "custom_point_accounts": {
            "columns": {"id", "chat_id", "type_id", "user_id", "balance", "updated_at"},
            "uniques": [
                {"name": "uq_custom_point_account_chat_type_user", "column_names": ["chat_id", "type_id", "user_id"]},
            ],
        },
        "custom_point_ledger": {
            "columns": {"id", "chat_id", "type_id", "user_id", "delta", "reason_note", "operator_user_id", "created_at"},
            "indexes": [{"name": "ix_custom_point_ledger_created_at", "column_names": ["created_at"], "unique": False}],
        },
        "points_level_settings": {
            "columns": {"chat_id", "enabled", "exclude_teacher_enabled", "updated_at"},
        },
        "points_levels": {
            "columns": {
                "id", "chat_id", "level_no", "level_name", "point_threshold", "allow_text", "allow_audio",
                "allow_photo", "allow_video", "allow_sticker", "allow_document", "allow_mention", "enabled",
                "created_at", "updated_at",
            },
            "uniques": [
                {"name": "uq_points_level_chat_no", "column_names": ["chat_id", "level_no"]},
                {"name": "uq_points_level_chat_threshold", "column_names": ["chat_id", "point_threshold"]},
            ],
        },
        "points_mall_settings": {
            "columns": {
                "chat_id", "enabled", "entry_command", "auto_unlist_when_out_of_stock",
                "redeem_notice_delete_seconds", "cover_media_type", "cover_file_id", "updated_at",
            },
        },
        "points_mall_products": {
            "columns": {
                "product_id", "chat_id", "name", "price_points", "stock_total", "stock_left", "status",
                "cover_media_type", "cover_file_id", "limit_per_user", "fulfiller_user_id", "description",
                "sort_weight", "created_at", "updated_at",
            },
            "indexes": [{"name": "ix_points_mall_products_created_at", "column_names": ["created_at"], "unique": False}],
        },
        "points_mall_orders": {
            "columns": {
                "order_id", "chat_id", "product_id", "buyer_user_id", "price_points", "quantity",
                "order_status", "operator_user_id", "created_at", "updated_at",
            },
            "indexes": [{"name": "ix_points_mall_orders_created_at", "column_names": ["created_at"], "unique": False}],
        },
        "points_mall_order_logs": {
            "columns": {"id", "order_id", "action", "payload", "created_at"},
            "indexes": [{"name": "ix_points_mall_order_logs_created_at", "column_names": ["created_at"], "unique": False}],
        },
        "moderation_violations": {"columns": {"id", "chat_id", "user_id", "message_id", "rule", "detail", "action", "created_at"}},
        "moderation_warnings": {
            "columns": {
                "id", "chat_id", "user_id", "warning_count", "last_rule",
                "expires_at", "created_at", "updated_at",
            },
            "uniques": [{"name": "uq_moderation_warnings_chat_user", "column_names": ["chat_id", "user_id"]}],
        },
        "verification_challenges": {
            "columns": {
                "id", "chat_id", "user_id", "token", "expires_at", "solved",
                "verification_type", "question", "answer", "timeout_handled",
                "timeout_status", "timeout_action", "timeout_attempts",
                "timeout_next_retry_at", "timeout_lease_until",
                "timeout_send_started_at", "timeout_last_error",
                "timeout_completed_at", "created_at",
                "timeout_replay_of_attempt_id",
            },
            "indexes": [
                {
                    "name": "ix_verification_timeout_due",
                    "column_names": [
                        "timeout_status",
                        "timeout_next_retry_at",
                        "timeout_lease_until",
                    ],
                    "unique": False,
                },
            ],
        },
        "verification_timeout_attempts": {
            "columns": {
                "id", "challenge_id", "attempt_no", "status", "action",
                "lease_until", "send_started_at", "error_code", "error_message",
                "completed_at", "replay_of_id", "created_at",
            },
            "indexes": [
                {
                    "name": "ix_verification_timeout_attempt_status_created",
                    "column_names": ["status", "created_at"],
                    "unique": False,
                },
            ],
            "uniques": [
                {
                    "name": "uq_verification_timeout_attempt_no",
                    "column_names": ["challenge_id", "attempt_no"],
                },
            ],
        },
        "admin_accounts": {
            "columns": {
                "id", "username", "password_hash", "display_name", "status",
                "last_login_at", "created_at", "updated_at",
            },
        },
        "admin_sessions": {
            "columns": {
                "id", "token_hash", "admin_account_id", "expires_at",
                "revoked_at", "created_at", "last_seen_at",
            },
            "indexes": [{"name": "ix_admin_sessions_token_hash", "column_names": ["token_hash"], "unique": True}],
        },
        "admin_audit_logs": {
            "columns": {
                "id", "admin_account_id", "action", "target_type", "target_id",
                "detail", "created_at",
            },
            "indexes": [{"name": "ix_admin_audit_logs_created_at", "column_names": ["created_at"], "unique": False}],
        },
        "app_settings": {"columns": {"key", "value", "updated_at"}},
        "subscription_plans": {"columns": {"id", "code", "name", "price_cents", "duration_days", "feature_flags", "created_at"}},
        "chat_subscriptions": {"columns": {"id", "chat_id", "plan_id", "status", "start_at", "end_at", "created_at"}},
        "renewal_card_key_batches": {
            "columns": {
                "id", "batch_no", "spec_days", "quantity", "created_by_admin_id",
                "copy_count", "export_count", "created_at",
            },
            "uniques": [{"name": "uq_renewal_card_key_batch_no", "column_names": ["batch_no"]}],
        },
        "renewal_card_keys": {
            "columns": {
                "id", "card_key_hash", "batch_id", "card_code_plain", "spec_days",
                "created_by_admin_id", "duration_seconds", "expires_at", "used",
                "used_by_chat_id", "used_by_user_id", "used_at", "created_at",
                "copy_status", "export_status", "copied_at", "exported_at",
            },
            "uniques": [{"name": "uq_renewal_card_key_hash", "column_names": ["card_key_hash"]}],
        },
        "renewal_audit_logs": {
            "columns": {"id", "chat_id", "operator_user_id", "action", "reason", "payload", "created_at"},
            "indexes": [{"name": "ix_renewal_audit_logs_created_at", "column_names": ["created_at"], "unique": False}],
        },
        "ad_campaigns": {
            "columns": {
                "id", "chat_id", "created_by_user_id", "title", "content", "image_file_id", "image_url",
                "has_image", "schedule_time", "frequency", "last_sent_at", "send_locked", "enabled",
                "start_time", "interval_hours", "max_send_count", "send_count",
                "buttons", "sort_order", "end_time", "last_sent_message_id", "last_sent_cycle_no",
                "created_at", "updated_at",
            },
        },
        "ad_rotation_rules": {
            "columns": {
                "chat_id", "enabled", "start_at", "interval_seconds", "mode", "delete_policy",
                "delete_delay_seconds", "unpin_previous", "last_sent_at", "next_run_at",
                "current_order_cursor", "last_sent_item_id", "last_sent_message_id",
                "last_pinned_message_id", "created_at", "updated_at",
            },
        },
        "conversation_states": {"columns": {"id", "chat_id", "user_id", "state_type", "state_data", "created_at", "updated_at"}},
        "lotteries": {
            "columns": {
                "id", "chat_id", "created_by_user_id", "title", "description", "lottery_type",
                "draw_time", "prizes", "draw_mode", "status", "message_id", "qualification_rules",
                "min_points", "max_participants", "participation_cost", "join_start_time",
                "join_end_time", "requirement_days", "created_at", "drawn_at",
            },
        },
        "lottery_participants": {"columns": {"id", "lottery_id", "user_id", "points_balance", "created_at"}},
        "lottery_winners": {"columns": {"id", "lottery_id", "user_id", "prize_name", "prize_index", "points_reward", "created_at"}},
        "scheduled_messages": {"columns": {"id", "chat_id", "created_by_user_id", "content", "schedule_type", "interval_minutes", "is_active", "next_send_time", "last_sent_at", "send_count", "repeat_enabled", "created_at", "updated_at"}},
        "auto_reply_rules": {
            "columns": {
                "id", "chat_id", "created_by_user_id", "keywords", "reply_content",
                "cover_media_type", "cover_media_file_id", "buttons", "match_type",
                "sort_order", "delete_source", "delete_reply_delay_seconds",
                "is_active", "match_count", "case_sensitive", "stop_after_match", "created_at", "updated_at",
            },
        },
        "banned_words": {"columns": {"id", "chat_id", "created_by_user_id", "word", "match_type", "action", "mute_duration", "notify", "notify_message", "is_active", "trigger_count", "case_sensitive", "created_at", "updated_at"}},
        "invite_links": {"columns": {"id", "chat_id", "created_by_user_id", "invite_link", "name", "status", "member_limit", "member_count", "expire_date", "creates_join_request", "created_at", "updated_at"}},
        "invite_tracking": {"columns": {"id", "chat_id", "inviter_user_id", "invited_user_id", "invite_link_id", "points_awarded", "joined_at", "created_at"}},
        "solitaires": {"columns": {"id", "chat_id", "created_by_user_id", "title", "description", "status", "max_participants", "points_required", "deadline", "message_id", "created_at", "updated_at"}},
        "solitaire_entries": {"columns": {"id", "solitaire_id", "user_id", "username", "content", "joined_at", "updated_at", "created_at"}},
        "scheduled_message_tasks": {
            "columns": {
                "task_id", "short_id", "chat_id", "created_by_user_id", "title", "enabled",
                "repeat_interval_min", "day_start_hour", "day_end_hour", "start_at", "end_at",
                "text", "parse_mode", "media_type", "media_file_id", "buttons", "delete_previous",
                "pin_message", "last_sent_message_id", "next_run_at", "created_at", "updated_at",
            },
            "indexes": [{"name": "uq_smt_short_id", "column_names": ["short_id"], "unique": True}],
        },
        "scheduled_message_logs": {
            "columns": {
                "id", "task_id", "chat_id", "run_key", "scheduled_for", "content_snapshot",
                "status", "attempt_count", "next_retry_at", "lease_until", "send_started_at",
                "completed_at", "error_code", "message_id", "sent_at", "success", "error_message",
            },
            "indexes": [
                {"name": "uq_sml_run_key", "column_names": ["run_key"], "unique": True},
                {"name": "ix_sml_due", "column_names": ["status", "next_retry_at", "lease_until"], "unique": False},
            ],
        },
        "welcome_messages": {
            "columns": {
                "id", "chat_id", "title", "enabled", "welcome_mode", "cover_media_type",
                "cover_media_file_id", "text_content", "buttons", "delete_mode",
                "delete_delay_seconds", "last_sent_message_id", "created_at", "updated_at",
            },
        },
        "group_alliances": {
            "columns": {
                "alliance_id", "name", "owner_chat_id", "invite_code_hash",
                "invite_code_expire_at", "created_at", "updated_at",
            },
        },
        "group_alliance_members": {
            "columns": {"id", "alliance_id", "chat_id", "joined_at", "status"},
            "uniques": [{"name": "uq_group_alliance_member_chat", "column_names": ["chat_id"]}],
        },
        "group_alliance_settings": {
            "columns": {"chat_id", "alliance_id", "joint_ban_enabled", "updated_at"},
        },
        "group_alliance_ban_pool": {
            "columns": {
                "id", "alliance_id", "target_user_id", "source_chat_id",
                "source_operator_user_id", "reason", "created_at",
            },
            "uniques": [{"name": "uq_group_alliance_ban_pool", "column_names": ["alliance_id", "target_user_id"]}],
        },
        "group_alliance_audit": {
            "columns": {
                "id", "chat_id", "alliance_id", "action", "operator_user_id",
                "payload", "result", "created_at",
            },
        },
        "garage_forward_settings": {
            "columns": {
                "chat_id",
                "enabled",
                "sync_mode",
                "keyword_rules",
                "button_template_enabled",
                "button_template",
                "updated_at",
            },
        },
        "garage_forward_sources": {
            "columns": {"id", "chat_id", "source_channel_id", "source_name", "enabled", "last_seen_message_id", "created_at"},
            "uniques": [{"name": "uq_garage_forward_source_chat_channel", "column_names": ["chat_id", "source_channel_id"]}],
        },
        "garage_forward_message_map": {
            "columns": {
                "id", "chat_id", "source_channel_id", "source_message_id",
                "target_message_id", "forwarded_at",
            },
            "uniques": [{"name": "uq_garage_forward_message_map", "column_names": ["chat_id", "source_channel_id", "source_message_id"]}],
        },
        "garage_forward_audit_logs": {
            "columns": {
                "id", "chat_id", "source_channel_id", "source_message_id",
                "action", "result", "reason", "created_at",
            },
        },
        "garage_forward_retry_queue": {
            "columns": {
                "id", "chat_id", "source_channel_id", "source_message_id",
                "message_map_id", "reply_markup_snapshot", "status", "retry_count",
                "max_retries", "next_retry_at", "lease_until", "send_started_at",
                "last_error", "completed_at", "created_at", "updated_at",
            },
            "indexes": [{
                "name": "ix_garage_forward_retry_due",
                "column_names": ["status", "next_retry_at", "lease_until"],
                "unique": False,
            }],
            "uniques": [{
                "name": "uq_garage_forward_retry_event",
                "column_names": ["chat_id", "source_channel_id", "source_message_id"],
            }],
        },
        "garage_certified_teachers": {
            "columns": {
                "id", "chat_id", "user_id", "certified_by_user_id",
                "enabled", "created_at", "updated_at",
            },
            "uniques": [{"name": "uq_garage_certified_teacher_chat_user", "column_names": ["chat_id", "user_id"]}],
        },
        "garage_speech_whitelist": {
            "columns": {"id", "chat_id", "user_id", "created_by_user_id", "created_at"},
            "uniques": [{"name": "uq_garage_speech_whitelist_chat_user", "column_names": ["chat_id", "user_id"]}],
        },
        "teacher_search_settings": {
            "columns": {
                "chat_id", "tag_search_enabled", "nearby_search_enabled", "attendance_enabled",
                "only_open_course_enabled", "attendance_mode", "attendance_source_chat_id",
                "attendance_open_keyword", "attendance_full_keyword", "attendance_rest_keyword",
                "force_location_enabled", "delete_mode", "footer_button_label", "footer_button_url",
                "created_at", "updated_at",
            },
        },
        "teacher_profiles": {
            "columns": {
                "id", "chat_id", "user_id", "labels", "region_text", "price_text",
                "latitude", "longitude", "open_course_today", "open_course_status", "last_location_at",
                "created_at", "updated_at",
            },
            "uniques": [{"name": "uq_teacher_profile_chat_user", "column_names": ["chat_id", "user_id"]}],
        },
        "teacher_source_posts": {
            "columns": {
                "id", "chat_id", "source_channel_id", "source_message_id",
                "source_channel_username", "source_channel_title", "source_url",
                "username", "teacher_user_id", "bind_status", "labels",
                "region_text", "price_text", "raw_text", "failure_reason",
                "created_at", "updated_at",
            },
            "uniques": [{"name": "uq_teacher_source_post_message", "column_names": ["chat_id", "source_channel_id", "source_message_id"]}],
        },
        "teacher_daily_attendance": {
            "columns": {"id", "chat_id", "user_id", "biz_date", "status", "source_message_id", "created_at"},
            "uniques": [{"name": "uq_teacher_attendance_chat_user_date", "column_names": ["chat_id", "user_id", "biz_date"]}],
        },
        "member_locations": {
            "columns": {"id", "chat_id", "user_id", "latitude", "longitude", "updated_by_user_id", "created_at", "updated_at"},
            "uniques": [{"name": "uq_member_location_chat_user", "column_names": ["chat_id", "user_id"]}],
        },
        "car_review_settings": {
            "columns": {
                "chat_id", "enabled", "review_mode", "teacher_lookup_mode", "auto_refresh_board_enabled",
                "submit_command", "rank_command", "publish_to_main_group",
                "publish_to_comment_group", "publish_to_bound_channel", "approver_user_id",
                "reward_points", "template_text", "created_at", "updated_at",
            },
        },
        "car_review_custom_fields": {
            "columns": {"id", "chat_id", "field_key", "field_label", "enabled", "sort_order", "created_at", "updated_at"},
            "uniques": [{"name": "uq_car_review_field_chat_key", "column_names": ["chat_id", "field_key"]}],
        },
        "car_review_reports": {
            "columns": {
                "report_id", "chat_id", "teacher_user_id", "author_user_id", "review_text",
                "scores", "process_text", "media_file_ids", "report_status",
                "approved_by_user_id", "approved_at", "published_message_id",
                "created_at", "updated_at",
            },
        },
        "car_review_audit_logs": {
            "columns": {"id", "report_id", "chat_id", "action", "operator_user_id", "payload", "created_at"},
        },
        "auction_settings": {
            "columns": {
                "chat_id", "enabled", "pin_message_enabled", "auto_extend_enabled",
                "create_permission", "points_mode", "updated_at",
            },
        },
        "lottery_settings": {
            "columns": {
                "chat_id", "publish_pin_enabled", "result_pin_enabled", "delete_join_message_enabled", "updated_at",
            },
        },
        "auction_items": {
            "columns": {
                "id", "chat_id", "creator_user_id", "source_message_id", "title",
                "start_price", "current_price", "status", "start_at", "end_at",
                "winner_user_id", "winner_bid_id", "last_announce_message_id",
                "created_at", "updated_at",
            },
        },
        "auction_bids": {
            "columns": {"id", "auction_id", "chat_id", "bid_user_id", "bid_amount", "created_at"},
        },
        "bottom_button_settings": {
            "columns": {
                "chat_id", "enabled", "header_text", "generated_message_id",
                "repeat_generate_enabled", "repeat_interval_seconds",
                "last_generated_at", "updated_at",
            },
        },
        "bottom_button_layouts": {
            "columns": {
                "id", "chat_id", "row_no", "col_no", "button_text", "payload_text",
                "action_mode", "sort_key", "created_at", "updated_at",
            },
            "uniques": [{"name": "uq_bottom_button_layout_chat_pos", "column_names": ["chat_id", "row_no", "col_no"]}],
        },
        "game_settings": {
            "columns": {
                "chat_id", "k3_enabled", "blackjack_enabled", "rake_ratio", "rake_owner_user_id",
                "points_source_chat_id", "auto_schedule_enabled", "auto_start_time", "auto_stop_time",
                "delete_game_message_mode", "k3_panel_message_id", "blackjack_panel_message_id", "updated_at",
            },
        },
        "game_rounds": {
            "columns": {
                "id", "chat_id", "game_type", "creator_user_id", "status", "settle_at",
                "announcement_message_id", "result_data", "created_at", "updated_at",
            },
        },
        "game_participants": {
            "columns": {
                "id", "round_id", "chat_id", "user_id", "bet_points", "status",
                "choice_data", "payout_points", "created_at", "updated_at",
            },
            "uniques": [{"name": "uq_game_participant_round_user", "column_names": ["round_id", "user_id"]}],
        },
        "guess_settings": {
            "columns": {"chat_id", "rake_ratio", "rake_owner_user_id", "delete_message_mode", "updated_at"},
        },
        "guess_events": {
            "columns": {
                "id", "chat_id", "creator_user_id", "title", "cover_file_id", "description",
                "mode", "banker_user_id", "public_pool", "options_json", "command_keyword",
                "deadline_at", "allow_repeat_bet", "status", "winner_option",
                "announcement_message_id", "created_at", "updated_at",
            },
        },
        "guess_bets": {
            "columns": {"id", "event_id", "chat_id", "user_id", "option_key", "bet_points", "created_at"},
        },
        "engagement_settings": {
            "columns": {"chat_id", "updated_at"},
        },
        "engagement_egg": {
            "columns": {
                "chat_id", "enabled", "answer", "clues", "clue_rewards", "clue_times",
                "winner_user_id", "status", "published_clue_count", "updated_at",
            },
        },
        "engagement_egg_events": {
            "columns": {
                "id", "chat_id", "title", "enabled", "answer", "clues", "clue_rewards",
                "clue_times", "winner_user_id", "status", "published_clue_count",
                "created_at", "updated_at",
            },
        },
        "engagement_egg_history": {
            "columns": {
                "id", "chat_id", "event_id", "title", "answer", "winner_user_id", "reward_points", "status",
                "published_clue_count", "snapshot_data", "created_at",
            },
        },
        "engagement_chat_reward": {
            "columns": {
                "chat_id", "enabled", "reward_type", "daily_message_target",
                "reward_points_plan", "after_7d_mode", "command_keyword", "updated_at",
            },
        },
        "engagement_chat_stats": {
            "columns": {
                "id", "chat_id", "user_id", "biz_date", "message_count",
                "streak_days", "reward_claimed", "rewarded_points", "updated_at",
            },
            "uniques": [{"name": "uq_engagement_chat_stats_daily", "column_names": ["chat_id", "user_id", "biz_date"]}],
        },
        "account_inherit_settings": {
            "columns": {"chat_id", "enabled", "token_expire_minutes", "updated_at"},
        },
        "account_inherit_tokens": {
            "columns": {
                "id", "chat_id", "old_user_id", "token_hash", "expires_at",
                "used", "used_by_user_id", "used_at", "created_at",
            },
            "uniques": [{"name": "uq_account_inherit_token_hash", "column_names": ["token_hash"]}],
        },
        "account_inherit_audit": {
            "columns": {
                "id", "chat_id", "old_user_id", "new_user_id",
                "asset_snapshot", "result", "reason", "created_at",
            },
        },
    }


@pytest.mark.asyncio
async def test_schema_gate_passes_when_required_shape_exists(monkeypatch) -> None:
    inspector = FakeInspector(schemas=["bot"], tables=_full_tables())
    monkeypatch.setattr("backend.platform.db.runtime.schema_gate.inspect", lambda _: inspector)
    engine = FakeEngine(inspector)

    await validate_database_schema(engine)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_schema_gate_fails_when_required_column_missing(monkeypatch) -> None:
    tables = _full_tables()
    tables["scheduled_message_tasks"]["columns"].remove("short_id")
    inspector = FakeInspector(schemas=["bot"], tables=tables)
    monkeypatch.setattr("backend.platform.db.runtime.schema_gate.inspect", lambda _: inspector)
    engine = FakeEngine(inspector)

    with pytest.raises(SchemaValidationError, match="short_id"):
        await validate_database_schema(engine)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_schema_gate_fails_when_required_index_missing(monkeypatch) -> None:
    tables = _full_tables()
    tables["scheduled_message_tasks"]["indexes"] = []
    inspector = FakeInspector(schemas=["bot"], tables=tables)
    monkeypatch.setattr("backend.platform.db.runtime.schema_gate.inspect", lambda _: inspector)
    engine = FakeEngine(inspector)

    with pytest.raises(SchemaValidationError, match="uq_smt_short_id"):
        await validate_database_schema(engine)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_schema_gate_fails_when_custom_points_unique_missing(monkeypatch) -> None:
    tables = _full_tables()
    tables["points_levels"]["uniques"] = [
        {"name": "uq_points_level_chat_no", "column_names": ["chat_id", "level_no"]},
    ]
    inspector = FakeInspector(schemas=["bot"], tables=tables)
    monkeypatch.setattr("backend.platform.db.runtime.schema_gate.inspect", lambda _: inspector)
    engine = FakeEngine(inspector)

    with pytest.raises(SchemaValidationError, match="uq_points_level_chat_threshold"):
        await validate_database_schema(engine)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_schema_gate_fails_when_garage_forward_source_unique_missing(monkeypatch) -> None:
    tables = _full_tables()
    tables["garage_forward_sources"]["uniques"] = []
    inspector = FakeInspector(schemas=["bot"], tables=tables)
    monkeypatch.setattr("backend.platform.db.runtime.schema_gate.inspect", lambda _: inspector)
    engine = FakeEngine(inspector)

    with pytest.raises(SchemaValidationError, match="uq_garage_forward_source_chat_channel"):
        await validate_database_schema(engine)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_schema_gate_fails_when_garage_retry_event_unique_missing(monkeypatch) -> None:
    tables = _full_tables()
    tables["garage_forward_retry_queue"]["uniques"] = []
    inspector = FakeInspector(schemas=["bot"], tables=tables)
    monkeypatch.setattr("backend.platform.db.runtime.schema_gate.inspect", lambda _: inspector)

    with pytest.raises(SchemaValidationError, match="uq_garage_forward_retry_event"):
        await validate_database_schema(FakeEngine(inspector))  # type: ignore[arg-type]
