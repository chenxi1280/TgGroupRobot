from __future__ import annotations

from backend.features.admin.ui.antispam import format_garbage_guard_home_text
from backend.platform.db.schema.models.core import ChatSettings


def format_anti_spam_menu_text(chat_title: str, settings: ChatSettings) -> str:
    return format_garbage_guard_home_text(chat_title, settings)


def anti_spam_config_prompt_text() -> str:
    return (
        "🚫 反垃圾文本配置 ( /cancel 取消 )\n\n"
        "支持按键值配置，示例：\n\n"
        "状态: 开启\n"
        "惩罚动作: mute\n"
        "禁言时长: 3600\n"
        "管理员豁免: 开启\n"
        "删除提醒: 开启\n"
        "删除提醒时长: 600\n"
        "反洪水条数: 3\n"
        "反洪水间隔: 15\n"
        "AI屏蔽垃圾消息: 开启\n"
        "全网拦截广告: 开启\n"
        "反洪水攻击: 开启\n"
        "屏蔽被封禁账号: 开启\n"
        "AI屏蔽图片广告: 开启\n"
        "屏蔽链接: 开启\n"
        "屏蔽频道马甲发言: 开启\n"
        "屏蔽来自频道/用户转发: 开启\n"
        "屏蔽@群组ID/@用户ID: 开启\n"
        "屏蔽以太坊地址: 开启\n"
        "清除命令消息: 开启\n"
        "屏蔽超长消息/姓名: 开启\n"
        "消息最大长度: 500\n"
        "姓名最大长度: 32\n"
        "例外用户ID: 12345,67890\n"
        "例外群组ID: -100111,-100222\n"
        "封禁账号名单: 111,222\n"
        "屏蔽转发来源频道ID: -100333\n"
        "屏蔽转发来源用户ID: 999\n"
        "屏蔽@对象ID: 555\n"
        "链接黑名单: scam.com,bad.site"
    )
