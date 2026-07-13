from __future__ import annotations

import re

from backend.features.activity.services.engagement_service import (
    parse_reward_plan as parse_engagement_reward_plan,
    update_chat_reward as update_engagement_chat_reward,
    update_egg_event_from_template,
)
from backend.features.admin.activity.runtime import admin_handler_instance, clear_private_admin_state
from backend.shared.services.base import ValidationError


async def _finish_engagement_input(
    update, context, session, *, target_chat_id: int, user_id: int,
    event_id: int | None = None,
) -> None:
    await clear_private_admin_state(
        session, target_chat_id=target_chat_id, user_id=user_id
    )
    await session.commit()
    handler = admin_handler_instance()
    if event_id is not None:
        await handler._show_engagement_egg(
            update, context, target_chat_id, event_id=event_id
        )
        return
    await handler._show_engagement_chat_reward(update, context, target_chat_id)


async def _handle_engagement_chat_input(
    update, context, session, *, state_type: str, value: str,
    target_chat_id: int, user_id: int,
) -> bool:
    if state_type == "engagement_wait_chat_target":
        if not re.fullmatch(r"\d+", value):
            await update.effective_message.reply_text("发言达标数量必须是正整数。")
            return True
        await _save_engagement_chat_input(
            update, context, session, target_chat_id=target_chat_id,
            user_id=user_id, changes={"daily_message_target": max(int(value), 1)},
        )
        return True
    if state_type == "engagement_wait_chat_plan":
        await _save_engagement_chat_input(
            update, context, session, target_chat_id=target_chat_id,
            user_id=user_id,
            changes={"reward_points_plan": parse_engagement_reward_plan(value)},
        )
        return True
    if state_type == "engagement_wait_chat_command":
        if not value:
            await update.effective_message.reply_text("领奖口令不能为空。")
            return True
        await _save_engagement_chat_input(
            update, context, session, target_chat_id=target_chat_id,
            user_id=user_id, changes={"command_keyword": value[:32]},
        )
        return True
    return False


async def _save_engagement_chat_input(
    update, context, session, *, target_chat_id: int, user_id: int, changes: dict
) -> None:
    await update_engagement_chat_reward(session, target_chat_id, **changes)
    await _finish_engagement_input(
        update, context, session, target_chat_id=target_chat_id, user_id=user_id
    )


async def handle_engagement_admin_input(
    update,
    context,
    session,
    *, state,
    message_text: str,

    target_chat_id: int,
) -> bool:
    if update.effective_user is None or update.effective_message is None:
        return True

    state_type = str(state.state_type)
    if not state_type.startswith("engagement_"):
        return False

    user_id = update.effective_user.id
    value = message_text.strip()
    try:
        if state_type == "engagement_wait_egg_template":
            event = await update_egg_event_from_template(
                session,
                target_chat_id,
                value,
                event_id=state.state_data.get("event_id"),
            )
            await _finish_engagement_input(
                update, context, session, target_chat_id=target_chat_id,
                user_id=user_id, event_id=event.id,
            )
            return True
        if await _handle_engagement_chat_input(
            update, context, session, state_type=state_type, value=value,
            target_chat_id=target_chat_id, user_id=user_id,
        ):
            return True
    except ValidationError as exc:
        await update.effective_message.reply_text(str(exc))
        return True

    await update.effective_message.reply_text("当前促活工具配置状态不支持该输入，请重新进入配置页面。")
    return True
