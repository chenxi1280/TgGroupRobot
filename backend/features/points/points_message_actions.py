from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database


async def handle_message_points_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    ensure_chat_func,
    ensure_user_func,
    get_chat_settings_func,
    points_extended_service,
    add_message_points_func,
    required_level_permission_func,
    should_send_level_block_notice_func,
    show_mall_catalog_func,
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
