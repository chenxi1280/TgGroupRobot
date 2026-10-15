"""Private configuration only; reading/saving a permission profile never applies it."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from backend.features.group_ops.services.group_permission_profiles import PERMISSION_FIELDS, profile_values
from backend.platform.db.schema.models.chat import ChatSettings
from backend.shared.callback_parser import CallbackParser
from backend.shared.handlers.base.message_helper import MessageHelper
from backend.shared.services.module_config_service import get_module_config, update_module_config
from backend.shared.services.permission_service import PermissionPolicyService


async def permission_profile_callback(update, context):
    cb = CallbackParser.parse(update.callback_query.data or "")
    chat_id, mode, action = cb.get_int_optional(1), cb.get(2), cb.get(3)
    if not _valid_target(update, chat_id, mode):
        await update.callback_query.answer("参数无效", show_alert=True)
        return
    if not await PermissionPolicyService.can_manage(context, chat_id, update.effective_user.id):
        await update.callback_query.answer("无权管理该群", show_alert=True)
        return
    db = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await session.scalar(select(ChatSettings).where(ChatSettings.chat_id == chat_id).with_for_update())
        if settings is None:
            await MessageHelper.safe_edit(update, "群配置不存在，请返回管理首页。")
            return
        if action == "set":
            try:
                _validate_change(cb)
                from backend.features.group_ops.services.permission_snapshot import capture_permissions
                await capture_permissions(context, session, settings, user_id=update.effective_user.id)
                await _save_profile(session, settings, mode=mode, cb=cb)
            except ValueError as exc:
                await update.callback_query.answer(str(exc), show_alert=True)
                return
            context.application.bot_data.setdefault("group_lock_state", {}).pop(chat_id, None)
        elif action != "view":
            await update.callback_query.answer("无效操作", show_alert=True)
            return
        snapshot = get_module_config(settings, "group_lock").get("original_permissions")
        values = profile_values(settings, closed=mode == "closed")
        await session.commit()
    await _show_profile(update, chat_id, mode=mode, values=values, snapshot=snapshot)


def _valid_target(update, chat_id, mode) -> bool:
    return chat_id is not None and chat_id < 0 and mode in {"open", "closed"} and update.effective_chat.type == "private"


async def _save_profile(session, settings, *, mode: str, cb):
    key, value = _validate_change(cb)
    profiles = dict(get_module_config(settings, "group_lock").get("profiles", {}))
    values = dict(profiles.get(mode, {}))
    if not values:
        values = {field: False for _, field in PERMISSION_FIELDS.values()}
        values["can_send_messages"] = mode == "open"
    values[PERMISSION_FIELDS[key][1]] = value == "1"
    profiles[mode] = values
    await update_module_config(session, settings, module="group_lock", patch={"profiles": profiles})


async def _show_profile(update, chat_id: int, *, mode: str, values, snapshot=None):
    configured = values is not None
    values = values or {"can_send_messages": mode == "open"}
    text = f"{'开群' if mode == 'open' else '关群'}成员权限\n群：{chat_id}\n"
    text += "保存只更新方案；在下一次已启用的口令/定时开关群时执行。\n"
    text += "未配置的媒体权限默认关闭；公开群限制由 Telegram 决定。\n"
    text += "已配置独立方案" if configured else "当前沿用旧版仅控制文本的方案；修改任一项后启用完整方案。"
    text += "\n原群权限快照：" + (str(snapshot) if snapshot is not None else "未读取；首次保存前将只读校验，失败则不启用方案。")
    rows = []
    for key, (label, field) in PERMISSION_FIELDS.items():
        enabled = bool(values.get(field, False))
        rows.append([InlineKeyboardButton(label, callback_data=f"gperm:{chat_id}:{mode}:view"),
            InlineKeyboardButton("✅ 允许" if enabled else "允许", callback_data=f"gperm:{chat_id}:{mode}:set:{key}:1"),
            InlineKeyboardButton("不允许" if enabled else "✅ 不允许", callback_data=f"gperm:{chat_id}:{mode}:set:{key}:0")])
    rows.append([InlineKeyboardButton("返回夜间管控", callback_data=f"adm:menu:night:{chat_id}")])
    await MessageHelper.safe_edit(update, text, reply_markup=InlineKeyboardMarkup(rows))


def _validate_change(cb):
    key, value = cb.get(4), cb.get(5)
    if key not in PERMISSION_FIELDS or value not in {'0','1'}:
        raise ValueError('无效成员权限或开关值')
    return key, value
