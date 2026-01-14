from __future__ import annotations

import asyncio
import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest, TelegramError

from bot.config import get_settings
from bot.db.session import Database
from bot.handlers.base.base_handler import BaseHandler
from bot.i18n.strings import t
from bot.keyboards.admin.admin_main import (
    admin_main_menu,
    create_group_selection_keyboard,
    create_guide_keyboard,
    format_admin_main_menu_text,
    format_verification_menu_text,
    toggle_menu,
    verification_mode_menu,
)
from bot.services.integration.chat_group_service import get_user_current_chat, get_user_managed_chats, set_user_current_chat
from bot.services.core.chat_service import ensure_chat, get_chat_settings, get_settings_toggle_rows
from bot.services.core.permission_service import is_user_admin
from bot.utils.callback_parser import CallbackParser


log = structlog.get_logger(__name__)


class AdminHandler(BaseHandler):
    """管理员 Handler"""

    def __init__(self) -> None:
        super().__init__()
        # 关闭默认权限检查，因为我们在 process 中自己处理
        self._require_admin_permission = False

    async def process(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
    ) -> None:
        """处理管理回调"""
        q = update.callback_query
        await q.answer()

        # 解析 callback data
        callback_data = CallbackParser.parse(q.data)
        action = callback_data.get(1)

        # 根据操作类型分发
        if action == "menu":
            await self._handle_menu(update, context, target_chat_id, callback_data)
        elif action == "switch_group":
            await self._handle_switch_group(update, context)
        elif action == "select_group":
            await self._handle_select_group(update, context, target_chat_id)
        elif action == "back_to_main":
            await self._handle_back_to_main(update, context)
        elif action == "back_to_menu":
            await self._handle_back_to_menu(update, context, target_chat_id)
        elif action == "toggle":
            await self._handle_toggle(update, context, target_chat_id, callback_data)
        elif action == "vfy_mode":
            await self._handle_verification_mode(update, context, target_chat_id, callback_data)

    async def _handle_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        """处理菜单操作"""
        menu_action = callback_data.get(2)

        # 分发到不同的子菜单处理器
        handlers = {
            "main": self._show_main_menu,
            "settings": self._show_settings_menu,
            "lottery": self._show_lottery_menu,
            "solitaire": self._show_solitaire_menu,
            "invite": self._show_invite_menu,
            "autoreply": self._show_autoreply_menu,
            "keywords": self._show_keywords_menu,
            "scheduled": self._show_scheduled_menu,
            "ads": self._show_ads_menu,
            "verification": self._show_verification_menu,
            "points": self._show_points_menu,
            "autodel": self._show_auto_delete_menu,
        }

        handler = handlers.get(menu_action, self._show_main_menu)
        await handler(update, context, chat_id)

    async def _handle_switch_group(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """处理切换群组操作"""
        db: Database = context.application.bot_data["db"]
        chats = await get_user_managed_chats(db, update.effective_user.id, context.bot)
        current_chat_id = await get_user_current_chat(db, update.effective_user.id)

        await self._show_group_selection(update, chats, current_chat_id)

    async def _handle_select_group(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """处理选择群组操作"""
        db: Database = context.application.bot_data["db"]
        await set_user_current_chat(db, update.effective_user.id, chat_id)
        await self._show_main_menu(update, context, chat_id)

    async def _handle_back_to_main(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """处理返回主菜单操作"""
        db: Database = context.application.bot_data["db"]
        current_chat_id = await get_user_current_chat(db, update.effective_user.id)
        chats = await get_user_managed_chats(db, update.effective_user.id, context.bot)
        if current_chat_id is None and chats:
            current_chat_id = chats[0][0]
        await self._show_main_menu(update, context, current_chat_id)

    async def _handle_back_to_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """处理返回指定群组菜单操作"""
        await self._show_main_menu(update, context, chat_id)

    async def _handle_toggle(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        """处理开关切换操作"""
        field = callback_data.get(3) if callback_data.length() >= 4 else callback_data.get(2)

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            if hasattr(settings, field):
                current = bool(getattr(settings, field))
                setattr(settings, field, not current)
                await session.commit()

        await self._show_settings_menu(update, context, chat_id)

    async def _handle_verification_mode(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        """处理验证模式切换操作"""
        selected_mode = callback_data.get(3)

        if selected_mode in ["button", "math", "captcha"]:
            db: Database = context.application.bot_data["db"]
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                settings.verification_mode = selected_mode
                await session.commit()

        await self._show_verification_menu(update, context, chat_id)

    async def _get_chat_title(self, db: Database, chat_id: int) -> str:
        """获取群组标题"""
        from bot.models.core import TgChat
        from sqlalchemy import select

        async with db.session_factory() as session:
            chat_stmt = select(TgChat).where(TgChat.id == chat_id)
            chat_result = await session.execute(chat_stmt)
            chat = chat_result.scalar_one_or_none()
            return chat.title if chat else f"群组{chat_id}"

    async def _set_current_chat(
        self,
        db: Database,
        user_id: int,
        chat_id: int,
    ) -> None:
        """设置当前管理的群组"""
        await set_user_current_chat(db, user_id, chat_id)

    # ==================== 菜单显示方法 ====================

    async def _show_main_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示主菜单"""
        db: Database = context.application.bot_data["db"]
        chat_title = await self._get_chat_title(db, chat_id)

        # 使用 keyboards 层格式化消息
        text = format_admin_main_menu_text(chat_title)
        keyboard = admin_main_menu(chat_id)

        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=keyboard
        )

    async def _show_settings_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示设置菜单（已整合到主菜单）"""
        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        await self._show_main_menu(update, context, chat_id)

    async def _show_lottery_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示抽奖管理菜单"""
        from bot.keyboards.activity.lottery import lottery_menu_keyboard
        from bot.services.activity.lottery_service import get_lottery_stats

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        async with db.session_factory() as session:
            stats = await get_lottery_stats(session, chat_id)
            await session.commit()

        chat_title = await self._get_chat_title(db, chat_id)
        text = f"🎁[{chat_title}]抽奖\n\n"
        text += f"创建的抽奖次数:{stats['total']}\n\n"
        text += f"已开奖:{stats['completed']}       未开奖:{stats['pending']}       取消:{stats['cancelled']}"

        keyboard = lottery_menu_keyboard(chat_id)

        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_solitaire_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示接龙管理菜单"""
        from bot.keyboards.activity.solitaire import solitaire_menu_keyboard

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        text = "📋 接龙管理\n\n请选择操作："
        keyboard = solitaire_menu_keyboard(chat_id)

        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_invite_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示邀请链接管理菜单"""
        from bot.keyboards.integration.invite_link import invite_link_menu_keyboard

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        text = "🔗 邀请链接管理\n\n请选择操作："
        keyboard = invite_link_menu_keyboard(chat_id)

        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_autoreply_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示自动回复管理菜单"""
        from bot.keyboards.content.auto_reply import auto_reply_menu_keyboard

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        text = "💬 自动回复管理\n\n请选择操作："
        keyboard = auto_reply_menu_keyboard(chat_id)

        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_keywords_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示违禁词管理菜单"""
        from bot.keyboards.content.banned_word import banned_word_menu_keyboard

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        text = "🔇 违禁词管理\n\n请选择操作："
        keyboard = banned_word_menu_keyboard(chat_id)

        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_scheduled_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示定时消息管理菜单"""
        from bot.keyboards.integration.scheduled import scheduled_menu_keyboard

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        text = "⏰ 定时消息管理\n\n请选择操作："
        keyboard = scheduled_menu_keyboard(chat_id)

        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_ads_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示广告管理菜单"""
        from bot.keyboards.content.ads import ads_menu_keyboard

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        text = "📢 广告管理\n\n请选择操作："
        keyboard = ads_menu_keyboard(chat_id)

        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_verification_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示新人验证设置菜单"""
        from bot.keyboards.admin.admin_main import verification_mode_menu

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            await session.commit()

        chat_title = await self._get_chat_title(db, chat_id)

        # 使用 keyboards 层格式化消息
        text = format_verification_menu_text(
            chat_title=chat_title,
            verification_mode=settings.verification_mode,
            timeout_seconds=settings.verification_timeout_seconds,
            restrict_can_send=settings.verification_restrict_can_send,
        )
        keyboard = verification_mode_menu(settings.verification_mode, chat_id)

        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_points_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示积分设置菜单"""
        from bot.keyboards.admin.points import points_config_keyboard

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            await session.commit()

        chat_title = await self._get_chat_title(db, chat_id)
        text = f"💰 [{chat_title}] 积分配置\n\n"
        text += f"请选择要修改的项目："

        keyboard = points_config_keyboard(settings, chat_id)

        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_auto_delete_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示自动删除配置菜单"""
        from bot.keyboards.admin.auto_delete import auto_delete_config_keyboard

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            await session.commit()

        chat_title = await self._get_chat_title(db, chat_id)
        text = f"🧹 [{chat_title}] 自动删除配置\n\n"
        text += f"自动清理群组中的系统消息"

        keyboard = auto_delete_config_keyboard(settings, chat_id)

        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_group_selection(
        self,
        update: Update,
        managed_chats: list,
        current_chat_id: int | None,
    ) -> None:
        """显示群组选择列表"""
        # 使用 keyboards 层创建键盘
        keyboard = create_group_selection_keyboard(managed_chats, current_chat_id)
        text = "🔄 选择要管理的群组："

        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=keyboard
        )


# 创建单例实例
_admin_handler = AdminHandler()


# ==================== 适配器函数（供 Router 注册）====================

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """管理员命令 - 在群聊中引导到私聊设置"""
    log.info("admin_command_called")

    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        log.warning("admin_command_missing_update_data")
        return

    chat = update.effective_chat
    user = update.effective_user

    log.info("admin_command_chat_info", chat_type=chat.type, chat_id=chat.id, user_id=user.id)

    # 群聊中：引导用户到私聊进行设置
    if chat.type != "private":
        log.info("admin_command_group_chat")
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

        # 使用 keyboards 层创建引导按钮
        keyboard = create_guide_keyboard(context.bot.username)

        # 发送消息
        msg = await update.effective_message.reply_text(
            f"欢迎使用 @{context.bot.username}:\n\n"
            f"1) 点击下方按钮选择设置（仅限管理员）\n"
            f"2) 点击机器人对话框底部[开始]按钮\n\n"
            f"🟩 功能更新提醒: 在机器人私聊中发送 /start 也可打开管理菜单",
            reply_markup=keyboard
        )

        # 10秒后删除消息（保持群组整洁）
        async def delete_later():
            try:
                await asyncio.sleep(10)
                await msg.delete()
            except Exception:
                pass

        asyncio.create_task(delete_later())
        return

    # 私聊中：显示管理面板
    log.info("admin_command_private_chat")

    try:
        db: Database = context.application.bot_data["db"]

        # 获取用户管理的群组
        log.info("admin_command_fetching_chats", user_id=user.id)
        chats = await get_user_managed_chats(db, user.id, context.bot)
        log.info("admin_command_chats_fetched", user_id=user.id, chat_count=len(chats))

        current_chat_id = await get_user_current_chat(db, user.id)
        log.info("admin_command_current_chat", user_id=user.id, current_chat_id=current_chat_id)

        if not chats:
            log.info("admin_command_no_chats")
            await update.effective_message.reply_text(
                "👋 欢迎使用群管理 Bot！\n\n"
                "暂无群组，请先将 bot 添加到群组中并设为管理员..."
            )
            return

        # 如果没有选中的群组，默认选择第一个
        if current_chat_id is None and chats:
            current_chat_id = chats[0][0]  # 第一个群组的 chat_id
            log.info("admin_command_setting_default_chat", user_id=user.id, default_chat_id=current_chat_id)
            await set_user_current_chat(db, user.id, current_chat_id)

        # 显示管理面板
        log.info("admin_command_showing_menu", user_id=user.id, current_chat_id=current_chat_id)
        await _show_private_admin_menu(update, context, current_chat_id)
        log.info("admin_command_menu_shown", user_id=user.id)
    except Exception as e:
        log.exception("admin_command_error", user_id=user.id, error=str(e))
        await update.effective_message.reply_text(f"发生错误：{str(e)}")


async def _show_private_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    """在私聊中显示管理面板（公开接口，供其他模块调用）"""
    await _admin_handler._show_main_menu(update, context, chat_id)


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """管理回调 - 支持群聊内联按钮和私聊管理"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    data = q.data or ""

    log.info("admin_callback_called", callback_data=data, chat_type=update.effective_chat.type, user_id=update.effective_user.id)

    # 私聊中的管理回调 - 使用 Handler 处理
    if update.effective_chat.type == "private":
        cb = CallbackParser.parse(data)
        if cb.length() >= 3 and cb.get(0) == "adm":
            # 提取 target_chat_id（如果有）
            target_chat_id = cb.get_int(3)

            # 检查管理员权限
            if target_chat_id != 0:
                is_admin = await is_user_admin(
                    context, target_chat_id, update.effective_user.id
                )
                if not is_admin:
                    await _admin_handler.message_helper.safe_edit(
                        update, "你没有该群组的管理权限"
                    )
                    return

            # 使用 Handler 处理
            if target_chat_id != 0:
                await _admin_handler.process(update, context, target_chat_id)
            else:
                # 对于不需要 target_chat_id 的操作（如 switch_group, back_to_main）
                await _admin_handler.process(update, context, 0)  # chat_id 0 表示不需要
        return

    # 群聊中的回调（保持向后兼容，用于其他功能模块）
    user = update.effective_user
    chat = update.effective_chat
    is_admin = await is_user_admin(context, chat.id, user.id)
    log.info("admin_permission_check", chat_id=chat.id, user_id=user.id, is_admin=is_admin)
    if not is_admin:
        log.warning("admin_permission_denied", callback_data=data, chat_id=chat.id, user_id=user.id)
        await _admin_handler.message_helper.safe_edit(q, "此操作仅限管理员使用")
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
        settings = await get_chat_settings(session, chat.id)

        cb = CallbackParser.parse(data)
        if cb.get(1) == "menu":
            menu = cb.get(2)
            if menu == "main":
                await session.commit()
                await _admin_handler.message_helper.safe_edit(q, t(settings.language, "admin.title"), reply_markup=admin_main_menu())
                return

            if menu == "settings":
                await session.commit()
                await _admin_handler.message_helper.safe_edit(
                    q,
                    "开关设置：",
                    reply_markup=toggle_menu(get_settings_toggle_rows(settings), back_to="main"),
                )
                return

            if menu == "verification":
                # 使用 keyboards 层格式化消息
                text = format_verification_menu_text(
                    chat_title="群组",
                    verification_mode=settings.verification_mode,
                    timeout_seconds=settings.verification_timeout_seconds,
                    restrict_can_send=settings.verification_restrict_can_send,
                )
                await session.commit()
                await _admin_handler.message_helper.safe_edit(q, text, reply_markup=verification_mode_menu(settings.verification_mode))
                return

        if cb.get(1) == "toggle":
            field = cb.get(2)
            if hasattr(settings, field):
                current = bool(getattr(settings, field))
                setattr(settings, field, not current)
                await session.commit()
                await _admin_handler.message_helper.safe_edit(
                    q,
                    "开关设置：",
                    reply_markup=toggle_menu(get_settings_toggle_rows(settings), back_to="main"),
                )
                return

        if cb.get(1) == "vfy_mode":
            # 验证模式选择
            selected_mode = cb.get(2)
            if selected_mode in ["button", "math", "captcha"]:
                settings.verification_mode = selected_mode
                await session.commit()

            # 使用 keyboards 层格式化消息
            text = format_verification_menu_text(
                chat_title="群组",
                verification_mode=settings.verification_mode,
                timeout_seconds=settings.verification_timeout_seconds,
                restrict_can_send=settings.verification_restrict_can_send,
            )
            await _admin_handler.message_helper.safe_edit(q, text, reply_markup=verification_mode_menu(settings.verification_mode))
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
