from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.features.moderation.auto_reply_common import get_match_type_label
from backend.features.moderation.services.auto_reply_service import (
    get_auto_reply_rule_in_chat,
    get_chat_auto_reply_rules,
)
from backend.platform.db.runtime.session import Database
from backend.shared.ui.message_config_panel import (
    PanelField,
    button_status,
    format_completion_lines,
    format_panel,
    media_status,
    summarize_text,
)
_EXTRACT_AUTO_REPLY_LIST_PAGE_THRESHOLD_4 = 4



def _format_keywords(keywords: list[str] | None) -> str:
    values = [str(item).strip() for item in (keywords or []) if str(item).strip()]
    return "、".join(values) if values else "待配置"


def _format_match_short(match_type: str | None) -> str:
    return {
        "exact": "等于",
        "contains": "包含",
    }.get(match_type or "", get_match_type_label(match_type or ""))


def _format_cover_status(rule) -> str:
    return media_status(has_media=bool(getattr(rule, "cover_media_file_id", None)))


def _format_delay_status(rule) -> str:
    delay = int(getattr(rule, "delete_reply_delay_seconds", 0) or 0)
    return f"{delay}秒后删除" if delay else "不删除"


def format_auto_reply_rule_detail(rule, *, toast: str | None = None) -> str:
    has_keywords = bool(getattr(rule, "keywords", None))
    has_content = bool(str(getattr(rule, "reply_content", "") or "").strip())
    return format_panel(
        "💬 自动回复",
        [
            PanelField("📸", "关键词", f"【{_format_keywords(getattr(rule, 'keywords', None))}】"),
            PanelField("🏞️", "封面设置", _format_cover_status(rule)),
            PanelField("📄", "文本内容", summarize_text(getattr(rule, "reply_content", ""), limit=180)),
            PanelField("⭕", "设置按钮", button_status(getattr(rule, "buttons", None))),
        ],
        footer=[
            f"⚙️ 状态: {'✅ 启用' if rule.is_active else '❌ 关闭'}",
            f"🎯 匹配: {_format_match_short(getattr(rule, 'match_type', ''))}",
            f"🧹 删除来源: {'删除' if getattr(rule, 'delete_source', False) else '保留'}",
            f"🕘 延迟删除: {_format_delay_status(rule)}",
            f"🔁 顺序: {getattr(rule, 'sort_order', 0)}",
        ] + format_completion_lines(
            [("关键词", has_keywords), ("回复文本", has_content)],
            next_step="预览效果 → 启用",
            test_step="到目标群发送关键词确认触发结果",
        ),
        toast=toast,
    )


async def show_auto_reply_rule_detail(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    rule_id: int,
) -> None:
    from backend.features.moderation.ui.auto_reply import auto_reply_detail_keyboard

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        rule = await get_auto_reply_rule_in_chat(session, chat_id, rule_id)
        await session.commit()

    if rule is None or rule.chat_id != chat_id:
        if update.callback_query is not None:
            await update.callback_query.edit_message_text("规则不存在")
        return

    if update.callback_query is not None:
        await update.callback_query.edit_message_text(
            format_auto_reply_rule_detail(rule),
            reply_markup=auto_reply_detail_keyboard(rule, chat_id),
        )


def extract_auto_reply_list_page(callback_data: str | None) -> int:
    if not callback_data or not callback_data.startswith("auto_reply:list"):
        return 0
    parts = callback_data.split(":")
    if len(parts) < _EXTRACT_AUTO_REPLY_LIST_PAGE_THRESHOLD_4:
        return 0
    try:
        return max(int(parts[3]), 0)
    except ValueError:
        return 0


async def render_auto_reply_list(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    target_chat_id: int,
    page: int = 0,
) -> None:
    if update.callback_query is None:
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        rules = await get_chat_auto_reply_rules(session, target_chat_id)
        await session.commit()

    page_size = 8
    total_count = len(rules)
    total_pages = max(1, (total_count + page_size - 1) // page_size)
    current_page = min(max(page, 0), total_pages - 1)
    page_rules = rules[current_page * page_size:(current_page + 1) * page_size]

    text = "💬 自动回复\n\n可用于设置 导航/赞助等自动回复内容。\n\n"
    if rules:
        for rule in page_rules:
            status = "✅ 启用" if rule.is_active else "❌ 关闭"
            text += f"关键词： {_format_keywords(getattr(rule, 'keywords', None))} （状态: {status}）\n"
            text += f"┝匹配: {_format_match_short(getattr(rule, 'match_type', ''))}\n"
            text += f"┗顺序: {getattr(rule, 'sort_order', 0)}\n\n"

    text += f"{total_count} 条数据，第 {current_page + 1} 页/共 {total_pages} 页"

    from backend.features.moderation.ui.auto_reply import auto_reply_list_keyboard

    await update.callback_query.edit_message_text(
        text,
        reply_markup=auto_reply_list_keyboard(
            rules,
            target_chat_id,
            page=current_page,
            page_size=page_size,
            total_count=total_count,
        ),
    )


async def show_auto_reply_delay_page(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    rule_id: int,
) -> None:
    from backend.features.moderation.ui.auto_reply import auto_reply_delay_keyboard

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        rule = await get_auto_reply_rule_in_chat(session, chat_id, rule_id)
        await session.commit()

    if rule is None or rule.chat_id != chat_id:
        if update.callback_query is not None:
            await update.callback_query.edit_message_text("规则不存在")
        return

    text = "\n".join(
        [
            "💬 自动回复 | 延迟删除消息",
            "",
            "延时自动删除回复的消息",
            "",
            "👇 请选择下面的按钮",
        ]
    )
    if update.callback_query is not None:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=auto_reply_delay_keyboard(rule, chat_id),
        )
