from __future__ import annotations

import datetime as dt
import re

import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from backend.features.automation.ads_parsing import _parse_ads_config
from backend.features.automation.services.ad_rotation_service import (
    UNSET,
    ValidationError,
    cleanup_expired_rotation_items,
    create_rotation_item,
    describe_delete_policy,
    describe_rule_mode,
    format_local_datetime,
    format_interval_seconds_label,
    get_effective_item_count,
    get_or_create_rotation_rule,
    get_rotation_item,
    list_rotation_items,
    parse_datetime_text,
    parse_delay_seconds_text,
    parse_interval_hours_text,
    preview_rotation_item,
    update_rotation_item,
    update_rotation_rule,
)
from backend.features.automation.ui.ads import (
    ads_copy_time_keyboard,
    ads_item_detail_keyboard,
    ads_item_time_keyboard,
    ads_manage_keyboard,
    ads_menu_keyboard,
    ads_rules_interval_keyboard,
    ads_rules_keyboard,
)
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.automation import AdCampaign
from backend.platform.state.conversation_state_service import ConversationStateService
from backend.shared.callback_parser import CallbackParser
from backend.shared.handlers.base.base_handler import BaseHandler
from backend.shared.handlers.base.chat_resolver import ChatResolver
from backend.shared.button_layout_editor import ButtonEditorContext, show_layout_menu
from backend.shared.time_ui import build_datetime_prompt_text, next_top_of_hour
from backend.shared.services.chat_service import ensure_chat, get_chat_settings
from backend.shared.services.module_settings_service import ModuleSettingsService
from backend.shared.services.permission_service import PermissionPolicyService
from backend.shared.services.publish_service import PublishService
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
    mark_callback_query_answered,
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
        allowed = await PermissionPolicyService.can_manage(context, chat.id, user.id, capability="automation")
        if not allowed:
            await answer_callback_query_safely(update, "你没有该群组的管理权限", show_alert=True)
            return None
        return chat.id

    callback_data = update.callback_query.data if update.callback_query and update.callback_query.data else ""
    candidate_chat_ids = [value for value in _extract_int_parts(callback_data) if value < 0]

    if allow_current_chat_fallback:
        db: Database = context.application.bot_data["db"]
        current_chat_id = await ChatResolver.get_current_chat(db, user.id)
        if current_chat_id not in (None, 0) and current_chat_id not in candidate_chat_ids:
            candidate_chat_ids.append(current_chat_id)

    for target_chat_id in candidate_chat_ids:
        allowed = await PermissionPolicyService.can_manage(context, target_chat_id, user.id, capability="automation")
        if allowed:
            return target_chat_id

    if candidate_chat_ids:
        await answer_callback_query_safely(update, "你没有该群组的管理权限", show_alert=True)
    else:
        await answer_callback_query_safely(update, error_message, show_alert=True)
    return None


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
        page: int = 0,
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

    async def show_detail(self, update: Update, context: ContextTypes.DEFAULT_TYPE, target_chat_id: int, item_id: int) -> None:
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

    async def show_time_range(self, update: Update, context: ContextTypes.DEFAULT_TYPE, target_chat_id: int, item_id: int) -> None:
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


async def ad_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return
    chat = update.effective_chat
    if chat.type == "private":
        await update.effective_message.reply_text("请在群里使用 /ad。")
        return
    if not await PermissionPolicyService.can_manage(context, chat.id, update.effective_user.id, capability="automation"):
        await update.effective_message.reply_text("需要管理员权限。")
        return

    text = (update.effective_message.text or "").strip()
    if text == "/ad" or text.startswith("/ad@") or len(text.split(maxsplit=1)) == 1:
        await update.effective_message.reply_text("用法：/ad 标题|内容\n示例：/ad 置顶活动|今晚 8 点直播，欢迎参加")
        return

    payload = text.split(maxsplit=1)[1]
    if "|" in payload:
        title, content = payload.split("|", 1)
    else:
        title, content = "广告", payload
    title = title.strip()[:120]
    content = content.strip()
    if not content:
        await update.effective_message.reply_text("内容不能为空。")
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
        settings = await get_chat_settings(session, chat.id)
        if not settings.ads_enabled:
            await session.commit()
            await update.effective_message.reply_text("本群未开启广告功能（/admin → 群设置 中开启）。")
            return
        item = await create_rotation_item(
            session,
            chat_id=chat.id,
            created_by_user_id=update.effective_user.id,
            title=title,
            content=content,
        )
        await session.commit()

    await context.bot.send_message(chat_id=chat.id, text=_format_ad_push_text(item))


async def ads_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    await update.callback_query.answer()

    target_chat_id = await _resolve_ads_target_chat_id(update, context)
    if target_chat_id is None:
        return
    await _ads_handler.show_menu(update, context, target_chat_id)


async def ads_rules_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    cb = CallbackParser.parse(update.callback_query.data or "")
    if cb.get(2) == "hint":
        hint_key = cb.get(4)
        hint_text = {
            "unpin_previous": "这是说明栏，请点击下方「开启」或「关闭」按钮来切换取消上一条置顶。",
        }.get(hint_key, "这是说明栏，请点击旁边可操作的按钮。")
        await answer_callback_query_safely(update, hint_text, show_alert=False)
        return

    await update.callback_query.answer()
    target_chat_id = await _resolve_ads_target_chat_id(update, context)
    if target_chat_id is None:
        return
    await _ads_handler.show_rules(update, context, target_chat_id)


async def ads_rules_set_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    q = update.callback_query
    await q.answer()

    cb = CallbackParser.parse(q.data or "")
    chat_id = cb.require_int(3, label="chat_id")
    field = cb.get(4)
    value = cb.get(5)

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        rule = await get_or_create_rotation_rule(session, chat_id)
        kwargs: dict[str, object] = {}
        if field == "enabled":
            kwargs["enabled"] = value == "1"
        elif field == "mode":
            kwargs["mode"] = value
        elif field == "interval_minutes":
            kwargs["interval_seconds"] = int(value) * 60
        elif field == "delete_policy":
            kwargs["delete_policy"] = value
        elif field == "unpin_previous":
            kwargs["unpin_previous"] = value == "1"
        else:
            await session.commit()
            await answer_callback_query_safely(update, "无效配置项", show_alert=True)
            return

        if field == "delete_policy" and value == "delete_delay":
            if rule.delete_policy == "delete_delay":
                await ConversationStateService.start(
                    session,
                    chat_id=update.effective_chat.id,
                    user_id=update.effective_user.id,
                    state_type="ads_rule_edit_delay",
                    state_data={"target_chat_id": chat_id},
                )
                await session.commit()
                await q.edit_message_text(
                    "👉 请输入延迟删除秒数，例如 60。",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"ads:rules:{chat_id}")]]),
                )
                return
            kwargs["delete_delay_seconds"] = DEFAULT_DELETE_DELAY_SECONDS

        await update_rotation_rule(session, chat_id, **kwargs)
        await session.commit()
    await _ads_handler.show_rules(update, context, chat_id)


DEFAULT_DELETE_DELAY_SECONDS = 60


async def ads_rules_input_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    cb = CallbackParser.parse(q.data or "")
    chat_id = cb.require_int(3, label="chat_id")
    field = cb.get(4)

    if field == "interval":
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            rule = await get_or_create_rotation_rule(session, chat_id)
            await session.commit()
        await q.edit_message_text(
            "请选择轮播间隔",
            reply_markup=ads_rules_interval_keyboard(chat_id, getattr(rule, "interval_seconds", None)),
        )
        return

    state_map = {
        "start": "ads_rule_edit_start",
        "interval_custom": "ads_rule_edit_interval",
        "delay": "ads_rule_edit_delay",
    }
    state_type = state_map.get(field)
    if state_type is None:
        await answer_callback_query_safely(update, "无效配置项", show_alert=True)
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await ConversationStateService.start(
            session,
            chat_id=update.effective_chat.id,
            user_id=update.effective_user.id,
            state_type=state_type,
            state_data={"target_chat_id": chat_id},
        )
        await session.commit()

    if field == "start":
        sample_time = next_top_of_hour()
        sample_label = format_local_datetime(sample_time, empty="")
        await q.edit_message_text(
            build_datetime_prompt_text(
                title="🎠 轮播规则 | 编辑开始时间",
                sample_time_text=sample_label,
                sample_time_unix=int(sample_time.timestamp()),
                show_copy_hint=False,
                input_hint="👉🏻 现在输入定时开始时间:",
            ),
            parse_mode="HTML",
            reply_markup=ads_copy_time_keyboard(f"ads:rules:{chat_id}", sample_label),
        )
        return

    prompt = {
        "interval_custom": "👉 请输入自定义间隔时间（分钟）：",
        "delay": "👉 请输入延迟删除秒数，例如 60。",
    }[field]
    await q.edit_message_text(
        prompt,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"ads:rules:{chat_id}")]]),
    )


async def ads_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    await update.callback_query.answer()

    cb = CallbackParser.parse(update.callback_query.data or "")
    page = 0
    for index in range(cb.length() - 1, 0, -1):
        value = cb.get_int_optional(index)
        if value is not None and value >= 0:
            page = value
            break

    target_chat_id = await _resolve_ads_target_chat_id(update, context)
    if target_chat_id is None:
        return
    await _ads_handler.show_list(update, context, target_chat_id, page)


async def ads_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ads_menu_callback(update, context)


async def ads_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    await update.callback_query.answer()

    target_chat_id = await _resolve_ads_target_chat_id(update, context)
    if target_chat_id is None:
        return

    item_id = _parse_ad_id_from_callback(update.callback_query.data or "")
    if item_id <= 0:
        await answer_callback_query_safely(update, "轮播消息 ID 无效", show_alert=True)
        return
    await _ads_handler.show_detail(update, context, target_chat_id, item_id)


async def ads_create_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    target_chat_id = await _resolve_ads_target_chat_id(update, context)
    if target_chat_id is None:
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await ModuleSettingsService.ensure(
            session,
            chat_id=target_chat_id,
            chat_type="supergroup",
            title=update.effective_chat.title,
            user_id=update.effective_user.id,
            username=update.effective_user.username,
            first_name=update.effective_user.first_name,
            last_name=update.effective_user.last_name,
            language_code=update.effective_user.language_code,
        )
        item = await create_rotation_item(
            session,
            chat_id=target_chat_id,
            created_by_user_id=update.effective_user.id,
            title="新轮播消息",
            content="",
        )
        await session.commit()

    await _ads_handler.show_detail(update, context, target_chat_id, item.id)


async def ads_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    await update.callback_query.answer()

    target_chat_id = await _resolve_ads_target_chat_id(update, context)
    if target_chat_id is None:
        return
    item_id = _parse_ad_id_from_callback(update.callback_query.data or "")
    if item_id <= 0:
        await answer_callback_query_safely(update, "轮播消息 ID 无效", show_alert=True)
        return
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        item = await get_rotation_item(session, item_id)
        if item is None or item.chat_id != target_chat_id:
            await session.commit()
            await answer_callback_query_safely(update, "轮播消息不存在", show_alert=True)
            return
        item.enabled = not item.enabled
        await session.commit()
    await _ads_handler.show_list(update, context, target_chat_id)


async def ads_item_set_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    q = update.callback_query
    await q.answer()

    cb = CallbackParser.parse(q.data or "")
    if cb.has_int(4):
        item_id = cb.require_int(4, label="item_id")
        field = cb.get(5)
        value = cb.get(6)
    else:
        item_id = cb.require_int(3, label="item_id")
        field = cb.get(4)
        value = cb.get(5)

    target_chat_id = await _resolve_ads_target_chat_id(update, context)
    if target_chat_id is None:
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        item = await get_rotation_item(session, item_id)
        if item is None or item.chat_id != target_chat_id:
            await session.commit()
            await answer_callback_query_safely(update, "轮播消息不存在", show_alert=True)
            return

        if field == "enabled":
            await update_rotation_item(session, item_id, enabled=value == "1")
        else:
            await session.commit()
            await answer_callback_query_safely(update, "无效操作", show_alert=True)
            return
        await session.commit()
    await _ads_handler.show_detail(update, context, target_chat_id, item_id)


async def ads_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    await update.callback_query.answer()

    target_chat_id = await _resolve_ads_target_chat_id(update, context)
    if target_chat_id is None:
        return
    item_id = _parse_ad_id_from_callback(update.callback_query.data or "")
    if item_id <= 0:
        await answer_callback_query_safely(update, "轮播消息 ID 无效", show_alert=True)
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        item = await get_rotation_item(session, item_id)
        if item is None or item.chat_id != target_chat_id:
            await session.commit()
            await answer_callback_query_safely(update, "轮播消息不存在", show_alert=True)
            return
        await session.delete(item)
        await session.flush()
        remaining = await list_rotation_items(session, target_chat_id)
        for index, row in enumerate(remaining, start=1):
            row.sort_order = index
        await session.commit()
    await _ads_handler.show_list(update, context, target_chat_id)


async def ads_item_input_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None or update.effective_chat is None:
        return
    q = update.callback_query
    await q.answer()

    cb = CallbackParser.parse(q.data or "")
    if cb.has_int(4):
        item_id = cb.require_int(4, label="item_id")
        field = cb.get(5)
    else:
        item_id = cb.require_int(3, label="item_id")
        field = cb.get(4)
    target_chat_id = await _resolve_ads_target_chat_id(update, context)
    if target_chat_id is None:
        return

    if field == "buttons":
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            await show_layout_menu(
                update,
                context,
                ButtonEditorContext("ads", target_chat_id, item_id),
                session=session,
            )
            await session.commit()
        return

    state_map = {
        "title": "ads_item_edit_title",
        "text": "ads_item_edit_text",
        "cover": "ads_item_edit_cover",
        "start": "ads_item_edit_start",
        "end": "ads_item_edit_end",
        "order": "ads_item_edit_order",
    }
    state_type = state_map.get(field)
    if state_type is None:
        await answer_callback_query_safely(update, "无效配置项", show_alert=True)
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await ConversationStateService.start(
            session,
            chat_id=update.effective_chat.id,
            user_id=update.effective_user.id,
            state_type=state_type,
            state_data={"target_chat_id": target_chat_id, "item_id": item_id},
        )
        await session.commit()

    prompt = {
        "title": "🎠 轮播消息 | 标题备注\n\n请输入标题备注，例如：周末活动通知。\n输入“清空”可恢复默认标题。",
        "text": "🎠 轮播消息 | 文本内容\n\n请输入要轮播发送到群里的正文。\n可以直接发送多行文本，输入“清空”可清空文本。",
        "cover": "👉 请发送图片作为封面；发送“清空”可移除封面。",
        "order": "👉 请输入新的轮播顺序数字，例如 1。",
    }.get(field)
    if field == "start":
        sample_time = next_top_of_hour()
        sample_label = format_local_datetime(sample_time, empty="")
        await q.edit_message_text(
            build_datetime_prompt_text(
                title="🎠 轮播消息 | 编辑开始时间",
                sample_time_text=sample_label,
                sample_time_unix=int(sample_time.timestamp()),
                show_copy_hint=False,
                input_hint="👉🏻 现在输入定时开始时间:",
            ),
            parse_mode="HTML",
            reply_markup=ads_copy_time_keyboard(
                f"ads:detail:{target_chat_id}:{item_id}",
                sample_label,
            ),
        )
        return
    if field == "end":
        sample_time = next_top_of_hour(days_offset=1)
        sample_label = format_local_datetime(sample_time, empty="")
        await q.edit_message_text(
            build_datetime_prompt_text(
                title="🎠 轮播消息 | 编辑结束时间",
                sample_time_text=sample_label,
                sample_time_unix=int(sample_time.timestamp()),
                show_copy_hint=False,
                input_hint="👉🏻 现在输入定时结束时间:",
            ),
            parse_mode="HTML",
            reply_markup=ads_copy_time_keyboard(
                f"ads:detail:{target_chat_id}:{item_id}",
                sample_label,
            ),
        )
        return

    await q.edit_message_text(
        prompt or "请输入配置内容。",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"ads:detail:{target_chat_id}:{item_id}")]]),
    )


async def ads_item_time_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    await update.callback_query.answer()

    cb = CallbackParser.parse(update.callback_query.data or "")
    item_id = cb.require_int(4, label="item_id") if cb.has_int(4) else cb.require_int(3, label="item_id")
    target_chat_id = await _resolve_ads_target_chat_id(update, context)
    if target_chat_id is None:
        return
    await _ads_handler.show_time_range(update, context, target_chat_id, item_id)


async def ads_cleanup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    await update.callback_query.answer()

    target_chat_id = await _resolve_ads_target_chat_id(update, context)
    if target_chat_id is None:
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        deleted = await cleanup_expired_rotation_items(session, target_chat_id)
        await session.commit()
    await answer_callback_query_safely(update, f"已清理 {deleted} 条过期轮播", show_alert=False)
    await _ads_handler.show_list(update, context, target_chat_id)


async def ads_item_preview_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None:
        return
    await update.callback_query.answer()

    item_id = _parse_ad_id_from_callback(update.callback_query.data or "")
    target_chat_id = await _resolve_ads_target_chat_id(update, context)
    if target_chat_id is None:
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        item = await get_rotation_item(session, item_id)
        await session.commit()
    if item is None or item.chat_id != target_chat_id:
        await answer_callback_query_safely(update, "轮播消息不存在", show_alert=True)
        return

    await preview_rotation_item(context, chat_id=update.effective_user.id, item=item)
    await answer_callback_query_safely(update, "预览已发送到当前私聊", show_alert=False)


async def ads_send_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ads_item_preview_callback(update, context)


async def ads_create_config_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None or update.effective_user is None or update.effective_chat is None:
        return

    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    text_value = (message.text or message.caption or "").strip()

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state = await ConversationStateService.get(session, chat.id, user.id)
        if not state or not state.state_type.startswith("ads_"):
            await session.commit()
            return

        data = dict(state.state_data or {})
        target_chat_id = data.get("target_chat_id")
        item_id = data.get("item_id")
        allowed, error_text = await PermissionPolicyService.require_manage(
            context,
            target_chat_id,
            user.id,
            capability="automation",
        )
        if not allowed:
            await session.commit()
            if error_text:
                await message.reply_text(error_text)
            return
        try:
            if state.state_type == "ads_create_config":
                config = _parse_ads_config(text_value)
                item = await create_rotation_item(
                    session,
                    chat_id=target_chat_id,
                    created_by_user_id=user.id,
                    title=config["title"],
                    content=config["content"],
                )
                await update_rotation_item(
                    session,
                    item.id,
                    image_file_id=config.get("image_file_id"),
                    start_time=config.get("start_time", UNSET),
                )
                if config.get("interval_hours"):
                    await update_rotation_rule(
                        session,
                        target_chat_id,
                        interval_seconds=int(config["interval_hours"]) * 3600,
                    )
                if config.get("start_time"):
                    await update_rotation_rule(
                        session,
                        target_chat_id,
                        start_at=config["start_time"],
                    )
                await ConversationStateService.clear(session, chat.id, user.id)
                await session.commit()
                await _ads_handler.show_detail(update, context, target_chat_id, item.id)
                return

            if state.state_type == "ads_rule_edit_start":
                await update_rotation_rule(
                    session,
                    target_chat_id,
                    start_at=None if _is_clear_input(text_value) else parse_datetime_text(text_value),
                )
                await ConversationStateService.clear(session, chat.id, user.id)
                await session.commit()
                await _ads_handler.show_rules(update, context, target_chat_id)
                return

            if state.state_type == "ads_rule_edit_interval":
                await update_rotation_rule(
                    session,
                    target_chat_id,
                    interval_seconds=parse_interval_hours_text(text_value),
                )
                await ConversationStateService.clear(session, chat.id, user.id)
                await session.commit()
                await _ads_handler.show_rules(update, context, target_chat_id)
                return

            if state.state_type == "ads_rule_edit_delay":
                await update_rotation_rule(
                    session,
                    target_chat_id,
                    delete_delay_seconds=parse_delay_seconds_text(text_value),
                    delete_policy="delete_delay",
                )
                await ConversationStateService.clear(session, chat.id, user.id)
                await session.commit()
                await _ads_handler.show_rules(update, context, target_chat_id)
                return

            if item_id is None:
                raise ValidationError("轮播消息不存在")

            if state.state_type == "ads_item_edit_title":
                await update_rotation_item(session, item_id, title=text_value)
            elif state.state_type == "ads_item_edit_text":
                await update_rotation_item(session, item_id, content=text_value)
            elif state.state_type == "ads_item_edit_cover":
                if _is_clear_input(text_value):
                    await update_rotation_item(session, item_id, clear_image=True)
                elif message.photo:
                    await update_rotation_item(session, item_id, image_file_id=message.photo[-1].file_id)
                else:
                    raise ValidationError("请发送图片，或发送“清空”移除封面")
            elif state.state_type == "ads_item_edit_start":
                await update_rotation_item(
                    session,
                    item_id,
                    start_time=None if _is_clear_input(text_value) else parse_datetime_text(text_value),
                )
            elif state.state_type == "ads_item_edit_end":
                await update_rotation_item(
                    session,
                    item_id,
                    end_time=None if _is_clear_input(text_value) else parse_datetime_text(text_value),
                )
            elif state.state_type == "ads_item_edit_order":
                if not text_value.isdigit():
                    raise ValidationError("请输入有效的顺序数字")
                await update_rotation_item(session, item_id, sort_order=int(text_value))
            else:
                await session.commit()
                return

            await ConversationStateService.clear(session, chat.id, user.id)
            await session.commit()
        except ValidationError as exc:
            await session.commit()
            await message.reply_text(str(exc))
            return
        except Exception as exc:
            log.exception("ads_private_input_failed", error=str(exc), state_type=state.state_type)
            await session.commit()
            await message.reply_text("处理失败，请稍后重试")
            return

    await _ads_handler.show_detail(update, context, target_chat_id, int(item_id))


async def ads_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    target_chat_id = await _resolve_ads_target_chat_id(update, context)
    if target_chat_id is None:
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state_chat_id = _resolve_ads_state_chat_id(update, target_chat_id)
        await ConversationStateService.clear(session, state_chat_id, update.effective_user.id)
        await session.commit()

    await _ads_handler.show_menu(update, context, target_chat_id)
