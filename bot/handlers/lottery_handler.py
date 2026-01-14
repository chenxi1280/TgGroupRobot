from __future__ import annotations

import datetime as dt
import random
import re
import structlog

from telegram import Update
from telegram.ext import ContextTypes

from bot.db.session import Database
from bot.handlers.base.base_handler import BaseHandler
from bot.models.enums import ConversationStateType, LotteryDrawMode, PointsTxnType
from bot.models.core import ChatMember, TgUser
from bot.services.core.chat_service import ensure_chat, get_chat_settings
from bot.services.activity.lottery_service import (
    create_lottery,
    create_lottery_winner,
    format_lottery_announcement_text,
    format_lottery_stats_message,
    get_lottery,
    get_lottery_participant_count,
    get_lottery_participants,
    get_lottery_stats,
    join_lottery,
    JoinResult,
    parse_lottery_config_text,
    ParsedLotteryConfig,
)
from bot.services.activity.points_service import change_points, get_balance
from bot.services.state.state_service import clear_user_state, get_user_state, set_user_state
from bot.keyboards.activity.lottery import (
    manual_draw_prize_keyboard,
    manual_draw_summary_keyboard,
    manual_draw_summary_keyboard_with_winners,
)
from bot.utils.callback_parser import CallbackParser

from sqlalchemy import select

log = structlog.get_logger(__name__)


class LotteryHandler(BaseHandler):
    """抽奖 Handler"""

    def __init__(self) -> None:
        super().__init__()
        # 关闭默认权限检查，因为我们在各个方法中自己处理
        self._require_admin_permission = False

    async def process(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
    ) -> None:
        """处理抽奖回调（用于 BaseHandler 抽象方法）"""
        # LotteryHandler 不使用 process 方法，直接调用各个方法
        # 适配器函数会直接调用 show_menu, handle_join 等方法
        pass

    # ==================== 菜单显示 ====================

    async def show_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
    ) -> None:
        """显示抽奖菜单"""
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            from bot.models.core import TgChat

            # 获取群组信息
            chat_stmt = select(TgChat).where(TgChat.id == target_chat_id)
            chat_result = await session.execute(chat_stmt)
            target_chat = chat_result.scalar_one_or_none()

            stats = await get_lottery_stats(session, target_chat_id)
            await session.commit()

        chat_title = target_chat.title if target_chat else f"群组{target_chat_id}"
        # 使用 service 层格式化消息
        text = f"🎁[{chat_title}]抽奖\n\n{format_lottery_stats_message(stats)}"

        from bot.keyboards.activity.lottery import lottery_menu_keyboard

        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=lottery_menu_keyboard(target_chat_id)
        )

    async def start_create_flow(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
    ) -> None:
        """开始创建抽奖流程"""
        q = update.callback_query
        user = update.effective_user

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            await ensure_chat(session, chat_id=target_chat_id, chat_type="supergroup", title=None)
            from bot.services.core.user_service import ensure_user
            await ensure_user(
                session,
                user_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                language_code=user.language_code,
            )

            # 设置状态：等待输入配置，保存目标群组ID
            await set_user_state(
                session,
                chat_id=q.message.chat.id,  # 使用当前聊天（私聊）存储状态
                user_id=user.id,
                state_type=ConversationStateType.lottery_create.value,
                state_data={"step": "config", "target_chat_id": target_chat_id},
            )
            await session.commit()

        text = "🎁创建抽奖  ( /cancel 取消)\n\n"
        text += "请按以下格式一次性发送配置：\n\n"
        text += "```\n"
        text += "标题|描述（可选）\n"
        text += "开奖时间: 2025-12-30 12:00\n"
        text += "最低积分: 0\n"
        text += "参与费用: 0\n"
        text += "最大人数: 0（0=无限制）\n"
        text += "入群天数: 0（0=无限制）\n"
        text += "奖品:\n"
        text += "奖品1名称,数量\n"
        text += "奖品2名称,数量\n"
        text += "...\n"
        text += "```\n\n"
        text += "示例:\n"
        text += "```\n"
        text += "新年大抽奖|祝大家新年快乐！\n"
        text += "开奖时间: 2025-12-31 20:00\n"
        text += "最低积分: 100\n"
        text += "参与费用: 10\n"
        text += "最大人数: 50\n"
        text += "入群天数: 7\n"
        text += "奖品:\n"
        text += "一等奖:100U,1\n"
        text += "二等奖:50U,3\n"
        text += "三等奖:10U,10\n"
        text += "```"

        await self.message_helper.safe_edit(update, text=text, parse_mode="Markdown")

    async def handle_join(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        lottery_id: int,
    ) -> None:
        """处理用户参与抽奖"""
        q = update.callback_query
        chat = update.effective_chat
        user = update.effective_user

        if chat.type == "private":
            await self.message_helper.safe_edit(update, "请在群里使用。")
            return

        db: Database = context.application.bot_data["db"]
        participant_count = 0
        error_msg = None

        async with db.session_factory() as session:
            # 获取抽奖信息
            lottery = await get_lottery(session, lottery_id)
            if not lottery:
                error_msg = "抽奖不存在。"
            elif lottery.chat_id != chat.id:
                error_msg = "此抽奖不属于当前群组。"
            else:
                # 获取用户积分
                user_points = await get_balance(session, chat.id, user.id)

                # 获取用户入群时间
                stmt = select(ChatMember).where(
                    ChatMember.chat_id == chat.id,
                    ChatMember.user_id == user.id
                )
                result = await session.execute(stmt)
                member = result.scalar_one_or_none()
                member_joined_at = member.joined_at if member else None

                # 检查是否可以参与并扣费
                result = await join_lottery(
                    session,
                    lottery_id=lottery_id,
                    user_id=user.id,
                    points_balance=user_points,
                    member_joined_at=member_joined_at,
                )

                if not result.success:
                    error_messages = {
                        "already_joined": "你已经参与过此抽奖了",
                        "lottery_not_open": "抽奖尚未开始",
                        "lottery_closed": "抽奖已结束",
                        "lottery_completed": "抽奖已开奖",
                        "insufficient_points": f"积分不足，需要至少 {lottery.min_points} 积分",
                        "max_participants_reached": "参与人数已满",
                        "not_member_long_enough": f"入群天数不足，需要 {lottery.requirement_days} 天以上",
                        "outside_join_time": "不在参与时间内",
                    }
                    error_msg = error_messages.get(result.reason, "无法参与抽奖")
                else:
                    # 扣除参与费用
                    if lottery.participation_cost > 0:
                        success, new_balance = await change_points(
                            session,
                            chat_id=chat.id,
                            user_id=user.id,
                            amount=-lottery.participation_cost,
                            txn_type=PointsTxnType.lottery_join.value,
                            reason=f"参与抽奖: {lottery.title}",
                        )
                        if not success:
                            error_msg = "积分不足，无法参与"
                            await session.rollback()

                if not error_msg:
                    participant_count = await get_lottery_participant_count(session, lottery_id)
                else:
                    await session.rollback()

            await session.commit()

        # 显示结果
        if error_msg:
            await q.answer(error_msg, show_alert=True)
        else:
            await q.answer(f"🎉 参与成功！当前人数: {participant_count}", show_alert=True)

    async def handle_draw(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        lottery_id: int,
    ) -> None:
        """处理开奖"""
        q = update.callback_query
        chat = update.effective_chat

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            lottery = await get_lottery(session, lottery_id)
            if not lottery:
                await self.message_helper.safe_edit(update, "抽奖不存在。")
                await session.commit()
                return

            if lottery.chat_id != chat.id:
                await self.message_helper.safe_edit(update, "此抽奖不属于当前群组。")
                await session.commit()
                return

            if lottery.status != "pending":
                await self.message_helper.safe_edit(update, "抽奖已开奖或已取消。")
                await session.commit()
                return

            # 获取参与者
            participants = await get_lottery_participants(session, lottery_id)
            if not participants:
                await self.message_helper.safe_edit(update, "没有人参与抽奖。")
                await session.commit()
                return

            # 检查开奖模式
            if lottery.draw_mode == LotteryDrawMode.manual.value:
                # 手动开奖模式
                await session.commit()

                # 获取参与者用户信息
                user_ids = [p.user_id for p in participants]
                stmt = select(TgUser).where(TgUser.id.in_(user_ids))
                result = await session.execute(stmt)
                users = {u.id: u for u in result.scalars().all()}

                # 为每个参与者添加用户信息
                for p in participants:
                    p.user_info = users.get(p.user_id)

                # 构建奖品列表
                prize_list = []
                for i, prize in enumerate(lottery.prizes):
                    quantity = prize.get("quantity", 1)
                    for j in range(quantity):
                        prize_list.append({
                            "prize_index": i * 10 + j,
                            "name": prize["name"],
                            "original_index": i,
                        })

                text = f"📋 手动选择中奖人\n\n"
                text += f"抽奖: {lottery.title}\n"
                text += f"参与人数: {len(participants)}\n"
                text += f"奖品数量: {len(prize_list)}\n\n"
                text += f"请为每个奖项选择中奖人："

                await self.message_helper.safe_edit(
                    update,
                    text=text,
                    reply_markup=manual_draw_summary_keyboard(lottery_id, prize_list),
                )
                return

            # 随机开奖模式
            from bot.services.activity.lottery_service import (
                perform_random_draw,
                generate_lottery_announcement,
                distribute_lottery_rewards,
            )

            winners = await perform_random_draw(session, lottery)

            if winners:
                # 获取中奖用户信息
                user_ids = [w.user_id for w in winners]
                user_stmt = select(TgUser).where(TgUser.id.in_(user_ids))
                user_result = await session.execute(user_stmt)
                users = {u.id: u for u in user_result.scalars().all()}

                # 发放积分奖励
                await distribute_lottery_rewards(session, lottery, winners)

                # 更新抽奖状态
                lottery.status = "completed"
                lottery.drawn_at = dt.datetime.now(dt.timezone.utc)

                # 生成开奖公告
                announcement = generate_lottery_announcement(lottery, winners, users)

                await session.commit()
                await self.message_helper.safe_edit(update, text=announcement, parse_mode="Markdown")
            else:
                await self.message_helper.safe_edit(update, "没有人参与抽奖。")
                await session.commit()


# 创建单例实例
_lottery_handler = LotteryHandler()


# ==================== 适配器函数（供 Router 注册）====================

# ============================================
# 回调处理器
# ============================================

async def lottery_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """抽奖菜单回调"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    # 从回调数据中提取目标群组ID
    data = q.data or ""
    target_chat_id = None
    if data.startswith("lot:menu:"):
        cb = CallbackParser.parse(data)
        target_chat_id = cb.get_int(2)

    # 如果没有指定群组ID，使用当前群组
    if target_chat_id is None:
        if chat.type == "private":
            await _lottery_handler.message_helper.safe_edit(update, "请在群里使用。")
            return
        target_chat_id = chat.id

    # 检查管理员权限
    if not await _lottery_handler.permission_helper.is_user_admin(context, target_chat_id, user.id):
        await _lottery_handler.message_helper.safe_edit(update, "需要管理员权限。")
        return

    # 使用 Handler 处理
    await _lottery_handler.show_menu(update, context, target_chat_id)


async def lottery_create_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """开始创建抽奖流程"""
    try:
        log.info("lottery_create_start_entered")

        if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
            log.warning("lottery_create_start_missing_data")
            return
        q = update.callback_query
        await q.answer()

        chat = update.effective_chat
        user = update.effective_user

        # 从回调数据中提取目标群组ID
        data = q.data or ""
        target_chat_id = None
        if data.startswith("lot:create:"):
            cb = CallbackParser.parse(data)
            target_chat_id = cb.get_int(2)

        log.info("lottery_create_start_called", callback_data=data, target_chat_id=target_chat_id, user_id=user.id, chat_type=chat.type)

        # 如果没有指定群组ID，使用当前群组
        if target_chat_id is None:
            if chat.type == "private":
                await _lottery_handler.message_helper.safe_edit(update, "请在群里使用。")
                return
            target_chat_id = chat.id

        # 检查管理员权限
        log.info("lottery_create_checking_admin", target_chat_id=target_chat_id, user_id=user.id)
        is_admin = await _lottery_handler.permission_helper.is_user_admin(context, target_chat_id, user.id)
        log.info("lottery_create_admin_check_result", target_chat_id=target_chat_id, user_id=user.id, is_admin=is_admin)
        if not is_admin:
            log.warning("lottery_create_permission_denied", target_chat_id=target_chat_id, user_id=user.id)
            await _lottery_handler.message_helper.safe_edit(
                update,
                f"需要管理员权限。\n\n请确保你是群组 {target_chat_id} 的管理员，且 Bot 已加入该群组。"
            )
            return

        # 使用 Handler 处理
        await _lottery_handler.start_create_flow(update, context, target_chat_id)
        log.info("lottery_create_start_success")
    except Exception as e:
        log.exception("lottery_create_start_error", error=str(e))
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(f"发生错误: {str(e)}")
            except:
                pass


# ============================================
# 消息处理器
# ============================================

async def lottery_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理抽奖创建流程中的消息"""
    # 诊断日志
    import structlog
    log = structlog.get_logger(__name__)
    log.warning("=== LOTTERY_MESSAGE_HANDLER CALLED ===")

    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return

    chat = update.effective_chat
    user = update.effective_user
    text = update.effective_message.text or ""

    # 支持私聊和群聊中的消息
    if not text:
        return

    try:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            # 获取用户状态 - 私聊中使用 user.id 查询状态，与其他处理器保持一致
            state_chat_id = user.id if chat.type == "private" else chat.id
            state = await get_user_state(session, chat_id=state_chat_id, user_id=user.id)

            # 关键修复：不要 return，让代码继续执行到块结束
            if state is None or state.state_type != ConversationStateType.lottery_create.value:
                log.info("lottery_state_not_match", state_type=state.state_type if state else None)
                # 不要在这里 return，让代码继续执行到块结束
            else:
                step = state.state_data.get("step")
                log.info("lottery_step", step=step)

                if step == "config":
                    await _parse_lottery_config(update, context, session, state, text)
                else:
                    await session.commit()

            log.info("lottery_handler_done")
    except Exception as e:
        # 确保异常被记录但不会阻止后续处理器
        import structlog
        log = structlog.get_logger(__name__)
        log.exception(
            "lottery_message_handler_error",
            error=str(e),
            error_type=type(e).__name__,
            traceback=True
        )
        # 明确返回，不重新抛出异常，让后续处理器继续执行
        return


async def _parse_lottery_config(update: Update, context: ContextTypes.DEFAULT_TYPE, session, state: object, text: str) -> None:
    """解析抽奖配置（使用 service 层解析）"""
    try:
        # 使用 service 层解析配置
        config: ParsedLotteryConfig = parse_lottery_config_text(text)

        # 从状态中获取目标群组ID
        target_chat_id = state.state_data.get("target_chat_id")
        if not target_chat_id:
            target_chat_id = update.effective_chat.id

        # 创建抽奖
        lottery = await create_lottery(
            session,
            chat_id=target_chat_id,
            created_by_user_id=update.effective_user.id,
            title=config.title,
            draw_time=config.draw_time,
            prizes=config.prizes,
            description=config.description,
            min_points=config.min_points,
            max_participants=config.max_participants,
            participation_cost=config.participation_cost,
            requirement_days=config.requirement_days,
        )

        # 清除状态
        from bot.services.state.state_service import clear_user_state
        await clear_user_state(session, chat_id=update.effective_chat.id, user_id=update.effective_user.id)
        await session.commit()

        # 使用 service 层格式化公告文本
        announcement_text = format_lottery_announcement_text(config)

        # 向目标群组发送抽奖公告
        try:
            from bot.keyboards.activity.lottery import get_join_keyboard
            keyboard = get_join_keyboard(lottery.id)
            await context.bot.send_message(
                chat_id=target_chat_id,
                text=announcement_text,
                reply_markup=keyboard
            )
            log.info("lottery_announcement_sent", lottery_id=lottery.id, target_chat_id=target_chat_id)
        except Exception as e:
            log.error("lottery_announcement_failed", lottery_id=lottery.id, target_chat_id=target_chat_id, error=str(e))

        # 返回成功消息给用户
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        reply_text = f"✅ 抽奖创建成功！\n\n"
        reply_text += f"📢 标题: {config.title}\n"
        reply_text += f"🕐 开奖时间: {config.draw_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        reply_text += f"🎁 奖品数: {len(config.prizes)}\n"
        if config.min_points > 0:
            reply_text += f"💰 最低积分: {config.min_points}\n"
        if config.participation_cost > 0:
            reply_text += f"💸 参与费用: {config.participation_cost} 积分\n"
        if config.max_participants > 0:
            reply_text += f"👥 最大人数: {config.max_participants}\n"
        if config.requirement_days > 0:
            reply_text += f"📅 入群天数: {config.requirement_days}\n"
        reply_text += f"\n📢 已发送公告到群组"

        # 只显示一个返回按钮
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("« 返回管理菜单", callback_data=f"adm:menu:{target_chat_id}")]
        ])

        await update.effective_message.reply_text(reply_text, reply_markup=keyboard)

    except ValueError as e:
        await update.effective_message.reply_text(f"❌ 配置错误: {e}\n\n请重新发送配置，或使用 /cancel 取消。")
        await session.commit()
    except Exception as e:
        await update.effective_message.reply_text(f"❌ 解析失败: {e}\n\n请检查格式后重新发送。")
        await session.commit()


# ============================================
# 用户参与抽奖
# ============================================

async def join_lottery_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """用户参与抽奖回调"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return

    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    if chat.type == "private":
        await _lottery_handler.message_helper.safe_edit(update, "请在群里使用。")
        return

    # 解析抽奖ID
    data = q.data
    if not data.startswith("join_lottery_"):
        return

    try:
        lottery_id = int(data.split("_")[-1])
    except (ValueError, IndexError):
        await _lottery_handler.message_helper.safe_edit(update, "无效的抽奖。")
        return

    # 使用 Handler 处理
    await _lottery_handler.handle_join(update, context, lottery_id)


# ============================================
# 开奖处理
# ============================================

async def draw_lottery_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """开奖回调"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return

    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    if chat.type == "private":
        await _lottery_handler.message_helper.safe_edit(update, "请在群里使用。")
        return

    if not await _lottery_handler.permission_helper.is_user_admin(context, chat.id, user.id):
        await _lottery_handler.message_helper.safe_edit(update, "需要管理员权限。")
        return

    # 解析抽奖ID
    data = q.data
    if not data.startswith("draw_lottery_"):
        return

    try:
        lottery_id = int(data.split("_")[-1])
    except (ValueError, IndexError):
        await _lottery_handler.message_helper.safe_edit(update, "无效的抽奖。")
        return

    # 使用 Handler 处理
    await _lottery_handler.handle_draw(update, context, lottery_id)


# ============================================
# 手动开奖回调处理器
# ============================================

async def manual_draw_select_prize_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """选择奖项回调 - 显示参与者列表"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return

    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    if not await _lottery_handler.permission_helper.is_user_admin(context, chat.id, user.id):
        await _lottery_handler.message_helper.safe_edit(update, "需要管理员权限。")
        return

    data = q.data or ""
    cb = CallbackParser.parse(data)
    if cb.length() < 5:
        return

    lottery_id = cb.get_int(2)
    prize_index = cb.get_int(3)
    prize_name = cb.get(4)

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        lottery = await get_lottery(session, lottery_id)
        if not lottery:
            await _lottery_handler.message_helper.safe_edit(update, "抽奖不存在。")
            await session.commit()
            return

        participants = await get_lottery_participants(session, lottery_id)

        # 获取参与者用户信息
        user_ids = [p.user_id for p in participants]
        stmt = select(TgUser).where(TgUser.id.in_(user_ids))
        result = await session.execute(stmt)
        users = {u.id: u for u in result.scalars().all()}

        # 为每个参与者添加用户信息
        for p in participants:
            p.user_info = users.get(p.user_id)

        await session.commit()

    text = f"🎁 选择中奖人\n\n"
    text += f"奖项: {prize_name}\n"
    text += f"参与人数: {len(participants)}\n\n"
    text += f"请选择中奖者："

    await _lottery_handler.message_helper.safe_edit(
        update,
        text=text,
        reply_markup=manual_draw_prize_keyboard(lottery_id, prize_index, prize_name, participants),
    )


async def manual_draw_select_winner_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """选择中奖人回调"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return

    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    if not await _lottery_handler.permission_helper.is_user_admin(context, chat.id, user.id):
        await _lottery_handler.message_helper.safe_edit(update, "需要管理员权限。")
        return

    data = q.data or ""
    cb = CallbackParser.parse(data)
    if cb.length() < 6:
        return

    lottery_id = cb.get_int(2)
    prize_index = cb.get_int(3)
    winner_user_id = cb.get_int(4)
    prize_name = cb.get(5)

    # 保存中奖人信息到状态
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        # 获取或创建手动开奖状态
        state = await get_user_state(session, chat.id, user.id)
        if not state or state.state_type != "manual_draw":
            state = await set_user_state(session, chat.id, user.id, "manual_draw", {})

        # 更新中奖人信息
        winners = state.state_data.get("winners", {})
        winners[prize_index] = {
            "user_id": winner_user_id,
            "prize_name": prize_name,
        }
        state.state_data["winners"] = winners
        state.state_data["lottery_id"] = lottery_id
        await session.commit()

        # 获取抽奖信息
        lottery = await get_lottery(session, lottery_id)
        prizes = lottery.prizes if lottery else []

    # 获取中奖人名称
    stmt = select(TgUser).where(TgUser.id == winner_user_id)
    result = await session.execute(stmt)
    winner_user = result.scalar_one_or_none()
    winner_name = winner_user.first_name or winner_user.last_name or winner_user.username or f"用户{winner_user_id}" if winner_user else "未知用户"

    await _lottery_handler.message_helper.safe_edit(
        update,
        text=f"✅ 已选择中奖人\n\n"
        f"奖项: {prize_name}\n"
        f"中奖人: {winner_name}\n\n"
        f"请继续选择其他奖项或完成开奖。",
        reply_markup=manual_draw_summary_keyboard_with_winners(lottery_id, prizes, winners),
    )


async def manual_draw_complete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """完成手动开奖回调"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return

    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    if not await _lottery_handler.permission_helper.is_user_admin(context, chat.id, user.id):
        await _lottery_handler.message_helper.safe_edit(update, "需要管理员权限。")
        return

    data = q.data or ""
    cb = CallbackParser.parse(data)
    lottery_id = cb.get_int(2, default=0)

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        # 获取中奖人信息
        state = await get_user_state(session, chat.id, user.id)
        if not state or state.state_type != "manual_draw":
            await _lottery_handler.message_helper.safe_edit(update, "未找到开奖信息，请重新开始。")
            await session.commit()
            return

        winners = state.state_data.get("winners", {})
        if not winners:
            await _lottery_handler.message_helper.safe_edit(update, "请先为所有奖项选择中奖人。")
            await session.commit()
            return

        lottery = await get_lottery(session, lottery_id)
        if not lottery:
            await _lottery_handler.message_helper.safe_edit(update, "抽奖不存在。")
            await session.commit()
            return

        if lottery.status != "pending":
            await _lottery_handler.message_helper.safe_edit(update, "抽奖已开奖或已取消。")
            await session.commit()
            return

        # 构建奖品列表
        prize_pool = []
        for prize in lottery.prizes:
            for _ in range(prize.get("quantity", 1)):
                prize_pool.append(prize["name"])

        # 检查是否所有奖品都已选择
        total_prizes = len(prize_pool)
        selected_prizes = len(winners)
        if selected_prizes < total_prizes:
            await _lottery_handler.message_helper.safe_edit(
                update,
                f"还有 {total_prizes - selected_prizes} 个奖项未选择中奖人，请先完成选择。"
            )
            await session.commit()
            return

        # 创建中奖记录并发放积分奖励
        from bot.services.activity.lottery_service import distribute_lottery_rewards

        # 获取所有中奖用户信息
        winner_user_ids = [w["user_id"] for w in winners.values()]
        user_stmt = select(TgUser).where(TgUser.id.in_(winner_user_ids))
        user_result = await session.execute(user_stmt)
        users = {u.id: u for u in user_result.scalars().all()}

        winners_list = []
        for prize_index, winner_info in winners.items():
            # 查找对应的奖品配置
            prize_index_int = int(prize_index)
            original_index = prize_index_int // 10
            prize_config = lottery.prizes[original_index]
            points_reward = prize_config.get("points_reward", 0)

            winner = await create_lottery_winner(
                session,
                lottery_id=lottery_id,
                user_id=winner_info["user_id"],
                prize_name=winner_info["prize_name"],
                prize_index=prize_index_int,
            )
            winner.points_reward = points_reward
            winners_list.append(winner)

        # 发放积分奖励
        await distribute_lottery_rewards(session, lottery, winners_list)

        # 更新抽奖状态
        lottery.status = "completed"
        lottery.drawn_at = dt.datetime.now(dt.UTC)

        # 生成开奖公告（含@）
        from bot.services.activity.lottery_service import generate_lottery_announcement
        announcement = generate_lottery_announcement(lottery, winners_list, users)

        # 清除状态
        await clear_user_state(session, chat.id, user.id)

        await session.commit()

        await _lottery_handler.message_helper.safe_edit(update, text=announcement, parse_mode="Markdown")


async def manual_draw_winner_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """中奖人列表翻页回调"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return

    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    if not await _lottery_handler.permission_helper.is_user_admin(context, chat.id, user.id):
        await _lottery_handler.message_helper.safe_edit(update, "需要管理员权限。")
        return

    data = q.data or ""
    cb = CallbackParser.parse(data)
    if cb.length() < 5:
        return

    lottery_id = cb.get_int(2)
    prize_index = cb.get_int(3)
    page = cb.get_int(4)

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        lottery = await get_lottery(session, lottery_id)
        if not lottery:
            await _lottery_handler.message_helper.safe_edit(update, "抽奖不存在。")
            await session.commit()
            return

        # 获取奖品名称
        prizes = lottery.prizes
        original_index = prize_index // 10
        sub_index = prize_index % 10
        prize_name = prizes[original_index]["name"]

        participants = await get_lottery_participants(session, lottery_id)

        # 获取参与者用户信息
        user_ids = [p.user_id for p in participants]
        stmt = select(TgUser).where(TgUser.id.in_(user_ids))
        result = await session.execute(stmt)
        users = {u.id: u for u in result.scalars().all()}

        # 为每个参与者添加用户信息
        for p in participants:
            p.user_info = users.get(p.user_id)

        await session.commit()

    text = f"🎁 选择中奖人\n\n"
    text += f"奖项: {prize_name}\n"
    text += f"参与人数: {len(participants)}\n\n"
    text += f"请选择中奖者："

    await _lottery_handler.message_helper.safe_edit(
        update,
        text=text,
        reply_markup=manual_draw_prize_keyboard(lottery_id, prize_index, prize_name, participants, page),
    )


async def manual_draw_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """返回手动开奖菜单"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return

    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    if not await _lottery_handler.permission_helper.is_user_admin(context, chat.id, user.id):
        await _lottery_handler.message_helper.safe_edit(update, "需要管理员权限。")
        return

    data = q.data or ""
    cb = CallbackParser.parse(data)
    lottery_id = cb.get_int(2, default=0)

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state = await get_user_state(session, chat.id, user.id)
        winners = state.state_data.get("winners", {}) if state else {}

        lottery = await get_lottery(session, lottery_id)
        if not lottery:
            await _lottery_handler.message_helper.safe_edit(update, "抽奖不存在。")
            await session.commit()
            return

        prizes = lottery.prizes if lottery else []

        await session.commit()

    if winners:
        await _lottery_handler.message_helper.safe_edit(
            update,
            text=f"📋 手动选择中奖人\n\n"
            f"抽奖: {lottery.title}\n"
            f"已选择: {len(winners)}/{len(prizes)} 个奖项",
            reply_markup=manual_draw_summary_keyboard_with_winners(lottery_id, prizes, winners),
        )
    else:
        await _lottery_handler.message_helper.safe_edit(
            update,
            text=f"📋 手动选择中奖人\n\n"
            f"抽奖: {lottery.title}\n"
            f"请为每个奖项选择中奖人：",
            reply_markup=manual_draw_summary_keyboard(lottery_id, prizes),
        )