"""积分服务返回类型。"""

from __future__ import annotations

from typing import NamedTuple


class PointsResult(NamedTuple):
    success: bool
    balance: int
    reason: str | None = None


class SignResult(NamedTuple):
    success: bool
    balance: int
    consecutive_days: int
    bonus_points: int
    reason: str | None = None
