from __future__ import annotations

from backend.features.admin.moderation.actions import ModerationActionsMixin
from backend.features.admin.moderation.menus import ModerationMenusMixin
from backend.features.admin.moderation.state import ModerationStateMixin
from backend.features.admin.moderation.verification import ModerationVerificationMixin


class ModerationAdminControllerMixin(
    ModerationVerificationMixin,
    ModerationMenusMixin,
    ModerationActionsMixin,
    ModerationStateMixin,
):
    """Composed moderation admin controller."""

