from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from pydantic import BaseModel, Field

from backend.features.points.services.points_service_accounts import change_points
from backend.platform.db.schema.models.core import AppSetting, PointsMallSetting, TgChat
from backend.platform.db.schema.models.room_games import PlatformGameFee
from backend.shared.services.base import ValidationError
from backend.shared.services.ops_audit_service import record_ops_event

SETTINGS_KEY = "platform_game_fees"
MAX_ROOM_FEE = 100_000
GAME_NAMES = {"sichuan": "四川血战", "zhajinhua": "炸金花", "k3": "快三"}


class RoomFee(BaseModel):
    enabled: bool = False
    points: int = Field(default=10, ge=0, le=MAX_ROOM_FEE, strict=True)


class GroupRoomSettings(BaseModel):
    sichuan: RoomFee = Field(default_factory=RoomFee)
    zhajinhua: RoomFee = Field(default_factory=RoomFee)


class RoomSchedule(BaseModel):
    hands: int = Field(default=20, ge=1, le=20, strict=True)


class FeeSettings(BaseModel):
    sichuan: RoomSchedule = Field(default_factory=RoomSchedule)
    zhajinhua: RoomSchedule = Field(default_factory=RoomSchedule)
    k3: int = Field(default=0, ge=0, le=100_000, strict=True)


async def fee_settings(session) -> FeeSettings:
    setting = await session.get(AppSetting, SETTINGS_KEY)
    return FeeSettings.model_validate_json(setting.value) if setting else FeeSettings()


async def group_room_settings(session, chat_id: int) -> GroupRoomSettings:
    setting = await session.get(AppSetting, f"room_games:{chat_id}")
    return GroupRoomSettings.model_validate_json(setting.value) if setting else GroupRoomSettings()


async def update_group_room_settings(
    session, chat_id: int, *, user_id: int, game: str, enabled: bool | None = None, points: int | None = None,
) -> None:
    chat = await session.scalar(select(TgChat.id).where(TgChat.id == chat_id).with_for_update())
    if chat is None:
        raise ValidationError("机器人尚未登记该群")
    settings = await group_room_settings(session, chat_id)
    terms = getattr(settings, game)
    if enabled is not None:
        terms.enabled = enabled
    if points is not None:
        terms.points = points
    stmt = insert(AppSetting).values(key=f"room_games:{chat_id}", value=settings.model_dump_json())
    await session.execute(stmt.on_conflict_do_update(
        index_elements=[AppSetting.key],
        set_={"value": stmt.excluded.value, "updated_at": stmt.excluded.updated_at},
    ))
    await record_ops_event(
        session, domain="room_games", event_type="settings_updated",
        chat_id=chat_id, user_id=user_id, detail=settings.model_dump(),
    )


async def require_room_enabled(session, chat_id: int, game: str) -> RoomFee:
    config = getattr(await group_room_settings(session, chat_id), game)
    if not config.enabled:
        raise ValidationError("本群尚未开启此玩法")
    return config


async def require_closed_mall(session, chat_id: int) -> None:
    await session.execute(select(TgChat.id).where(TgChat.id == chat_id).with_for_update())
    setting = await session.get(PointsMallSetting, chat_id, with_for_update=True, populate_existing=True)
    if setting and setting.enabled:
        raise ValidationError("本群积分商城已开启，关闭后才可使用固定台费游戏")


async def change_game_points(session, chat_id: int, user_id: int, *, amount: int, reason: str) -> int:
    ok, balance = await change_points(
        session, chat_id, user_id, amount=amount,
        txn_type="reward" if amount > 0 else "penalty", reason=reason,
    )
    if not ok:
        raise ValidationError(f"可用积分不足，当前余额 {balance}")
    return balance


async def collect_fee(session, chat_id: int, user_id: int, *, game: str, session_id: int, amount: int) -> None:
    if not amount:
        return
    await change_game_points(
        session, chat_id, user_id, amount=-amount, reason=f"{GAME_NAMES[game]}台费 #{session_id}",
    )
    session.add(PlatformGameFee(
        game=game, session_id=session_id, chat_id=chat_id, user_id=user_id,
        amount=amount, charged_at=dt.datetime.now(dt.UTC),
    ))
