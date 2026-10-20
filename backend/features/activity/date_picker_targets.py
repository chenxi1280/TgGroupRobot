"""Adapters retain each activity's draft/preview boundaries."""
from backend.features.activity.date_picker import attach, clean
from backend.shared.services.permission_service import is_user_admin
from backend.shared.services.base import ValidationError


async def check_permission(session, update, context, *, state):
    target = state.state_data.get("target_chat_id", state.chat_id)
    if update.effective_chat.type != "private" and target != state.chat_id:
        raise ValidationError("当前群与草稿目标不一致")
    if state.state_type == "auction_wait_end_at":
        from backend.features.activity.auction_permissions import can_create_auction
        from backend.features.activity.services.auction_service import get_or_create_setting
        setting = await get_or_create_setting(session, target)
        allowed = await can_create_auction(context, setting, chat_id=target, user_id=state.user_id)
    elif state.state_type == "guess_wait_deadline":
        from backend.shared.services.permission_service import PermissionPolicyService
        allowed, _ = await PermissionPolicyService.require_manage(context, target, state.user_id, capability="engagement")
    else:
        allowed = await is_user_admin(context, target, state.user_id)
    if not allowed:
        raise ValidationError("活动创建权限已失效，本次未保存；草稿保留")


def scope(state):
    label = {"lottery_create": "抽奖开奖时间", "solitaire_create": "接龙截止时间",
             "guess_wait_deadline": "竞猜截止时间", "auction_wait_end_at": "拍卖截止时间"}[state.state_type]
    return f"群：{state.state_data.get('target_chat_id', state.chat_id)}\n草稿字段：{label}"


async def apply(session, update, context, *, state, value):
    handlers = {"lottery_create": _lottery, "guess_wait_deadline": _guess,
                "solitaire_create": _solitaire, "auction_wait_end_at": _auction}
    await handlers[state.state_type](session, update, context, state=state, value=value)


async def _lottery(session, update, context, *, state, value):
    from backend.features.activity.lottery_creation_wizard_messages import WizardMessageRequest, _handle_draw_param
    request = WizardMessageRequest(update, context, session, state, clean(state.state_data), value, None, None)
    await _handle_draw_param(request)


async def _guess(session, update, context, *, state, value):
    from backend.features.admin.activity.guess_input import _GuessInput, _guess_deadline_value, _save_guess_draft
    data = clean(state.state_data)
    flow = _GuessInput(update, session, state.state_type, value, data, data["target_chat_id"], state.user_id)
    draft = await _guess_deadline_value(flow)
    await _save_guess_draft(flow, context, draft)


async def _solitaire(session, update, context, *, state, value):
    import datetime as dt
    from backend.features.activity.solitaire_creation_config import _parse_deadline_config
    deadline = _parse_deadline_config(f"截止时间: {value}")
    if deadline is None or deadline <= dt.datetime.now(dt.UTC):
        raise ValidationError("截止时间必须是未来时间")
    state.state_data = {**clean(state.state_data), "calendar_deadline": value}
    await return_input(session, update, context, state=state)


async def _auction(session, update, context, *, state, value):
    from backend.features.activity.auction_handler import _AuctionFlow, _handle_auction_end_at
    from backend.features.activity.services.auction_service import get_or_create_setting
    setting = await get_or_create_setting(session, state.chat_id)
    flow = _AuctionFlow(update, context, session, setting, update.effective_chat,
                        update.effective_user, update.effective_message, value)
    await _handle_auction_end_at(flow, clean(state.state_data))


async def return_input(session, update, context, *, state):
    if state.state_type == "lottery_create":
        from backend.features.activity.lottery_creation_wizard_prompts import _edit_wizard_step_prompt
        await _edit_wizard_step_prompt(update, update.callback_query, session, state=state,
                                      data=clean(state.state_data), step="draw_param")
    elif state.state_type == "solitaire_create":
        from backend.features.activity.solitaire_creation_start import show_solitaire_config_prompt
        data = state.state_data
        state.state_data = attach(data, back=f"adm:menu:solitaire:{data['target_chat_id']}")
        await session.commit()
        await show_solitaire_config_prompt(update, state.state_data)
    else:
        await _return_field(session, update, context, state=state)
    await session.commit()


async def _return_field(session, update, context, *, state):
    from backend.shared.ui.datetime_picker import KEY, picker_view
    from backend.shared.handlers.base.message_helper import MessageHelper
    state.state_data = attach(state.state_data, back=state.state_data[KEY]["back"], initial=state.state_data[KEY]["value"])
    await session.commit()
    text, keyboard = picker_view(state.state_data[KEY], scope=scope(state))
    await MessageHelper.safe_edit(update, text, reply_markup=keyboard)
