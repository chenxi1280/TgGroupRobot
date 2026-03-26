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


class ControlPermissionPolicy(str, enum.Enum):
    """机器人管理权限门槛"""
    all_admins = "all_admins"
    can_restrict_members = "can_restrict_members"
    can_change_info = "can_change_info"
    can_promote_members = "can_promote_members"
    owner_only = "owner_only"


class GroupLockDeleteNoticeMode(str, enum.Enum):
    """关群通知消息处理方式"""
    delete = "delete"
    keep = "keep"


class ForceSubscribeCheckMode(str, enum.Enum):
    """强制订阅校验策略"""
    all = "all"
    any = "any"


class ForceSubscribeAction(str, enum.Enum):
    """未订阅时处理动作"""
    delete_and_warn = "delete_and_warn"
    delete_only = "delete_only"
    warn_only = "warn_only"
    mute = "mute"


class WelcomeMode(str, enum.Enum):
    on_join = "on_join"
    after_verify = "after_verify"


class WelcomeDeleteMode(str, enum.Enum):
    seconds = "seconds"
    delete_prev = "delete_prev"
    keep = "keep"


class ConversationStateType(str, enum.Enum):
    """对话状态类型"""
    lottery_create = "lottery_create"  # 创建抽奖流程
    scheduled_create = "scheduled_create"  # 创建定时消息流程
    auto_reply_create = "auto_reply_create"  # 创建自动回复流程
    banned_word_add = "banned_word_add"  # 添加违禁词流程
    verification_config = "verification_config"  # 验证配置流程
    anti_flood_config = "anti_flood_config"  # 防刷屏配置流程
    anti_spam_config = "anti_spam_config"  # 反垃圾配置流程
    renewal_card_input = "renewal_card_input"  # 续费卡密输入流程
    force_subscribe_channel_1_input = "force_subscribe_channel_1_input"  # 强制订阅频道1
    force_subscribe_channel_2_input = "force_subscribe_channel_2_input"  # 强制订阅频道2
    force_subscribe_text_input = "force_subscribe_text_input"  # 强制订阅文案
    force_subscribe_cover_input = "force_subscribe_cover_input"  # 强制订阅封面
    force_subscribe_buttons_input = "force_subscribe_buttons_input"  # 强制订阅按钮
    group_lock_open_keyword_input = "group_lock_open_keyword_input"  # 关群开群词
    group_lock_close_keyword_input = "group_lock_close_keyword_input"  # 关群关群词
    group_lock_open_time_input = "group_lock_open_time_input"  # 开群时间
    group_lock_close_time_input = "group_lock_close_time_input"  # 关群时间
    rename_monitor_text_input = "rename_monitor_text_input"  # 改名监控文案
    welcome_title_input = "welcome_title_input"  # 欢迎标题
    welcome_text_input = "welcome_text_input"  # 欢迎文本
    welcome_cover_input = "welcome_cover_input"  # 欢迎封面
    welcome_buttons_input = "welcome_buttons_input"  # 欢迎按钮
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
    control_permission_config = "control_permission_config"  # 控制权限配置流程
    group_lock_config = "group_lock_config"  # 关群设置配置流程
    name_change_monitor_config = "name_change_monitor_config"  # 改名监控配置流程
    force_subscribe_config = "force_subscribe_config"  # 强制订阅配置流程
    alliance_create_name_input = "alliance_create_name_input"  # 联盟名称输入
    alliance_join_code_input = "alliance_join_code_input"  # 联盟邀请码输入
    garage_forward_source_input = "garage_forward_source_input"  # 车库转发来源频道输入
    garage_forward_keyword_input = "garage_forward_keyword_input"  # 车库转发关键词输入
    garage_badge_input = "garage_badge_input"  # 车库认证图标输入
    garage_teacher_input = "garage_teacher_input"  # 手动认证老师输入
    garage_whitelist_input = "garage_whitelist_input"  # 车库发言白名单输入
    garage_limit_interval_input = "garage_limit_interval_input"  # 车库限制间隔输入
    garage_limit_max_count_input = "garage_limit_max_count_input"  # 车库限制次数输入
    teacher_search_delegate_target_input = "teacher_search_delegate_target_input"  # 老师搜索代录目标
    teacher_search_delegate_location_input = "teacher_search_delegate_location_input"  # 老师搜索代录定位
    car_review_submit_command_input = "car_review_submit_command_input"  # 车评提交指令
    car_review_rank_command_input = "car_review_rank_command_input"  # 车评排行指令
    car_review_approver_input = "car_review_approver_input"  # 车评审核人
    car_review_template_input = "car_review_template_input"  # 车评模板
    car_review_reward_points_input = "car_review_reward_points_input"  # 车评奖励积分


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
