from __future__ import annotations

from backend.features.admin.activity.auction import AuctionAdminControllerMixin
from backend.features.admin.activity.bottom_button import BottomButtonAdminControllerMixin
from backend.features.admin.activity.engagement import EngagementAdminControllerMixin
from backend.features.admin.activity.game import GameAdminControllerMixin
from backend.features.admin.activity.guess import GuessAdminControllerMixin


class ActivityAdminControllerMixin(
    AuctionAdminControllerMixin,
    BottomButtonAdminControllerMixin,
    GameAdminControllerMixin,
    GuessAdminControllerMixin,
    EngagementAdminControllerMixin,
):
    pass
