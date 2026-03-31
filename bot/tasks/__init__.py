"""定时任务模块"""

from bot.tasks.lottery_task import LotteryTask
from bot.tasks.solitaire_task import SolitaireTask
from bot.tasks.ads_task import AdsTask
from bot.tasks.message_task import MessageTask
from bot.tasks.cleanup_task import CleanupTask
from bot.tasks.verification_timeout_task import VerificationTimeoutTask
from bot.tasks.scheduled_message_task import ScheduledMessageTaskRunner
from bot.tasks.group_lock_task import GroupLockTask
from bot.tasks.auction_task import AuctionTask
from bot.tasks.bottom_button_task import BottomButtonTask
from bot.tasks.engagement_task import EngagementTask
from bot.tasks.game_task import GameTask
from bot.tasks.guess_task import GuessTask

__all__ = [
    "LotteryTask",
    "SolitaireTask",
    "AdsTask",
    "MessageTask",
    "CleanupTask",
    "VerificationTimeoutTask",
    "ScheduledMessageTaskRunner",
    "GroupLockTask",
    "AuctionTask",
    "BottomButtonTask",
    "EngagementTask",
    "GameTask",
    "GuessTask",
]
