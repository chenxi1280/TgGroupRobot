from __future__ import annotations

import datetime as dt
import re
import time
from dataclasses import dataclass
from http import HTTPStatus
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from telegram import InlineQueryResultArticle, InputTextMessageContent, User
from telegram.error import BadRequest, Forbidden, TelegramError

from backend.features.activity.room_games.fees import (
    fee_settings, group_room_settings, require_closed_mall, require_room_enabled,
)
from backend.features.activity.game_notice_delivery import deliver_game_notices, queue_game_notice
from backend.features.activity.room_games.notices import queue_room_notice, room_invite_card
from backend.features.activity.room_games.rooms import (
    ROOM_CREATES_PER_GROUP, ROOM_CREATES_PER_PLAYER, WAIT_MINUTES,
    advance_hand, available_rooms, create_room, hand_reserve, join_room, leave_room, now, open_hand,
    require_room_points, room_summary, room_view, seat_for,
)
from backend.features.mini_app.auth import renew_room_session, room_session_identity
from backend.features.points.services.points_service_accounts import get_balance
from backend.platform.db.schema.models.core import PointsMallSetting, TgChat
from backend.platform.db.schema.models.room_games import GameNotice, RoomGame
from backend.shared.services.base import ValidationError
from backend.shared.services.user_service import ensure_user

router = APIRouter(prefix="/miniapp/api/rooms")
MEMBERSHIP_READ_SECONDS = 30
MEMBERSHIP_CACHE_LIMIT = 1024


@dataclass(frozen=True)
class RoomMember:
    user: User
    chat_id: int


class CreateRoom(BaseModel):
    game: Literal["sichuan", "zhajinhua"]
    base: int = Field(ge=1, le=100, strict=True)
    multiplier: Literal[1, 2, 5, 10]
    special: bool = True


class RoomAction(BaseModel):
    operation: Literal["join", "leave", "start", "next", "move", "remove"]
    version: int = Field(ge=0, strict=True)
    action: dict = Field(default_factory=dict)
    target_user_id: int | None = Field(default=None, gt=0, strict=True)


class RoomInvite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: Literal["group", "private"]


async def _require_member(bot, chat_id: int, user_id: int) -> None:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except (BadRequest, Forbidden) as exc:
        raise HTTPException(403, "无法确认群成员资格") from exc
    except TelegramError as exc:
        raise HTTPException(503, "暂时无法验证群成员资格") from exc
    if member.status in {"creator", "administrator", "member"}:
        return
    if member.status == "restricted" and member.is_member and member.can_send_messages:
        return
    raise HTTPException(403, "请先加入原群并完成入群验证，房间仅对原群可发言成员开放")


async def room_member(request: Request, response: Response) -> RoomMember:
    actor, issued, expires = room_session_identity(request)
    scene = re.fullmatch(r"(?:rooms_([1-9][0-9]{0,15})|room_([1-9][0-9]{0,15})_[1-9][0-9]{0,9}(?:_[1-9][0-9]?)?)", actor.start_param)
    if not scene:
        raise HTTPException(403, "请从群内游戏房间入口打开")
    chat_id = -int(scene[1] or scene[2])
    key = (chat_id, actor.user.id)
    cache = request.app.state.room_read_membership
    if request.method != "GET" or cache.get(key, 0) <= time.monotonic():
        await _require_member(request.app.state.telegram_app.bot, chat_id, actor.user.id)
        if len(cache) >= MEMBERSHIP_CACHE_LIMIT:
            cache.clear()
        cache[key] = time.monotonic() + MEMBERSHIP_READ_SECONDS
    renew_room_session(request, response, actor, issued=issued, expires=expires)
    return RoomMember(actor.user, chat_id)


async def _ensure_member(session, member: RoomMember) -> None:
    user = member.user
    await ensure_user(
        session, user.id, user.username, first_name=user.first_name,
        last_name=user.last_name, language_code=user.language_code,
    )
    if await session.get(TgChat, member.chat_id) is None:
        raise HTTPException(404, "机器人尚未登记本群")


async def _room(session, room_id: int, member: RoomMember, *, lock: bool = False) -> RoomGame:
    room = await session.get(RoomGame, room_id, with_for_update=lock or None)
    if room is None or room.chat_id != member.chat_id:
        raise HTTPException(404, "房间不存在")
    return room


@router.get("")
async def lobby(request: Request, response: Response, member: RoomMember = Depends(room_member)):
    response.headers["Cache-Control"] = "no-store"
    async with request.app.state.db.session_factory() as session:
        config = await group_room_settings(session, member.chat_id)
        schedule = await fee_settings(session)
        mall = await session.get(PointsMallSetting, member.chat_id)
        return {
            "games": {
                game: terms | getattr(schedule, game).model_dump()
                for game, terms in config.model_dump().items()
            },
            "mall_open": bool(mall and mall.enabled),
            "rooms": [room_summary(room) for room in await available_rooms(session, member.chat_id)],
            "balance": await get_balance(session, member.chat_id, member.user.id),
        }


@router.post("")
async def open_room(
    data: CreateRoom, *, request: Request, member: RoomMember = Depends(room_member),
):
    async with request.app.state.db.session_factory() as session:
        try:
            await _ensure_member(session, member)
            room = await create_room(session, member.chat_id, member.user, data=data)
            view = await room_view(session, room, member.user.id)
            await session.commit()
        except ValidationError as exc:
            raise HTTPException(409, str(exc)) from exc
    return view


@router.get("/{room_id}")
async def read_room(
    room_id: int, *, request: Request, response: Response, member: RoomMember = Depends(room_member),
):
    response.headers["Cache-Control"] = "no-store"
    async with request.app.state.db.session_factory() as session:
        room = await _room(session, room_id, member)
        return await room_view(session, room, member.user.id)


def _require_fresh(room, data) -> None:
    if data.version != room.version:
        raise ValidationError("房间已更新，请重试")
    if room.deadline is not None and room.deadline <= now():
        raise ValidationError("本次操作已超时，请刷新牌桌")


async def _check_start_member(bot, room, player) -> None:
    try:
        await _require_member(bot, room.chat_id, player["id"])
    except HTTPException as exc:
        if exc.status_code != HTTPStatus.FORBIDDEN:
            raise
        raise ValidationError(f'{player["name"]} 已无本群游戏资格，请移除该座位') from exc


async def _open_paid_hand(session, room, member, *, first: bool, bot) -> str:
    if member.user.id != room.owner_id or room.status != ("waiting" if first else "between"):
        raise ValidationError("只有房主可以在此时开始")
    for player in room.seats:
        if player["id"] != member.user.id:
            await _check_start_member(bot, room, player)
    await open_hand(session, room, first=first)
    return "started" if first else "hand_started"


async def _join_waiting_room(session, room, member, *, data) -> None:
    if seat_for(room, member.user.id) is not None:
        return
    _require_fresh(room, data)
    await _ensure_member(session, member)
    await require_closed_mall(session, room.chat_id)
    await require_room_enabled(session, room.chat_id, room.game)
    await require_room_points(session, room.chat_id, member.user.id,
                              minimum=room.fee + hand_reserve(room.game, room.unit))
    join_room(room, member.user)


def _remove_waiting_seat(room, seat: int, target_user_id: int | None) -> None:
    target = seat_for(room, target_user_id)
    if room.status != "waiting" or room.seats[seat]["id"] != room.owner_id or target is None or target == seat:
        raise ValidationError("只有房主可以在开场前移除其他玩家")
    leave_room(room, target)


async def _change_room(session, room, member, *, data, bot) -> str | None:
    if data.operation == "join":
        await _join_waiting_room(session, room, member, data=data)
        return None
    seat = seat_for(room, member.user.id)
    _require_fresh(room, data)
    if seat is None:
        raise ValidationError("请先加入房间")
    if data.operation in {"start", "next"}:
        return await _open_paid_hand(session, room, member, first=data.operation == "start", bot=bot)
    if data.operation == "remove":
        _remove_waiting_seat(room, seat, data.target_user_id)
        return None
    if data.operation == "leave":
        leave_room(room, seat)
        return None
    if room.status != "playing":
        raise ValidationError("本小局没有在进行")
    settled = await advance_hand(session, room, seat=seat, action=data.action)
    return "settled" if settled else None


@router.post("/{room_id}")
async def change_room(
    room_id: int, data: RoomAction, *, request: Request, tasks: BackgroundTasks,
    member: RoomMember = Depends(room_member),
):
    bot = request.app.state.telegram_app.bot
    async with request.app.state.db.session_factory() as session:
        try:
            room = await _room(session, room_id, member, lock=True)
            event = await _change_room(session, room, member, data=data, bot=bot)
            view = await room_view(session, room, member.user.id)
            if event:
                notice = queue_room_notice(session, bot, room, event=event)
                await session.flush()
                tasks.add_task(deliver_game_notices, request.app.state.db, bot, [notice.id])
            await session.commit()
        except ValidationError as exc:
            raise HTTPException(409, str(exc)) from exc
    return view


async def _prepare_private_invite(bot, room, user_id: int, *, text: str, keyboard):
    result = await bot.do_api_request("savePreparedInlineMessage", api_kwargs={
        "user_id": user_id,
        "result": InlineQueryResultArticle(
            id=str(room.id), title="加入房间",
            input_message_content=InputTextMessageContent(text), reply_markup=keyboard,
        ),
        "allow_user_chats": True, "allow_bot_chats": False,
        "allow_group_chats": False, "allow_channel_chats": False,
    })
    return {"message_id": result["id"]}


async def _queue_group_invite(session, room, user_id: int, *, text: str, keyboard) -> int:
    await require_closed_mall(session, room.chat_id)
    counts = await session.execute(select(
        func.count(), func.count().filter(GameNotice.actor_id == user_id),
    ).where(GameNotice.chat_id == room.chat_id, GameNotice.actor_id.is_not(None),
            GameNotice.created_at > now() - dt.timedelta(minutes=WAIT_MINUTES)))
    group_count, player_count = counts.one()
    if group_count >= ROOM_CREATES_PER_GROUP or player_count >= ROOM_CREATES_PER_PLAYER:
        raise ValidationError("最近群发邀请次数已达上限，请稍后再试")
    notice = queue_game_notice(session, room.chat_id, text, keyboard=keyboard, actor_id=user_id)
    room.options = {**room.options, "group_invited": True}
    await session.flush()
    return notice.id


@router.post("/{room_id}/invite")
async def invite_room(
    room_id: int, data: RoomInvite, *, request: Request, tasks: BackgroundTasks,
    member: RoomMember = Depends(room_member),
):
    bot = request.app.state.telegram_app.bot
    async with request.app.state.db.session_factory() as session:
        room = await _room(session, room_id, member, lock=data.target == "group")
        if room.owner_id != member.user.id:
            raise HTTPException(403, "仅房主可以发出邀请")
        if room.status != "waiting" or room.deadline is not None and room.deadline <= now():
            raise HTTPException(409, "房间已停止接受邀请")
        if data.target == "group" and room.options.get("group_invited"):
            return {"sent": True}
        try:
            await require_room_enabled(session, room.chat_id, room.game)
            text, keyboard = room_invite_card(bot, room)
            if data.target == "private":
                return await _prepare_private_invite(bot, room, member.user.id, text=text, keyboard=keyboard)
            notice_id = await _queue_group_invite(session, room, member.user.id, text=text, keyboard=keyboard)
        except ValidationError as exc:
            raise HTTPException(409, str(exc)) from exc
        except TelegramError as exc:
            raise HTTPException(502, "暂时无法发出邀请，请稍后重试") from exc
        await session.commit()
    tasks.add_task(deliver_game_notices, request.app.state.db, bot, [notice_id])
    return {"sent": True}
