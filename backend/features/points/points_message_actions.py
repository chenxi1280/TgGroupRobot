from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.platform.db.schema.models.enums import PointsTxnType
from backend.platform.db.runtime.session import Database
from backend.shared.services.permission_service import PermissionPolicyService


_ADMIN_ADD_COMMANDS = {"加积分", "加分"}
_ADMIN_DEDUCT_COMMANDS = {"扣积分", "扣分"}


def _user_label(user) -> str:
    username = getattr(user, "username", None)
    if username:
        return f"@{username}"
    full_name = " ".join(
        item
        for item in (
            getattr(user, "first_name", None),
            getattr(user, "last_name", None),
        )
        if item
    ).strip()
    return full_name or str(getattr(user, "id", "用户"))


def _parse_admin_adjustment(text: str) -> tuple[int, str, str] | None:
    parts = text.strip().split(maxsplit=2)
    if not parts:
        return None
    command = parts[0]
    if command not in _ADMIN_ADD_COMMANDS and command not in _ADMIN_DEDUCT_COMMANDS:
        return None
    if len(parts) < 2:
        return 0, "", command
    try:
        amount = int(parts[1])
    except ValueError:
        return 0, "", command
    if amount <= 0:
        return 0, "", command
    if command in _ADMIN_DEDUCT_COMMANDS:
        amount = -amount
    default_reason = "管理员增加积分" if amount > 0 else "管理员扣除积分"
    reason = parts[2].strip() if len(parts) >= 3 and parts[2].strip() else default_reason
    return amount, reason[:255], command


async def _handle_admin_adjustment(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    *,
    chat,
    operator,
    message,
    text: str,
    ensure_user_func,
    change_points_func,
    require_manage_func,
) -> bool:
    parsed = _parse_admin_adjustment(text)
    if parsed is None:
        return False

    amount, reason, command = parsed
    usage = f"{command} 数字 备注"
    if amount == 0:
        await session.commit()
        await message.reply_text(f"格式错误，请使用：回复成员消息后发送“{usage}”。")
        return True

    replied_message = getattr(message, "reply_to_message", None)
    target_user = getattr(replied_message, "from_user", None)
    if target_user is None:
        await session.commit()
        await message.reply_text(f"请回复成员消息使用：{usage}")
        return True

    allowed, error_text = await require_manage_func(context, chat.id, operator.id, capability="points")
    if not allowed:
        await session.commit()
        await message.reply_text(error_text or "需要管理员权限")
        return True

    await ensure_user_func(
        session,
        user_id=getattr(target_user, "id"),
        username=getattr(target_user, "username", None),
        first_name=getattr(target_user, "first_name", None),
        last_name=getattr(target_user, "last_name", None),
        language_code=getattr(target_user, "language_code", None),
    )
    ok, balance = await change_points_func(
        session,
        chat.id,
        target_user.id,
        amount,
        PointsTxnType.admin_adjust.value,
        reason=reason,
    )
    await session.commit()
    if not ok:
        await message.reply_text("目标用户积分不足，无法扣除。")
        return True

    action = "增加" if amount > 0 else "扣除"
    await message.reply_text(
        f"✅ 已为 {_user_label(target_user)} {action} {abs(amount)} 积分，当前积分 {balance}。\n备注：{reason}"
    )
    return True


async def handle_message_points_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    ensure_chat_func,
    ensure_user_func,
    get_chat_settings_func,
    points_extended_service,
    change_points_func,
    sign_in_func,
    get_balance_func,
    get_user_rank_func,
    get_leaderboard_func,
    format_sign_in_success_message_func,
    format_sign_in_already_message_func,
    format_balance_message_func,
    format_leaderboard_message_func,
    add_message_points_func,
    required_level_permission_func,
    should_send_level_block_notice_func,
    show_mall_catalog_func,
    require_manage_func=PermissionPolicyService.require_manage,
) -> None:
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return
    if update.effective_chat.type not in ["group", "supergroup"]:
        return

    db: Database = context.application.bot_data["db"]
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    text = (message.text or "").strip()

    async with db.session_factory() as session:
        await ensure_chat_func(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
        await ensure_user_func(
            session,
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            language_code=user.language_code,
        )
        settings = await get_chat_settings_func(session, chat.id)

        handled_adjustment = await _handle_admin_adjustment(
            update,
            context,
            session,
            chat=chat,
            operator=user,
            message=message,
            text=text,
            ensure_user_func=ensure_user_func,
            change_points_func=change_points_func,
            require_manage_func=require_manage_func,
        )
        if handled_adjustment:
            return

        if text == "签到":
            sign_enabled = bool(getattr(settings, "sign_enabled", False))
            sign_points = int(getattr(settings, "sign_points", 0) or 0)
            if not sign_enabled:
                await session.commit()
                await update.effective_message.reply_text("本群未开启签到。")
                return
            result = await sign_in_func(
                session,
                chat_id=chat.id,
                user_id=user.id,
                points=sign_points,
                consecutive_days=int(getattr(settings, "sign_consecutive_days", 0) or 0),
                consecutive_bonus=int(getattr(settings, "sign_consecutive_bonus", 0) or 0),
            )
            await session.commit()
            if result.success:
                msg = format_sign_in_success_message_func(
                    points=sign_points,
                    balance=result.balance,
                    consecutive_days=result.consecutive_days,
                    bonus_points=result.bonus_points,
                )
            else:
                msg = format_sign_in_already_message_func(
                    balance=result.balance,
                    consecutive_days=result.consecutive_days,
                )
            await update.effective_message.reply_text(msg)
            return

        points_rank_alias = getattr(settings, "points_rank_alias", "积分排行")
        points_alias = getattr(settings, "points_alias", "积分")

        if text == points_rank_alias:
            leaderboard = await get_leaderboard_func(session, chat.id, limit=10)
            await session.commit()
            await update.effective_message.reply_text(format_leaderboard_message_func(leaderboard))
            return

        if text == points_alias:
            balance = await get_balance_func(session, chat.id, user.id)
            rank = await get_user_rank_func(session, chat.id, user.id)
            await session.commit()
            await update.effective_message.reply_text(format_balance_message_func(balance, rank))
            return

        mall_setting = await points_extended_service.get_or_create_mall_setting(session, chat.id)
        level_setting = await points_extended_service.get_or_create_level_setting(session, chat.id)

        if text and mall_setting.enabled and text == mall_setting.entry_command:
            products = await points_extended_service.list_on_sale_products(session, chat.id)
            await session.commit()
            if not products:
                await update.effective_message.reply_text("积分商城暂时没有可兑换商品。")
                return
            await show_mall_catalog_func(update, context, chat.id, products=products)
            return

        if text:
            custom_types = await points_extended_service.list_custom_point_types(session, chat.id)
            matched_type = next((item for item in custom_types if item.rank_command and text == item.rank_command), None)
            if matched_type is not None and not matched_type.enabled:
                await session.commit()
                await update.effective_message.reply_text(f"{matched_type.name} 已关闭。")
                return
            if matched_type is not None:
                rows = await points_extended_service.get_custom_point_leaderboard(
                    session,
                    chat_id=chat.id,
                    type_id=matched_type.id,
                    limit=10,
                )
                await session.commit()
                if not rows:
                    await update.effective_message.reply_text(f"{matched_type.name} 暂无排行数据。")
                    return
                lines = [f"🌐 {matched_type.name} 排行", ""]
                for index, (rank_user_id, balance) in enumerate(rows, start=1):
                    lines.append(f"{index}. {rank_user_id}｜{balance}")
                await update.effective_message.reply_text("\n".join(lines))
                return

        if level_setting.enabled:
            if level_setting.exclude_teacher_enabled:
                teacher_exempt = await points_extended_service.is_teacher_exempt(session, chat.id, user.id)
                if teacher_exempt:
                    await session.commit()
                    return
            level = await points_extended_service.resolve_user_level(session, chat.id, user.id)
            required_perm = required_level_permission_func(message)
            if required_perm is not None:
                allowed = True if level is None else bool(getattr(level, required_perm, False))
                if not allowed:
                    await session.commit()
                    try:
                        await message.delete()
                    except Exception:
                        pass
                    if should_send_level_block_notice_func(context, chat.id, user.id):
                        try:
                            await update.effective_chat.send_message("当前积分等级不足，无法发送此类消息。")
                        except Exception:
                            pass
                    return

        if not text or not settings.message_points_enabled:
            await session.commit()
            return

        await add_message_points_func(
            session,
            chat_id=chat.id,
            user_id=user.id,
            points=settings.message_points,
            daily_limit=settings.message_points_daily_limit,
            min_length=settings.message_min_length,
            message_length=len(text),
        )
        await session.commit()
