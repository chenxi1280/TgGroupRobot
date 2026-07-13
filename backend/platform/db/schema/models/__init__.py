from backend.platform.db.schema.models.activity import (  # noqa: F401
    Lottery,
    LotteryParticipant,
    LotteryWinner,
    Solitaire,
    SolitaireEntry,
)
from backend.platform.db.schema.models.admin_web import (  # noqa: F401
    AdminAccount,
    AdminAuditLog,
    AdminSession,
    AppSetting,
)
from backend.platform.db.schema.models.automation import (  # noqa: F401
    AdCampaign,
    InviteLink,
    InviteTracking,
    ScheduledMessage,
)
from backend.platform.db.schema.models.chat import (  # noqa: F401
    ChatMember,
    ChatSettings,
    ConversationState,
    GroupDailyStats,
    NearbyProfile,
    TgChat,
    TgUser,
)
from backend.platform.db.schema.models.moderation import (  # noqa: F401
    AutoReplyRule,
    BannedWord,
    ModerationWarning,
    ModerationViolation,
    VerificationChallenge,
    VerificationTimeoutAttempt,
)
from backend.platform.db.schema.models.points import (  # noqa: F401
    CustomPointAccount,
    CustomPointLedger,
    CustomPointType,
    PointsAccount,
    PointsLevel,
    PointsLevelSetting,
    PointsMallOrder,
    PointsMallOrderLog,
    PointsMallProduct,
    PointsMallSetting,
    PointsTransaction,
    SignInLog,
    UserDailyStats,
)
from backend.platform.db.schema.models.subscription import (  # noqa: F401
    ChatSubscription,
    RenewalAuditLog,
    RenewalCardKey,
    RenewalCardKeyBatch,
    SubscriptionPlan,
)
from backend.platform.db.schema.models.alliance import (  # noqa: F401
    GarageForwardAuditLog,
    GarageForwardMessageMap,
    GarageForwardSetting,
    GarageForwardSource,
    GroupAlliance,
    GroupAllianceAudit,
    GroupAllianceBanPool,
    GroupAllianceMember,
    GroupAllianceSetting,
)
from backend.platform.db.schema.models.garage_features import (  # noqa: F401
    CarReviewAuditLog,
    CarReviewCustomField,
    CarReviewReport,
    CarReviewSetting,
    GarageCertifiedTeacher,
    GarageSpeechWhitelist,
    MemberLocation,
    TeacherDailyAttendance,
    TeacherProfile,
    TeacherSearchSetting,
)
from backend.platform.db.schema.models.scheduled_message import ScheduledMessageLog, ScheduledMessageTask  # noqa: F401
from backend.platform.db.schema.models.welcome import WelcomeMessage  # noqa: F401
from backend.platform.db.schema.models.expansion import (  # noqa: F401
    AccountInheritAudit,
    AccountInheritSetting,
    AccountInheritToken,
    AuctionBid,
    AuctionItem,
    AuctionSetting,
    BottomButtonLayout,
    BottomButtonSetting,
    GameSetting,
    EngagementChatReward,
    EngagementChatStat,
    EngagementEgg,
    EngagementSetting,
    GuessBet,
    GuessEvent,
    GuessSetting,
)
