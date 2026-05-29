from __future__ import annotations

import pytest
from sqlalchemy.dialects import postgresql

from backend.features.points.services import points_service_leaderboard as leaderboard_module
from backend.features.points.services.points_service_messages import (
    format_daily_points_leaderboard_message,
    format_leaderboard_message,
)


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


def test_format_leaderboard_message_uses_display_name_before_user_id() -> None:
    text = format_leaderboard_message(
        [
            (11, 20, None, "洋芋", "洋芋"),
            (12, 10, "alice", "Alice", None),
        ]
    )

    assert "1. 洋芋 洋芋 - 20 积分" in text
    assert "2. @alice - 10 积分" in text
    assert "用户11" not in text


def test_format_daily_points_leaderboard_message_uses_display_name_before_user_id() -> None:
    text = format_daily_points_leaderboard_message(
        [
            (11, 20, None, "洋芋", "洋芋"),
            (12, 10, "alice", "Alice", None),
        ]
    )

    assert "1. 洋芋 洋芋 - 今日获得 20 积分" in text
    assert "2. @alice - 今日获得 10 积分" in text
    assert "用户11" not in text
