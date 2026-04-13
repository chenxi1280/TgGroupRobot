from __future__ import annotations

from backend.features.points.services.points_mall_orders import PointsMallOrdersMixin
from backend.features.points.services.points_mall_products import PointsMallProductsMixin
from backend.features.points.services.points_mall_settings import PointsMallSettingsMixin, UNSET


class PointsExtendedMallMixin(
    PointsMallSettingsMixin,
    PointsMallOrdersMixin,
    PointsMallProductsMixin,
):
    """Composed points mall service mixin."""


__all__ = ["PointsExtendedMallMixin", "UNSET"]
