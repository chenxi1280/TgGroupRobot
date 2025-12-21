from __future__ import annotations

import enum


class ChatType(str, enum.Enum):
    group = "group"
    supergroup = "supergroup"


class MemberRole(str, enum.Enum):
    owner = "owner"
    admin = "admin"
    member = "member"


class ModerationAction(str, enum.Enum):
    delete = "delete"
    warn = "warn"
    mute = "mute"
    ban = "ban"


class PointsTxnType(str, enum.Enum):
    sign_in = "sign_in"
    admin_adjust = "admin_adjust"
    reward = "reward"
    penalty = "penalty"


class SubscriptionStatus(str, enum.Enum):
    active = "active"
    expired = "expired"
    cancelled = "cancelled"



