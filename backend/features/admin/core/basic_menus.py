from __future__ import annotations

from backend.features.admin.support import *


class CoreBasicMenusMixin:
    async def _show_lottery_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示抽奖管理菜单"""
        from backend.features.activity.services.lottery_service import count_lotteries_by_type, get_lottery_stats
        from backend.features.activity.ui.lottery import lottery_menu_keyboard

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        async with db.session_factory() as session:
            stats = await get_lottery_stats(session, chat_id)
            type_counts = await count_lotteries_by_type(session, chat_id)
            await session.commit()

        chat_title = await self._get_chat_title(db, chat_id)
        text = f"🎁[{chat_title}]抽奖\n\n"
        text += f"创建的抽奖次数:{stats['total']}\n\n"
        text += f"已开奖:{stats['completed']}       未开奖:{stats['pending']}       取消:{stats['cancelled']}\n\n"
        text += (
            f"🎁 通用:{type_counts['common']}  "
            f"💰 积分:{type_counts['points']}  "
            f"👥 邀请:{type_counts['invite']}  "
            f"🔥 活跃:{type_counts['activity']}  "
            f"📣 订阅:{type_counts['subscribe']}"
        )

        keyboard = lottery_menu_keyboard(chat_id)
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_solitaire_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示接龙管理菜单"""
        from backend.features.activity.ui.solitaire import solitaire_menu_keyboard

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
        from backend.features.invite.invite_link_handler import _invite_link_handler

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        chat_title = await self._get_chat_title(db, chat_id)
        await _invite_link_handler.show_menu(update, context, chat_id, chat_title)

    async def _show_stats_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示群组统计摘要"""
        import datetime as dt
        from sqlalchemy import func, select

        from backend.features.invite.services.invite_stats import get_link_stats
        from backend.platform.db.schema.models.chat import ChatMember
        from backend.platform.db.schema.models.core import InviteTracking, ModerationViolation
        from backend.platform.db.schema.models.points import PointsTransaction, UserDailyStats

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            member_count = (await session.execute(
                select(func.count(ChatMember.id)).where(ChatMember.chat_id == chat_id)
            )).scalar() or 0
            invite_count = (await session.execute(
                select(func.count(InviteTracking.id)).where(InviteTracking.chat_id == chat_id)
            )).scalar() or 0
            points_txn_count = (await session.execute(
                select(func.count(PointsTransaction.id)).where(PointsTransaction.chat_id == chat_id)
            )).scalar() or 0
            violation_count = (await session.execute(
                select(func.count(ModerationViolation.id)).where(ModerationViolation.chat_id == chat_id)
            )).scalar() or 0
            since_date = dt.datetime.now(dt.UTC).date() - dt.timedelta(days=6)
            recent_stats = await session.execute(
                select(
                    func.coalesce(func.sum(UserDailyStats.message_points_earned), 0),
                    func.coalesce(func.sum(UserDailyStats.invites_count), 0),
                ).where(
                    UserDailyStats.chat_id == chat_id,
                    UserDailyStats.stat_date >= since_date,
                )
            )
            recent_message_points, recent_invites = recent_stats.one()
            link_stats = await get_link_stats(session, chat_id)
            await session.commit()

        chat_title = await self._get_chat_title(db, chat_id)
        text = "\n".join(
            [
                f"📊 群组统计 | {chat_title}",
                "",
                f"成员数量: {member_count}",
                f"邀请加入: {invite_count}",
                f"积分流水: {points_txn_count}",
                f"违规记录: {violation_count}",
                "",
                f"近7日发言积分: {recent_message_points}",
                f"近7日邀请人数: {recent_invites}",
                "",
                "邀请链接概览：",
                f"• 总链接数: {link_stats['total']}",
                f"• 激活中: {link_stats['active']} | 已撤销: {link_stats['revoked']} | 已过期: {link_stats['expired']}",
                f"• 统计成员: {link_stats['total_members']}",
            ]
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_autoreply_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示自动回复管理菜单"""
        from backend.features.moderation.auto_reply_views import render_auto_reply_list

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        await render_auto_reply_list(update, context, target_chat_id=chat_id)

    async def _show_keywords_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示违禁词管理菜单"""
        from backend.features.moderation.ui.banned_word import banned_word_menu_keyboard

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
        from backend.features.automation.scheduled_message_handler import _scheduled_message_handler

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        await _scheduled_message_handler.show_list(update, context, chat_id)

    async def _show_ads_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示轮播广告菜单"""
        from backend.features.automation.ads_handler import _ads_handler

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        await _ads_handler.show_menu(update, context, chat_id)
