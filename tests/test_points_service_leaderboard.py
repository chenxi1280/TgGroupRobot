from __future__ import annotations

import pytest
from sqlalchemy.dialects import postgresql

from backend.features.points.services import points_service_leaderboard as leaderboard_module


class _ScalarResult:
    def scalar(self) -> int:
        return 2


class _CaptureSession:
    def __init__(self) -> None:
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return _ScalarResult()


@pytest.mark.asyncio
async def test_get_user_rank_uses_sql_and_operator(monkeypatch) -> None:
    async def get_balance(*args, **kwargs):
        return 12

    monkeypatch.setattr(leaderboard_module, "get_balance", get_balance)
    session = _CaptureSession()

    rank = await leaderboard_module.get_user_rank(session, -1001, 42)

    assert rank == 3
    sql = str(session.statements[0].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "WHERE and(" not in sql
    assert "bot.points_accounts.chat_id = -1001 AND bot.points_accounts.balance > 12" in sql
