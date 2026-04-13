from __future__ import annotations

from backend.features.admin.moderation.config_menus import ModerationConfigMenusMixin
from backend.features.admin.moderation.control_menus import ModerationControlMenusMixin
from backend.features.admin.moderation.member_menus import ModerationMemberMenusMixin


class ModerationMenusMixin(
    ModerationControlMenusMixin,
    ModerationMemberMenusMixin,
    ModerationConfigMenusMixin,
):
    """Composed moderation menu mixin."""
