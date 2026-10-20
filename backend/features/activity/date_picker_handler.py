"""Authenticated, revisioned activity calendar callbacks for private and group drafts."""
import datetime as dt

from sqlalchemy import select

from backend.features.activity import date_picker_targets as targets
from backend.features.activity.date_picker import STATES, fingerprint
from backend.platform.db.schema.models.chat import ConversationState, TgUser
from backend.shared.handlers.base.message_helper import MessageHelper
from backend.shared.services.base import ValidationError
from backend.shared.ui.datetime_picker import KEY, picker_view, transition

CALLBACK_PARTS = 5


async def _load(session, update, *, token, revision):
    user, chat = update.effective_user.id, update.effective_chat.id
    await session.execute(select(TgUser.id).where(TgUser.id == user).with_for_update())
    state = await session.scalar(select(ConversationState).where(
        ConversationState.chat_id == chat, ConversationState.user_id == user,
    ).with_for_update().execution_options(populate_existing=True))
    picker = (state.state_data or {}).get(KEY) if state else None
    if not state or state.state_type not in STATES or not picker:
        raise ValidationError("活动日期输入已失效，请重新进入原草稿")
    _validate_picker(state, picker, token=token, revision=revision)
    return state, dict(picker)


def _validate_picker(state, picker, *, token, revision):
    if picker.get("token") != token or picker.get("revision") != revision:
        raise ValidationError("旧日历或其他用户的日历不能操作当前草稿")
    if picker.get("expires", 0) <= dt.datetime.now(dt.UTC).timestamp():
        raise ValidationError("日历已过期，请重新进入原草稿")
    if picker.get("base") != fingerprint(state.state_data):
        raise ValidationError("草稿已修改，请重新进入日期输入；本次未覆盖")
    if state.state_type == "lottery_create" and (
        state.state_data.get("step") != "draw_param" or state.state_data.get("draw_trigger") == "full_participants"
    ):
        raise ValidationError("当前抽奖步骤不接受日期")


async def activity_date_callback(update, context):
    if not update.effective_user or not update.effective_chat or not update.callback_query:
        return
    parts = (update.callback_query.data or "").split(":")
    if len(parts) != CALLBACK_PARTS or not parts[2].isdigit():
        await MessageHelper.safe_answer(update, "无效日期操作", show_alert=True)
        return
    _, token, revision, action, value = parts
    async with context.application.bot_data["db"].session_factory() as session:
        try:
            state, picker = await _load(session, update, token=token, revision=int(revision))
            await targets.check_permission(session, update, context, state=state)
            await _operate(session, update, context, state=state, picker=picker, action=action, value=value)
        except (ValidationError, ValueError, KeyError) as exc:
            await session.rollback()
            await MessageHelper.safe_answer(update, str(exc), show_alert=True)


async def _operate(session, update, context, *, state, picker, action, value):
    if action in {"cancel", "manual"}:
        await targets.return_input(session, update, context, state=state)
    elif action == "apply":
        if picker["step"] != "confirm":
            raise ValidationError("请先完成日期与时间选择")
        await targets.apply(session, update, context, state=state, value=picker["value"])
        await session.commit()
    elif action == "noop":
        await MessageHelper.safe_answer(update, "请选择有数字的日期")
        return
    else:
        picker = transition(picker, action, value)
        state.state_data = {**state.state_data, KEY: picker}
        await session.commit()
        text, keyboard = picker_view(picker, scope=targets.scope(state))
        await MessageHelper.safe_edit(update, text, reply_markup=keyboard)
    await MessageHelper.safe_answer(update)
