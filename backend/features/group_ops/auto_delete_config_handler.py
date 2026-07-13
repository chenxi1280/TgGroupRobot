from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import TelegramError

from backend.platform.db.runtime.session import Database
from backend.features.admin.ui.auto_delete import auto_delete_config_keyboard
from backend.features.group_ops.auto_delete_handler import get_auto_delete_permission_warning
from backend.shared.services.module_settings_service import ModuleSettingsService
from backend.shared.services.permission_service import PermissionPolicyService
from backend.platform.telegram.errors import build_public_error_text
from backend.shared.callback_parser import CallbackParser
_AUTO_DELETE_CONFIG_CALLBACK_THRESHOLD_4 = 4


log = structlog.get_logger(__name__)

# 字段名映射：键盘回调数据使用简化名，模型使用完整字段名
FIELD_MAPPING = {
    "enabled": "auto_delete_enabled",
    "join": "auto_delete_join",
    "left": "auto_delete_left",
    "pinned": "auto_delete_pinned",
    "avatar": "auto_delete_avatar",
    "title": "auto_delete_title",
    "anonymous": "auto_delete_anonymous",
}


async def _safe_edit_message(q, text: str, **kwargs) -> None:
    """安全地编辑消息"""
    try:
        await q.edit_message_text(text, **kwargs)
    except TelegramError as e:
        # 捕获所有 Telegram 错误，记录日志但不抛出异常
        log.warning("edit_message_failed", error=str(e), callback_data=q.data)


def _resolve_chat_id(cb: CallbackParser, action: str) -> int | None:
    """严格解析配置回调中的群组 ID，兼容旧/新两种协议。"""
    indices = (4,) if action == "set" else (3,)
    for index in indices:
        try:
            return cb.require_int(index, label="chat_id")
        except ValueError:
            continue
    return None


def _sync_master_toggle(settings) -> None:
    """根据分项开关回填总开关，兼容旧运行时逻辑。"""
    per_item_enabled = any(
        bool(getattr(settings, field_name, False))
        for field_name in (
            "auto_delete_join",
            "auto_delete_left",
            "auto_delete_pinned",
            "auto_delete_avatar",
            "auto_delete_title",
            "auto_delete_anonymous",
        )
    )
    settings.auto_delete_enabled = per_item_enabled


def _format_enabled_types(settings) -> str:
    enabled_labels = [
        label
        for enabled, label in [
            (bool(getattr(settings, "auto_delete_join", False)), "进群"),
            (bool(getattr(settings, "auto_delete_left", False)), "退群"),
            (bool(getattr(settings, "auto_delete_pinned", False)), "置顶"),
            (bool(getattr(settings, "auto_delete_avatar", False)), "头像"),
            (bool(getattr(settings, "auto_delete_title", False)), "群名"),
            (bool(getattr(settings, "auto_delete_anonymous", False)), "匿名消息"),
        ]
        if enabled
    ]
    return "、".join(enabled_labels) if enabled_labels else "暂无"


async def auto_delete_config_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """自动删除配置回调处理器"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return

    q = update.callback_query
    try:
        await q.answer()
    except TelegramError:
        # 回调查询已过期，忽略错误继续处理
        pass

    if update.effective_chat.type != "private":
        await q.edit_message_text("请在私聊中使用此功能")
        return

    data = q.data or ""
    cb = CallbackParser.parse(data)

    if cb.length() < _AUTO_DELETE_CONFIG_CALLBACK_THRESHOLD_4:
        await _safe_edit_message(q, "参数错误")
        return

    action = cb.get(1)
    field = cb.get(2)
    chat_id = _resolve_chat_id(cb, action)
    if chat_id is None:
        log.warning("invalid_chat_id", data=q.data)
        await _safe_edit_message(q, "无效的群组ID")
        return

    allowed, reason = await PermissionPolicyService.require_manage(
        context,
        chat_id,
        update.effective_user.id,
        capability="settings",
    )
    if not allowed:
        await _safe_edit_message(q, build_public_error_text(RuntimeError(reason or "没有权限")))
        return

    if action == "noop":
        return

    if action not in {"toggle", "set"}:
        await _safe_edit_message(q, "无效操作")
        return

    db: Database = context.application.bot_data["db"]

    # 获取完整字段名
    actual_field = FIELD_MAPPING.get(field, field)

    async with db.session_factory() as session:
        settings = await ModuleSettingsService.ensure(
            session,
            chat_id=chat_id,
            chat_type="supergroup" if chat_id < 0 else "private",
            user_id=update.effective_user.id,
            username=update.effective_user.username,
            first_name=update.effective_user.first_name,
            last_name=update.effective_user.last_name,
            language_code=update.effective_user.language_code,
        )

        if hasattr(settings, actual_field):
            current = bool(getattr(settings, actual_field))
            if action == "set":
                desired = cb.get_int_optional(3)
                if desired not in {0, 1}:
                    await _safe_edit_message(q, "无效配置值")
                    return
                next_value = bool(desired)
            else:
                next_value = not current

            log.info(
                "auto_delete_toggle",
                field=actual_field,
                before=current,
                after=next_value,
                chat_id=chat_id,
                action=action,
            )
            setattr(settings, actual_field, next_value)
            _sync_master_toggle(settings)
            await session.commit()

        # 在同一个会话中重新查询获取最新数据
        settings = await ModuleSettingsService.ensure(
            session,
            chat_id=chat_id,
            chat_type="supergroup" if chat_id < 0 else "private",
        )

    keyboard = auto_delete_config_keyboard(settings, chat_id)

    text = "🧹 删除系统提示\n\n"
    text += "本功能会自动清除系统提示消息\n\n"
    text += f"总开关状态：{'✅ 已生效' if bool(getattr(settings, 'auto_delete_enabled', False)) else '❌ 未生效'}\n"
    text += f"当前明细：{_format_enabled_types(settings)}\n\n"
    text += "配置已更新"
    if bool(getattr(settings, "auto_delete_enabled", False)):
        permission_warning = await get_auto_delete_permission_warning(context, chat_id)
        if permission_warning:
            text += f"\n\n{permission_warning}"
    await _safe_edit_message(q, text, reply_markup=keyboard)
