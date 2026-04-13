from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.platform.db.runtime.base import Base


@dataclass(frozen=True)
class RequiredIndex:
    table_name: str
    index_name: str
    columns: tuple[str, ...]
    unique: bool = False


class SchemaValidationError(RuntimeError):
    """数据库结构不满足当前版本运行要求。"""


REQUIRED_INDEXES: tuple[RequiredIndex, ...] = (
    RequiredIndex(
        table_name="scheduled_message_tasks",
        index_name="uq_smt_short_id",
        columns=("short_id",),
        unique=True,
    ),
    RequiredIndex(
        table_name="custom_point_types",
        index_name="uq_custom_point_type_chat_no",
        columns=("chat_id", "type_no"),
        unique=True,
    ),
    RequiredIndex(
        table_name="custom_point_types",
        index_name="uq_custom_point_type_chat_name",
        columns=("chat_id", "name"),
        unique=True,
    ),
    RequiredIndex(
        table_name="custom_point_accounts",
        index_name="uq_custom_point_account_chat_type_user",
        columns=("chat_id", "type_id", "user_id"),
        unique=True,
    ),
    RequiredIndex(
        table_name="custom_point_ledger",
        index_name="ix_custom_point_ledger_created_at",
        columns=("created_at",),
    ),
    RequiredIndex(
        table_name="points_levels",
        index_name="uq_points_level_chat_no",
        columns=("chat_id", "level_no"),
        unique=True,
    ),
    RequiredIndex(
        table_name="points_levels",
        index_name="uq_points_level_chat_threshold",
        columns=("chat_id", "point_threshold"),
        unique=True,
    ),
    RequiredIndex(
        table_name="points_mall_products",
        index_name="ix_points_mall_products_created_at",
        columns=("created_at",),
    ),
    RequiredIndex(
        table_name="points_mall_orders",
        index_name="ix_points_mall_orders_created_at",
        columns=("created_at",),
    ),
    RequiredIndex(
        table_name="points_mall_order_logs",
        index_name="ix_points_mall_order_logs_created_at",
        columns=("created_at",),
    ),
    RequiredIndex(
        table_name="group_alliance_members",
        index_name="uq_group_alliance_member_chat",
        columns=("chat_id",),
        unique=True,
    ),
    RequiredIndex(
        table_name="group_alliance_ban_pool",
        index_name="uq_group_alliance_ban_pool",
        columns=("alliance_id", "target_user_id"),
        unique=True,
    ),
    RequiredIndex(
        table_name="garage_forward_message_map",
        index_name="uq_garage_forward_message_map",
        columns=("chat_id", "source_channel_id", "source_message_id"),
        unique=True,
    ),
    RequiredIndex(
        table_name="garage_forward_sources",
        index_name="uq_garage_forward_source_chat_channel",
        columns=("chat_id", "source_channel_id"),
        unique=True,
    ),
    RequiredIndex(
        table_name="garage_certified_teachers",
        index_name="uq_garage_certified_teacher_chat_user",
        columns=("chat_id", "user_id"),
        unique=True,
    ),
    RequiredIndex(
        table_name="garage_speech_whitelist",
        index_name="uq_garage_speech_whitelist_chat_user",
        columns=("chat_id", "user_id"),
        unique=True,
    ),
    RequiredIndex(
        table_name="teacher_profiles",
        index_name="uq_teacher_profile_chat_user",
        columns=("chat_id", "user_id"),
        unique=True,
    ),
    RequiredIndex(
        table_name="teacher_daily_attendance",
        index_name="uq_teacher_attendance_chat_user_date",
        columns=("chat_id", "user_id", "biz_date"),
        unique=True,
    ),
    RequiredIndex(
        table_name="member_locations",
        index_name="uq_member_location_chat_user",
        columns=("chat_id", "user_id"),
        unique=True,
    ),
    RequiredIndex(
        table_name="car_review_custom_fields",
        index_name="uq_car_review_field_chat_key",
        columns=("chat_id", "field_key"),
        unique=True,
    ),
    RequiredIndex(
        table_name="renewal_card_keys",
        index_name="uq_renewal_card_key_hash",
        columns=("card_key_hash",),
        unique=True,
    ),
    RequiredIndex(
        table_name="renewal_audit_logs",
        index_name="ix_renewal_audit_logs_created_at",
        columns=("created_at",),
    ),
    RequiredIndex(
        table_name="bottom_button_layouts",
        index_name="uq_bottom_button_layout_chat_pos",
        columns=("chat_id", "row_no", "col_no"),
        unique=True,
    ),
    RequiredIndex(
        table_name="engagement_chat_stats",
        index_name="uq_engagement_chat_stats_daily",
        columns=("chat_id", "user_id", "biz_date"),
        unique=True,
    ),
    RequiredIndex(
        table_name="account_inherit_tokens",
        index_name="uq_account_inherit_token_hash",
        columns=("token_hash",),
        unique=True,
    ),
)


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


def _format_missing_items(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def _normalize_columns(columns: list[dict]) -> set[str]:
    return {col["name"] for col in columns}


def _collect_index_keys(indexes: list[dict], uniques: list[dict]) -> set[tuple[str, tuple[str, ...], bool]]:
    keys: set[tuple[str, tuple[str, ...], bool]] = set()
    for idx in indexes:
        keys.add(
            (
                idx["name"],
                tuple(idx.get("column_names") or ()),
                bool(idx.get("unique", False)),
            )
        )
    for constraint in uniques:
        keys.add(
            (
                constraint["name"],
                tuple(constraint.get("column_names") or ()),
                True,
            )
        )
    return keys


def _is_optional_column(column) -> bool:
    return bool(getattr(column, "info", {}).get("schema_gate_optional", False))


async def validate_database_schema(engine: AsyncEngine) -> None:
    """启动前执行 schema gate，发现结构漂移则拒绝启动。"""
    _load_model_metadata()
    issues: list[str] = []

    async with engine.begin() as conn:
        def _inspect(sync_conn) -> None:
            inspector = inspect(sync_conn)
            schemas = set(inspector.get_schema_names())
            if "bot" not in schemas:
                issues.append("缺少 schema: bot")
                return

            for table in Base.metadata.sorted_tables:
                if table.schema != "bot":
                    continue

                if not inspector.has_table(table.name, schema=table.schema):
                    issues.append(f"缺少数据表: {table.schema}.{table.name}")
                    continue

                db_columns = _normalize_columns(inspector.get_columns(table.name, schema=table.schema))
                model_columns = {
                    column.name
                    for column in table.columns
                    if not _is_optional_column(column)
                }
                for column_name in sorted(model_columns - db_columns):
                    issues.append(f"缺少字段: {table.schema}.{table.name}.{column_name}")

            for required in REQUIRED_INDEXES:
                if not inspector.has_table(required.table_name, schema="bot"):
                    continue

                indexes = inspector.get_indexes(required.table_name, schema="bot")
                uniques = inspector.get_unique_constraints(required.table_name, schema="bot")
                keys = _collect_index_keys(indexes, uniques)
                expected = (required.index_name, required.columns, required.unique)
                if expected not in keys:
                    issues.append(
                        "缺少索引: "
                        f"bot.{required.table_name}.{required.index_name}"
                        f" columns={required.columns} unique={required.unique}"
                    )

        await conn.run_sync(_inspect)

    if issues:
        raise SchemaValidationError(
            "数据库结构校验失败，拒绝启动：\n"
            f"{_format_missing_items(issues)}\n"
            "请先执行迁移或更新初始化脚本。"
        )
