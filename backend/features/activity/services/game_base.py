from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal, InvalidOperation

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.points.services.points_extended_service import PointsExtendedService
from backend.platform.db.schema.models.core import TgUser
from backend.platform.db.schema.models.expansion import GameSetting
from backend.shared.services.base import ValidationError
from backend.shared.services.module_settings_service import ModuleSettingsService
from backend.shared.ui.message_config_panel import format_completion_lines

MAX_GAME_BET_POINTS = 500
log = structlog.get_logger(__name__)


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def format_ratio(value: str | None) -> str:
    return value or "未设置"


def parse_ratio(raw: str) -> str:
    try:
        value = Decimal(raw.strip())
    except (InvalidOperation, AttributeError):
        raise ValidationError("抽水比例格式错误，请输入 0 到 1 之间的小数，例如 0.1。")
    if value < 0 or value > 1:
        raise ValidationError("抽水比例必须在 0 到 1 之间。")
    normalized = value.normalize()
    return format(normalized, "f")


def validate_hhmm(raw: str) -> str:
    value = raw.strip()
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
        raise ValidationError("时间格式错误，请输入 HH:MM，例如 23:05。")
    return value


async def get_or_create_setting(session: AsyncSession, chat_id: int) -> GameSetting:
    await ModuleSettingsService.ensure(session, chat_id=chat_id)
    setting = await session.get(GameSetting, chat_id)
    if setting is None:
        setting = GameSetting(chat_id=chat_id)
        session.add(setting)
        await session.flush()
    return setting


async def update_setting(session: AsyncSession, chat_id: int, **updates) -> GameSetting:
    setting = await get_or_create_setting(session, chat_id)
    for key, value in updates.items():
        if hasattr(setting, key):
            setattr(setting, key, value)
    setting.updated_at = now_utc()
    await session.flush()
    return setting


async def resolve_rake_owner(session: AsyncSession, raw: str) -> int | None:
    if raw.strip() == "清空":
        return None
    user_id = await PointsExtendedService.resolve_user_id(session, raw)
    if user_id is None:
        raise ValidationError("未找到该用户，请输入用户ID或已记录的用户名。")
    return user_id


async def get_rake_owner_label(session: AsyncSession, user_id: int | None) -> str:
    if user_id is None:
        return "未设置"
    user = await session.get(TgUser, user_id)
    if user is None:
        return str(user_id)
    if user.username:
        return f"@{user.username}"
    return user.first_name or str(user_id)


def resolve_points_chat_id(setting: GameSetting, fallback_chat_id: int | None = None) -> int:
    return int(setting.points_source_chat_id or fallback_chat_id or setting.chat_id)


def get_round_points_chat_id(round_obj, default_chat_id: int) -> int:
    data = getattr(round_obj, "result_data", None) or {}
    try:
        return int(data.get("points_chat_id") or default_chat_id)
    except (TypeError, ValueError):
        log.warning(
            "game_round_points_chat_id_parse_failed",
            default_chat_id=default_chat_id,
            raw_value=data.get("points_chat_id"),
        )
        return int(default_chat_id)


async def get_game_points_chat_label(session: AsyncSession, chat_id: int, points_source_chat_id: int | None) -> str:
    if points_source_chat_id is None or int(points_source_chat_id) == int(chat_id):
        return "本群分"
    from backend.platform.db.schema.models.core import TgChat

    chat = await session.get(TgChat, int(points_source_chat_id))
    title = chat.title if chat and chat.title else str(points_source_chat_id)
    return f"主群分：{title}"


async def apply_auto_schedule(session: AsyncSession, now_local: dt.datetime) -> list[int]:
    stmt = select(GameSetting).where(GameSetting.auto_schedule_enabled.is_(True))
    result = await session.execute(stmt)
    settings = list(result.scalars().all())
    changed: list[int] = []
    hhmm = now_local.strftime("%H:%M")
    for setting in settings:
        if _apply_schedule_to_setting(setting, hhmm):
            setting.updated_at = now_utc()
            changed.append(setting.chat_id)
    await session.flush()
    return changed


def _apply_schedule_to_setting(setting: GameSetting, hhmm: str) -> bool:
    should_start = setting.auto_start_time == hhmm
    should_stop = setting.auto_stop_time == hhmm
    if should_start and (not setting.k3_enabled or not setting.blackjack_enabled):
        setting.k3_enabled = True
        setting.blackjack_enabled = True
        return True
    if should_stop and (setting.k3_enabled or setting.blackjack_enabled):
        setting.k3_enabled = False
        setting.blackjack_enabled = False
        return True
    return False


def format_game_menu_text(
    chat_title: str,
    *,
    k3_enabled: bool,
    blackjack_enabled: bool,
    rake_ratio: str | None,
    rake_owner: str,
    auto_schedule_enabled: bool,
    auto_start_time: str | None,
    auto_stop_time: str | None,
    delete_mode: str,
    points_chat_label: str = "本群分",
) -> str:
    lines = [
        f"🎮 游戏 | {chat_title}",
        "",
        f"🎲 快三：{'✅ 启动' if k3_enabled else '❌ 关闭'}",
        f"🃏 黑杰克：{'✅ 启动' if blackjack_enabled else '❌ 关闭'}",
        f"🔗 关联积分：{points_chat_label}",
        f"💧 抽水比例：{format_ratio(rake_ratio)}",
        f"👤 抽水归属：{rake_owner}",
        f"⏰ 定时启停：{'✅ 启动' if auto_schedule_enabled else '❌ 关闭'}",
        f"🕒 启动时间：{auto_start_time or '未设置'}",
        f"🌙 关停时间：{auto_stop_time or '未设置'}",
        f"🧹 删除游戏消息：{'🗑 删除' if delete_mode == 'delete' else '💾 不删除'}",
    ]
    lines.extend(
        format_completion_lines(
            [
                ("至少开启一个玩法", bool(k3_enabled or blackjack_enabled)),
                ("确认积分来源", bool(points_chat_label)),
                ("查看指令帮助", True),
            ],
            next_step="开启玩法后到群里发送 快三/黑杰克 进行冷启动",
            test_step="用测试账号下注 1 局，开奖后查看最近牌局",
        )
    )
    return "\n".join(lines)


def parse_positive_int(raw: str, field_name: str) -> int:
    try:
        value = int(raw.strip())
    except (ValueError, AttributeError):
        raise ValidationError(f"{field_name}必须是正整数。")
    if value <= 0:
        raise ValidationError(f"{field_name}必须大于 0。")
    if value > MAX_GAME_BET_POINTS:
        raise ValidationError(f"{field_name}不能超过 {MAX_GAME_BET_POINTS}。")
    return value


def parse_k3_command(text: str) -> tuple[str, int] | None:
    match = re.fullmatch(r"快(?:3|三)\s+(大|小|单|双|豹子|豹子通杀|对子|对子号|半顺|半顺号|三连|三连号|杂六|杂六号)\s+(\d+)", text.strip())
    if not match:
        return None
    return match.group(1), parse_positive_int(match.group(2), "下注积分")


def parse_blackjack_bet(text: str) -> int | None:
    match = re.fullmatch(r"黑杰克\s+(\d+)", text.strip())
    if not match:
        return None
    return parse_positive_int(match.group(1), "下注积分")


def get_rake_ratio_value(setting: GameSetting) -> Decimal:
    try:
        return Decimal(setting.rake_ratio or "0")
    except InvalidOperation:
        log.warning(
            "game_rake_ratio_parse_failed",
            chat_id=getattr(setting, "chat_id", None),
            raw_value=setting.rake_ratio,
        )
        return Decimal("0")
