"""Durable private date picker with scoped permission and stale-step protection."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from backend.platform.db.schema.models.chat import ConversationState, TgUser
from backend.platform.state.conversation_state_service import ConversationStateService
from backend.shared import datetime_picker_targets as targets
from backend.shared.handlers.base.message_helper import MessageHelper
from backend.shared.services.base import ValidationError
from backend.shared.services.permission_service import PermissionPolicyService
from backend.shared.ui.datetime_picker import KEY, SUPPORTED_STATES, picker_view, transition


CALLBACK_PARTS = 5


async def _load(session, update, *, token, revision):
    user_id = update.effective_user.id
    # Match the shared input lifecycle lock order, including cross-process calls.
    await session.execute(select(TgUser.id).where(TgUser.id == user_id).with_for_update())
    state = (await session.execute(select(ConversationState).where(
        ConversationState.chat_id == user_id, ConversationState.user_id == user_id,
    ).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    picker = (state.state_data or {}).get(KEY) if state else None
    if (not state or state.state_type not in SUPPORTED_STATES or not picker
            or picker.get("token") != token or picker.get("revision") != revision
            or picker.get("expires", 0) <= dt.datetime.now(dt.UTC).timestamp()):
        raise ValidationError("此时间选择器已过期，请从原功能重新进入；本次未保存")
    return state, dict(picker)


async def datetime_picker_callback(update, context):
    if not update.effective_chat or update.effective_chat.type != "private" or not update.effective_user:
        await MessageHelper.safe_answer(update, "请在私聊配置时间", show_alert=True)
        return
    parts = (update.callback_query.data or "").split(":")
    if len(parts) != CALLBACK_PARTS or not parts[2].isdigit():
        await MessageHelper.safe_answer(update, "无效时间操作", show_alert=True)
        return
    _, token, revision, action, value = parts
    db = context.application.bot_data["db"]
    async with db.session_factory() as session:
        try:
            state, picker = await _load(session, update, token=token, revision=int(revision))
            await _operate(session, update, context, state=state, picker=picker, action=action, value=value)
        except (ValidationError, ValueError, KeyError) as exc:
            await session.rollback()
            text = str(exc) if isinstance(exc, ValidationError) else "时间选项无效，请重新选择"
            await MessageHelper.safe_answer(update, text, show_alert=True)


async def _operate(session, update, context, *, state, picker, action, value):
    allowed, reason = await PermissionPolicyService.require_manage(
        context, state.state_data["target_chat_id"], update.effective_user.id, capability="automation")
    if not allowed:
        await ConversationStateService.clear(session, state.chat_id, state.user_id)
        await session.commit()
        await MessageHelper.safe_answer(update, reason or "权限已失效，已退出输入", show_alert=True)
        return
    if action == "cancel":
        await _finish(session, update, context, state=state, applied=False)
        return
    if action == "noop":
        await MessageHelper.safe_answer(update, "日期按周一至周日排列；请选择有数字的日期")
        return
    row = await targets.resource(session, state)
    if action == "apply":
        if picker["step"] != "confirm":
            raise ValidationError("请先完成日期与时间选择")
        if picker.get("base") != targets.date_version(row):
            raise ValidationError("时间配置已被修改，请取消后重新打开；本次未覆盖")
        await targets.apply_value(session, state, picker["value"])
        await _finish(session, update, context, state=state, applied=True)
        return
    if action == "open":
        picker["base"] = targets.date_version(row)
    picker = transition(picker, action, value)
    state.state_data = {**state.state_data, KEY: picker}
    scope = targets.scope_label(state)
    await session.commit()
    await MessageHelper.safe_answer(update)
    text, keyboard = picker_view(picker, scope=scope)
    await MessageHelper.safe_edit(update, text, reply_markup=keyboard)


async def _finish(session, update, context, *, state, applied):
    kind, data = state.state_type, dict(state.state_data)
    await ConversationStateService.clear(session, state.chat_id, state.user_id)
    await session.commit()
    await MessageHelper.safe_answer(update, "时间已保存" if applied else "已取消，原时间保持不变")
    try:
        await targets.return_to_source(update, context, state_type=kind, data=data)
    except Exception:
        # The transaction has committed. A rendering failure must never imply
        # that the setting was not applied or revive the consumed input.
        back = data[KEY]["back"]
        await update.effective_message.reply_text(
            "时间已保存，页面刷新失败，请返回查看。" if applied else "已退出输入，请返回查看。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("返回原功能", callback_data=back)]]))
