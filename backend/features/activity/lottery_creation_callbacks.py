from __future__ import annotations

from dataclasses import dataclass
import structlog
from typing import Awaitable, Callable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from backend.features.activity.lottery_creation_config import (
    _append_lottery_wizard_guide,
    _build_config_from_state,
    _format_lottery_wizard_summary,
    _is_private_admin_context,
    _participation_cost_prompt,
    _previous_lottery_wizard_step,
    _save_state_data,
    _state_data,
    _wizard_back_callback,
    _wizard_nav_keyboard,
)
from backend.features.activity.lottery_creation_parsing import _lottery_type_title
from backend.features.activity.lottery_creation_wizard import (
    _create_and_publish_lottery,
    _edit_wizard_step_prompt,
)
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.enums import ConversationStateType
from backend.platform.state.state_service import clear_user_state, get_user_state


CALLBACK_BASE_PARTS = 4
CALLBACK_ACTION_PARTS = 5
log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class LotteryCallbackRequest:
    update: Update
    context: ContextTypes.DEFAULT_TYPE
    session: object
    state: object
    data: dict
    target_chat_id: int
    state_chat_id: int
    parts: list[str]


CallbackHandler = Callable[[LotteryCallbackRequest], Awaitable[None]]


def _nav_keyboard(target_chat_id: int) -> InlineKeyboardMarkup:
    return _wizard_nav_keyboard(
        target_chat_id,
        back_callback=_wizard_back_callback(target_chat_id),
    )


async def _handle_back(request: LotteryCallbackRequest) -> None:
    previous_step = _previous_lottery_wizard_step(request.data)
    if previous_step is not None:
        await _edit_wizard_step_prompt(
            request.update,
            request.update.callback_query,
            request.session,
            state=request.state,
            data=request.data,
            step=previous_step,
        )
        return
    await clear_user_state(
        request.session,
        chat_id=request.state_chat_id,
        user_id=request.update.effective_user.id,
    )
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "🔙 返回抽奖类型",
            callback_data=f"lot:create_menu:{request.target_chat_id}",
        )
    ]])
    await request.update.callback_query.edit_message_text(
        "已返回上级，请重新选择抽奖条件。",
        reply_markup=keyboard,
    )


def _callback_value(request: LotteryCallbackRequest, error_text: str) -> str:
    if len(request.parts) < CALLBACK_ACTION_PARTS:
        raise ValueError(error_text)
    return request.parts[4]


async def _point_type_data(request: LotteryCallbackRequest, type_id: int) -> dict:
    if type_id <= 0:
        return {
            **request.data,
            "point_type_id": None,
            "point_type_name": "积分",
            "step": "participation_cost",
        }
    from backend.features.points.services.points_extended_service import PointsExtendedService

    item = await PointsExtendedService.get_custom_point_type(
        request.session,
        request.target_chat_id,
        type_id,
    )
    if item is None or not getattr(item, "enabled", True):
        raise ValueError("该积分类型不可用")
    return {
        **request.data,
        "point_type_id": int(item.id),
        "point_type_name": item.name,
        "step": "participation_cost",
    }


async def _handle_point_type(request: LotteryCallbackRequest) -> None:
    type_id = int(_callback_value(request, "积分类型参数无效"))
    data = await _point_type_data(request, type_id)
    _save_state_data(request.state, data)
    text = _append_lottery_wizard_guide(
        f"已选择：{data['point_type_name']}\n\n{_participation_cost_prompt(data['point_type_name'])}",
        data,
        next_step="填写玩法门槛或确认发布",
    )
    await request.update.callback_query.edit_message_text(
        text,
        reply_markup=_nav_keyboard(request.target_chat_id),
    )


def _preset_prompt(data: dict) -> str:
    prize_names = [
        str(prize.get("name") or "").strip()
        for prize in data.get("prizes") or []
        if str(prize.get("name") or "").strip()
    ]
    if len(prize_names) > 1:
        template = "\n".join(f"{name}: 随机" for name in prize_names)
        return (
            "本次有多个奖品，请逐个奖品设置内定人。\n"
            "格式：奖品名称: @用户\n"
            "不内定的奖品写：奖品名称: 随机\n"
            f"可直接按下面模板修改：\n{template}"
        )
    prize_name = prize_names[0] if prize_names else "奖品"
    return (
        "本步只输入内定中奖人，支持数字ID、@用户名、用户资料链接。\n"
        f"可直接输入用户，或写成：{prize_name}: @用户\n"
        "发送“随机”或“无”可清空内定名单。"
    )


async def _handle_preset(request: LotteryCallbackRequest) -> None:
    if not _is_private_admin_context(request.update):
        raise ValueError("请在机器人私聊中配置此项")
    data = {**request.data, "step": "preset_winners"}
    _save_state_data(request.state, data)
    text = _append_lottery_wizard_guide(
        _preset_prompt(data),
        data,
        next_step="回到确认页后发布到群",
    )
    await request.update.callback_query.edit_message_text(
        text,
        reply_markup=_nav_keyboard(request.target_chat_id),
    )


async def _handle_prize(request: LotteryCallbackRequest) -> None:
    action = _callback_value(request, "奖品操作参数无效")
    steps = {"add": "prize_name", "done": "draw_param"}
    step = steps.get(action)
    if step is None:
        raise ValueError("奖品操作参数无效")
    await _edit_wizard_step_prompt(
        request.update,
        request.update.callback_query,
        request.session,
        state=request.state,
        data=request.data,
        step=step,
    )


def _publish_keyboard(target_chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 返回抽奖管理", callback_data=f"adm:menu:lottery:{target_chat_id}")],
        [InlineKeyboardButton("🏠 返回主菜单", callback_data=f"adm:menu:main:{target_chat_id}")],
    ])


async def _handle_publish(request: LotteryCallbackRequest) -> None:
    config = _build_config_from_state(request.data)
    lottery = await _create_and_publish_lottery(
        request.update,
        request.context,
        request.session,
        target_chat_id=request.target_chat_id,
        creator_user_id=request.update.effective_user.id,
        config=config,
    )
    await clear_user_state(
        request.session,
        chat_id=request.state_chat_id,
        user_id=request.update.effective_user.id,
    )
    summary = _format_lottery_wizard_summary(
        config,
        include_sensitive=_is_private_admin_context(request.update),
    )
    text = (
        f"✅ {_lottery_type_title(config.lottery_type)}创建成功！\n\n{summary}"
        f"\n\n📢 已发送公告到群组\n抽奖ID：{lottery.id}"
    )
    await request.update.callback_query.edit_message_text(
        text,
        reply_markup=_publish_keyboard(request.target_chat_id),
    )


CALLBACK_HANDLERS: dict[str, CallbackHandler] = {
    "back": _handle_back,
    "pt": _handle_point_type,
    "preset": _handle_preset,
    "prize": _handle_prize,
    "publish": _handle_publish,
}


def _state_chat_id(update: Update) -> int:
    chat = update.effective_chat
    if chat is None or chat.type == "private":
        return update.effective_user.id
    return chat.id


async def _load_request(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    *,
    target_chat_id: int,
    parts: list[str],
) -> LotteryCallbackRequest | None:
    state_chat_id = _state_chat_id(update)
    state = await get_user_state(session, state_chat_id, update.effective_user.id)
    if state is None or state.state_type != ConversationStateType.lottery_create.value:
        await update.callback_query.edit_message_text("创建状态已失效，请重新进入抽奖创建。")
        return None
    data = _state_data(state)
    if int(data.get("target_chat_id") or 0) != target_chat_id:
        await update.callback_query.answer("这不是当前创建中的群组", show_alert=True)
        return None
    return LotteryCallbackRequest(
        update,
        context,
        session,
        state,
        data,
        target_chat_id,
        state_chat_id,
        parts,
    )


async def _dispatch_callback(request: LotteryCallbackRequest, action: str) -> None:
    handler = CALLBACK_HANDLERS.get(action)
    if handler is None:
        raise ValueError("无效的抽奖创建操作")
    await handler(request)


async def handle_lottery_wizard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None:
        return
    await update.callback_query.answer()
    parts = (update.callback_query.data or "").split(":")
    if len(parts) < CALLBACK_BASE_PARTS:
        await update.callback_query.answer("回调参数无效", show_alert=True)
        return
    try:
        target_chat_id = int(parts[2])
    except ValueError:
        await update.callback_query.answer("群组参数无效", show_alert=True)
        return
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        request = await _load_request(
            update,
            context,
            session,
            target_chat_id=target_chat_id,
            parts=parts,
        )
        if request is None:
            return
        try:
            await _dispatch_callback(request, parts[3])
            await session.commit()
        except ValueError as exc:
            await session.rollback()
            await update.callback_query.answer(str(exc), show_alert=True)
        except Exception as exc:
            log.exception("lottery_wizard_callback_error", error=str(exc))
            await session.rollback()
            await update.callback_query.edit_message_text(f"❌ 创建失败: {exc}")
