from __future__ import annotations

from backend.features.admin.moderation.config_actions import ModerationConfigActionsMixin
from backend.features.admin.moderation.control_actions import ModerationControlActionsMixin
from backend.features.admin.moderation.member_actions import ModerationMemberActionsMixin


class ModerationActionsMixin(
    ModerationControlActionsMixin,
    ModerationMemberActionsMixin,
    ModerationConfigActionsMixin,
):
    """Composed moderation action mixin."""
