from __future__ import annotations

from sqlalchemy import delete
from telegram.ext import ConversationHandler, ContextTypes

from backend.features.admin.points_config_shared import WAIT_VALUE, resolve_points_target_user, safe_edit_message, log
from backend.features.admin.ui.points import format_points_home_text, points_config_keyboard
from backend.features.points.services.points_service import change_points
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.core import PointsAccount, PointsTransaction, SignInLog, UserDailyStats
from backend.platform.db.schema.models.enums import PointsTxnType
from backend.shared.services.chat_service import get_chat_settings
_HANDLE_POINTS_CONFIG_MESSAGE_THRESHOLD_2 = 2



async def _resolve_points_adjustment_input(message, session, text: str, *, amount_error: str):
    parts = text.strip().split(maxsplit=2)
    if len(parts) < _HANDLE_POINTS_CONFIG_MESSAGE_THRESHOLD_2:
        await message.reply_text("格式错误，请输入：目标用户 金额 原因(可选)")
        return None
    target_user = await resolve_points_target_user(session, parts[0])
    if target_user is None:
        await message.reply_text("目标用户不存在，请输入已记录的用户 ID 或 @用户名")
        return None
    amount = int(parts[1])
    if amount <= 0:
        await message.reply_text(amount_error)
        return None
    reason = parts[2] if len(parts) > _HANDLE_POINTS_CONFIG_MESSAGE_THRESHOLD_2 else None
    return target_user, amount, reason


async def _apply_points_transfer(message, session, chat_id: int, *, text: str, actor_user_id: int) -> bool:
    parsed = await _resolve_points_adjustment_input(message, session, text, amount_error="转让积分必须大于 0")
    if parsed is None:
        return False
    target_user, amount, reason = parsed
    if target_user.id == actor_user_id:
        await message.reply_text("不能给自己转让积分")
        return False
    reason = reason or "管理员面板转让积分"
    ok, _ = await change_points(
        session, chat_id, actor_user_id, amount=-amount,
        txn_type=PointsTxnType.penalty.value, reason=f"转让给 {target_user.id}: {reason}",
    )
    if not ok:
        await message.reply_text("积分不足，无法转让。")
        return False
    await change_points(
        session, chat_id, target_user.id, amount=amount,
        txn_type=PointsTxnType.reward.value, reason=f"来自 {actor_user_id} 的积分转让: {reason}",
    )
    return True


async def _apply_admin_points_adjustment(message, session, chat_id: int, *, text: str, field: str) -> bool:
    parsed = await _resolve_points_adjustment_input(message, session, text, amount_error="积分数量必须大于 0")
    if parsed is None:
        return False
    target_user, amount, reason = parsed
    is_add = field == "admin_add"
    reason = reason or ("管理员增加积分" if is_add else "管理员扣除积分")
    ok, _ = await change_points(
        session, chat_id, target_user.id, amount=amount if is_add else -amount,
        txn_type=PointsTxnType.admin_adjust.value, reason=reason,
    )
    if not ok:
        await message.reply_text("目标用户积分不足，无法扣除。")
        return False
    return True


async def _clear_chat_points(message, session, chat_id: int, *, text: str) -> bool:
    if text.strip().upper() != "CONFIRM":
        await message.reply_text("请输入 CONFIRM 确认清空积分。")
        return False
    for model in (PointsAccount, PointsTransaction, UserDailyStats, SignInLog):
        await session.execute(delete(model).where(model.chat_id == chat_id))
    return True


async def _apply_points_config_field(session, settings, update, *, field: str, text: str, chat_id: int) -> bool:
    message = update.effective_message
    if field == "transfer":
        return await _apply_points_transfer(message, session, chat_id, text=text, actor_user_id=update.effective_user.id)
    if field in {"admin_add", "admin_deduct"}:
        return await _apply_admin_points_adjustment(message, session, chat_id, text=text, field=field)
    if field == "clear_points":
        return await _clear_chat_points(message, session, chat_id, text=text)
    if field == "sign_consecutive":
        parts = text.split(",")
        if len(parts) != _HANDLE_POINTS_CONFIG_MESSAGE_THRESHOLD_2:
            await message.reply_text("格式错误，请输入：天数,积分（例如 7,10）")
            return False
        settings.sign_consecutive_days = int(parts[0].strip())
        settings.sign_consecutive_bonus = int(parts[1].strip())
        return True
    if field in {"message_daily_limit", "message_min_length", "invite_daily_limit"}:
        value = int(text.strip())
        setattr(settings, field, value if value > 0 else None)
        return True
    if field in {"points_alias", "points_rank_alias"}:
        setattr(settings, field, text.strip())
        from backend.features.points.points_handler import get_points_alias_handler
        get_points_alias_handler().clear_cache(chat_id)
        return True
    setattr(settings, field, int(text.strip()))
    return True


def _points_config_success_text(field: str) -> str:
    return {
        "transfer": "✅ 积分转让成功",
        "admin_add": "✅ 增加积分成功",
        "admin_deduct": "✅ 扣除积分成功",
        "clear_points": "✅ 已清空本群主积分数据",
    }.get(field, "✅ 配置已更新")


async def handle_points_config_message(update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    if update.effective_chat is None or update.effective_message is None:
        return ConversationHandler.END
    if update.effective_chat.type != "private":
        return ConversationHandler.END

    text = update.effective_message.text
    if not text:
        return ConversationHandler.END

    field = context.user_data.get("points_edit_field")
    chat_id = context.user_data.get("points_edit_chat_id")
    if not field or chat_id is None:
        return ConversationHandler.END

    db: Database = context.application.bot_data["db"]

    try:
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            applied = await _apply_points_config_field(
                session, settings, update, field=field, text=text, chat_id=chat_id
            )
            if not applied:
                return WAIT_VALUE
            await session.commit()
            settings = await get_chat_settings(session, chat_id)
            await session.commit()

        keyboard = points_config_keyboard(settings, chat_id)
        success_text = _points_config_success_text(field)
        await update.effective_message.reply_text(success_text, reply_markup=keyboard)

        context.user_data.pop("points_edit_field", None)
        context.user_data.pop("points_edit_chat_id", None)
        return ConversationHandler.END

    except ValueError:
        await update.effective_message.reply_text("输入格式错误，请输入有效的数字")
        return WAIT_VALUE
    except Exception as exc:
        log.error("points_config_error", error=str(exc))
        await update.effective_message.reply_text(f"配置失败：{str(exc)}")
        return ConversationHandler.END


async def handle_points_config_cancel(
    update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    get_chat_settings_func=get_chat_settings,
    safe_edit_func=safe_edit_message,
) -> int:
    chat_id = context.user_data.get("points_edit_chat_id")
    context.user_data.pop("points_edit_field", None)
    context.user_data.pop("points_edit_chat_id", None)

    if update.callback_query and chat_id:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            settings = await get_chat_settings_func(session, chat_id)
            await session.commit()

        keyboard = points_config_keyboard(settings, chat_id)
        await safe_edit_func(update.callback_query, format_points_home_text(settings), reply_markup=keyboard)

    return ConversationHandler.END
