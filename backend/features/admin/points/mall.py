from __future__ import annotations

from backend.features.admin.points.detail_pages import PointsDetailPagesMixin
from backend.features.admin.points.mall_base_pages import PointsMallBasePagesMixin
from backend.features.admin.points.mall_order_pages import PointsMallOrderPagesMixin
from backend.features.admin.points.mall_product_pages import PointsMallProductPagesMixin


class PointsMallAdminControllerMixin(
    PointsMallBasePagesMixin,
    PointsMallOrderPagesMixin,
    PointsMallProductPagesMixin,
    PointsDetailPagesMixin,
):
    pass
