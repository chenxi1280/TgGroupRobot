"""定时任务配置"""

# 任务配置
TASK_CONFIG = {
    "lottery": {
        "interval": 300,  # 5分钟
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
    "message": {
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
}
