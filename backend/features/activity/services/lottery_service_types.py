from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Literal


@dataclass
class ParsedLotteryConfig:
    lottery_type: str
    title: str
    description: str | None
    draw_time: dt.datetime
    min_points: int
    participation_cost: int
    max_participants: int
    requirement_days: int
    qualification_window_days: int
    required_invites: int
    required_activity_count: int
    finalist_limit: int
    selection_mode: str
    prizes: list[dict]


@dataclass
class JoinResult:
    success: bool
    reason: Literal[
        "ok",
        "already_joined",
        "lottery_not_found",
        "lottery_not_open",
        "lottery_closed",
        "lottery_completed",
        "insufficient_points",
        "insufficient_invites",
        "insufficient_activity",
        "ranking_auto_selection",
        "max_participants_reached",
        "not_member_long_enough",
        "outside_join_time",
    ]
