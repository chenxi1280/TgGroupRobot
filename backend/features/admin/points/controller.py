from __future__ import annotations

from backend.features.admin.points.custom_points import CustomPointsAdminControllerMixin
from backend.features.admin.points.levels import PointsLevelAdminControllerMixin
from backend.features.admin.points.mall import PointsMallAdminControllerMixin


class PointsAdminControllerMixin(
    CustomPointsAdminControllerMixin,
    PointsLevelAdminControllerMixin,
    PointsMallAdminControllerMixin,
):
    pass
