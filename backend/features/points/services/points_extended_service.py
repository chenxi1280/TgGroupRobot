from __future__ import annotations

from backend.features.points.services.points_extended_custom import PointsExtendedCustomMixin
from backend.features.points.services.points_extended_levels import PointsExtendedLevelsMixin
from backend.features.points.services.points_extended_mall import PointsExtendedMallMixin
from backend.features.points.services.points_extended_users import PointsExtendedUserMixin


class PointsExtendedService(
    PointsExtendedCustomMixin,
    PointsExtendedLevelsMixin,
    PointsExtendedMallMixin,
    PointsExtendedUserMixin,
):
    pass
