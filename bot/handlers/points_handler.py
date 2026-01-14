from __future__ import annotations

import re
from telegram import Update
from telegram.ext import ContextTypes, filters
from sqlalchemy.orm import selectinload

from bot.db.session import Database
from bot.handlers.base.base_handler import BaseHandler
from bot.services.core.chat_service import ensure_chat, get_chat_settings
from bot.services.activity.points_service import (
    add_message_points,
    get_balance,
    get_leaderboard,
    get_user_rank,
    sign_in,
)
from bot.services.core.user_service import ensure_user


class PointsHandler(BaseHandler):
    """积分 Handler"""

    def __init__(self) -> None:
        super().__init__()
        # 积分功能不需要管理员权限
        self._require_admin_permission = False

    async def process(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
    ) -> None:
        """处理积分回调（用于 BaseHandler 抽象方法）"""
        # PointsHandler 主要用于消息处理，不使用 process 方法
        pass

    async def handle_sign_in(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """处理签到"""
        if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
            return
        if update.effective_chat.type == "private":
            await update.effective_message.reply_text("请在群组中使用此功能")
            return

        db: Database = context.application.bot_data["db"]
        chat = update.effective_chat
        user = update.effective_user

        async with db.session_factory() as session:
            await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
            await ensure_user(
                session,
                user_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                language_code=user.language_code,
            )
            settings = await get_chat_settings(session, chat.id)
            if not settings.sign_enabled:
                await session.commit()
                await update.effective_message.reply_text("本群未开启签到。")
                return

            result = await sign_in(
                session,
                chat_id=chat.id,
                user_id=user.id,
                points=settings.sign_points,
                consecutive_days=settings.sign_consecutive_days,
                consecutive_bonus=settings.sign_consecutive_bonus,
            )
            await session.commit()

        if result.success:
            msg = f"✅ 签到成功！\n"
            msg += f"获得 {settings.sign_points} 积分\n"
            msg += f"当前余额：{result.balance} 积分"
            if result.consecutive_days > 1:
                msg += f"\n连续签到：{result.consecutive_days} 天"
            if result.bonus_points > 0:
                msg += f"\n🎉 连续签到奖励：+{result.bonus_points} 积分"
            await update.effective_message.reply_text(msg)
        else:
            msg = f"❌ 今日已签到\n"
            msg += f"当前余额：{result.balance} 积分"
            if result.consecutive_days > 0:
                msg += f"\n连续签到：{result.consecutive_days} 天"
            await update.effective_message.reply_text(msg)

    async def handle_balance(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """处理积分余额查询"""
        if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
            return
        if update.effective_chat.type == "private":
            await update.effective_message.reply_text("请在群组中使用此功能")
            return

        db: Database = context.application.bot_data["db"]
        chat = update.effective_chat
        user = update.effective_user

        async with db.session_factory() as session:
            await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
            await ensure_user(
                session,
                user_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                language_code=user.language_code,
            )
            settings = await get_chat_settings(session, chat.id)
            balance = await get_balance(session, chat.id, user.id)
            rank = await get_user_rank(session, chat.id, user.id)
            await session.commit()

        msg = f"💰 你的积分：{balance}"
        if rank:
            msg += f"\n🏆 排名：第 {rank} 名"
        await update.effective_message.reply_text(msg)

    async def handle_leaderboard(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """处理积分排行榜"""
        if update.effective_chat is None or update.effective_message is None:
            return
        if update.effective_chat.type == "private":
            await update.effective_message.reply_text("请在群组中使用此功能")
            return

        db: Database = context.application.bot_data["db"]
        chat = update.effective_chat

        async with db.session_factory() as session:
            await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
            leaderboard = await get_leaderboard(session, chat.id, limit=10)
            await session.commit()

        if not leaderboard:
            await update.effective_message.reply_text("暂无积分排行数据")
            return

        msg = "🏆 积分排行榜（前10名）\n\n"
        for i, (user_id, balance, username) in enumerate(leaderboard, 1):
            name = username or f"用户{user_id}"
            msg += f"{i}. {name} - {balance} 积分\n"
        await update.effective_message.reply_text(msg)

    async def handle_message_points(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """处理发言积分"""
        if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
            return

        # 只在群聊中处理
        if update.effective_chat.type not in ["group", "supergroup"]:
            return

        db: Database = context.application.bot_data["db"]
        chat = update.effective_chat
        user = update.effective_user
        message = update.effective_message

        # 获取消息文本
        text = message.text or ""
        if not text:
            return

        async with db.session_factory() as session:
            await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
            await ensure_user(
                session,
                user_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                language_code=user.language_code,
            )
            settings = await get_chat_settings(session, chat.id)

            # 检查是否开启发言积分
            if not settings.message_points_enabled:
                await session.commit()
                return

            # 添加发言积分
            result = await add_message_points(
                session,
                chat_id=chat.id,
                user_id=user.id,
                points=settings.message_points,
                daily_limit=settings.message_points_daily_limit,
                min_length=settings.message_min_length,
                message_length=len(text),
            )
            await session.commit()

            # 不发送通知，避免打扰群聊
            return


# 创建单例实例
_points_handler = PointsHandler()


# ==================== 命令处理器（适配器函数）====================

async def sign_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """签到命令"""
    await _points_handler.handle_sign_in(update, context)


async def points_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """积分余额命令"""
    await _points_handler.handle_balance(update, context)


async def points_rank_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """积分排行命令"""
    await _points_handler.handle_leaderboard(update, context)


async def message_points_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """发言积分处理器"""
    await _points_handler.handle_message_points(update, context)


async def alias_points_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """积分别名处理器"""
    await _points_handler.handle_balance(update, context)


async def alias_rank_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """积分排行别名处理器"""
    await _points_handler.handle_leaderboard(update, context)


class PointsAliasHandler:
    """积分别名动态处理器（根据配置的别名匹配）"""

    def __init__(self):
        self._patterns_cache: dict[int, dict[str, re.Pattern]] = {}

    async def _get_patterns(self, chat_id: int, db: Database) -> dict[str, re.Pattern]:
        """获取群组配置的别名正则"""
        if chat_id in self._patterns_cache:
            return self._patterns_cache[chat_id]

        async with db.session_factory() as session:
            from bot.models.core import TgChat
            from sqlalchemy import select

            # 预加载 settings 关系，避免异步上下文中的懒加载问题
            stmt = select(TgChat).options(
                selectinload(TgChat.settings)
            ).where(TgChat.id == chat_id)
            result = await session.execute(stmt)
            chat = result.scalar_one_or_none()

            if not chat or not chat.settings:
                return {}

            settings = chat.settings
            self._patterns_cache[chat_id] = {
                "points": re.compile(rf"^{re.escape(settings.points_alias)}$"),
                "rank": re.compile(rf"^{re.escape(settings.points_rank_alias)}$"),
            }
            return self._patterns_cache[chat_id]

    def clear_cache(self, chat_id: int | None = None) -> None:
        """清除缓存（配置更改后调用）"""
        if chat_id:
            self._patterns_cache.pop(chat_id, None)
        else:
            self._patterns_cache.clear()

    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理别名消息"""
        if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
            return

        if update.effective_chat.type not in ["group", "supergroup"]:
            return

        text = update.effective_message.text
        if not text:
            return

        db: Database = context.application.bot_data["db"]
        chat_id = update.effective_chat.id

        patterns = await self._get_patterns(chat_id, db)

        # 匹配积分别名
        if patterns.get("points") and patterns["points"].match(text.strip()):
            await alias_points_handler(update, context)
            return

        # 匹配排行别名
        if patterns.get("rank") and patterns["rank"].match(text.strip()):
            await alias_rank_handler(update, context)
            return


# 全局别名处理器实例
_points_alias_handler = PointsAliasHandler()


def get_points_alias_handler() -> PointsAliasHandler:
    """获取别名处理器实例"""
    return _points_alias_handler
