from __future__ import annotations

from backend.features.admin.garage.review_actions import GarageReviewActionsMixin
from backend.features.admin.garage.review_views import GarageReviewViewsMixin


class GarageReviewAdminMixin(
    GarageReviewViewsMixin,
    GarageReviewActionsMixin,
):
    """Composed car review admin controller."""
