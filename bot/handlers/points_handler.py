from __future__ import annotations

import datetime as dt
import re
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy.orm import selectinload

from bot.db.session import Database
from bot.handlers.base.base_handler import BaseHandler
from bot.keyboards.admin.points_extended import user_points_mall_keyboard
from bot.services.core.chat_service import (
    build_points_alias_patterns,
    ensure_chat,
    get_chat_settings,
)
from bot.services.activity.points_extended_service import PointsExtendedService
from bot.services.activity.points_service import (
    add_message_points,
    change_points,
    format_balance_message,
    format_leaderboard_message,
    format_sign_in_already_message,
    format_sign_in_success_message,
    get_balance,
    get_leaderboard,
    get_user_rank,
    sign_in,
)
from bot.services.core.user_service import ensure_user
from bot.services.shared.publish_service import PublishService
from bot.utils.telegram_errors import answer_callback_query_safely, mark_callback_query_answered


class PointsHandler(BaseHandler):
    """积分 Handler"""

    def __init__(self) -> None:
        super().__init__()
        # 积分功能不需要管理员权限
        self._require_admin_permission = False

    @staticmethod
    def _should_send_level_block_notice(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int) -> bool:
        cache = context.application.bot_data.setdefault("points_level_block_notice", {})
        key = (chat_id, user_id)
        now = dt.datetime.now(dt.UTC)
        last_sent = cache.get(key)
        if isinstance(last_sent, dt.datetime) and (now - last_sent).total_seconds() < 60:
            return False
        cache[key] = now
        return True

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

        # 使用 service 层格式化消息
        if result.success:
            msg = format_sign_in_success_message(
                points=settings.sign_points,
                balance=result.balance,
                consecutive_days=result.consecutive_days,
                bonus_points=result.bonus_points,
            )
            await update.effective_message.reply_text(msg)
        else:
            msg = format_sign_in_already_message(
                balance=result.balance,
                consecutive_days=result.consecutive_days,
            )
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

        # 使用 service 层格式化消息
        msg = format_balance_message(balance, rank)
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

        # 使用 service 层格式化消息
        msg = format_leaderboard_message(leaderboard)
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

        text = (message.text or "").strip()

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
            mall_setting = await PointsExtendedService.get_or_create_mall_setting(session, chat.id)
            level_setting = await PointsExtendedService.get_or_create_level_setting(session, chat.id)

            # 积分商城入口
            if text and mall_setting.enabled and text == mall_setting.entry_command:
                products = await PointsExtendedService.list_on_sale_products(session, chat.id)
                await session.commit()
                if not products:
                    await update.effective_message.reply_text("积分商城暂时没有可兑换商品。")
                    return
                await self.show_mall_catalog(update, context, chat.id, products=products)
                return

            if text:
                custom_types = await PointsExtendedService.list_custom_point_types(session, chat.id)
                matched_type = next((item for item in custom_types if item.rank_command and text == item.rank_command), None)
                if matched_type is not None and not matched_type.enabled:
                    await session.commit()
                    await update.effective_message.reply_text(f"{matched_type.name} 已关闭。")
                    return
                if matched_type is not None:
                    rows = await PointsExtendedService.get_custom_point_leaderboard(
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

            # 积分等级限制
            if level_setting.enabled:
                if level_setting.exclude_teacher_enabled:
                    teacher_exempt = await PointsExtendedService.is_teacher_exempt(session, chat.id, user.id)
                    if teacher_exempt:
                        await session.commit()
                        return
                level = await PointsExtendedService.resolve_user_level(session, chat.id, user.id)
                required_perm = _required_level_permission(message)
                if required_perm is not None:
                    allowed = True if level is None else bool(getattr(level, required_perm, False))
                    if not allowed:
                        await session.commit()
                        try:
                            await message.delete()
                        except Exception:
                            pass
                        if self._should_send_level_block_notice(context, chat.id, user.id):
                            try:
                                await update.effective_chat.send_message("当前积分等级不足，无法发送此类消息。")
                            except Exception:
                                pass
                        return

            # 检查是否开启发言积分
            if not text or not settings.message_points_enabled:
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

    async def show_mall_catalog(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *,
        products=None,
        setting=None,
    ) -> None:
        if products is None or setting is None:
            db: Database = context.application.bot_data["db"]
            async with db.session_factory() as session:
                if products is None:
                    products = await PointsExtendedService.list_on_sale_products(session, chat_id)
                if setting is None:
                    setting = await PointsExtendedService.get_or_create_mall_setting(session, chat_id)
                await session.commit()
        text = "🏦 积分商城\n\n"
        if products:
            text += "\n".join(f"{p.name}｜{p.price_points}积分｜库存 {p.stock_left}" for p in products)
        else:
            text += "暂无可兑换商品。"
        if update.callback_query:
            message = update.callback_query.message
            if message and (message.photo or message.video):
                try:
                    await update.callback_query.edit_message_caption(
                        caption=text,
                        reply_markup=user_points_mall_keyboard(chat_id, products),
                    )
                    return
                except Exception:
                    pass
            await update.callback_query.edit_message_text(text, reply_markup=user_points_mall_keyboard(chat_id, products))
        elif update.effective_message:
            if setting and setting.cover_file_id:
                if setting.cover_media_type == "photo":
                    await update.effective_message.reply_photo(
                        photo=setting.cover_file_id,
                        caption=text,
                        reply_markup=user_points_mall_keyboard(chat_id, products),
                    )
                    return
                if setting.cover_media_type == "video":
                    await update.effective_message.reply_video(
                        video=setting.cover_file_id,
                        caption=text,
                        reply_markup=user_points_mall_keyboard(chat_id, products),
                    )
                    return
            await update.effective_message.reply_text(text, reply_markup=user_points_mall_keyboard(chat_id, products))

    async def handle_mall_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.callback_query is None or update.effective_user is None:
            return
        data = update.callback_query.data or ""
        parts = data.split(":")
        if len(parts) < 3:
            await answer_callback_query_safely(update, "无效操作", show_alert=True)
            return
        try:
            chat_id = int(parts[2])
        except ValueError:
            await answer_callback_query_safely(update, "无效群组", show_alert=True)
            return

        action = parts[1]
        db: Database = context.application.bot_data["db"]

        if action == "list":
            mark_callback_query_answered(update)
            await self.show_mall_catalog(update, context, chat_id)
            return

        if action == "redeem":
            if len(parts) < 4:
                await answer_callback_query_safely(update, "无效商品", show_alert=True)
                return
            try:
                product_id = int(parts[3])
            except ValueError:
                await answer_callback_query_safely(update, "无效商品", show_alert=True)
                return
            async with db.session_factory() as session:
                await ensure_chat(session, chat_id=chat_id, chat_type="supergroup", title=None)
                await ensure_user(
                    session,
                    user_id=update.effective_user.id,
                    username=update.effective_user.username,
                    first_name=update.effective_user.first_name,
                    last_name=update.effective_user.last_name,
                    language_code=update.effective_user.language_code,
                )
                success, reason, _order = await PointsExtendedService.redeem_product(
                    session,
                    chat_id=chat_id,
                    product_id=product_id,
                    buyer_user_id=update.effective_user.id,
                )
                setting = await PointsExtendedService.get_or_create_mall_setting(session, chat_id)
                await session.commit()
            if not success:
                await answer_callback_query_safely(update, reason, show_alert=True)
                return
            mark_callback_query_answered(update)
            await PublishService.send_temporary(
                context,
                chat_id=chat_id,
                text=f"兑换成功，订单已创建。用户：{update.effective_user.id}",
                delete_after_seconds=setting.redeem_notice_delete_seconds,
            )
            await self.show_mall_catalog(update, context, chat_id)
            return

        await answer_callback_query_safely(update, "暂不支持该操作", show_alert=True)


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


async def mall_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _points_handler.handle_mall_callback(update, context)


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
            # 使用 service 层构建正则
            self._patterns_cache[chat_id] = build_points_alias_patterns(settings)
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


def _required_level_permission(message) -> str | None:
    if message.sticker:
        return "allow_sticker"
    if message.audio or message.voice:
        return "allow_audio"
    if message.video:
        return "allow_video"
    if message.photo:
        return "allow_photo"
    if message.document:
        return "allow_document"
    text = message.text or message.caption or ""
    entities = list(message.entities or []) + list(message.caption_entities or [])
    has_mention = any(entity.type in {"mention", "text_mention"} for entity in entities)
    if has_mention:
        return "allow_mention"
    if text:
        return "allow_text"
    return None
