from __future__ import annotations

from sqlalchemy import delete
from telegram.ext import ConversationHandler, ContextTypes

from backend.features.admin.points_config_shared import WAIT_VALUE, resolve_points_target_user, safe_edit_message, log
from backend.features.admin.points_config_views import show_points_home
from backend.features.admin.ui.points import points_config_keyboard
from backend.features.points.services.points_service import change_points
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.core import PointsAccount, PointsTransaction, SignInLog, UserDailyStats
from backend.platform.db.schema.models.enums import PointsTxnType
from backend.shared.services.chat_service import get_chat_settings


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

            if field == "transfer":
                parts = text.strip().split(maxsplit=2)
                if len(parts) < 2:
                    await update.effective_message.reply_text("格式错误，请输入：目标用户 金额 原因(可选)")
                    return WAIT_VALUE
                target_user = await resolve_points_target_user(session, parts[0])
                if target_user is None:
                    await update.effective_message.reply_text("目标用户不存在，请输入已记录的用户 ID 或 @用户名")
                    return WAIT_VALUE
                amount = int(parts[1])
                if amount <= 0:
                    await update.effective_message.reply_text("转让积分必须大于 0")
                    return WAIT_VALUE
                if target_user.id == update.effective_user.id:
                    await update.effective_message.reply_text("不能给自己转让积分")
                    return WAIT_VALUE
                reason = parts[2] if len(parts) > 2 else "管理员面板转让积分"
                ok, _ = await change_points(
                    session,
                    chat_id,
                    update.effective_user.id,
                    -amount,
                    PointsTxnType.penalty.value,
                    reason=f"转让给 {target_user.id}: {reason}",
                )
                if not ok:
                    await update.effective_message.reply_text("积分不足，无法转让。")
                    return WAIT_VALUE
                await change_points(
                    session,
                    chat_id,
                    target_user.id,
                    amount,
                    PointsTxnType.reward.value,
                    reason=f"来自 {update.effective_user.id} 的积分转让: {reason}",
                )
            elif field in {"admin_add", "admin_deduct"}:
                parts = text.strip().split(maxsplit=2)
                if len(parts) < 2:
                    await update.effective_message.reply_text("格式错误，请输入：目标用户 金额 原因(可选)")
                    return WAIT_VALUE
                target_user = await resolve_points_target_user(session, parts[0])
                if target_user is None:
                    await update.effective_message.reply_text("目标用户不存在，请输入已记录的用户 ID 或 @用户名")
                    return WAIT_VALUE
                amount = int(parts[1])
                if amount <= 0:
                    await update.effective_message.reply_text("积分数量必须大于 0")
                    return WAIT_VALUE
                signed_amount = amount if field == "admin_add" else -amount
                reason_prefix = "管理员增加积分" if field == "admin_add" else "管理员扣除积分"
                reason = parts[2] if len(parts) > 2 else reason_prefix
                ok, _ = await change_points(
                    session,
                    chat_id,
                    target_user.id,
                    signed_amount,
                    PointsTxnType.admin_adjust.value,
                    reason=reason,
                )
                if not ok:
                    await update.effective_message.reply_text("目标用户积分不足，无法扣除。")
                    return WAIT_VALUE
            elif field == "clear_points":
                if text.strip().upper() != "CONFIRM":
                    await update.effective_message.reply_text("请输入 CONFIRM 确认清空积分。")
                    return WAIT_VALUE
                await session.execute(delete(PointsAccount).where(PointsAccount.chat_id == chat_id))
                await session.execute(delete(PointsTransaction).where(PointsTransaction.chat_id == chat_id))
                await session.execute(delete(UserDailyStats).where(UserDailyStats.chat_id == chat_id))
                await session.execute(delete(SignInLog).where(SignInLog.chat_id == chat_id))
            elif field == "sign_consecutive":
                parts = text.split(",")
                if len(parts) != 2:
                    await update.effective_message.reply_text("格式错误，请输入：天数,积分（例如 7,10）")
                    return WAIT_VALUE
                settings.sign_consecutive_days = int(parts[0].strip())
                settings.sign_consecutive_bonus = int(parts[1].strip())
            elif field in ["message_daily_limit", "message_min_length", "invite_daily_limit"]:
                value = int(text.strip())
                setattr(settings, field, value if value > 0 else None)
            elif field in ["points_alias", "points_rank_alias"]:
                setattr(settings, field, text.strip())
            else:
                setattr(settings, field, int(text.strip()))

            await session.commit()
            settings = await get_chat_settings(session, chat_id)
            await session.commit()

        keyboard = points_config_keyboard(settings, chat_id)
        success_text = "✅ 配置已更新"
        if field == "transfer":
            success_text = "✅ 积分转让成功"
        elif field == "admin_add":
            success_text = "✅ 增加积分成功"
        elif field == "admin_deduct":
            success_text = "✅ 扣除积分成功"
        elif field == "clear_points":
            success_text = "✅ 已清空本群主积分数据"
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
        await safe_edit_func(update.callback_query, "💰 主积分", reply_markup=keyboard)

    return ConversationHandler.END
