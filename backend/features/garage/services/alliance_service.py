from __future__ import annotations

from backend.features.garage.services.alliance_ban import AllianceBanMixin
from backend.features.garage.services.alliance_base import AllianceBaseMixin
from backend.features.garage.services.alliance_lifecycle import AllianceLifecycleMixin


class AllianceService(
    AllianceLifecycleMixin,
    AllianceBanMixin,
    AllianceBaseMixin,
):
    pass
