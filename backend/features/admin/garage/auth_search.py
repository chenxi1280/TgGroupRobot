from __future__ import annotations

from backend.features.admin.garage.auth_actions import GarageAuthActionsMixin
from backend.features.admin.garage.auth_views import GarageAuthViewsMixin
from backend.features.admin.garage.teacher_search_actions import TeacherSearchActionsMixin
from backend.features.admin.garage.teacher_search_views import TeacherSearchViewsMixin


class GarageAuthSearchAdminMixin(
    GarageAuthViewsMixin,
    GarageAuthActionsMixin,
    TeacherSearchViewsMixin,
    TeacherSearchActionsMixin,
):
    """Composed garage auth and teacher search admin controller."""
