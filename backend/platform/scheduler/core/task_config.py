"""定时任务配置"""

# 任务配置
TASK_CONFIG = {
    "lottery": {
        "interval": 60,  # 1分钟，保障定时开奖、提前提醒更接近真实时间点
        "enabled": True,
        "max_consecutive_failures": 10,
    },
    "solitaire": {
        "interval": 60,  # 1分钟
        "enabled": True,
        "max_consecutive_failures": 10,
    },
    "ads": {
        "interval": 60,  # 1分钟
        "enabled": True,
        "max_consecutive_failures": 10,
    },
    "cleanup": {
        "interval": 300,  # 5分钟
        "enabled": True,
        "max_consecutive_failures": 10,
    },
    "scheduled_message": {
        "interval": 60,  # 1分钟
        "enabled": True,
        "max_consecutive_failures": 10,
    },
    "group_lock": {
        "interval": 60,  # 每分钟同步一次关群权限
        "enabled": True,
        "max_consecutive_failures": 10,
    },
    "rename_monitor": {
        "interval": 300,  # 每5分钟巡检一批已记录成员资料
        "enabled": True,
        "max_consecutive_failures": 10,
        "max_members_per_chat": 50,
        "max_members_per_run": 200,
        "request_pause_seconds": 0.05,
    },
    "auction": {
        "interval": 30,
        "enabled": True,
        "max_consecutive_failures": 10,
    },
    "bottom_button": {
        "interval": 60,
        "enabled": True,
        "max_consecutive_failures": 10,
    },
    "game": {
        "interval": 60,
        "enabled": True,
        "max_consecutive_failures": 10,
    },
    "guess": {
        "interval": 30,
        "enabled": True,
        "max_consecutive_failures": 10,
    },
    "engagement": {
        "interval": 60,
        "enabled": True,
        "max_consecutive_failures": 10,
    },
    "teacher_search": {
        "interval": 60,
        "enabled": True,
        "max_consecutive_failures": 10,
    },
    "garage_forward_retry": {
        "interval": 120,  # 2分钟，平衡重试及时性与 Telegram 限流
        "enabled": True,
        "max_consecutive_failures": 10,
    },
}
