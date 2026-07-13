from __future__ import annotations

from backend.features.admin.garage.alliance import GarageAllianceAdminMixin
from backend.features.admin.garage.auth_search import GarageAuthSearchAdminMixin
from backend.features.admin.garage.forward import GarageForwardAdminMixin
from backend.features.admin.garage.forward_operations import GarageForwardOperationsMixin
from backend.features.admin.garage.review import GarageReviewAdminMixin


class GarageAdminControllerMixin(
    GarageReviewAdminMixin,
    GarageAuthSearchAdminMixin,
    GarageForwardOperationsMixin,
    GarageForwardAdminMixin,
    GarageAllianceAdminMixin,
):
    """Composed garage admin controller."""
