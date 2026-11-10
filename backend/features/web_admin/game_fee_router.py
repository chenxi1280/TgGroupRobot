from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from backend.features.activity.room_games.fees import SETTINGS_KEY, FeeSettings, fee_settings
from backend.features.web_admin.api_common import ok
from backend.features.web_admin.auth_service import append_audit
from backend.features.web_admin.dependencies import admin_session, current_admin
from backend.platform.db.schema.models.core import AppSetting
from backend.platform.db.schema.models.room_games import PlatformGameFee

router = APIRouter()


@router.get("/admin/api/game-fees")
async def read_game_fees(
    chat_id: int | None = None, offset: int = Query(default=0, ge=0),
    *, admin=Depends(current_admin), session=Depends(admin_session),
):
    totals = select(PlatformGameFee.chat_id, func.sum(PlatformGameFee.amount)).group_by(PlatformGameFee.chat_id)
    entries = select(PlatformGameFee)
    if chat_id is not None:
        entries = entries.where(PlatformGameFee.chat_id == chat_id)
    entries = entries.order_by(
        PlatformGameFee.charged_at.desc(), PlatformGameFee.game, PlatformGameFee.session_id, PlatformGameFee.user_id,
    )
    return ok({
        "settings": await fee_settings(session),
        "balances": [{"chat_id": key, "points": amount} for key, amount in (await session.execute(totals)).all()],
        "entries": list((await session.scalars(entries.offset(offset).limit(50))).all()),
    })


@router.put("/admin/api/game-fees")
async def set_game_fees(payload: FeeSettings, *, admin=Depends(current_admin), session=Depends(admin_session)):
    value = payload.model_dump_json()
    stmt = insert(AppSetting).values(key=SETTINGS_KEY, value=value)
    await session.execute(stmt.on_conflict_do_update(index_elements=["key"], set_={"value": value}))
    await append_audit(
        session, admin_account_id=admin.id, action="game_fees.update", target_type="app_settings",
        target_id=SETTINGS_KEY, detail=payload.model_dump(),
    )
    await session.commit()
    return ok(payload, "游戏设置已保存")
