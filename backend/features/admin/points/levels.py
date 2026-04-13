from __future__ import annotations

from backend.features.admin.points.level_actions import PointsLevelActionsMixin
from backend.features.admin.points.mall_actions import PointsMallActionsMixin
from backend.features.admin.points.overview_views import PointsOverviewViewsMixin


class PointsLevelAdminControllerMixin(
    PointsLevelActionsMixin,
    PointsMallActionsMixin,
    PointsOverviewViewsMixin,
):
    """Composed points admin actions and overview pages."""
