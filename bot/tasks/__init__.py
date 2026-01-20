"""定时任务模块"""

from bot.tasks.lottery_task import LotteryTask
from bot.tasks.solitaire_task import SolitaireTask
from bot.tasks.ads_task import AdsTask
from bot.tasks.message_task import MessageTask
from bot.tasks.cleanup_task import CleanupTask
from bot.tasks.verification_timeout_task import VerificationTimeoutTask

__all__ = [
    "LotteryTask",
    "SolitaireTask",
    "AdsTask",
    "MessageTask",
    "CleanupTask",
    "VerificationTimeoutTask",
]
