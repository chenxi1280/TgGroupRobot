from __future__ import annotations

from backend.features.admin.core.basic_menus import CoreBasicMenusMixin
from backend.features.admin.core.menu_dispatch import CoreMenuDispatchMixin
from backend.features.admin.core.navigation import CoreNavigationMixin


class CoreAdminControllerMixin(
    CoreMenuDispatchMixin,
    CoreBasicMenusMixin,
    CoreNavigationMixin,
):
    pass
