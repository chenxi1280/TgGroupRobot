from __future__ import annotations

import re

import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from backend.features.automation.services.ad_rotation_service import (
    describe_delete_policy,
    describe_rule_mode,
    format_local_datetime,
    format_interval_seconds_label,
    get_effective_item_count,
    get_or_create_rotation_rule,
    get_rotation_item,
    list_rotation_items,
)
from backend.features.automation.ui.ads import (
    ads_item_detail_keyboard,
    ads_item_time_keyboard,
    ads_manage_keyboard,
    ads_menu_keyboard,
    ads_rules_keyboard,
)
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.automation import AdCampaign
from backend.shared.callback_parser import CallbackParser
from backend.shared.handlers.base.base_handler import BaseHandler
from backend.shared.handlers.base.chat_resolver import ChatResolver
from backend.shared.services.permission_service import PermissionPolicyService
from backend.shared.ui.message_config_panel import (
    PanelField,
    button_status,
    format_completion_lines,
    format_panel,
    media_status,
    summarize_text,
)
from backend.platform.telegram.errors import (
    answer_callback_query_safely,
)

log = structlog.get_logger(__name__)


def _is_clear_input(value: str) -> bool:
    normalized = (value or "").strip().lower()
    return normalized in {"清空", "/clear"} or normalized.startswith("/clear@")


def _extract_int_parts(callback_data: str) -> list[int]:
    values: list[int] = []
    for part in (callback_data or "").split(":"):
        try:
            values.append(int(part))
        except ValueError:
            continue
    return values


async def _resolve_ads_target_chat_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    allow_current_chat_fallback: bool = True,
    error_message: str = "请先选择一个群组",
) -> int | None:
    if update.effective_chat is None or update.effective_user is None:
        return None

    chat = update.effective_chat
    user = update.effective_user
    if chat.type != "private":
        return await _resolve_group_ads_target(update, context, chat_id=chat.id, user_id=user.id)
    return await _resolve_private_ads_target(
        update,
        context,
        user_id=user.id,
        allow_current_chat_fallback=allow_current_chat_fallback,
        error_message=error_message,
    )


async def _resolve_group_ads_target(update: Update, context, *, chat_id: int, user_id: int) -> int | None:
    allowed = await PermissionPolicyService.can_manage(
        context,
        chat_id,
        user_id,
        capability="automation",
    )
    if allowed:
        return chat_id
    await answer_callback_query_safely(update, "你没有该群组的管理权限", show_alert=True)
    return None


async def _resolve_private_ads_target(
    update: Update,
    context,
    *,
    user_id: int,
    allow_current_chat_fallback: bool,
    error_message: str,
) -> int | None:
    candidate_chat_ids = await _private_ads_candidates(
        update,
        context,
        user_id=user_id,
        allow_current_chat_fallback=allow_current_chat_fallback,
    )
    for target_chat_id in candidate_chat_ids:
        allowed = await PermissionPolicyService.can_manage(
            context,
            target_chat_id,
            user_id,
            capability="automation",
        )
        if allowed:
            return target_chat_id
    message = "你没有该群组的管理权限" if candidate_chat_ids else error_message
    await answer_callback_query_safely(update, message, show_alert=True)
    return None


async def _private_ads_candidates(
    update: Update,
    context,
    *,
    user_id: int,
    allow_current_chat_fallback: bool,
) -> list[int]:
    callback_data = update.callback_query.data if update.callback_query else ""
    candidate_chat_ids = [value for value in _extract_int_parts(callback_data or "") if value < 0]
    if allow_current_chat_fallback:
        db: Database = context.application.bot_data["db"]
        current_chat_id = await ChatResolver.get_current_chat(db, user_id)
        if current_chat_id not in (None, 0) and current_chat_id not in candidate_chat_ids:
            candidate_chat_ids.append(current_chat_id)
    return candidate_chat_ids


def _resolve_ads_state_chat_id(update: Update, target_chat_id: int) -> int:
    if update.effective_chat is None:
        return target_chat_id
    return update.effective_chat.id if update.effective_chat.type == "private" else target_chat_id


def _parse_ad_id_from_callback(data: str) -> int:
    cb = CallbackParser.parse(data)
    for index in range(cb.length() - 1, -1, -1):
        value = cb.get_int_optional(index)
        if value is not None and value > 0:
            return value
    match = re.search(r"^ads:(?:detail|toggle|delete|send)_(\d+)$", data)
    if match:
        return int(match.group(1))
    return 0


def _format_ad_push_text(ad: AdCampaign) -> str:
    return (ad.content or "").strip() or ad.title


def _format_ad_detail_text(ad: AdCampaign, rule=None) -> str:
    start_text = format_local_datetime(getattr(ad, "start_time", None), empty="【等待设置】")
    end_text = format_local_datetime(getattr(ad, "end_time", None), empty="【等待设置】")
    if getattr(ad, "end_time", None) is None:
        end_text = "【等待设置】"
    has_content = bool(str(getattr(ad, "content", "") or "").strip())
    has_media = bool(getattr(ad, "image_file_id", None))
    footer = [
        f"⚙️ 状态: {'✅ 启用' if ad.enabled else '❌ 关闭'}",
        f"🔁 轮播顺序: {getattr(ad, 'sort_order', 0)}",
    ]
    if rule is not None:
        footer.append(f"⌛ 发送频率: {format_interval_seconds_label(getattr(rule, 'interval_seconds', 7200))}")
        footer.append(f"📌 轮播方式: {describe_rule_mode(rule)}")
        footer.append(f"🧹 删除规则: {describe_delete_policy(rule)}")
    footer.extend(
        format_completion_lines(
            [("文本或封面", has_content or has_media)],
            next_step="预览效果 → 启用",
            test_step="到目标群确认轮播发送结果",
        )
    )

    return format_panel(
        "🎠 轮播消息",
        [
            PanelField("📮", "标题备注", summarize_text(getattr(ad, "title", None), limit=80)),
            PanelField("🏞️", "封面设置", media_status(has_media=has_media)),
            PanelField("📄", "文本内容", summarize_text(getattr(ad, "content", None), limit=180)),
            PanelField("⭕", "设置按钮", button_status(getattr(ad, "buttons", None))),
            PanelField("⏰", "开始时间", start_text),
            PanelField("⏰", "结束时间", end_text),
        ],
        footer=footer,
    )


def _render_ads_home_text(rule, items: list[AdCampaign]) -> str:
    enabled_text = "✅ 启用" if rule.enabled else "❌ 关闭"
    return (
        "本功能可以实现设置多个内容，按固定间隔时间一个一个发送到群里并置顶。\n\n"
        f"┗轮播状态: {enabled_text}\n"
        f"┗起始时间: {format_local_datetime(rule.start_at)}\n"
        f"┗上次轮播: {format_local_datetime(rule.last_sent_at)}\n"
        f"┗下次轮播: {format_local_datetime(rule.next_run_at)}\n"
        f"┗轮播间隔: {format_interval_seconds_label(getattr(rule, 'interval_seconds', 7200))}\n"
        f"┗轮播方式: {describe_rule_mode(rule)}\n"
        f"┗删除规则: {describe_delete_policy(rule)}\n"
        f"┗取消上一条轮播置顶: {'✅ 启用' if rule.unpin_previous else '❌ 关闭'}\n"
        f"┗当前生效的轮播条数: {get_effective_item_count(items)}"
    )


def _render_rules_text(rule) -> str:
    delay_hint = ""
    if rule.delete_policy == "delete_delay":
        delay_hint = f"\n当前延迟删除: {int(rule.delete_delay_seconds or 60)} 秒"
    return (
        "🎠 轮播规则配置\n\n"
        "删除规则：\n"
        "┝举例：1>2>3>1（发送消息顺序）\n"
        "┝删上条: 当前是发送1，删除3\n"
        "┝删上轮: 当前是发送1，删除上一个1\n"
        "┝延迟删: 每条消息延迟删除\n"
        "┗不删: 所有消息不删除，可取消置顶"
        f"{delay_hint}"
    )


def _render_manage_text(items: list[AdCampaign], page: int) -> str:
    total = len(items)
    total_pages = max((total - 1) // 1 + 1, 1)
    if not items:
        return (
            "🎠 轮播消息\n\n"
            "按照顺序和间隔时间发送启用的消息，可用于设置广告/赞助等内容。\n\n"
            f"0 条数据，第 1 页/共 {total_pages} 页"
        )

    page = max(0, min(page, total_pages - 1))
    item = items[page]
    end_time = format_local_datetime(item.end_time, empty="永久") if item.end_time else "永久"
    last_sent = format_local_datetime(item.last_sent_at, empty="未发送")
    return (
        "🎠 轮播消息\n\n"
        "按照顺序和间隔时间发送启用的消息，可用于设置广告/赞助等内容。\n\n"
        f"标题：{item.title}（{'✅ 启用' if item.enabled else '❌ 关闭'}）\n"
        f"┝结束时间: {end_time}\n"
        f"┝上次发送: {last_sent}\n"
        f"┗顺序: {item.sort_order}\n\n"
        f"{total} 条数据，第 {page + 1} 页/共 {total_pages} 页"
    )


class AdsHandler(BaseHandler):
    def __init__(self) -> None:
        super().__init__()
        self._require_admin_permission = False

    async def process(self, update: Update, context: ContextTypes.DEFAULT_TYPE, target_chat_id: int) -> None:
        return None

    async def show_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE, target_chat_id: int) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            rule = await get_or_create_rotation_rule(session, target_chat_id)
            items = await list_rotation_items(session, target_chat_id)
            await session.commit()
        await self.message_helper.safe_edit(
            update,
            text=_render_ads_home_text(rule, items),
            reply_markup=ads_menu_keyboard(target_chat_id),
        )

    async def show_rules(self, update: Update, context: ContextTypes.DEFAULT_TYPE, target_chat_id: int) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            rule = await get_or_create_rotation_rule(session, target_chat_id)
            await session.commit()
        await self.message_helper.safe_edit(
            update,
            text=_render_rules_text(rule),
            reply_markup=ads_rules_keyboard(target_chat_id, rule),
        )

    async def show_list(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        *, page: int = 0,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            items = await list_rotation_items(session, target_chat_id)
            await session.commit()

        if not items:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ 添加一条", callback_data=f"ads:create:{target_chat_id}")],
                [InlineKeyboardButton("🔙 返回", callback_data=f"ads:menu:{target_chat_id}")],
            ])
            await self.message_helper.safe_edit(update, text=_render_manage_text(items, 0), reply_markup=keyboard)
            return

        total_pages = max((len(items) - 1) // 1 + 1, 1)
        current_page = max(0, min(page, total_pages - 1))
        current_item = items[current_page]
        await self.message_helper.safe_edit(
            update,
            text=_render_manage_text(items, current_page),
            reply_markup=ads_manage_keyboard(target_chat_id, current_item, page=current_page, total_pages=total_pages),
        )

    async def show_detail(self, update: Update, context: ContextTypes.DEFAULT_TYPE, target_chat_id: int, *, item_id: int) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            item = await get_rotation_item(session, item_id)
            rule = await get_or_create_rotation_rule(session, target_chat_id)
            await session.commit()
        if item is None or item.chat_id != target_chat_id:
            await self.message_helper.safe_edit(update, text="轮播消息不存在", reply_markup=ads_menu_keyboard(target_chat_id))
            return
        await self.message_helper.safe_edit(
            update,
            text=_format_ad_detail_text(item, rule),
            reply_markup=ads_item_detail_keyboard(target_chat_id, item, rule),
        )

    async def show_time_range(self, update: Update, context: ContextTypes.DEFAULT_TYPE, target_chat_id: int, *, item_id: int) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            item = await get_rotation_item(session, item_id)
            await session.commit()
        if item is None or item.chat_id != target_chat_id:
            await self.message_helper.safe_edit(update, text="轮播消息不存在", reply_markup=ads_menu_keyboard(target_chat_id))
            return
        text = (
            "🎠 轮播消息 | 编辑时间范围\n\n"
            f"开始时间：{format_local_datetime(item.start_time, empty='立刻生效')}\n"
            f"结束时间：{format_local_datetime(item.end_time, empty='一直生效')}\n\n"
            "💡 可不设置开始/结束时间，即为立刻启动一直有效！\n"
            "💡 如果没设置开始时间，重复间隔时间从第一次启动任务开始算起！"
        )
        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=ads_item_time_keyboard(target_chat_id, item_id),
        )


_ads_handler = AdsHandler()
