"""Version guards for resumed legacy editors; no silent overwrite on resume."""
from __future__ import annotations
import hashlib
import json
from sqlalchemy import select
from backend.platform.db.schema.models.core import (
    ChatSettings, PointsMallSetting, PointsMallProduct, PointsLevel, AdCampaign, AutoReplyRule,
)
from backend.platform.db.schema.models.welcome import WelcomeMessage

VERSION_KEY = "__draft_base_version__"


def _binding(state_type, data, chat_id):
    # Entity identifiers are always combined with the original target group.
    if state_type.startswith("points_mall"):
        if data.get("product_id"):
            return PointsMallProduct, PointsMallProduct.product_id == int(data["product_id"])
        return PointsMallSetting, PointsMallSetting.chat_id == chat_id
    bindings = (
        ("points_level", "level_id", PointsLevel, PointsLevel.id),
        ("ads", "item_id", AdCampaign, AdCampaign.id),
        ("auto_reply", "rule_id", AutoReplyRule, AutoReplyRule.id),
        ("welcome", "welcome_id", WelcomeMessage, WelcomeMessage.id),
    )
    for prefix, key, model, column in bindings:
        if state_type.startswith(prefix) and data.get(key):
            return model, column == int(data[key])
    return ChatSettings, ChatSettings.chat_id == chat_id


async def version_for_state(session, state_type, data, *, chat_id, lock=False):
    model, predicate = _binding(state_type, data, chat_id)
    stmt = select(model).where(predicate, model.chat_id == chat_id)
    if lock:
        stmt = stmt.with_for_update()
    item = (await session.execute(stmt.execution_options(populate_existing=True))).scalar_one_or_none()
    if item is None:
        return "missing"
    # Ignore bookkeeping timestamps. Domain status and all editable fields remain.
    values = {column.key: getattr(item, column.key) for column in model.__table__.columns
              if column.key not in {"created_at", "updated_at"}}
    return hashlib.sha256(json.dumps(values, sort_keys=True, default=str).encode()).hexdigest()


async def resumed_version_matches(session, state, *, lock=False):
    data = state.state_data or {}
    expected = data.get(VERSION_KEY)
    if expected is None:
        return True
    target = data.get("target_chat_id") or data.get("managed_chat_id") or state.chat_id
    return expected == await version_for_state(session, state.state_type, data, chat_id=target, lock=lock)
