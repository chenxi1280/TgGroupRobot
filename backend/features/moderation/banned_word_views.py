from __future__ import annotations

from backend.features.moderation.banned_word_common import get_action_label, get_compact_match_type_label


def build_banned_word_list_text(words, total_triggers: int) -> str:
    text = "📋 违禁词列表\n\n"
    if words:
        active_count = sum(1 for word in words if word.is_active)
        text += f"总计: {len(words)} 条  |  激活: {active_count} 条  |  总触发: {total_triggers} 次\n\n"
        for word in words:
            status = "🟢 激活" if word.is_active else "🔴 暂停"
            notify_label = "📢" if word.notify else "🔇"
            text += f"{status} [{word.id}] {word.word[:30]}\n"
            text += (
                f"   匹配: {get_compact_match_type_label(word.match_type)} | "
                f"处罚: {get_action_label(word.action)} {notify_label}\n\n"
            )
    else:
        text += "暂无违禁词"
    return text
