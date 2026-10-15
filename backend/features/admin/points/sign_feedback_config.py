"""Sign feedback controls. Saving and previewing never sign in or award points."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from backend.platform.db.schema.models.chat import ChatSettings
from backend.platform.state.state_service import clear_user_state, set_user_state
from backend.features.points.sign_feedback import validate_template, MAX_DELETE_SECONDS
from backend.shared.callback_parser import CallbackParser
from backend.shared.handlers.base.message_helper import MessageHelper
from backend.shared.services.module_config_service import get_module_config, update_module_config
from backend.shared.services.permission_service import PermissionPolicyService


async def sign_feedback_callback(update, context):
    cb = CallbackParser.parse(update.callback_query.data or "")
    chat_id = cb.get_int_optional(1)
    if chat_id is None or chat_id >= 0 or update.effective_chat.type != "private":
        return
    if not await PermissionPolicyService.can_manage(context, chat_id, update.effective_user.id, capability="points"):
        await update.callback_query.answer("无权管理该群签到配置", show_alert=True)
        return
    async with context.application.bot_data["db"].session_factory() as session:
        settings = await session.scalar(select(ChatSettings).where(ChatSettings.chat_id == chat_id).with_for_update())
        if settings is None:
            await MessageHelper.safe_edit(update, "群配置不存在。")
            return
        if not await _configure(update, session, settings=settings, chat_id=chat_id, cb=cb):
            return
        config = get_module_config(settings, "sign_feedback")
        await session.commit()
    await _show_config(update, chat_id, config=config)


async def _configure(update, session, *, settings, chat_id: int, cb) -> bool:
    action, key = cb.get(2), cb.get(3)
    if action == "set" and key in {"show_count", "show_rank"} and cb.get(4) in {"0", "1"}:
        await update_module_config(session, settings, module="sign_feedback", patch={key: cb.get(4) == "1"})
    elif action == "input" and key in {"template", "delete_seconds"}:
        await _start_input(update, session, chat_id=chat_id, key=key)
        await session.commit()
        return False
    elif action != "view":
        await update.callback_query.answer("无效签到配置", show_alert=True)
        return False
    return True


async def _start_input(update, session, *, chat_id: int, key: str):
    await set_user_state(session, update.effective_user.id, update.effective_user.id,
        state_type="sign_feedback_input", state_data={"target_chat_id": chat_id, "key": key})
    prompt = "输入签到反馈文案（纯文本）。支持 {points} {balance} {days} {bonus} {total} {position}；输入 清空 恢复默认。"
    if key == "delete_seconds":
        prompt = "输入反馈保留秒数（0 为不删除，最多 86400 秒）。"
    await MessageHelper.safe_edit(update, prompt, reply_markup=InlineKeyboardMarkup([[
        InlineKeyboardButton("返回签到反馈", callback_data=f"signcfg:{chat_id}:view")]]))


async def _show_config(update, chat_id: int, *, config: dict):
    rows = []
    for key, title in (("show_count", "显示签到人数"), ("show_rank", "显示签到名次")):
        enabled = bool(config.get(key))
        rows.append([InlineKeyboardButton(title, callback_data=f"signcfg:{chat_id}:view"),
            InlineKeyboardButton("✅ 开启" if enabled else "开启", callback_data=f"signcfg:{chat_id}:set:{key}:1"),
            InlineKeyboardButton("关闭" if enabled else "✅ 关闭", callback_data=f"signcfg:{chat_id}:set:{key}:0")])
    rows.extend([[InlineKeyboardButton("签到文案", callback_data=f"signcfg:{chat_id}:input:template"),
        InlineKeyboardButton("反馈保留时长", callback_data=f"signcfg:{chat_id}:input:delete_seconds")],
        [InlineKeyboardButton("返回签到规则", callback_data=f"pts:rule:checkin:{chat_id}")]])
    text = f"签到反馈\n群：{chat_id}\n保留时长：{config.get('delete_seconds', 0)} 秒（0 不删）\n"
    text += "签到人数按 Asia/Shanghai 当天的有效签到去重；签到名次与积分排行分别计算。\n"
    text += "当前文案：" + (config.get("template") or "默认文案")
    await MessageHelper.safe_edit(update, text, reply_markup=InlineKeyboardMarkup(rows))


async def handle_sign_feedback_input(update, context, session, *, state, message_text):
    data = state.state_data or {}
    chat_id, key = data.get("target_chat_id"), data.get("key")
    if not isinstance(chat_id, int) or chat_id >= 0 or not await PermissionPolicyService.can_manage(context, chat_id, update.effective_user.id, capability="points"):
        await clear_user_state(session, state.chat_id, update.effective_user.id)
        await session.commit()
        await update.effective_message.reply_text("权限已失效，已退出。")
        return
    try:
        value = _parse_value(key, message_text.strip())
    except ValueError as exc:
        await update.effective_message.reply_text(str(exc))
        return
    settings = await session.scalar(select(ChatSettings).where(ChatSettings.chat_id == chat_id).with_for_update())
    if settings is None:
        await clear_user_state(session, state.chat_id, update.effective_user.id)
        await session.commit()
        await update.effective_message.reply_text("群配置已失效，已退出。")
        return
    await update_module_config(session, settings, module="sign_feedback", patch={str(key): value})
    await clear_user_state(session, state.chat_id, update.effective_user.id)
    await session.commit()
    await _show_config(update, chat_id, config=get_module_config(settings, "sign_feedback"))


def _parse_value(key: str, text: str):
    if key == "template":
        return None if text == "清空" else validate_template(text)
    if key == "delete_seconds" and text.isascii() and text.isdigit() and int(text) <= MAX_DELETE_SECONDS:
        return int(text)
    raise ValueError("请输入 0—86400 的整数秒数。")
