from __future__ import annotations

import structlog

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.enums import ConversationStateType
from backend.shared.services.chat_service import ensure_chat
from backend.platform.state.state_service import clear_user_state, set_user_state
from backend.features.activity.services.lottery_service import (
    ParsedLotteryConfig,
    create_lottery,
    format_lottery_announcement_text,
    get_or_create_lottery_setting,
    parse_lottery_config_text,
)

log = structlog.get_logger(__name__)


def _lottery_type_title(lottery_type: str) -> str:
    return {
        "common": "🎁 通用抽奖",
        "points": "💰 积分抽奖",
        "invite": "👥 邀请抽奖",
        "activity": "🔥 群活跃抽奖",
    }.get(lottery_type, "🎁 抽奖")


class LotteryCreationMixin:
    async def start_create_flow(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        lottery_type: str = "common",
        selection_mode: str = "threshold_random",
    ) -> None:
        q = update.callback_query
        user = update.effective_user

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            await ensure_chat(session, chat_id=target_chat_id, chat_type="supergroup", title=None)
            from backend.shared.services.user_service import ensure_user

            await ensure_user(
                session,
                user_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                language_code=user.language_code,
            )
            await set_user_state(
                session,
                chat_id=q.message.chat.id,
                user_id=user.id,
                state_type=ConversationStateType.lottery_create.value,
                state_data={
                    "step": "config",
                    "target_chat_id": target_chat_id,
                    "lottery_type": lottery_type,
                    "selection_mode": selection_mode,
                },
            )
            await session.commit()

        text = f"{_lottery_type_title(lottery_type)} | 创建抽奖  ( /cancel 取消)\n\n"
        if selection_mode == "ranking_random":
            text += "当前玩法：🏆 排名入围随机\n\n"
        elif lottery_type in {"invite", "activity"}:
            text += "当前玩法：🎯 达标随机\n\n"
        text += "请按以下格式一次性发送配置：\n\n"
        text += "```\n"
        text += "标题|描述（可选）\n"
        text += "开奖时间: 2025-12-30 12:00\n"
        text += "最低积分: 0\n"
        text += "参与费用: 0\n"
        text += "最大人数: 0（0=无限制）\n"
        text += "入群天数: 0（0=无限制）\n"
        if lottery_type == "invite":
            text += "邀请人数: 3\n"
            text += "统计天数: 7\n"
            if selection_mode == "ranking_random":
                text += "入围人数: 10\n"
        elif lottery_type == "activity":
            text += "活跃消息数: 200\n"
            text += "统计天数: 7\n"
            if selection_mode == "ranking_random":
                text += "入围人数: 10\n"
        text += "奖品:\n奖品1名称,数量\n奖品2名称,数量\n...\n```\n\n"
        text += "示例:\n```\n"
        text += "新年大抽奖|祝大家新年快乐！\n"
        text += "开奖时间: 2025-12-31 20:00\n"
        text += f"最低积分: {100 if lottery_type == 'points' else 0}\n"
        text += f"参与费用: {10 if lottery_type == 'points' else 0}\n"
        text += "最大人数: 50\n入群天数: 7\n"
        if lottery_type == "invite":
            text += "邀请人数: 3\n统计天数: 7\n"
            if selection_mode == "ranking_random":
                text += "入围人数: 10\n"
        elif lottery_type == "activity":
            text += "活跃消息数: 200\n统计天数: 7\n"
            if selection_mode == "ranking_random":
                text += "入围人数: 10\n"
        text += "奖品:\n一等奖:100U,1\n二等奖:50U,3\n三等奖:10U,10\n```"

        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("❌ 取消配置", callback_data=f"lottery:cancel:{target_chat_id}")]]
        )
        await self.message_helper.safe_edit(update, text=text, parse_mode="Markdown", reply_markup=keyboard)


async def parse_lottery_config_message(update: Update, context: ContextTypes.DEFAULT_TYPE, session, state: object, text: str) -> None:
    try:
        lottery_type = state.state_data.get("lottery_type", "common")
        selection_mode = state.state_data.get("selection_mode", "threshold_random")
        config: ParsedLotteryConfig = parse_lottery_config_text(
            text,
            lottery_type=lottery_type,
            selection_mode=selection_mode,
        )

        target_chat_id = state.state_data.get("target_chat_id") or update.effective_chat.id
        lottery = await create_lottery(
            session,
            chat_id=target_chat_id,
            created_by_user_id=update.effective_user.id,
            title=config.title,
            draw_time=config.draw_time,
            prizes=config.prizes,
            description=config.description,
            lottery_type=config.lottery_type,
            qualification_rules={
                "window_days": config.qualification_window_days,
                "required_invites": config.required_invites,
                "required_activity_count": config.required_activity_count,
                "finalist_limit": config.finalist_limit,
                "selection_mode": config.selection_mode,
            },
            min_points=config.min_points,
            max_participants=config.max_participants,
            participation_cost=config.participation_cost,
            requirement_days=config.requirement_days,
        )

        await clear_user_state(session, chat_id=update.effective_chat.id, user_id=update.effective_user.id)
        await session.commit()

        announcement_text = format_lottery_announcement_text(config)
        try:
            keyboard = None
            if config.selection_mode != "ranking_random":
                from backend.features.activity.ui.lottery import get_join_keyboard

                keyboard = get_join_keyboard(lottery.id)
            sent_message = await context.bot.send_message(
                chat_id=target_chat_id,
                text=announcement_text,
                reply_markup=keyboard,
            )
            setting = await get_or_create_lottery_setting(session, target_chat_id)
            if setting.publish_pin_enabled:
                try:
                    await context.bot.pin_chat_message(chat_id=target_chat_id, message_id=sent_message.message_id)
                except Exception:
                    pass
            log.info("lottery_announcement_sent", lottery_id=lottery.id, target_chat_id=target_chat_id)
        except Exception as exc:
            log.error("lottery_announcement_failed", lottery_id=lottery.id, target_chat_id=target_chat_id, error=str(exc))

        reply_text = f"✅ {_lottery_type_title(config.lottery_type)}创建成功！\n\n"
        reply_text += f"📢 标题: {config.title}\n"
        reply_text += f"🕐 开奖时间: {config.draw_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        reply_text += f"🎁 奖品数: {len(config.prizes)}\n"
        if config.min_points > 0:
            reply_text += f"💰 最低积分: {config.min_points}\n"
        if config.participation_cost > 0:
            reply_text += f"💸 参与费用: {config.participation_cost} 积分\n"
        if config.required_invites > 0:
            reply_text += f"👥 邀请人数门槛: {config.required_invites}\n"
        if config.required_activity_count > 0:
            reply_text += f"🔥 活跃消息门槛: {config.required_activity_count}\n"
        if config.qualification_window_days > 0:
            reply_text += f"📊 统计天数: 最近 {config.qualification_window_days} 天\n"
        if config.max_participants > 0:
            reply_text += f"👥 最大人数: {config.max_participants}\n"
        if config.requirement_days > 0:
            reply_text += f"📅 入群天数: {config.requirement_days}\n"
        reply_text += "\n📢 已发送公告到群组"

        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("🔙 返回抽奖管理", callback_data=f"adm:menu:lottery:{target_chat_id}")],
                [InlineKeyboardButton("🏠 返回主菜单", callback_data=f"adm:menu:{target_chat_id}")],
            ]
        )
        await update.effective_message.reply_text(reply_text, reply_markup=keyboard)
    except ValueError as exc:
        await update.effective_message.reply_text(f"❌ 配置错误: {exc}\n\n请重新发送配置，或使用 /cancel 取消。")
        await session.commit()
    except Exception as exc:
        await update.effective_message.reply_text(f"❌ 解析失败: {exc}\n\n请检查格式后重新发送。")
        await session.commit()
