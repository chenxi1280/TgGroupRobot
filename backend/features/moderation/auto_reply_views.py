from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.features.moderation.auto_reply_common import get_match_type_label
from backend.features.moderation.services.auto_reply_service import (
    get_auto_reply_rule_in_chat,
    get_chat_auto_reply_rules,
    get_match_count,
)
from backend.platform.db.runtime.session import Database


def format_auto_reply_rule_detail(rule) -> str:
    status = "🟢 启用" if rule.is_active else "🔴 停用"
    delete_source = "删除" if getattr(rule, "delete_source", False) else "保留"
    delete_delay = getattr(rule, "delete_reply_delay_seconds", 0)
    match_type_label = get_match_type_label(rule.match_type)
    keywords = ", ".join(rule.keywords)
    cover_label = "未设置"
    if getattr(rule, "cover_media_file_id", None):
        cover_type = getattr(rule, "cover_media_type", None) or "media"
        cover_label = f"已设置（{cover_type}）"
    button_rows = getattr(rule, "buttons", None) or []
    button_count = sum(len(row) for row in button_rows if isinstance(row, list))
    return "\n".join(
        [
            f"💬 自动回复规则 #{rule.sort_order}",
            "",
            f"ID: {rule.id}",
            f"状态: {status}",
            f"匹配方式: {match_type_label}",
            f"区分大小写: {'是' if rule.case_sensitive else '否'}",
            f"命中后停止继续匹配: {'是' if getattr(rule, 'stop_after_match', True) else '否'}",
            f"删除触发源: {delete_source}",
            f"回复延迟删除: {delete_delay} 秒" if delete_delay else "回复延迟删除: 不删除",
            f"命中次数: {rule.match_count}",
            f"封面: {cover_label}",
            f"按钮: {button_count} 个",
            "",
            f"关键词: {keywords}",
            "",
            "回复内容:",
            rule.reply_content,
        ]
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
    if len(parts) < 4:
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
        total_matches = await get_match_count(session, target_chat_id)
        await session.commit()

    page_size = 8
    total_count = len(rules)
    total_pages = max(1, (total_count + page_size - 1) // page_size)
    current_page = min(max(page, 0), total_pages - 1)
    page_rules = rules[current_page * page_size:(current_page + 1) * page_size]

    text = "📋 自动回复规则列表\n\n"
    if rules:
        active_count = sum(1 for rule in rules if rule.is_active)
        text += (
            f"总计: {len(rules)} 条  |  激活: {active_count} 条  |  总匹配: {total_matches} 次\n"
            f"页码: 第 {current_page + 1} 页/共 {total_pages} 页\n\n"
        )
        for rule in page_rules:
            status = "🟢 激活" if rule.is_active else "🔴 暂停"
            keywords_display = ", ".join(rule.keywords[:3]) + ("..." if len(rule.keywords) > 3 else "")
            delete_source = "删源" if getattr(rule, "delete_source", False) else "留源"
            delete_delay = getattr(rule, "delete_reply_delay_seconds", 0)
            delay_label = f"{delete_delay}s删回复" if delete_delay else "不删回复"
            cover_label = "有封面" if getattr(rule, "cover_media_file_id", None) else "无封面"
            button_count = sum(len(row) for row in (getattr(rule, "buttons", None) or []) if isinstance(row, list))
            stop_label = "命中即停" if getattr(rule, "stop_after_match", True) else "继续匹配"
            text += f"{status} #{rule.sort_order} [{rule.id}] {keywords_display}\n"
            text += (
                f"   匹配: {get_match_type_label(rule.match_type)} | {stop_label}\n"
                f"   行为: {delete_source} | {delay_label}\n"
                f"   展示: {cover_label} | 按钮 {button_count} 个\n"
                f"   回复: {rule.reply_content[:30]}{'...' if len(rule.reply_content) > 30 else ''}\n\n"
            )
    else:
        text += "0 条数据，第 1 页/共 1 页\n\n暂无自动回复规则"

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
