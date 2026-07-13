"""定时任务模块"""

from backend.platform.scheduler.tasks.lottery_task import LotteryTask
from backend.platform.scheduler.tasks.solitaire_task import SolitaireTask
from backend.platform.scheduler.tasks.ads_task import AdsTask
from backend.platform.scheduler.tasks.message_task import MessageTask
from backend.platform.scheduler.tasks.cleanup_task import CleanupTask
from backend.platform.scheduler.tasks.verification_timeout_task import VerificationTimeoutTask
from backend.platform.scheduler.tasks.scheduled_message_task import ScheduledMessageTaskRunner
from backend.platform.scheduler.tasks.group_lock_task import GroupLockTask
from backend.platform.scheduler.tasks.rename_monitor_task import RenameMonitorTask
from backend.platform.scheduler.tasks.auction_task import AuctionTask
from backend.platform.scheduler.tasks.bottom_button_task import BottomButtonTask
from backend.platform.scheduler.tasks.engagement_task import EngagementTask
from backend.platform.scheduler.tasks.game_task import GameTask
from backend.platform.scheduler.tasks.guess_task import GuessTask
from backend.platform.scheduler.tasks.teacher_search_task import TeacherSearchTask
from backend.platform.scheduler.tasks.garage_forward_retry_task import GarageForwardRetryTask

__all__ = [
    "LotteryTask",
    "SolitaireTask",
    "AdsTask",
    "MessageTask",
    "CleanupTask",
    "VerificationTimeoutTask",
    "ScheduledMessageTaskRunner",
    "GroupLockTask",
    "RenameMonitorTask",
    "AuctionTask",
    "BottomButtonTask",
    "EngagementTask",
    "GameTask",
    "GuessTask",
    "TeacherSearchTask",
    "GarageForwardRetryTask",
]
