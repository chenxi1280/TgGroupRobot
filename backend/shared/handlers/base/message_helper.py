"""消息发送工具类

提供统一的消息发送接口，处理各种异常情况。
"""
from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import TelegramError

log = structlog.get_logger(__name__)


class MessageHelper:
    """消息发送工具类

    封装所有消息发送操作，统一异常处理。
    """

    @staticmethod
    async def safe_edit(
        update: Update,
        text: str,
        reply_markup=None,
        *, parse_mode: str | None = None,
        show_alert: bool = False,
    ) -> bool:
        """安全编辑消息（用于 callback）

        Args:
            update: Telegram 更新对象
            text: 要发送的文本
            reply_markup: 键盘布局（可选）
            parse_mode: 解析模式（可选）
            show_alert: 是否以 alert 形式显示

        Returns:
            bool: 是否成功编辑
        """
        if update.callback_query is None:
            if update.effective_message is None:
                return False
            try:
                await update.effective_message.reply_text(
                    text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                )
                return True
            except TelegramError as e:
                log.warning("reply_message_failed", error=str(e))
                return False

        try:
            # 先 answer callback query，避免"一直加载"
            if show_alert:
                await update.callback_query.answer(text, show_alert=True)
                return True
            else:
                await update.callback_query.answer()
                # 然后编辑消息
                await update.callback_query.edit_message_text(
                    text, reply_markup=reply_markup, parse_mode=parse_mode
                )
                return True
        except TelegramError as e:
            log.warning("edit_message_failed", error=str(e))
            return False

    @staticmethod
    async def safe_answer(update: Update, text: str = "", show_alert: bool = False) -> bool:
        """安全回答回调

        Args:
            update: Telegram 更新对象
            text: 要显示的文本
            show_alert: 是否以 alert 形式显示

        Returns:
            bool: 是否成功回答
        """
        if update.callback_query is None:
            return False

        try:
            await update.callback_query.answer(text, show_alert=show_alert)
            return True
        except TelegramError:
            return False

    @staticmethod
    async def safe_reply(
        update: Update,
        text: str,
        reply_markup=None,
        *, parse_mode: str | None = None,
    ) -> bool:
        """安全回复消息

        Args:
            update: Telegram 更新对象
            text: 要发送的文本
            reply_markup: 键盘布局（可选）
            parse_mode: 解析模式（可选）

        Returns:
            bool: 是否成功回复
        """
        if update.effective_message is None:
            return False

        try:
            await update.effective_message.reply_text(
                text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
            return True
        except TelegramError as e:
            log.warning("reply_message_failed", error=str(e))
            return False

    @staticmethod
    async def safe_send_message(
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        text: str,
        *, reply_markup=None,
        parse_mode: str | None = None,
    ) -> bool:
        """安全发送消息

        Args:
            context: Bot 上下文
            chat_id: 目标聊天 ID
            text: 要发送的文本
            reply_markup: 键盘布局（可选）
            parse_mode: 解析模式（可选）

        Returns:
            bool: 是否成功发送
        """
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
            return True
        except TelegramError as e:
            log.warning("send_message_failed", chat_id=chat_id, error=str(e))
            return False

    @staticmethod
    async def safe_delete(update: Update) -> bool:
        """安全删除消息

        Args:
            update: Telegram 更新对象

        Returns:
            bool: 是否成功删除
        """
        if update.effective_message is None:
            return False

        try:
            await update.effective_message.delete()
            return True
        except TelegramError as e:
            log.warning("delete_message_failed", error=str(e))
            return False
