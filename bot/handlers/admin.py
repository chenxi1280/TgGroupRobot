from __future__ import annotations

import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest, TelegramError

from bot.db.session import Database
from bot.i18n.strings import t
from bot.keyboards.admin import admin_main_menu, toggle_menu, verification_mode_menu
from bot.services.chat_group_service import get_user_current_chat, get_user_managed_chats, set_user_current_chat
from bot.services.chat_service import ensure_chat, get_chat_settings
from bot.services.telegram_perm import is_user_admin


def _settings_toggle_rows(settings) -> list[tuple[str, str, bool]]:
    return [
        ("签到", "sign_enabled", settings.sign_enabled),
        ("进群欢迎", "welcome_enabled", settings.welcome_enabled),
        ("新人验证", "verification_enabled", settings.verification_enabled),
        ("内容审核", "moderation_enabled", settings.moderation_enabled),
        ("屏蔽链接", "moderation_block_links", settings.moderation_block_links),
        ("反刷屏", "anti_flood_enabled", settings.anti_flood_enabled),
        ("广告", "ads_enabled", settings.ads_enabled),
        ("商业化", "monetization_enabled", settings.monetization_enabled),
    ]


log = structlog.get_logger(__name__)


async def _safe_edit_message(q, text: str, **kwargs) -> None:
    """安全地编辑消息，忽略"Message is not modified"错误"""
    try:
        await q.edit_message_text(text, **kwargs)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            # 忽略此错误，用户只是重复点击了相同的按钮
            log.debug("message_not_modified", callback_data=q.data)
        else:
            raise
    except TelegramError as e:
        log.error("edit_message_failed", error=str(e))
        raise


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """管理员命令 - 在群聊中引导到私聊设置"""
    log.info("admin_command_called")

    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        log.warning("admin_command_missing_update_data")
        return

    chat = update.effective_chat
    user = update.effective_user

    # 群聊中：引导用户到私聊进行设置
    if chat.type != "private":
        # 检查管理员权限
        try:
            is_admin = await is_user_admin(context, chat.id, user.id)
        except TelegramError as e:
            log.error("admin_command_get_chat_member_failed", error=str(e))
            await update.effective_message.reply_text("无法获取管理员信息，请确保 bot 有读取群成员的权限")
            return

        if not is_admin:
            await update.effective_message.reply_text("此命令仅限管理员使用")
            return

        db: Database = context.application.bot_data["db"]

        # 设置当前管理的群组
        await set_user_current_chat(db, user.id, chat.id)

        # 保存群组信息
        async with db.session_factory() as session:
            await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
            await session.commit()

        # 发送引导按钮，点击后跳转到私聊
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎛️ 前往设置", url=f"https://t.me/{context.bot.username}")],
        ])
        await update.effective_message.reply_text(
            f"⚙️ 管理面板\n\n"
            f"请点击下方按钮前往私聊进行设置，保护群组管理安全。",
            reply_markup=keyboard
        )
        return

    # 私聊中：显示管理面板
    db: Database = context.application.bot_data["db"]

    # 获取用户管理的群组
    chats = await get_user_managed_chats(db, user.id, context.bot)
    current_chat_id = await get_user_current_chat(db, user.id)

    if not chats:
        await update.effective_message.reply_text(
            "👋 欢迎使用群管理 Bot！\n\n"
            "暂无群组，请先将 bot 添加到群组中并设为管理员..."
        )
        return

    # 如果没有选中的群组，默认选择第一个
    if current_chat_id is None and chats:
        current_chat_id = chats[0][0]  # 第一个群组的 chat_id
        await set_user_current_chat(db, user.id, current_chat_id)

    # 显示管理面板
    await _show_private_admin_menu(update, context, current_chat_id, chats)


async def _show_private_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, managed_chats: list) -> None:
    """在私聊中显示管理面板"""
    db: Database = context.application.bot_data["db"]

    async with db.session_factory() as session:
        from bot.models.core import TgChat
        from sqlalchemy import select

        # 获取群组信息
        chat_stmt = select(TgChat).where(TgChat.id == chat_id)
        chat_result = await session.execute(chat_stmt)
        chat = chat_result.scalar_one_or_none()

        if not chat:
            await update.effective_message.reply_text("群组不存在")
            return

        settings = await get_chat_settings(session, chat_id)
        await session.commit()

    # 查找当前群组在列表中的标题
    current_chat_title = chat.title if chat else f"群组{chat_id}"

    # 构建管理面板
    text = f"🎛️ 群组管理\n\n"
    text += f"📍 当前群组: {current_chat_title}\n\n"
    text += f"请选择要管理的内容："

    # 构建键盘
    keyboard = _private_admin_keyboard(chat_id, managed_chats)

    if update.callback_query:
        await _safe_edit_message(update.callback_query, text, reply_markup=keyboard)
    else:
        await update.effective_message.reply_text(text, reply_markup=keyboard)


def _private_admin_keyboard(chat_id: int, managed_chats: list) -> InlineKeyboardMarkup:
    """私聊管理面板键盘"""
    buttons = []

    # 第一行：切换群组按钮
    if len(managed_chats) > 1:
        buttons.append([InlineKeyboardButton("🔄 切换群组", callback_data=f"adm:switch_group")])

    # 功能菜单
    buttons.append([InlineKeyboardButton("⚙️ 群组设置", callback_data=f"adm:private:settings:{chat_id}")])
    buttons.append([InlineKeyboardButton("🎁 抽奖管理", callback_data=f"adm:private:lottery:{chat_id}")])
    buttons.append([InlineKeyboardButton("📋 接龙管理", callback_data=f"adm:private:solitaire:{chat_id}")])
    buttons.append([InlineKeyboardButton("🔗 邀请链接", callback_data=f"adm:private:invite:{chat_id}")])
    buttons.append([InlineKeyboardButton("💬 自动回复", callback_data=f"adm:private:autoreply:{chat_id}")])
    buttons.append([InlineKeyboardButton("🔇 违禁词", callback_data=f"adm:private:keywords:{chat_id}")])
    buttons.append([InlineKeyboardButton("⏰ 定时消息", callback_data=f"adm:private:scheduled:{chat_id}")])

    return InlineKeyboardMarkup(buttons)


async def _show_group_selection(update: Update, managed_chats: list, current_chat_id: int | None) -> None:
    """显示群组选择列表"""
    buttons = []

    for chat_id, title, is_admin in managed_chats:
        is_current = "✅ " if chat_id == current_chat_id else ""
        buttons.append([
            InlineKeyboardButton(f"{is_current}{title}", callback_data=f"adm:select_group:{chat_id}")
        ])

    buttons.append([InlineKeyboardButton("🔙 返回", callback_data=f"adm:back_to_main")])

    text = "🔄 选择要管理的群组："

    if update.callback_query:
        await _safe_edit_message(update.callback_query, text, reply_markup=InlineKeyboardMarkup(buttons))


# 私聊管理功能处理器
async def _handle_private_settings(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    """处理私聊中的群组设置"""
    db: Database = context.application.bot_data["db"]
    user_id = update.effective_user.id

    async with db.session_factory() as session:
        from bot.models.core import TgChat
        from sqlalchemy import select

        chat_stmt = select(TgChat).where(TgChat.id == chat_id)
        chat_result = await session.execute(chat_stmt)
        chat = chat_result.scalar_one_or_none()

        settings = await get_chat_settings(session, chat_id)
        await session.commit()

    chat_title = chat.title if chat else f"群组{chat_id}"
    text = f"⚙️ [{chat_title}] 群组设置\n\n"
    text += "请选择要修改的项目："

    # 返回按钮
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ 签到功能", callback_data=f"adm:toggle:{chat_id}:sign_enabled")],
        [InlineKeyboardButton("✅ 进群欢迎", callback_data=f"adm:toggle:{chat_id}:welcome_enabled")],
        [InlineKeyboardButton("✅ 新人验证", callback_data=f"adm:toggle:{chat_id}:verification_enabled")],
        [InlineKeyboardButton("✅ 内容审核", callback_data=f"adm:toggle:{chat_id}:moderation_enabled")],
        [InlineKeyboardButton("✅ 屏蔽链接", callback_data=f"adm:toggle:{chat_id}:moderation_block_links")],
        [InlineKeyboardButton("✅ 反刷屏", callback_data=f"adm:toggle:{chat_id}:anti_flood_enabled")],
        [InlineKeyboardButton("🔙 返回", callback_data=f"adm:back_to_menu:{chat_id}")],
    ])

    if update.callback_query:
        await _safe_edit_message(update.callback_query, text, reply_markup=keyboard)


async def _handle_private_lottery(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    """处理私聊中的抽奖管理"""
    from bot.keyboards.lottery import lottery_menu_keyboard
    from bot.services.lottery_service import get_lottery_stats

    db: Database = context.application.bot_data["db"]

    async with db.session_factory() as session:
        from bot.models.core import TgChat
        from sqlalchemy import select

        chat_stmt = select(TgChat).where(TgChat.id == chat_id)
        chat_result = await session.execute(chat_stmt)
        chat = chat_result.scalar_one_or_none()

        stats = await get_lottery_stats(session, chat_id)
        await session.commit()

    chat_title = chat.title if chat else f"群组{chat_id}"
    text = f"🎁[{chat_title}]抽奖\n\n"
    text += f"创建的抽奖次数:{stats['total']}\n\n"
    text += f"已开奖:{stats['completed']}       未开奖:{stats['pending']}       取消:{stats['cancelled']}"

    if update.callback_query:
        await _safe_edit_message(update.callback_query, text, reply_markup=lottery_menu_keyboard())


async def _handle_private_solitaire(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    """处理私聊中的接龙管理"""
    from bot.keyboards.solitaire import solitaire_list_keyboard
    from bot.services.solitaire_service import get_chat_solitaires

    db: Database = context.application.bot_data["db"]

    async with db.session_factory() as session:
        from bot.models.core import TgChat
        from sqlalchemy import select

        chat_stmt = select(TgChat).where(TgChat.id == chat_id)
        chat_result = await session.execute(chat_stmt)
        chat = chat_result.scalar_one_or_none()

        solitaires = await get_chat_solitaires(session, chat_id)
        await session.commit()

    chat_title = chat.title if chat else f"群组{chat_id}"
    text = f"📋 [{chat_title}] 接龙管理\n\n"
    text += f"活跃接龙: {len([s for s in solitaires if s.status == 'active'])}\n"
    text += f"总接龙数: {len(solitaires)}"

    keyboard = solitaire_list_keyboard(solitaires)

    if update.callback_query:
        await _safe_edit_message(update.callback_query, text, reply_markup=keyboard)


async def _handle_private_invite(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    """处理私聊中的邀请链接管理"""
    from bot.keyboards.invite_link import invite_link_menu_keyboard

    text = "🔗 邀请链接管理\n\n请选择操作："

    keyboard = invite_link_menu_keyboard()

    if update.callback_query:
        await _safe_edit_message(update.callback_query, text, reply_markup=keyboard)


async def _handle_private_autoreply(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    """处理私聊中的自动回复管理"""
    from bot.keyboards.auto_reply import auto_reply_menu_keyboard

    text = "💬 自动回复管理\n\n请选择操作："

    keyboard = auto_reply_menu_keyboard()

    if update.callback_query:
        await _safe_edit_message(update.callback_query, text, reply_markup=keyboard)


async def _handle_private_keywords(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    """处理私聊中的违禁词管理"""
    from bot.keyboards.banned_word import banned_word_menu_keyboard

    text = "🔇 违禁词管理\n\n请选择操作："

    keyboard = banned_word_menu_keyboard()

    if update.callback_query:
        await _safe_edit_message(update.callback_query, text, reply_markup=keyboard)


async def _handle_private_scheduled(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    """处理私聊中的定时消息管理"""
    from bot.keyboards.scheduled import scheduled_menu_keyboard

    text = "⏰ 定时消息管理\n\n请选择操作："

    keyboard = scheduled_menu_keyboard()

    if update.callback_query:
        await _safe_edit_message(update.callback_query, text, reply_markup=keyboard)


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """管理回调 - 支持群聊内联按钮和私聊管理"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user
    data = q.data or ""
    parts = data.split(":")

    # 私聊中的管理回调
    if chat.type == "private":
        # adm:switch_group - 切换群组
        if len(parts) >= 2 and parts[1] == "switch_group":
            db: Database = context.application.bot_data["db"]
            chats = await get_user_managed_chats(db, user.id, context.bot)
            current_chat_id = await get_user_current_chat(db, user.id)

            # 显示群组选择列表
            await _show_group_selection(update, chats, current_chat_id)
            return

        # adm:select_group:chat_id - 选择群组
        if len(parts) >= 3 and parts[1] == "select_group":
            chat_id = int(parts[2])
            db: Database = context.application.bot_data["db"]
            await set_user_current_chat(db, user.id, chat_id)
            chats = await get_user_managed_chats(db, user.id, context.bot)
            await _show_private_admin_menu(update, context, chat_id, chats)
            return

        # adm:back_to_main - 返回主菜单
        if len(parts) >= 2 and parts[1] == "back_to_main":
            db: Database = context.application.bot_data["db"]
            current_chat_id = await get_user_current_chat(db, user.id)
            chats = await get_user_managed_chats(db, user.id, context.bot)
            if current_chat_id is None and chats:
                current_chat_id = chats[0][0]
            await _show_private_admin_menu(update, context, current_chat_id, chats)
            return

        # adm:back_to_menu:chat_id - 返回指定群组的菜单
        if len(parts) >= 3 and parts[1] == "back_to_menu":
            chat_id = int(parts[2])
            db: Database = context.application.bot_data["db"]
            chats = await get_user_managed_chats(db, user.id, context.bot)
            await _show_private_admin_menu(update, context, chat_id, chats)
            return

        # adm:toggle:chat_id:field - 切换设置
        if len(parts) >= 4 and parts[1] == "toggle":
            chat_id = int(parts[2])
            field = parts[3]

            if not await is_user_admin(context, chat_id, user.id):
                await _safe_edit_message(q, "你没有该群组的管理权限")
                return

            db: Database = context.application.bot_data["db"]
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                if hasattr(settings, field):
                    current = bool(getattr(settings, field))
                    setattr(settings, field, not current)
                    await session.commit()
            await _handle_private_settings(update, context, chat_id)
            return

        # adm:private:xxx:chat_id - 私聊中的管理功能
        if len(parts) >= 4 and parts[1] == "private":
            action = parts[2]
            chat_id = int(parts[3])

            # 检查用户是否有权限管理该群组
            if not await is_user_admin(context, chat_id, user.id):
                await _safe_edit_message(q, "你没有该群组的管理权限")
                return

            # 处理不同的管理功能
            if action == "settings":
                await _handle_private_settings(update, context, chat_id)
            elif action == "lottery":
                await _handle_private_lottery(update, context, chat_id)
            elif action == "solitaire":
                await _handle_private_solitaire(update, context, chat_id)
            elif action == "invite":
                await _handle_private_invite(update, context, chat_id)
            elif action == "autoreply":
                await _handle_private_autoreply(update, context, chat_id)
            elif action == "keywords":
                await _handle_private_keywords(update, context, chat_id)
            elif action == "scheduled":
                await _handle_private_scheduled(update, context, chat_id)
            return

    # 群聊中的回调（保持向后兼容，用于其他功能模块）
    if not await is_user_admin(context, chat.id, user.id):
        await _safe_edit_message(q, "此操作仅限管理员使用")
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
        settings = await get_chat_settings(session, chat.id)

        if parts[1] == "menu":
            menu = parts[2]
            if menu == "main":
                await session.commit()
                await _safe_edit_message(q, t(settings.language, "admin.title"), reply_markup=admin_main_menu())
                return

            if menu == "settings":
                await session.commit()
                await _safe_edit_message(
                    q,
                    "开关设置：",
                    reply_markup=toggle_menu(_settings_toggle_rows(settings), back_to="main"),
                )
                return

            if menu == "verification":
                mode_labels = {
                    "button": "🔘 按钮验证",
                    "math": "🔢 数学题验证",
                    "captcha": "🔢 验证码验证",
                }
                mode_label = mode_labels.get(settings.verification_mode, settings.verification_mode)
                text = f"🤖 新人验证\n\n"
                text += f"当前验证模式: {mode_label}\n"
                text += f"超时时间: {settings.verification_timeout_seconds} 秒\n"
                text += f"限制发言: {'是' if settings.verification_restrict_can_send else '否'}\n\n"
                text += f"💡 点击下方按钮切换验证模式"
                await session.commit()
                await _safe_edit_message(q, text, reply_markup=verification_mode_menu(settings.verification_mode))
                return

        if parts[1] == "toggle":
            field = parts[2]
            if hasattr(settings, field):
                current = bool(getattr(settings, field))
                setattr(settings, field, not current)
                await session.commit()
                await _safe_edit_message(
                    q,
                    "开关设置：",
                    reply_markup=toggle_menu(_settings_toggle_rows(settings), back_to="main"),
                )
                return

        if parts[1] == "vfy_mode":
            # 验证模式选择
            selected_mode = parts[2]
            if selected_mode in ["button", "math", "captcha"]:
                settings.verification_mode = selected_mode
                await session.commit()

            mode_labels = {
                "button": "🔘 按钮验证",
                "math": "🔢 数学题验证",
                "captcha": "🔢 验证码验证",
            }
            mode_label = mode_labels.get(settings.verification_mode, settings.verification_mode)
            text = f"🤖 新人验证\n\n"
            text += f"当前验证模式: {mode_label}\n"
            text += f"超时时间: {settings.verification_timeout_seconds} 秒\n"
            text += f"限制发言: {'是' if settings.verification_restrict_can_send else '否'}\n\n"
            text += f"💡 点击下方按钮切换验证模式"
            await _safe_edit_message(q, text, reply_markup=verification_mode_menu(settings.verification_mode))
            return

        await session.commit()


def _get_action_label(action: str) -> str:
    """获取惩罚动作标签"""
    labels = {
        "delete": "删除消息",
        "mute": "禁言",
        "ban": "封禁",
    }
    return labels.get(action, action)
