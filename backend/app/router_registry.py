from __future__ import annotations

from telegram.ext import Application

from backend.features.activity.game_runtime_router import GameRuntimeRouter
from backend.features.activity.lottery_router import LotteryRouter
from backend.features.activity.solitaire_router import SolitaireRouter
from backend.features.admin.admin_router import AdminRouter
from backend.features.automation.ads_router import AdsRouter
from backend.features.automation.scheduled_message_router import ScheduledMessageRouter
from backend.features.group_ops.bottom_button_router import BottomButtonRouter
from backend.features.group_ops.group_router import GroupRouter
from backend.features.invite.invite_router import InviteRouter
from backend.features.moderation.auto_reply_router import AutoReplyRouter
from backend.features.moderation.banned_word_router import BannedWordRouter
from backend.features.nearby.nearby_router import NearbyRouter
from backend.features.points.points_router import PointsRouter
from backend.features.subscription.renewal_router import RenewalRouter
from backend.features.verification.verification_router import VerificationRouter


def build_feature_routers() -> list[object]:
    return [
        AdminRouter(),
        LotteryRouter(),
        SolitaireRouter(),
        InviteRouter(),
        AdsRouter(),
        ScheduledMessageRouter(),
        AutoReplyRouter(),
        BannedWordRouter(),
        PointsRouter(),
        RenewalRouter(),
        NearbyRouter(),
        GroupRouter(),
        VerificationRouter(),
        BottomButtonRouter(),
        GameRuntimeRouter(),
    ]


def register_feature_routers(app: Application) -> None:
    for router in build_feature_routers():
        router.register(app)

