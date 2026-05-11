from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession


EventResolver = Callable[[AsyncSession, int, str], Awaitable[str | None]]

CUSTOM_TRIGGER_CATEGORY = "custom"
BOTTOM_BUTTON_EVENT_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("points", "积分"),
    ("teacher", "老师搜索"),
    ("invite", "邀请"),
    ("activity", "活动"),
    ("game", "游戏"),
    ("car_review", "车评"),
    (CUSTOM_TRIGGER_CATEGORY, "自定义触发词"),
)


@dataclass(frozen=True)
class BottomButtonEvent:
    key: str
    label: str
    category: str
    default_button_text: str
    resolver: EventResolver


async def _resolve_points_alias(session: AsyncSession, chat_id: int, event_key: str) -> str | None:
    from backend.shared.services.chat_service import get_chat_settings

    settings = await get_chat_settings(session, chat_id)
    if event_key == "points.balance":
        return (str(getattr(settings, "points_alias", "") or "").strip() or "积分")
    if event_key == "points.rank":
        return (str(getattr(settings, "points_rank_alias", "") or "").strip() or "积分排行")
    return None


async def _resolve_points_mall(session: AsyncSession, chat_id: int, _event_key: str) -> str | None:
    from backend.features.points.services.points_extended_service import PointsExtendedService

    setting = await PointsExtendedService.get_or_create_mall_setting(session, chat_id)
    return (str(getattr(setting, "entry_command", "") or "").strip() or "积分商城")


async def _resolve_custom_point_rank(session: AsyncSession, chat_id: int, event_key: str) -> str | None:
    from backend.features.points.services.points_extended_service import PointsExtendedService

    prefix = "points.custom_rank:"
    if not event_key.startswith(prefix):
        return None
    try:
        type_id = int(event_key[len(prefix):])
    except ValueError:
        return None
    item = await PointsExtendedService.get_custom_point_type(session, chat_id, type_id)
    if item is None or not getattr(item, "rank_command", None):
        return None
    return str(item.rank_command).strip() or None


async def _resolve_teacher_attendance(session: AsyncSession, chat_id: int, event_key: str) -> str | None:
    from backend.features.garage.services.garage_features_service import TeacherSearchService

    setting = await TeacherSearchService.get_setting(session, chat_id)
    if event_key == "teacher.attendance.open":
        if (getattr(setting, "attendance_mode", "message") or "message") == "keyword":
            return (getattr(setting, "attendance_open_keyword", None) or "开课").strip()
        return "开课打卡"
    if event_key == "teacher.attendance.full":
        return (getattr(setting, "attendance_full_keyword", None) or "满课").strip()
    if event_key == "teacher.attendance.rest":
        return (getattr(setting, "attendance_rest_keyword", None) or "休息").strip()
    return None


async def _resolve_engagement_reward(session: AsyncSession, chat_id: int, _event_key: str) -> str | None:
    from backend.features.activity.services.engagement_service import get_or_create_chat_reward

    reward = await get_or_create_chat_reward(session, chat_id)
    return (str(getattr(reward, "command_keyword", "") or "").strip() or "我爱水群")


async def _resolve_car_review_rank(session: AsyncSession, chat_id: int, event_key: str) -> str | None:
    from backend.features.garage.services.garage_features_service import CarReviewService

    setting = await CarReviewService.get_setting(session, chat_id)
    rank_command = str(getattr(setting, "rank_command", "") or "").strip() or "出击排行"
    if event_key == "car_review.rank":
        return rank_command
    if event_key == "car_review.week_rank":
        return f"本周{rank_command}"
    if event_key == "car_review.month_rank":
        return f"本月{rank_command}"
    return None


def _text_event(key: str, label: str, category: str, default_button_text: str, trigger_text: str) -> BottomButtonEvent:
    async def resolve(_session: AsyncSession, _chat_id: int, _event_key: str) -> str | None:
        return trigger_text

    return BottomButtonEvent(key, label, category, default_button_text, resolve)


STATIC_BOTTOM_BUTTON_EVENTS: tuple[BottomButtonEvent, ...] = (
    _text_event("points.sign", "签到", "points", "签到", "签到"),
    BottomButtonEvent("points.balance", "我的积分", "points", "我的积分", _resolve_points_alias),
    BottomButtonEvent("points.rank", "积分排行榜", "points", "排行榜", _resolve_points_alias),
    BottomButtonEvent("points.mall", "积分商城", "points", "商城", _resolve_points_mall),
    _text_event("teacher.search", "老师搜索", "teacher", "老师搜索", "老师搜索"),
    _text_event("teacher.nearby", "附近老师", "teacher", "附近", "附近"),
    _text_event("teacher.open_courses", "开课老师", "teacher", "开课老师", "开课老师"),
    BottomButtonEvent("teacher.attendance.open", "开课打卡", "teacher", "开课打卡", _resolve_teacher_attendance),
    BottomButtonEvent("teacher.attendance.full", "满课", "teacher", "满课", _resolve_teacher_attendance),
    BottomButtonEvent("teacher.attendance.rest", "休息", "teacher", "休息", _resolve_teacher_attendance),
    _text_event("invite.link", "我的邀请链接", "invite", "邀请", "邀请"),
    _text_event("invite.stats", "邀请统计", "invite", "邀请统计", "邀请统计"),
    _text_event("invite.rank", "邀请排行榜", "invite", "邀请排行", "邀请排行"),
    BottomButtonEvent("engagement.reward", "水群奖励", "activity", "水群奖励", _resolve_engagement_reward),
    _text_event("guess.entry", "竞猜入口", "activity", "竞猜", "竞猜"),
    _text_event("game.k3.panel", "快3面板", "game", "快3", "快3"),
    _text_event("game.k3.rules", "快3规则", "game", "快3规则", "快3规则"),
    _text_event("game.k3.stats", "快3统计", "game", "快3统计", "快3统计"),
    _text_event("game.blackjack.panel", "黑杰克面板", "game", "黑杰克", "黑杰克"),
    _text_event("game.blackjack.rules", "黑杰克规则", "game", "黑杰克规则", "黑杰克规则"),
    _text_event("game.blackjack.stats", "黑杰克统计", "game", "黑杰克统计", "黑杰克统计"),
    _text_event("car_review.submit", "提交车评", "car_review", "提交车评", "提交车评"),
    BottomButtonEvent("car_review.rank", "车评排行", "car_review", "车评排行", _resolve_car_review_rank),
    BottomButtonEvent("car_review.week_rank", "本周车评排行", "car_review", "本周车评", _resolve_car_review_rank),
    BottomButtonEvent("car_review.month_rank", "本月车评排行", "car_review", "本月车评", _resolve_car_review_rank),
)

BOTTOM_BUTTON_EVENT_OPTIONS: tuple[tuple[str, str], ...] = tuple(
    (event.key, event.label) for event in STATIC_BOTTOM_BUTTON_EVENTS
)
BOTTOM_BUTTON_EVENT_LABELS: dict[str, str] = dict(BOTTOM_BUTTON_EVENT_OPTIONS)
_STATIC_EVENTS_BY_KEY = {event.key: event for event in STATIC_BOTTOM_BUTTON_EVENTS}


def encode_event_callback_key(event_key: str) -> str:
    return event_key.replace(":", "~")


def decode_event_callback_key(token: str) -> str:
    return token.replace("~", ":")


def get_event_label(event_key: str | None) -> str:
    if not event_key:
        return "未绑定"
    if event_key.startswith("points.custom_rank:"):
        return "自定义积分排行"
    return BOTTOM_BUTTON_EVENT_LABELS.get(event_key, "未知事件")


async def list_bottom_button_events(
    session: AsyncSession,
    chat_id: int,
    *,
    category: str | None = None,
) -> list[BottomButtonEvent]:
    events = [
        event
        for event in STATIC_BOTTOM_BUTTON_EVENTS
        if category is None or event.category == category
    ]
    if category in {None, "points"}:
        from backend.features.points.services.points_extended_service import PointsExtendedService

        for item in await PointsExtendedService.list_custom_point_types(session, chat_id):
            rank_command = str(getattr(item, "rank_command", "") or "").strip()
            if not rank_command:
                continue
            events.append(
                BottomButtonEvent(
                    key=f"points.custom_rank:{item.id}",
                    label=f"{item.name}排行",
                    category="points",
                    default_button_text=f"{item.name}排行"[:16],
                    resolver=_resolve_custom_point_rank,
                )
            )
    return events


async def find_bottom_button_event(
    session: AsyncSession,
    chat_id: int,
    event_key: str,
) -> BottomButtonEvent | None:
    static_event = _STATIC_EVENTS_BY_KEY.get(event_key)
    if static_event is not None:
        return static_event
    if event_key.startswith("points.custom_rank:"):
        for event in await list_bottom_button_events(session, chat_id, category="points"):
            if event.key == event_key:
                return event
    return None


async def resolve_event_trigger_text(
    session: AsyncSession,
    chat_id: int,
    event_key: str,
) -> str | None:
    event = await find_bottom_button_event(session, chat_id, event_key)
    if event is None:
        return None
    return await event.resolver(session, chat_id, event_key)
