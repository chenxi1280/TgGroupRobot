from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, NamedTuple

from backend.platform.db.schema.models.core import InviteLink


@dataclass
class CreateResult:
    """创建邀请链接结果"""

    success: bool
    reason: Literal["ok", "error", "limit_reached", "permission_denied"]
    invite_link: InviteLink | None = None


@dataclass
class RevokeResult:
    """撤销邀请链接结果"""

    success: bool
    reason: Literal["ok", "not_found", "already_revoked", "error"]


class InviteStats(NamedTuple):
    """邀请统计"""

    total_invites: int
    active_links: int
    total_links: int
    link_limit: int | None
    links_generated: int
