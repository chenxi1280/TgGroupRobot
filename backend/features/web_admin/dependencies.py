from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.web_admin.auth_service import (
    SESSION_COOKIE_NAME,
    get_account_by_session_token,
)
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.core import AdminAccount


async def admin_session(request: Request) -> AsyncIterator[AsyncSession]:
    db: Database = request.app.state.db
    async with db.session_factory() as session:
        yield session


async def current_admin(
    request: Request,
    session: AsyncSession = Depends(admin_session),
) -> AdminAccount:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    account = await get_account_by_session_token(session, token)
    if account is None:
        raise HTTPException(status_code=401, detail="请先登录后台")
    return account
