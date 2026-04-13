from __future__ import annotations

from backend.features.admin.moderation.verification_config_start import VerificationConfigStartMixin
from backend.features.admin.moderation.verification_home_actions import VerificationHomeActionsMixin
from backend.features.admin.moderation.verification_views import VerificationViewsMixin


class ModerationVerificationMixin(
    VerificationConfigStartMixin,
    VerificationViewsMixin,
    VerificationHomeActionsMixin,
):
    pass
