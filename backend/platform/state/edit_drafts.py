"""Durable suspended inputs, separate from the legacy active state record."""
from __future__ import annotations

import datetime as dt
import secrets

from sqlalchemy import select

from backend.platform.db.schema.models.chat import ConversationState, EditDraft, TgUser


async def suspend_inputs(session, user_id: int, *, exclude_scope: int | None = None) -> list[EditDraft]:
    await session.execute(select(TgUser.id).where(TgUser.id == user_id).with_for_update())
    stmt = select(ConversationState).where(
        ConversationState.user_id == user_id,
        ConversationState.state_type != "selected_chat",
    )
    if exclude_scope is not None:
        stmt = stmt.where(ConversationState.chat_id != exclude_scope)
    states = (await session.execute(stmt.with_for_update())).scalars().all()
    drafts = [await archive_state(session, state) for state in states]
    await session.flush()
    return [draft for draft in drafts if draft is not None]


async def archive_state(session, state):
    data = dict(state.state_data or {})
    data.pop("__expire_at__", None)
    target = data.get("target_chat_id") or data.get("managed_chat_id") or state.chat_id
    if state.state_type == "admin_list_search_input":
        state.state_type = "selected_chat"
        state.state_data = {"managed_chat_id": target}
        await session.flush()
        return None
    from backend.platform.state.draft_versions import VERSION_KEY, version_for_state
    if VERSION_KEY not in data:
        data[VERSION_KEY] = await version_for_state(session, state.state_type, data, chat_id=int(target))
    draft = EditDraft(
        token=secrets.token_hex(12), user_id=state.user_id, chat_id=int(target),
        state_chat_id=state.chat_id, state_type=state.state_type, state_data=data,
        expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(days=7),
    )
    session.add(draft)
    if state.chat_id == state.user_id:
        state.state_type = "selected_chat"
        state.state_data = {"managed_chat_id": target}
    else:
        await session.delete(state)
    await session.flush()
    return draft


async def list_drafts(session, user_id: int, chat_id: int):
    return list((await session.execute(select(EditDraft).where(
        EditDraft.user_id == user_id, EditDraft.chat_id == chat_id,
        EditDraft.state_type.not_in(["mall_fulfillment_confirmation", "button_layout_draft"]),
        EditDraft.expires_at > dt.datetime.now(dt.UTC),
    ).order_by(EditDraft.created_at.desc()))).scalars().all())


MIN_CONFLICTING_INPUTS = 2


async def suspend_conflicting_legacy_inputs(session, user_id: int) -> list[EditDraft]:
    """One-time reconciliation before interpreting a legacy user's next message."""
    stmt = select(ConversationState).where(
        ConversationState.user_id == user_id,
        ConversationState.state_type.not_in(["selected_chat", "guess_draft"]),
    )
    active = list((await session.execute(stmt)).scalars())
    if len(active) < MIN_CONFLICTING_INPUTS:
        return []
    await session.execute(select(TgUser.id).where(TgUser.id == user_id).with_for_update())
    active = list((await session.execute(stmt.with_for_update().execution_options(populate_existing=True))).scalars())
    if len(active) < MIN_CONFLICTING_INPUTS:
        return []
    return [await archive_state(session, state) for state in active]
