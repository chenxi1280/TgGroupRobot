from __future__ import annotations

import asyncio
import json
import structlog

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes


log = structlog.get_logger(__name__)

from backend.platform.db.runtime.session import Database
from backend.shared.handlers.base.base_handler import BaseHandler
from backend.shared.handlers.base.chat_resolver import ChatResolver
from backend.platform.db.schema.models.enums import AutoReplyMatchType, ConversationStateType
from backend.features.moderation.services.auto_reply_service import (
    create_auto_reply_rule,
    delete_auto_reply_rule,
    get_auto_reply_rule,
    get_auto_reply_rule_in_chat,
    get_chat_auto_reply_rules,
    get_match_count,
    match_auto_reply,
    move_auto_reply_rule,
    toggle_auto_reply_rule,
    update_auto_reply_rule,
    CreateResult,
)
from backend.shared.services.chat_service import ensure_chat, get_chat_settings
from backend.features.automation.services.scheduled_message_service import ScheduledMessageService
from backend.platform.state.state_service import clear_user_state, get_user_state, set_user_state
from backend.shared.services.permission_service import is_user_admin
from backend.shared.services.user_service import ensure_user
from backend.shared.chat_context import PrivateChatContext

def _ensure_callback_update(update: Update) -> bool:
    """
    确保 Update 包含回调所需的所有字段

    Args:
        update: Telegram Update 对象

    Returns:
        bool: 如果包含所有必需字段则返回 True
    """
    return not (
        update.callback_query is None
        or update.effective_chat is None
        or update.effective_user is None
    )


def _ensure_message_update(update: Update, require_user: bool = True) -> bool:
    """
    确保 Update 包含消息所需的所有字段

    Args:
        update: Telegram Update 对象
        require_user: 是否要求用户字段

    Returns:
        bool: 如果包含所有必需字段则返回 True
    """
    if update.effective_chat is None or update.effective_message is None:
        return False
    if require_user and update.effective_user is None:
        return False
    return True


async def _resolve_auto_reply_target_chat_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_index: int = 2,
) -> int | None:
    """统一解析自动回复管理目标群组。"""
    return await PrivateChatContext.resolve_target_chat_with_permission_check(
        update,
        context,
        chat_index=chat_index,
    )


def _format_auto_reply_rule_detail(rule) -> str:
    status = "🟢 启用" if rule.is_active else "🔴 停用"
    delete_source = "删除" if getattr(rule, "delete_source", False) else "保留"
    delete_delay = getattr(rule, "delete_reply_delay_seconds", 0)
    match_type_label = _get_match_type_label(rule.match_type)
    keywords = ", ".join(rule.keywords)
    cover_label = "未设置"
    if getattr(rule, "cover_media_file_id", None):
        cover_type = getattr(rule, "cover_media_type", None) or "media"
        cover_label = f"已设置（{cover_type}）"
    button_rows = getattr(rule, "buttons", None) or []
    button_count = sum(len(row) for row in button_rows if isinstance(row, list))
    return "\n".join([
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
    ])


def _parse_auto_reply_buttons_input(raw_text: str) -> list[list[dict[str, str]]]:
    raw = raw_text.strip()
    if not raw:
        raise ValueError("按钮配置不能为空。")

    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"按钮 JSON 格式错误：{exc.msg}") from exc
        return ScheduledMessageService.normalize_buttons_config(parsed)

    rows: list[list[dict[str, str]]] = []
    for line in [item.strip() for item in raw.splitlines() if item.strip()]:
        if "|" not in line:
            raise ValueError("文本格式错误：每行必须包含“按钮文案|URL”。")
        button_text, button_url = [part.strip() for part in line.split("|", 1)]
        if not button_text or not button_url:
            raise ValueError("按钮文案和 URL 不能为空。")
        rows.append([{"text": button_text[:32], "url": button_url}])
    if not rows:
        raise ValueError("未解析到有效按钮。")
    return ScheduledMessageService.normalize_buttons_config(rows)


def _build_auto_reply_markup(rule) -> InlineKeyboardMarkup | None:
    raw_buttons = getattr(rule, "buttons", None) or []
    if not raw_buttons:
        return None
    try:
        normalized = ScheduledMessageService.normalize_buttons_config(raw_buttons)
    except Exception:
        return None

    keyboard_rows: list[list[InlineKeyboardButton]] = []
    for row in normalized:
        button_row: list[InlineKeyboardButton] = []
        for item in row:
            text = str(item.get("text") or "").strip()
            url = str(item.get("url") or "").strip()
            callback_data = str(item.get("callback_data") or "").strip()
            if text and url:
                button_row.append(InlineKeyboardButton(text, url=url))
            elif text and callback_data:
                button_row.append(InlineKeyboardButton(text, callback_data=callback_data))
        if button_row:
            keyboard_rows.append(button_row)
    return InlineKeyboardMarkup(keyboard_rows) if keyboard_rows else None


async def _send_auto_reply_payload(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    text: str,
    rule,
    reply_to_message_id: int | None = None,
) -> object:
    reply_markup = _build_auto_reply_markup(rule)
    cover_type = getattr(rule, "cover_media_type", None)
    cover_file_id = getattr(rule, "cover_media_file_id", None)
    if cover_type == "photo" and cover_file_id:
        return await context.bot.send_photo(
            chat_id=chat_id,
            photo=cover_file_id,
            caption=text,
            reply_markup=reply_markup,
            reply_to_message_id=reply_to_message_id,
        )
    if cover_type == "video" and cover_file_id:
        return await context.bot.send_video(
            chat_id=chat_id,
            video=cover_file_id,
            caption=text,
            reply_markup=reply_markup,
            reply_to_message_id=reply_to_message_id,
        )
    return await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=reply_markup,
        reply_to_message_id=reply_to_message_id,
    )


async def _show_auto_reply_rule_detail(
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

    text = _format_auto_reply_rule_detail(rule)
    if update.callback_query is not None:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=auto_reply_detail_keyboard(rule, chat_id),
        )


def _extract_auto_reply_list_page(callback_data: str | None) -> int:
    if not callback_data or not callback_data.startswith("auto_reply:list"):
        return 0
    parts = callback_data.split(":")
    if len(parts) < 4:
        return 0
    try:
        return max(int(parts[3]), 0)
    except ValueError:
        return 0


async def _render_auto_reply_list(
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
    start_idx = current_page * page_size
    page_rules = rules[start_idx:start_idx + page_size]

    text = "📋 自动回复规则列表\n\n"
    if rules:
        active_count = sum(1 for r in rules if r.is_active)
        text += (
            f"总计: {len(rules)} 条  |  激活: {active_count} 条  |  总匹配: {total_matches} 次\n"
            f"页码: 第 {current_page + 1} 页/共 {total_pages} 页\n\n"
        )

        for r in page_rules:
            status = "🟢 激活" if r.is_active else "🔴 暂停"
            match_type_label = _get_match_type_label(r.match_type)
            keywords_display = ", ".join(r.keywords[:3]) + ("..." if len(r.keywords) > 3 else "")
            delete_source = "删源" if getattr(r, "delete_source", False) else "留源"
            delete_delay = getattr(r, "delete_reply_delay_seconds", 0)
            delay_label = f"{delete_delay}s删回复" if delete_delay else "不删回复"
            cover_label = "有封面" if getattr(r, "cover_media_file_id", None) else "无封面"
            button_count = sum(len(row) for row in (getattr(r, "buttons", None) or []) if isinstance(row, list))
            stop_label = "命中即停" if getattr(r, "stop_after_match", True) else "继续匹配"
            text += f"{status} #{r.sort_order} [{r.id}] {keywords_display}\n"
            text += (
                f"   匹配: {match_type_label} | {stop_label}\n"
                f"   行为: {delete_source} | {delay_label}\n"
                f"   展示: {cover_label} | 按钮 {button_count} 个\n"
                f"   回复: {r.reply_content[:30]}{'...' if len(r.reply_content) > 30 else ''}\n\n"
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


# ============================================
# 回调处理器
# ============================================

# Handler 类定义（使用 BaseHandler）

def _get_match_type_label(match_type: str) -> str:
    """获取匹配类型标签"""
    labels = {
        "exact": "精确匹配",
        "contains": "包含匹配",
        "starts_with": "开头匹配",
        "ends_with": "结尾匹配",
        "regex": "正则表达式",
    }
    return labels.get(match_type, match_type)
