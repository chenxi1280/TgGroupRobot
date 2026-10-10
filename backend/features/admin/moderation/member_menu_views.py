from __future__ import annotations

from dataclasses import dataclass

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from backend.shared.ui.common.keyboard import toggle_row

from backend.features.admin.module_settings import (
    describe_force_subscribe_target,
    describe_force_subscribe_target_diagnostics,
    format_duration_label,
)
from backend.platform.db.schema.models.enums import ForceSubscribeAction
from backend.shared.ui.message_config_panel import (
    PanelField,
    action_button,
    button_count,
    button_status,
    format_panel,
    mark_configured,
    media_status,
    summarize_text,
)

DEFAULT_DELETE_SECONDS = 60
DEFAULT_NEW_MEMBER_WINDOW_SECONDS = 3_600
TARGET_BUTTON_LABEL_LENGTH = 16
PHRASE_BUTTON_LABEL_LENGTH = 8


@dataclass(frozen=True)
class ForceSubscribeView:
    chat_id: int
    enabled: bool
    channel_1: str
    channel_2: str
    delete_after: int
    guide_text: str
    cover_set: bool
    cover_media_type: str | None
    custom_buttons: bool
    buttons_configured: bool
    button_summary: str
    diagnostics: tuple[str, ...]
    check_mode_label: str
    action_label: str
    guide_configured: bool


def _force_action_label(action: str) -> str:
    labels = {
        ForceSubscribeAction.delete_and_warn.value: "删除消息并提示关注",
        ForceSubscribeAction.delete_only.value: "仅删除消息",
        ForceSubscribeAction.warn_only.value: "仅提示关注",
        ForceSubscribeAction.mute.value: "禁言并提示关注",
    }
    return labels.get(action, "删除消息并提示关注")


async def build_force_subscribe_view(
    context: ContextTypes.DEFAULT_TYPE,
    settings,
    chat_id: int,
) -> ForceSubscribeView:
    channel_1 = await describe_force_subscribe_target(
        context,
        getattr(settings, "force_subscribe_bound_channel_1", None),
    )
    channel_2 = await describe_force_subscribe_target(
        context,
        getattr(settings, "force_subscribe_bound_channel_2", None),
    )
    custom_buttons = bool(getattr(settings, "force_subscribe_custom_buttons_enabled", False))
    buttons = getattr(settings, "force_subscribe_buttons", None) or []
    check_mode = getattr(settings, "force_subscribe_check_mode", "all")
    action = getattr(settings, "force_subscribe_not_subscribed_action", ForceSubscribeAction.delete_and_warn.value)
    configured_guide = str(getattr(settings, "force_subscribe_guide_text", "") or "").strip()
    guide_text = configured_guide or "{member}，您需要关注指定频道/群组后才能发言。"
    return ForceSubscribeView(
        chat_id=chat_id,
        enabled=bool(getattr(settings, "force_subscribe_enabled", False)),
        channel_1=channel_1,
        channel_2=channel_2,
        delete_after=int(getattr(settings, "force_subscribe_delete_warn_after_seconds", DEFAULT_DELETE_SECONDS) or DEFAULT_DELETE_SECONDS),
        guide_text=guide_text,
        cover_set=bool(getattr(settings, "force_subscribe_cover_file_id", None)),
        cover_media_type=getattr(settings, "force_subscribe_cover_media_type", None),
        custom_buttons=custom_buttons,
        buttons_configured=custom_buttons and button_count(buttons) > 0,
        button_summary=button_status(buttons) if custom_buttons else "跟随绑定目标按钮",
        diagnostics=tuple(await describe_force_subscribe_target_diagnostics(context, settings)),
        check_mode_label="✅ 全部目标都关注" if check_mode == "all" else "🟡 任一目标已关注",
        action_label=_force_action_label(action),
        guide_configured=bool(configured_guide),
    )


def force_subscribe_text(view: ForceSubscribeView) -> str:
    return format_panel(
        "📣 发言前强制关注",
        [
            PanelField("📡", "绑定频道/群组1", view.channel_1),
            PanelField("📡", "绑定频道/群组2", view.channel_2),
            PanelField("🏞️", "封面设置", media_status(has_media=view.cover_set, media_type=view.cover_media_type)),
            PanelField("📄", "提示文案", summarize_text(view.guide_text, limit=180)),
            PanelField("⭕", "设置按钮", view.button_summary),
        ],
        footer=[
            f"⚙️ 状态: {'✅ 启动' if view.enabled else '❌ 关闭'}",
            f"🎯 关注判定: {view.check_mode_label}",
            f"🚫 未关注时处理: {view.action_label}",
            f"🧩 按钮来源: {'自定义按钮' if view.custom_buttons else '跟随绑定目标按钮'}",
            f"🕘 删除提示消息: {view.delete_after}秒后删除",
            *[f"⚠️ {item}" for item in view.diagnostics],
            "🏖️ 预览: 发送到当前私聊",
        ],
    )


def _force_target_rows(view: ForceSubscribeView) -> list[list[InlineKeyboardButton]]:
    chat_id = view.chat_id
    return [
        toggle_row("⚙️ 状态：", enabled=view.enabled, label_callback=f"adm:menu:forcesub:{chat_id}", on_callback=f"adm:fs:{chat_id}:set:enabled:1", off_callback=f"adm:fs:{chat_id}:set:enabled:0"),
        [InlineKeyboardButton(("⚙️ 绑定频道/群组1：") + " · " + (view.channel_1[:TARGET_BUTTON_LABEL_LENGTH]), callback_data=f"adm:fs:{chat_id}:input:channel1")],
        [InlineKeyboardButton(("⚙️ 绑定频道/群组2：") + " · " + (view.channel_2[:TARGET_BUTTON_LABEL_LENGTH]), callback_data=f"adm:fs:{chat_id}:input:channel2")],
    ]


def _force_content_rows(view: ForceSubscribeView) -> list[list[InlineKeyboardButton]]:
    chat_id = view.chat_id
    return [
        [
            action_button("设置封面", f"adm:fs:{chat_id}:input:cover", configured=view.cover_set),
            action_button("设置文案", f"adm:fs:{chat_id}:input:text", configured=view.guide_configured),
        ],
        [
            action_button("设置按钮", f"adm:fs:{chat_id}:input:buttons", configured=view.buttons_configured),
            InlineKeyboardButton("👀 预览效果", callback_data=f"adm:fs:{chat_id}:preview"),
        ],
    ]


def _force_policy_rows(view: ForceSubscribeView) -> list[list[InlineKeyboardButton]]:
    chat_id = view.chat_id
    delete_label = mark_configured(f"{view.delete_after}秒后删除", view.delete_after != DEFAULT_DELETE_SECONDS)
    return [
        [
            InlineKeyboardButton("⚙️ 关注判定：", callback_data=f"adm:menu:forcesub:{chat_id}"),
            InlineKeyboardButton(view.check_mode_label, callback_data=f"adm:fs:{chat_id}:cycle_check_mode"),
        ],
        [
            InlineKeyboardButton("⚙️ 未关注时处理：", callback_data=f"adm:menu:forcesub:{chat_id}"),
            InlineKeyboardButton(view.action_label, callback_data=f"adm:fs:{chat_id}:cycle_action"),
        ],
        [
            InlineKeyboardButton("⚙️ 删除提示消息：", callback_data=f"adm:menu:forcesub:{chat_id}"),
            InlineKeyboardButton(delete_label, callback_data=f"adm:fs:{chat_id}:delete_after"),
        ],
        [InlineKeyboardButton("🧹 清空封面", callback_data=f"adm:fs:{chat_id}:clear_cover")],
        [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:category_safety:{chat_id}")],
    ]


def force_subscribe_keyboard(view: ForceSubscribeView) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(_force_target_rows(view) + _force_content_rows(view) + _force_policy_rows(view))


@dataclass(frozen=True)
class NewMemberLimitView:
    chat_id: int
    enabled: bool
    duration_label: str
    block_media: bool
    block_links: bool
    text_only: bool
    delete_message: bool
    warn_enabled: bool
    warn_text: str
    warn_delete: int


def build_new_member_limit_view(settings, chat_id: int) -> NewMemberLimitView:
    window = int(getattr(settings, "new_member_limit_window_seconds", DEFAULT_NEW_MEMBER_WINDOW_SECONDS) or DEFAULT_NEW_MEMBER_WINDOW_SECONDS)
    return NewMemberLimitView(
        chat_id=chat_id,
        enabled=bool(getattr(settings, "new_member_limit_enabled", False)),
        duration_label=format_duration_label(window),
        block_media=bool(getattr(settings, "new_member_limit_block_media", True)),
        block_links=bool(getattr(settings, "new_member_limit_block_links", True)),
        text_only=bool(getattr(settings, "new_member_limit_text_only", False)),
        delete_message=bool(getattr(settings, "new_member_limit_delete_message", True)),
        warn_enabled=bool(getattr(settings, "new_member_limit_warn_enabled", True)),
        warn_text=getattr(settings, "new_member_limit_warn_text", "") or "新成员需等待 {duration} 才可发送媒体/链接。",
        warn_delete=int(getattr(settings, "new_member_limit_warn_delete_after_seconds", DEFAULT_DELETE_SECONDS) or DEFAULT_DELETE_SECONDS),
    )


def _enabled_text(value: bool) -> str:
    return "✅ 开启" if value else "❌ 关闭"


def new_member_limit_text(view: NewMemberLimitView) -> str:
    return (
        "🧑‍🍼 新成员限制\n\n用于控制新成员在入群后的可发言范围，避免新号刷广告。\n\n"
        f"状态: {'✅ 启动' if view.enabled else '❌ 关闭'}\n"
        f"限制时长: {view.duration_label}\n"
        f"限制媒体: {_enabled_text(view.block_media)}\n"
        f"限制链接: {_enabled_text(view.block_links)}\n"
        f"仅纯文本: {_enabled_text(view.text_only)}\n"
        f"删除触发消息: {_enabled_text(view.delete_message)}\n"
        f"提示消息: {_enabled_text(view.warn_enabled)}\n"
        f"提示删除: {view.warn_delete}秒后删除\n\n当前提示文案:\n{view.warn_text}"
    )


def _toggle_label(value: bool) -> str:
    return "✅ 开启" if value else "关闭"


def new_member_limit_keyboard(view: NewMemberLimitView) -> InlineKeyboardMarkup:
    chat_id = view.chat_id
    rows = [
        toggle_row("⚙️ 状态：", enabled=view.enabled, label_callback=f"adm:menu:newmem:{chat_id}", on_callback=f"adm:nml:{chat_id}:set:enabled:1", off_callback=f"adm:nml:{chat_id}:set:enabled:0"),
        [InlineKeyboardButton(f"⏱ 限制时长（{view.duration_label}）", callback_data=f"adm:nml:{chat_id}:input:window")],
        toggle_row("🖼️ 媒体", enabled=view.block_media, label_callback=f"adm:menu:newmem:{chat_id}", on_callback=f"adm:nml:{chat_id}:set:block_media:1", off_callback=f"adm:nml:{chat_id}:set:block_media:0"),
        toggle_row("🔗 链接", enabled=view.block_links, label_callback=f"adm:menu:newmem:{chat_id}", on_callback=f"adm:nml:{chat_id}:set:block_links:1", off_callback=f"adm:nml:{chat_id}:set:block_links:0"),
        toggle_row("📝 仅纯文本", enabled=view.text_only, label_callback=f"adm:menu:newmem:{chat_id}", on_callback=f"adm:nml:{chat_id}:set:text_only:1", off_callback=f"adm:nml:{chat_id}:set:text_only:0"),
        toggle_row("🗑 删除触发消息", enabled=view.delete_message, label_callback=f"adm:menu:newmem:{chat_id}", on_callback=f"adm:nml:{chat_id}:set:delete_message:1", off_callback=f"adm:nml:{chat_id}:set:delete_message:0"),
        toggle_row("💬 提示消息", enabled=view.warn_enabled, label_callback=f"adm:menu:newmem:{chat_id}", on_callback=f"adm:nml:{chat_id}:set:warn_enabled:1", off_callback=f"adm:nml:{chat_id}:set:warn_enabled:0"),
        [InlineKeyboardButton("✏️ 提示文案", callback_data=f"adm:nml:{chat_id}:input:warn_text"), InlineKeyboardButton(f"🕒 删除提示（{view.warn_delete}秒）", callback_data=f"adm:nml:{chat_id}:cycle:warn_delete")],
        [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:category_safety:{chat_id}")],
    ]
    return InlineKeyboardMarkup(rows)


@dataclass(frozen=True)
class NightModeView:
    chat_id: int
    message_control: bool
    start_time: str
    end_time: str
    exempt_admin: bool
    whitelist_summary: str
    delete_message: bool
    warn_enabled: bool
    warn_text: str
    warn_delete: int
    lock_schedule: bool
    phrase_enabled: bool
    open_phrase: str
    close_phrase: str
    delete_notice: bool


def _night_times(settings) -> tuple[str, str]:
    start = getattr(settings, "night_mode_start_time", None) or getattr(settings, "group_lock_close_time", None)
    end = getattr(settings, "night_mode_end_time", None) or getattr(settings, "group_lock_open_time", None)
    return start or "未设置", end or "未设置"


def _whitelist_summary(settings) -> str:
    whitelist = getattr(settings, "night_mode_whitelist_user_ids", None) or []
    return f"{len(whitelist)} 人" if whitelist else "未配置"


def build_night_mode_view(settings, chat_id: int) -> NightModeView:
    start_time, end_time = _night_times(settings)
    return NightModeView(
        chat_id=chat_id,
        message_control=bool(getattr(settings, "night_mode_enabled", False)),
        start_time=start_time,
        end_time=end_time,
        exempt_admin=bool(getattr(settings, "night_mode_exempt_admin", True)),
        whitelist_summary=_whitelist_summary(settings),
        delete_message=bool(getattr(settings, "night_mode_delete_message", True)),
        warn_enabled=bool(getattr(settings, "night_mode_warn_enabled", True)),
        warn_text=getattr(settings, "night_mode_warn_text", "") or "🌙 夜间管控生效中，请稍后再试。",
        warn_delete=int(getattr(settings, "night_mode_warn_delete_after_seconds", DEFAULT_DELETE_SECONDS) or DEFAULT_DELETE_SECONDS),
        lock_schedule=bool(getattr(settings, "group_lock_schedule_enabled", False)),
        phrase_enabled=bool(getattr(settings, "group_lock_phrase_enabled", False)),
        open_phrase=getattr(settings, "group_lock_open_phrase", None) or "开群",
        close_phrase=getattr(settings, "group_lock_close_phrase", None) or "关群",
        delete_notice=getattr(settings, "group_lock_delete_notice_mode", "keep") == "delete",
    )


def night_mode_text(view: NightModeView) -> str:
    return (
        "🌙 夜间管控\n\n以夜间模式为主，统一管理夜间时段、消息拦截、全员禁言和口令开关群。\n\n"
        f"管控开始: {view.start_time}\n管控结束: {view.end_time}\n"
        f"消息拦截: {_enabled_text(view.message_control)}\n全员禁言: {_enabled_text(view.lock_schedule)}\n"
        f"口令开关群: {_enabled_text(view.phrase_enabled)}\n管理员豁免: {_enabled_text(view.exempt_admin)}\n"
        f"白名单: {view.whitelist_summary}\n删除触发消息: {_enabled_text(view.delete_message)}\n"
        f"提示消息: {_enabled_text(view.warn_enabled)}\n开群词/关群词: {view.open_phrase} / {view.close_phrase}\n"
        f"口令通知删除: {'✅ 删除' if view.delete_notice else '保留'}\n"
        f"提示删除: {view.warn_delete}秒后删除\n\n当前提示文案:\n{view.warn_text}"
    )


def _night_control_rows(view: NightModeView) -> list[list[InlineKeyboardButton]]:
    chat_id = view.chat_id
    return [
        toggle_row("🧹 消息拦截", enabled=view.message_control, label_callback=f"adm:menu:night:{chat_id}", on_callback=f"adm:night:{chat_id}:set:enabled:1", off_callback=f"adm:night:{chat_id}:set:enabled:0"),
        [InlineKeyboardButton(f"⏰ 管控开始（{view.start_time}）", callback_data=f"adm:night:{chat_id}:input:start"), InlineKeyboardButton(f"⏰ 管控结束（{view.end_time}）", callback_data=f"adm:night:{chat_id}:input:end")],
        toggle_row("🔒 全员禁言模式", enabled=view.lock_schedule, label_callback=f"adm:menu:night:{chat_id}", on_callback=f"adm:night:{chat_id}:set:lock_schedule:1", off_callback=f"adm:night:{chat_id}:set:lock_schedule:0"),
        toggle_row("🗣 口令开关群", enabled=view.phrase_enabled, label_callback=f"adm:menu:night:{chat_id}", on_callback=f"adm:night:{chat_id}:set:lock_phrase:1", off_callback=f"adm:night:{chat_id}:set:lock_phrase:0"),
        [InlineKeyboardButton(f"🔓 开群词（{view.open_phrase[:PHRASE_BUTTON_LABEL_LENGTH]}）", callback_data=f"adm:night:{chat_id}:input:open_phrase"), InlineKeyboardButton(f"🔒 关群词（{view.close_phrase[:PHRASE_BUTTON_LABEL_LENGTH]}）", callback_data=f"adm:night:{chat_id}:input:close_phrase")],
    ]


def _night_policy_rows(view: NightModeView) -> list[list[InlineKeyboardButton]]:
    chat_id = view.chat_id
    next_notice = "keep" if view.delete_notice else "delete"
    return [
        toggle_row("🛡️ 管理员豁免", enabled=view.exempt_admin, label_callback=f"adm:menu:night:{chat_id}", on_callback=f"adm:night:{chat_id}:set:exempt_admin:1", off_callback=f"adm:night:{chat_id}:set:exempt_admin:0"),
        [InlineKeyboardButton(f"👥 白名单（{view.whitelist_summary}）", callback_data=f"adm:night:{chat_id}:input:whitelist")],
        toggle_row("🗑 删除触发消息", enabled=view.delete_message, label_callback=f"adm:menu:night:{chat_id}", on_callback=f"adm:night:{chat_id}:set:delete_message:1", off_callback=f"adm:night:{chat_id}:set:delete_message:0"),
        toggle_row("💬 提示消息", enabled=view.warn_enabled, label_callback=f"adm:menu:night:{chat_id}", on_callback=f"adm:night:{chat_id}:set:warn_enabled:1", off_callback=f"adm:night:{chat_id}:set:warn_enabled:0"),
        [InlineKeyboardButton("✏️ 提示文案", callback_data=f"adm:night:{chat_id}:input:warn_text"), InlineKeyboardButton(f"🕒 删除提示（{view.warn_delete}秒）", callback_data=f"adm:night:{chat_id}:cycle:warn_delete")],
        [InlineKeyboardButton(("🧹 口令通知") + " · " + ("删除" if view.delete_notice else "保留"), callback_data=f"adm:night:{chat_id}:notice:{next_notice}")],
        [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:category_safety:{chat_id}")],
    ]


def night_mode_keyboard(view: NightModeView) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(_night_control_rows(view) + _night_policy_rows(view))
