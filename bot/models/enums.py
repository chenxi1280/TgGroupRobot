from __future__ import annotations

import enum


class ChatType(str, enum.Enum):
    private = "private"
    group = "group"
    supergroup = "supergroup"


class MemberRole(str, enum.Enum):
    owner = "owner"
    admin = "admin"
    member = "member"


class ModerationAction(str, enum.Enum):
    delete = "delete"
    warn = "warn"
    mute = "mute"
    ban = "ban"


class PointsTxnType(str, enum.Enum):
    sign_in = "sign_in"
    sign_in_consecutive = "sign_in_consecutive"  # 连续签到奖励
    admin_adjust = "admin_adjust"
    reward = "reward"
    penalty = "penalty"
    lottery_join = "lottery_join"       # 参与抽奖扣费
    lottery_win = "lottery_win"         # 中奖奖励
    message = "message"                 # 发言积分
    invite = "invite"                   # 邀请积分


class SubscriptionStatus(str, enum.Enum):
    active = "active"
    expired = "expired"
    cancelled = "cancelled"


class ConversationStateType(str, enum.Enum):
    """对话状态类型"""
    lottery_create = "lottery_create"  # 创建抽奖流程
    scheduled_create = "scheduled_create"  # 创建定时消息流程
    auto_reply_create = "auto_reply_create"  # 创建自动回复流程
    banned_word_add = "banned_word_add"  # 添加违禁词流程
    verification_config = "verification_config"  # 验证配置流程
    anti_flood_config = "anti_flood_config"  # 防刷屏配置流程
    anti_spam_config = "anti_spam_config"  # 反垃圾配置流程
    sm_edit_text = "sm_edit_text"  # 编辑定时消息文本
    sm_edit_media = "sm_edit_media"  # 编辑定时消息媒体
    sm_edit_buttons = "sm_edit_buttons"  # 编辑定时消息按钮
    sm_edit_start_at = "sm_edit_start_at"  # 编辑开始时间
    sm_edit_end_at = "sm_edit_end_at"  # 编辑终止时间
    sm_edit_day_start = "sm_edit_day_start"  # 编辑时段开始
    sm_edit_day_end = "sm_edit_day_end"  # 编辑时段结束
    nearby_edit_price = "nearby_edit_price"  # 编辑周边资料价格
    nearby_edit_method = "nearby_edit_method"  # 编辑周边资料方式
    nearby_edit_address = "nearby_edit_address"  # 编辑周边资料备注
    nearby_edit_location = "nearby_edit_location"  # 编辑周边资料定位


class BannedWordMatchType(str, enum.Enum):
    """违禁词匹配类型"""
    exact = "exact"  # 精确匹配
    contains = "contains"  # 包含匹配
    regex = "regex"  # 正则表达式


class AutoReplyMatchType(str, enum.Enum):
    """自动回复匹配类型"""
    exact = "exact"  # 精确匹配
    contains = "contains"  # 包含匹配
    regex = "regex"  # 正则表达式
    starts_with = "starts_with"  # 以...开头
    ends_with = "ends_with"  # 以...结尾


class ScheduleType(str, enum.Enum):
    """定时消息类型"""
    none = "none"  # 一次性消息
    every_minute = "every_minute"  # 每分钟
    every_5_minutes = "every_5_minutes"  # 每5分钟
    every_15_minutes = "every_15_minutes"  # 每15分钟
    every_30_minutes = "every_30_minutes"  # 每30分钟
    every_hour = "every_hour"  # 每小时
    every_6_hours = "every_6_hours"  # 每6小时
    every_12_hours = "every_12_hours"  # 每12小时
    every_day = "every_day"  # 每天
    custom = "custom"  # 自定义间隔


class VerificationMode(str, enum.Enum):
    """验证模式"""
    button = "button"  # 按钮验证
    math = "math"  # 数学题验证
    captcha = "captcha"  # 验证码验证
    admin = "admin"  # 管理员确认（管理员手动审核）


class InviteLinkStatus(str, enum.Enum):
    """邀请链接状态"""
    active = "active"  # 激活
    revoked = "revoked"  # 已撤销
    expired = "expired"  # 已过期


class SolitaireStatus(str, enum.Enum):
    """接龙状态"""
    active = "active"  # 进行中
    closed = "closed"  # 已结束


class LotteryDrawMode(str, enum.Enum):
    """抽奖开奖模式"""
    random = "random"  # 随机开奖
    manual = "manual"  # 手动指定中奖人



