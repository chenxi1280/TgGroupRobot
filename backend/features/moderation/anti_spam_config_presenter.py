from __future__ import annotations

from backend.features.moderation.services.anti_spam_service import get_antispam_rules
from backend.platform.db.schema.models.core import ChatSettings


def format_anti_spam_menu_text(chat_title: str, settings: ChatSettings) -> str:
    rules = get_antispam_rules(settings)
    status = "开启" if settings.anti_spam_enabled else "关闭"
    notify = "开启" if settings.anti_spam_delete_notify else "关闭"
    admin_exempt = "开启" if settings.anti_spam_exempt_admin else "关闭"
    enabled_rule_count = sum(1 for value in rules.values() if isinstance(value, bool) and value)

    def s(key: str) -> str:
        return "开启" if bool(rules.get(key)) else "关闭"

    text = f"🚫 [{chat_title}] 反垃圾\n\n"
    text += "当前为集中配置页，可统一管理常见广告、链接、转发、超长内容和黑名单规则。\n\n"
    text += f"总开关: {status}\n"
    text += f"惩罚动作: {settings.anti_spam_action}\n"
    text += f"禁言时长: {settings.anti_spam_mute_duration} 秒\n"
    text += f"管理员豁免: {admin_exempt}\n"
    text += f"删除提醒: {notify} ({settings.anti_spam_delete_notify_seconds} 秒)\n"
    text += f"反洪水阈值: {settings.anti_spam_repeat_seconds} 秒内 {settings.anti_spam_repeat_messages} 条\n\n"
    text += f"已启用规则: {enabled_rule_count} 项\n\n"

    text += "AI 屏蔽垃圾消息: " + s("ai_text") + "\n"
    text += "全网拦截广告: " + s("global_ads") + "\n"
    text += "反洪水攻击: " + s("flood_attack") + "\n"
    text += "屏蔽被封禁账号: " + s("banned_accounts") + "\n"
    text += "AI 屏蔽图片广告: " + s("ai_image_ads") + "\n"
    text += "屏蔽链接: " + s("block_links") + "\n"
    text += "屏蔽频道马甲发言: " + s("block_channel_alias") + "\n"
    text += "屏蔽来自频道/用户转发: " + s("block_forwards") + "\n"
    text += "屏蔽 @群组/@用户 ID: " + s("block_mentions") + "\n"
    text += "屏蔽以太坊地址: " + s("block_eth_address") + "\n"
    text += "清除命令消息: " + s("clear_commands") + "\n"
    text += "屏蔽超长消息/姓名: " + s("block_long_content") + "\n"
    text += f"超长阈值: 消息{rules['message_max_length']} 字, 姓名{rules['name_max_length']} 字\n"
    text += f"例外用户: {len(rules['exception_user_ids'])} 个, 例外群组: {len(rules['exception_chat_ids'])} 个\n\n"
    text += "💡 可用按钮快速切换，也可点“文本配置”一次性设置"
    return text


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
