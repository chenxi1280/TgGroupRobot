from __future__ import annotations

from backend.features.admin.moderation.verification_config_start import VerificationConfigStartMixin
from backend.features.admin.moderation.verification_home_actions import VerificationHomeActionsMixin
from backend.features.admin.moderation.verification_views import VerificationViewsMixin
from backend.features.admin.moderation.verification_timeout_operations import VerificationTimeoutOperationsMixin


class ModerationVerificationMixin(
    VerificationConfigStartMixin,
    VerificationViewsMixin,
    VerificationHomeActionsMixin,
    VerificationTimeoutOperationsMixin,
):
    pass
