from __future__ import annotations

import datetime as dt
import random

from telegram import Update
from telegram.ext import ContextTypes

from bot.db.session import Database
from bot.models.enums import ConversationStateType, LotteryDrawMode, PointsTxnType
from bot.models.core import ChatMember, TgUser
from bot.services.chat_service import ensure_chat, get_chat_settings
from bot.services.lottery_service import (
    create_lottery,
    create_lottery_winner,
    get_lottery,
    get_lottery_participant_count,
    get_lottery_participants,
    get_lottery_stats,
    get_lottery_winners,
    join_lottery,
    JoinResult,
)
from bot.services.points_service import change_points, get_balance
from bot.services.state_service import clear_user_state, get_user_state, set_user_state
from bot.services.telegram_perm import is_user_admin
from bot.services.user_service import ensure_user
from bot.keyboards.lottery import (
    manual_draw_prize_keyboard,
    manual_draw_summary_keyboard,
    manual_draw_summary_keyboard_with_winners,
)

from sqlalchemy import select


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
    if chat.type == "private":
        await q.edit_message_text("请在群里使用。")
        return
    if not await is_user_admin(context, chat.id, user.id):
        await q.edit_message_text("需要管理员权限。")
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
        stats = await get_lottery_stats(session, chat.id)
        await session.commit()

    text = f"🎁[{chat.title}]抽奖\n\n"
    text += f"创建的抽奖次数:{stats['total']}\n\n"
    text += f"已开奖:{stats['completed']}       未开奖:{stats['pending']}       取消:{stats['cancelled']}"

    from bot.keyboards.lottery import lottery_menu_keyboard

    await q.edit_message_text(text, reply_markup=lottery_menu_keyboard())


async def lottery_create_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """开始创建抽奖流程"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user
    if chat.type == "private":
        await q.edit_message_text("请在群里使用。")
        return
    if not await is_user_admin(context, chat.id, user.id):
        await q.edit_message_text("需要管理员权限。")
        return

    db: Database = context.application.bot_data["db"]
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

        # 设置状态：等待输入配置
        await set_user_state(
            session,
            chat_id=chat.id,
            user_id=user.id,
            state_type=ConversationStateType.lottery_create.value,
            state_data={"step": "config"},
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

    await q.edit_message_text(text, parse_mode="Markdown")


# ============================================
# 消息处理器
# ============================================

async def lottery_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理抽奖创建流程中的消息"""
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return

    chat = update.effective_chat
    user = update.effective_user
    text = update.effective_message.text or ""

    if chat.type == "private" or not text:
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        # 获取用户状态
        state = await get_user_state(session, chat_id=chat.id, user_id=user.id)
        if state is None or state.state_type != ConversationStateType.lottery_create.value:
            await session.commit()
            return

        step = state.state_data.get("step")

        if step == "config":
            await _parse_lottery_config(update, session, state, text)
        else:
            await session.commit()


async def _parse_lottery_config(update: Update, session, state: object, text: str) -> None:
    """解析抽奖配置"""
    try:
        lines = text.strip().split("\n")
        if len(lines) < 7:
            raise ValueError("配置格式不完整")

        # 解析标题和描述
        title_line = lines[0].strip()
        if "|" in title_line:
            title, description = title_line.split("|", 1)
            title = title.strip()
            description = description.strip()
        else:
            title = title_line.strip()
            description = None

        if not title:
            raise ValueError("标题不能为空")

        # 解析开奖时间
        draw_time_line = lines[1].strip()
        if not draw_time_line.startswith("开奖时间:"):
            raise ValueError("开奖时间格式错误，应为: 开奖时间: 2025-12-30 12:00")
        time_pattern = r"(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{1,2})"
        match = time_pattern.search(draw_time_line)
        if not match:
            raise ValueError("开奖时间格式错误，请使用: YYYY-MM-DD HH:MM")
        year, month, day, hour, minute = map(int, match.groups())
        local_tz = dt.timezone(dt.timedelta(hours=8))
        draw_time = dt.datetime(year, month, day, hour, minute, tzinfo=local_tz)
        draw_time_utc = draw_time.astimezone(dt.timezone.utc)

        if draw_time_utc <= dt.datetime.now(dt.timezone.utc):
            raise ValueError("开奖时间必须是未来时间")

        # 解析参与条件
        min_points = 0
        participation_cost = 0
        max_participants = 0
        requirement_days = 0

        for line in lines[2:6]:
            line = line.strip()
            if line.startswith("最低积分:"):
                min_points = int(line.split(":", 1)[1].strip())
            elif line.startswith("参与费用:"):
                participation_cost = int(line.split(":", 1)[1].strip())
            elif line.startswith("最大人数:"):
                max_participants = int(line.split(":", 1)[1].strip())
            elif line.startswith("入群天数:"):
                requirement_days = int(line.split(":", 1)[1].strip())

        # 解析奖品
        prizes = []
        prize_start = False
        for line in lines[6:]:
            line = line.strip()
            if line == "奖品:":
                prize_start = True
                continue
            if prize_start and line:
                if "," not in line:
                    raise ValueError(f"奖品格式错误: {line}")
                prize_name, quantity = line.rsplit(",", 1)
                prizes.append({"name": prize_name.strip(), "quantity": int(quantity.strip())})

        if not prizes:
            raise ValueError("至少需要一个奖品")

        # 创建抽奖
        lottery = await create_lottery(
            session,
            chat_id=update.effective_chat.id,
            created_by_user_id=update.effective_user.id,
            title=title,
            draw_time=draw_time_utc,
            prizes=prizes,
            description=description,
            min_points=min_points,
            max_participants=max_participants,
            participation_cost=participation_cost,
            requirement_days=requirement_days,
        )

        # 清除状态
        from bot.services.state_service import clear_user_state
        await clear_user_state(session, chat_id=update.effective_chat.id, user_id=update.effective_user.id)
        await session.commit()

        # 返回成功消息
        from bot.keyboards.admin import admin_main_menu
        reply_text = f"✅ 抽奖创建成功！\n\n"
        reply_text += f"📢 标题: {title}\n"
        reply_text += f"🕐 开奖时间: {draw_time.strftime('%Y-%m-%d %H:%M:%S UTC+8')}\n"
        reply_text += f"🎁 奖品数: {len(prizes)}\n"
        if min_points > 0:
            reply_text += f"💰 最低积分: {min_points}\n"
        if participation_cost > 0:
            reply_text += f"💸 参与费用: {participation_cost} 积分\n"
        if max_participants > 0:
            reply_text += f"👥 最大人数: {max_participants}\n"
        if requirement_days > 0:
            reply_text += f"📅 入群天数: {requirement_days}\n"
        reply_text += f"\n抽奖ID: {lottery.id}"

        await update.effective_message.reply_text(reply_text, reply_markup=admin_main_menu())

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
        await q.edit_message_text("请在群里使用。")
        return

    # 解析抽奖ID
    data = q.data
    if not data.startswith("join_lottery_"):
        return

    try:
        lottery_id = int(data.split("_")[-1])
    except (ValueError, IndexError):
        await q.edit_message_text("无效的抽奖。")
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
                # 扣除参与费用（在 join_lottery 之外单独处理，因为需要检查余额）
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
                    # 获取当前参与人数
                    participant_count = await get_lottery_participant_count(session, lottery_id)
                else:
                    # 扣费失败，确保不提交任何更改
                    await session.rollback()

        await session.commit()

    # 显示结果
    if error_msg:
        await q.answer(error_msg, show_alert=True)
    else:
        await q.answer(f"🎉 参与成功！当前人数: {participant_count}", show_alert=True)


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
        await q.edit_message_text("请在群里使用。")
        return

    if not await is_user_admin(context, chat.id, user.id):
        await q.edit_message_text("需要管理员权限。")
        return

    # 解析抽奖ID
    data = q.data
    if not data.startswith("draw_lottery_"):
        return

    try:
        lottery_id = int(data.split("_")[-1])
    except (ValueError, IndexError):
        await q.edit_message_text("无效的抽奖。")
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        lottery = await get_lottery(session, lottery_id)
        if not lottery:
            await q.edit_message_text("抽奖不存在。")
            await session.commit()
            return

        if lottery.chat_id != chat.id:
            await q.edit_message_text("此抽奖不属于当前群组。")
            await session.commit()
            return

        if lottery.status != "pending":
            await q.edit_message_text("抽奖已开奖或已取消。")
            await session.commit()
            return

        # 获取参与者
        participants = await get_lottery_participants(session, lottery_id)
        if not participants:
            await q.edit_message_text("没有人参与抽奖。")
            await session.commit()
            return

        # 检查开奖模式
        if lottery.draw_mode == LotteryDrawMode.manual.value:
            # 手动开奖模式 - 进入选择中奖人流程
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

            await q.edit_message_text(
                text,
                reply_markup=manual_draw_summary_keyboard(lottery_id, prize_list),
            )
            return

        # 随机开奖模式（原有逻辑）
        winners_text = f"🎉【{lottery.title}】开奖结果 🎉\n\n"
        winners_text += f"参与人数: {len(participants)}\n\n"
        winners_text += "🏆 中奖名单:\n"

        # 展开奖品列表
        prize_pool = []
        for prize in lottery.prizes:
            for _ in range(prize.get("quantity", 1)):
                prize_pool.append(prize["name"])

        if not prize_pool:
            await q.edit_message_text("奖品配置错误。")
            await session.commit()
            return

        # 随机抽取中奖者
        random.shuffle(participants)
        random.shuffle(prize_pool)

        win_count = min(len(participants), len(prize_pool))

        for i in range(win_count):
            participant = participants[i]
            prize_name = prize_pool[i]

            await create_lottery_winner(
                session,
                lottery_id=lottery_id,
                user_id=participant.user_id,
                prize_name=prize_name,
                prize_index=i,
            )

            winners_text += f"\n{i + 1}. {prize_name}"

        # 更新抽奖状态
        from bot.models.core import Lottery
        lottery.status = "completed"
        lottery.drawn_at = dt.datetime.now(dt.timezone.utc)

        await session.commit()

        await q.edit_message_text(winners_text)


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

    if not await is_user_admin(context, chat.id, user.id):
        await q.edit_message_text("需要管理员权限。")
        return

    data = q.data or ""
    parts = data.split(":")
    if len(parts) < 4:
        return

    lottery_id = int(parts[2])
    prize_index = int(parts[3])
    prize_name = parts[4]

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        lottery = await get_lottery(session, lottery_id)
        if not lottery:
            await q.edit_message_text("抽奖不存在。")
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

    await q.edit_message_text(
        text,
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

    if not await is_user_admin(context, chat.id, user.id):
        await q.edit_message_text("需要管理员权限。")
        return

    data = q.data or ""
    parts = data.split(":")
    if len(parts) < 6:
        return

    lottery_id = int(parts[2])
    prize_index = int(parts[3])
    winner_user_id = int(parts[4])
    prize_name = parts[5]

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

    await q.edit_message_text(
        f"✅ 已选择中奖人\n\n"
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

    if not await is_user_admin(context, chat.id, user.id):
        await q.edit_message_text("需要管理员权限。")
        return

    data = q.data or ""
    parts = data.split(":")
    lottery_id = int(parts[2]) if len(parts) > 2 else 0

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        # 获取中奖人信息
        state = await get_user_state(session, chat.id, user.id)
        if not state or state.state_type != "manual_draw":
            await q.edit_message_text("未找到开奖信息，请重新开始。")
            await session.commit()
            return

        winners = state.state_data.get("winners", {})
        if not winners:
            await q.edit_message_text("请先为所有奖项选择中奖人。")
            await session.commit()
            return

        lottery = await get_lottery(session, lottery_id)
        if not lottery:
            await q.edit_message_text("抽奖不存在。")
            await session.commit()
            return

        if lottery.status != "pending":
            await q.edit_message_text("抽奖已开奖或已取消。")
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
            await q.edit_message_text(f"还有 {total_prizes - selected_prizes} 个奖项未选择中奖人，请先完成选择。")
            await session.commit()
            return

        # 创建中奖记录
        winners_text = f"🎉【{lottery.title}】开奖结果 🎉\n\n"
        winners_text += f"参与人数: {len(await get_lottery_participants(session, lottery_id))}\n\n"
        winners_text += "🏆 中奖名单:\n"

        for prize_index, winner_info in winners.items():
            await create_lottery_winner(
                session,
                lottery_id=lottery_id,
                user_id=winner_info["user_id"],
                prize_name=winner_info["prize_name"],
                prize_index=int(prize_index),
            )

            # 获取中奖人名称
            stmt = select(TgUser).where(TgUser.id == winner_info["user_id"])
            result = await session.execute(stmt)
            winner_user = result.scalar_one_or_none()
            winner_name = winner_user.first_name or winner_user.last_name or winner_user.username or f"用户{winner_user_id}" if winner_user else "未知用户"

            winners_text += f"\n• {winner_info['prize_name']} - {winner_name}"

        # 更新抽奖状态
        lottery.status = "completed"
        lottery.drawn_at = dt.datetime.now(dt.UTC)

        # 清除状态
        await clear_user_state(session, chat.id, user.id)

        await session.commit()

        await q.edit_message_text(winners_text)


async def manual_draw_winner_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """中奖人列表翻页回调"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return

    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    if not await is_user_admin(context, chat.id, user.id):
        await q.edit_message_text("需要管理员权限。")
        return

    data = q.data or ""
    parts = data.split(":")
    if len(parts) < 4:
        return

    lottery_id = int(parts[2])
    prize_index = int(parts[3])
    page = int(parts[4])

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        lottery = await get_lottery(session, lottery_id)
        if not lottery:
            await q.edit_message_text("抽奖不存在。")
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

    await q.edit_message_text(
        text,
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

    if not await is_user_admin(context, chat.id, user.id):
        await q.edit_message_text("需要管理员权限。")
        return

    data = q.data or ""
    parts = data.split(":")
    lottery_id = int(parts[2]) if len(parts) > 2 else 0

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state = await get_user_state(session, chat.id, user.id)
        winners = state.state_data.get("winners", {}) if state else {}

        lottery = await get_lottery(session, lottery_id)
        if not lottery:
            await q.edit_message_text("抽奖不存在。")
            await session.commit()
            return

        prizes = lottery.prizes if lottery else []

        await session.commit()

    if winners:
        await q.edit_message_text(
            f"📋 手动选择中奖人\n\n"
            f"抽奖: {lottery.title}\n"
            f"已选择: {len(winners)}/{len(prizes)} 个奖项",
            reply_markup=manual_draw_summary_keyboard_with_winners(lottery_id, prizes, winners),
        )
    else:
        await q.edit_message_text(
            f"📋 手动选择中奖人\n\n"
            f"抽奖: {lottery.title}\n"
            f"请为每个奖项选择中奖人：",
            reply_markup=manual_draw_summary_keyboard(lottery_id, prizes),
        )