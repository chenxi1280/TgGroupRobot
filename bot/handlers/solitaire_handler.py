from __future__ import annotations

import asyncio
import datetime as dt
import structlog
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from bot.db.session import Database
from bot.handlers.base.base_handler import BaseHandler
from bot.keyboards.solitaire import (
    solitaire_detail_keyboard,
    solitaire_list_keyboard,
    solitaire_menu_keyboard,
)
from bot.models.enums import SolitaireStatus
from bot.services.activity.solitaire_service import (
    close_solitaire,
    create_solitaire,
    delete_solitaire,
    format_solitaire_message,
    format_solitaire_stats_message,
    get_chat_solitaires,
    get_solitaire,
    get_solitaire_stats,
    join_solitaire,
    leave_solitaire,
    parse_config_value,
    update_entry,
)
from bot.services.state.state_service import clear_user_state, set_user_state, get_user_state
from bot.utils.callback_parser import CallbackParser
from bot.utils.chat_context import PrivateChatContext

# 创建流程状态
WAIT_CONFIG = 1
WAIT_DESCRIPTION = 2
WAIT_MAX_PARTICIPANTS = 3
WAIT_POINTS_REQUIRED = 4
WAIT_DEADLINE = 5

log = structlog.get_logger(__name__)


class SolitaireHandler(BaseHandler):
    """接龙 Handler"""

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
        """处理接龙回调（用于 BaseHandler 抽象方法）"""
        # SolitaireHandler 不使用 process 方法，直接调用各个方法
        # 适配器函数会直接调用 show_menu, show_list 等方法
        pass

    async def show_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        chat_title: str | None = None,
    ) -> None:
        """显示接龙管理菜单"""
        text = f"📋 [{chat_title or target_chat_id}] 接龙管理\n\n管理群内接龙活动"
        keyboard = solitaire_menu_keyboard()
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def show_list(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        page: int = 0,
    ) -> None:
        """显示接龙列表"""
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            solitaires = await get_chat_solitaires(session, target_chat_id)
            await session.commit()

        if not solitaires:
            keyboard = solitaire_menu_keyboard(target_chat_id)
            await self.message_helper.safe_edit(
                update,
                text="📋 接龙列表\n\n暂无接龙，点击「创建接龙」开始",
                reply_markup=keyboard,
            )
            return

        text = f"📋 接龙列表\n\n共 {len(solitaires)} 个接龙"
        keyboard = solitaire_list_keyboard(solitaires, target_chat_id, page)
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def show_stats(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
    ) -> None:
        """显示接龙统计"""
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            stats = await get_solitaire_stats(session, target_chat_id)
            await session.commit()

        # 使用 service 层格式化消息
        text = format_solitaire_stats_message(stats)

        keyboard = solitaire_menu_keyboard(target_chat_id)
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def show_detail(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        solitaire_id: int,
        target_chat_id: int,
    ) -> None:
        """显示接龙详情"""
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            solitaire = await get_solitaire(session, solitaire_id)
            if not solitaire:
                await session.commit()
                keyboard = solitaire_menu_keyboard(target_chat_id)
                await self.message_helper.safe_edit(
                    update,
                    text="接龙不存在",
                    reply_markup=keyboard
                )
                return

            text = format_solitaire_message(solitaire, show_closed=False)
            is_active = solitaire.status == SolitaireStatus.active.value
            await session.commit()

        keyboard = solitaire_detail_keyboard(solitaire_id, is_active, target_chat_id)
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)


# 创建单例实例
_solitaire_handler = SolitaireHandler()


# ==================== 适配器函数（供 Router 注册）====================

async def solitaire_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """接龙菜单回调"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    # 私聊中的接龙管理 - 从回调中获取目标群组ID
    target_chat_id = None
    if chat.type == "private":
        from bot.services.integration.chat_group_service import get_user_current_chat, get_user_managed_chats
        db: Database = context.application.bot_data["db"]
        target_chat_id = await get_user_current_chat(db, user.id)
        if target_chat_id is None:
            await _solitaire_handler.message_helper.safe_edit(update, "请先选择一个群组")
            return
        if not await _solitaire_handler.permission_helper.is_user_admin(context, target_chat_id, user.id):
            await _solitaire_handler.message_helper.safe_edit(update, "你没有该群组的管理权限")
            return

        # 返回到管理面板
        chats = await get_user_managed_chats(db, user.id, context.bot)
        from bot.handlers.admin_handler import _show_private_admin_menu
        await _show_private_admin_menu(update, context, target_chat_id, chats)
        return
    else:
        if not await _solitaire_handler.permission_helper.is_user_admin(context, chat.id, user.id):
            await _solitaire_handler.message_helper.safe_edit(update, "仅管理员可使用此功能")
            return
        target_chat_id = chat.id

    # 使用 Handler 处理
    await _solitaire_handler.show_menu(update, context, target_chat_id, chat.title)


async def solitaire_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """接龙列表回调"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    data = q.data or ""
    cb = CallbackParser.parse(data)

    # 解析页面参数
    chat = update.effective_chat
    if chat.type == "private":
        # sol:list:{chat_id}:{page} 格式
        page = cb.get_int(3, default=0)
    else:
        # 群聊场景：sol:list 或 sol:list:{page}
        page = cb.get_int(2, default=0) if cb.get(2).isdigit() else 0

    # 使用 PrivateChatContext 解析目标群组并检查权限
    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(
        update, context, chat_index=2
    )
    if target_chat_id is None:
        return  # 错误消息已发送

    # 使用 Handler 处理
    await _solitaire_handler.show_list(update, context, target_chat_id, page)


async def solitaire_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """接龙统计回调"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    # 使用 PrivateChatContext 解析目标群组并检查权限
    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(
        update, context, chat_index=2
    )
    if target_chat_id is None:
        return  # 错误消息已发送

    # 使用 Handler 处理
    await _solitaire_handler.show_stats(update, context, target_chat_id)


async def solitaire_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """接龙详情回调"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    data = q.data or ""
    cb = CallbackParser.parse(data)
    if cb.length() < 3:
        return

    solitaire_id = cb.get_int(2)
    if solitaire_id == 0:
        return

    # 使用 PrivateChatContext 解析目标群组并检查权限
    # callback_data 格式: sol:detail:{solitaire_id}:{chat_id}（私聊场景）
    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(
        update, context, chat_index=3
    )
    if target_chat_id is None:
        return  # 错误消息已发送

    # 使用 Handler 处理
    await _solitaire_handler.show_detail(update, context, solitaire_id, target_chat_id)


async def solitaire_create_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """开始创建接龙"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    # 使用 PrivateChatContext 解析目标群组并检查权限
    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(
        update, context, chat_index=2
    )
    if target_chat_id is None:
        return  # 错误消息已发送

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await set_user_state(session, chat.id, user.id, "solitaire_create", {"target_chat_id": target_chat_id})
        await session.commit()

    # 显示配置模板
    text = "➕ 创建接龙 ( /cancel 取消)\n\n"
    text += "请按以下格式一次性发送配置：\n\n"
    text += "```\n"
    text += "接龙标题\n"
    text += "描述（可选，可直接留空）\n"
    text += "最大人数: 0（0=无限制）\n"
    text += "参与积分: 0（0=无限制）\n"
    text += "截止时间: YYYY-MM-DD HH:MM（可选，可直接留空）\n"
    text += "```\n\n"
    text += "示例:\n"
    text += "```\n"
    text += "今晚聚餐\n"
    text += "一起吃火锅\n"
    text += "最大人数: 10\n"
    text += "参与积分: 50\n"
    # 计算当前时间+24小时
    now_local = dt.datetime.now(dt.timezone.utc).astimezone(dt.timezone(dt.timedelta(hours=8)))
    deadline_example = now_local + dt.timedelta(hours=24)
    text += f"截止时间: {deadline_example.strftime('%Y-%m-%d %H:%M')}\n"
    text += "```"

    await q.edit_message_text(text, parse_mode="Markdown")
    return WAIT_CONFIG


async def solitaire_create_config_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """处理一次性配置输入"""
    if update.effective_message is None or update.effective_user is None or update.effective_chat is None:
        return ConversationHandler.END

    user = update.effective_user
    chat = update.effective_chat
    text = update.effective_message.text

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state = await get_user_state(session, chat.id, user.id)
        if not state or not state.state_data.get("target_chat_id"):
            await update.effective_message.reply_text("会话已过期，请重新开始")
            return ConversationHandler.END

        target_chat_id = state.state_data["target_chat_id"]

    # 解析配置
    try:
        lines = text.strip().split("\n")

        title = lines[0].strip() if len(lines) > 0 else ""
        description = None
        max_participants = None
        points_required = None
        deadline = None

        # 解析可选参数
        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue

            if line.startswith("最大人数:") or line.startswith("最大人数："):
                try:
                    value = _parse_config_value(line, "最大人数")
                    if value:
                        max_participants = int(value)
                        if max_participants <= 0:
                            max_participants = None
                except ValueError:
                    pass
            elif line.startswith("参与积分:") or line.startswith("参与积分："):
                try:
                    value = _parse_config_value(line, "参与积分")
                    if value:
                        points_required = int(value)
                        if points_required < 0:
                            points_required = None
                except ValueError:
                    pass
            elif line.startswith("截止时间:") or line.startswith("截止时间："):
                try:
                    value = _parse_config_value(line, "截止时间")
                    if value:
                        # 解析用户输入的本地时间
                        deadline_local = dt.datetime.strptime(value, "%Y-%m-%d %H:%M")
                        # 将本地时间转换为UTC时间（假设用户使用北京时间 UTC+8）
                        local_tz = dt.timezone(dt.timedelta(hours=8))
                        deadline = deadline_local.replace(tzinfo=local_tz).astimezone(dt.timezone.utc)
                except ValueError:
                    pass
            elif line and not line.startswith("最大人数") and not line.startswith("参与积分") and not line.startswith("截止时间"):
                # 如果不是参数行，就是描述
                if not description:
                    description = line

        # 验证标题
        if not title:
            await update.effective_message.reply_text("❌ 标题不能为空\n\n请重新输入配置")
            return WAIT_CONFIG

        # 验证截止时间（如果设置了）
        if deadline:
            import datetime as dt
            now = dt.datetime.now(dt.timezone.utc)
            if deadline <= now:
                await update.effective_message.reply_text("❌ 截止时间必须是未来时间\n\n请重新输入配置")
                return WAIT_CONFIG

        # 创建接龙
        async with db.session_factory() as session:
            result = await create_solitaire(
                session,
                chat_id=target_chat_id,
                created_by_user_id=user.id,
                title=title,
                description=description,
                max_participants=max_participants,
                points_required=points_required,
                deadline=deadline,
            )

            if result.success:
                # 构建接龙消息
                text_msg = format_solitaire_message(result.solitaire)

                # 向目标群组发送接龙（带一键接龙按钮）
                try:
                    from bot.keyboards.solitaire import get_join_solitaire_keyboard
                    keyboard = get_join_solitaire_keyboard(result.solitaire.id)
                    group_message = await context.bot.send_message(
                        chat_id=target_chat_id,
                        text=text_msg,
                        reply_markup=keyboard
                    )
                    # 保存消息ID
                    result.solitaire.message_id = group_message.message_id
                    await session.commit()
                except Exception as e:
                    log.error("solitaire_send_failed", error=str(e))

                # 返回成功消息给创建者
                # 只显示一个返回按钮
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("« 返回管理菜单", callback_data=f"adm:menu:{target_chat_id}")]
                ])
                await update.effective_message.reply_text(
                    f"✅ 接龙创建成功！\n\n已发送到群组\n\n接龙ID: {result.solitaire.id}",
                    reply_markup=keyboard
                )

                await clear_user_state(session, chat.id, user.id)
                await session.commit()
            else:
                await update.effective_message.reply_text(f"❌ 创建失败: {result.error or '未知错误'}")

    except Exception as e:
        log.error("solitaire_create_error", error=str(e))
        await update.effective_message.reply_text(f"❌ 配置格式错误，请检查后重试\n\n错误: {str(e)}")
        return WAIT_CONFIG

    return ConversationHandler.END


# 删除旧的多步处理函数（保留以便兼容）
async def solitaire_create_title_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """处理标题输入"""
    if update.effective_message is None or update.effective_user is None or update.effective_chat is None:
        return ConversationHandler.END

    user = update.effective_user
    chat = update.effective_chat
    title = update.effective_message.text

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state_data = await set_user_state(session, chat.id, user.id, "solitaire_create", {"title": title})
        await session.commit()

    await update.effective_message.reply_text(
        f"标题: {state_data.state_data.get('title')}\n\n请输入接龙描述（可选）\n\n输入 /skip 跳过"
    )
    return WAIT_DESCRIPTION


async def solitaire_create_description_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """处理描述输入"""
    if update.effective_message is None or update.effective_user is None or update.effective_chat is None:
        return ConversationHandler.END

    user = update.effective_user
    chat = update.effective_chat
    text = update.effective_message.text

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state = await get_user_state(session, chat.id, user.id)
        state_data = state.state_data if state else {}
        description = None if text == "/skip" else text
        state_data["description"] = description
        await set_user_state(session, chat.id, user.id, "solitaire_create", state_data)
        await session.commit()

    await update.effective_message.reply_text(
        f"描述: {description or '无'}\n\n请输入最大参与人数（可选）\n输入数字或 /skip 跳过"
    )
    return WAIT_MAX_PARTICIPANTS


async def solitaire_create_max_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """处理最大人数输入"""
    if update.effective_message is None or update.effective_user is None or update.effective_chat is None:
        return ConversationHandler.END

    user = update.effective_user
    chat = update.effective_chat
    text = update.effective_message.text

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state = await get_user_state(session, chat.id, user.id)
        state_data = state.state_data if state else {}

    max_participants = None
    if text != "/skip":
        try:
            max_participants = int(text)
            if max_participants <= 0:
                await update.effective_message.reply_text("人数必须大于0，请重新输入或 /skip 跳过")
                return WAIT_MAX_PARTICIPANTS
        except ValueError:
            await update.effective_message.reply_text("请输入有效的数字或 /skip 跳过")
            return WAIT_MAX_PARTICIPANTS

    state_data["max_participants"] = max_participants

    async with db.session_factory() as session:
        await set_user_state(session, chat.id, user.id, "solitaire_create", state_data)
        await session.commit()

    await update.effective_message.reply_text(
        f"最大人数: {max_participants or '无限制'}\n\n请输入参与所需积分（可选）\n输入数字或 /skip 跳过"
    )
    return WAIT_POINTS_REQUIRED


async def solitaire_create_points_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """处理积分限制输入"""
    if update.effective_message is None or update.effective_user is None or update.effective_chat is None:
        return ConversationHandler.END

    user = update.effective_user
    chat = update.effective_chat
    text = update.effective_message.text

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state = await get_user_state(session, chat.id, user.id)
        state_data = state.state_data if state else {}

    points_required = None
    if text != "/skip":
        try:
            points_required = int(text)
            if points_required < 0:
                await update.effective_message.reply_text("积分不能为负数，请重新输入或 /skip 跳过")
                return WAIT_POINTS_REQUIRED
        except ValueError:
            await update.effective_message.reply_text("请输入有效的数字或 /skip 跳过")
            return WAIT_POINTS_REQUIRED

    state_data["points_required"] = points_required

    async with db.session_factory() as session:
        await set_user_state(session, chat.id, user.id, "solitaire_create", state_data)
        await session.commit()

    await update.effective_message.reply_text(
        f"积分限制: {points_required or '无限制'}\n\n请输入截止时间（可选）\n格式: YYYY-MM-DD HH:MM 或 /skip 跳过\n示例: 2024-12-31 23:59"
    )
    return WAIT_DEADLINE


async def solitaire_create_deadline_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """处理截止时间输入"""
    if update.effective_message is None or update.effective_user is None or update.effective_chat is None:
        return ConversationHandler.END

    user = update.effective_user
    chat = update.effective_chat
    text = update.effective_message.text

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state = await get_user_state(session, chat.id, user.id)
        state_data = state.state_data if state else {}

    deadline = None
    if text != "/skip":
        try:
            # 尝试解析时间格式
            deadline = dt.datetime.strptime(text, "%Y-%m-%d %H:%M")
            # 将本地时间转换为UTC（假设用户使用北京时间 UTC+8）
            if deadline.tzinfo is None:
                local_tz = dt.timezone(dt.timedelta(hours=8))
                deadline = deadline.replace(tzinfo=local_tz).astimezone(dt.timezone.utc)
        except ValueError:
            await update.effective_message.reply_text("时间格式错误，请使用 YYYY-MM-DD HH:MM 格式或 /skip 跳过")
            return WAIT_DEADLINE

    state_data["deadline"] = deadline

    # 创建接龙
    async with db.session_factory() as session:
        result = await create_solitaire(
            session,
            chat_id=chat.id,
            created_by_user_id=user.id,
            title=state_data.get("title"),
            description=state_data.get("description"),
            max_participants=state_data.get("max_participants"),
            points_required=state_data.get("points_required"),
            deadline=state_data.get("deadline"),
        )

        await clear_user_state(session, chat.id, user.id)

        await session.commit()

        if result.success:
            text_msg = format_solitaire_message(result.solitaire)
            message = await update.effective_message.reply_text(text_msg, reply_markup=solitaire_menu_keyboard())

            # 保存消息ID
            result.solitaire.message_id = message.message_id
            await session.commit()
        else:
            await update.effective_message.reply_text("❌ 创建失败", reply_markup=solitaire_menu_keyboard())

    return ConversationHandler.END


async def solitaire_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """取消创建流程"""
    if update.callback_query is None or update.effective_user is None or update.effective_chat is None:
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    # 获取目标群组ID
    target_chat_id = None
    if chat.type == "private":
        from bot.services.integration.chat_group_service import get_user_current_chat
        db: Database = context.application.bot_data["db"]
        target_chat_id = await get_user_current_chat(db, user.id)
    else:
        target_chat_id = chat.id

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await clear_user_state(session, target_chat_id, user.id)
        await session.commit()

    keyboard = solitaire_menu_keyboard(target_chat_id if chat.type == "private" else None)
    await q.edit_message_text("已取消创建", reply_markup=keyboard)
    return ConversationHandler.END


async def join_solitaire_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """用户参与接龙回调"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return

    q = update.callback_query
    await q.answer()

    data = q.data or ""
    if not data.startswith("join_solitaire:"):
        return

    try:
        solitaire_id = int(data.split(":")[1])
    except (ValueError, IndexError):
        await q.answer("无效的接龙")
        return

    user_id = update.effective_user.id

    # 生成@用户的文本（使用 HTML 格式）
    user_mention = update.effective_user.username or f"<a href=\"tg://user?id={user_id}\">@{update.effective_user.first_name or '用户'}</a>"

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        solitaire = await get_solitaire(session, solitaire_id)
        if not solitaire:
            await q.answer()
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"❌ 接龙不存在",
                parse_mode='HTML'
            )
            return

        # 检查是否已关闭
        if solitaire.status != SolitaireStatus.active.value:
            await q.answer()
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"❌ 接龙已关闭",
                parse_mode='HTML'
            )
            return

        # 检查人数限制
        if solitaire.max_participants and len(solitaire.entries_rel) >= solitaire.max_participants:
            await q.answer()
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"❌ 接龙已满员",
                parse_mode='HTML'
            )
            return

        # 检查积分限制
        if solitaire.points_required and solitaire.points_required > 0:
            from bot.services.activity.points_service import get_balance
            points = await get_balance(session, solitaire.chat_id, user_id)
            log.info("checking_points", solitaire_id=solitaire_id, required=solitaire.points_required, user_points=points)
            if points < solitaire.points_required:
                # 先 answer 防止按钮加载
                await q.answer()
                # 在群组中发送可见的消息提示，@用户
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"{user_mention} ❌ 积分不足\n参与接龙需要 {solitaire.points_required} 积分，你当前有 {points} 积分",
                    parse_mode='HTML'
                )
                return

        # 检查是否已参与（查询数据库）
        from bot.models.core import SolitaireEntry
        from sqlalchemy import select
        existing_stmt = select(SolitaireEntry).where(
            SolitaireEntry.solitaire_id == solitaire_id,
            SolitaireEntry.user_id == user_id
        )
        existing_result = await session.execute(existing_stmt)
        if existing_result.scalar_one_or_none():
            await q.answer()
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"{user_mention} ❌ 你已经参与过这个接龙",
                parse_mode='HTML'
            )
            return

        # 参与接龙（使用默认内容）
        # 优先使用 username，如果没有则使用 first_name
        username = update.effective_user.username or update.effective_user.first_name or f"用户{user_id}"
        result = await join_solitaire(
            session,
            solitaire_id=solitaire_id,
            user_id=user_id,
            username=username,
            content="✅ 已参与",
        )

        await session.commit()

        if result.success:
            # commit 后使用新 session 查询，避免 session 过期问题
            async with db.session_factory() as new_session:
                from bot.models.core import Solitaire
                from sqlalchemy import select
                from sqlalchemy.orm import selectinload

                stmt = select(Solitaire).options(
                    selectinload(Solitaire.entries_rel)
                ).where(Solitaire.id == solitaire_id)
                query_result = await new_session.execute(stmt)
                solitaire = query_result.scalar_one_or_none()

                if solitaire is None:
                    await q.answer("❌ 接龙不存在")
                    return
                if solitaire:
                    # 刷新接龙消息
                    text_msg = format_solitaire_message(solitaire)

                    # 更新群组中的原始接龙消息
                    if solitaire.message_id:
                        from bot.keyboards.solitaire import get_join_solitaire_keyboard
                        try:
                            await context.bot.edit_message_text(
                                chat_id=solitaire.chat_id,
                                message_id=solitaire.message_id,
                                text=text_msg,
                                reply_markup=get_join_solitaire_keyboard(solitaire_id)
                            )
                        except Exception as e:
                            if "Message is not modified" not in str(e):
                                log.error("solitaire_group_message_update_failed", error=str(e))

            await q.answer("参与成功！")
        else:
            # 服务层返回错误，发送提示消息
            await q.answer()
            reason_map = {
                "full": "❌ 接龙已满员",
                "closed": "❌ 接龙已关闭",
                "expired": "❌ 接龙已过期",
                "insufficient_points": "❌ 积分不足",
                "already_joined": "❌ 你已经参与过这个接龙",
            }
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"{user_mention} {reason_map.get(result.reason, '❌ 参与失败')}",
                parse_mode='HTML'
            )


async def edit_solitaire_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """用户修改接龙报名回调"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return

    q = update.callback_query
    await q.answer()

    data = q.data or ""
    if not data.startswith("edit_solitaire:"):
        return

    try:
        solitaire_id = int(data.split(":")[1])
    except (ValueError, IndexError):
        await q.answer("无效的接龙")
        return

    user_id = update.effective_user.id

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        solitaire = await get_solitaire(session, solitaire_id)
        if not solitaire:
            await q.answer("接龙不存在", show_alert=True)
            return

        # 检查是否已参与（查询数据库）
        from bot.models.core import SolitaireEntry
        from sqlalchemy import select
        existing_stmt = select(SolitaireEntry).where(
            SolitaireEntry.solitaire_id == solitaire_id,
            SolitaireEntry.user_id == user_id
        )
        existing_result = await session.execute(existing_stmt)
        existing_entry = existing_result.scalar_one_or_none()

        if not existing_entry:
            await q.answer("你还没有参与这个接龙", show_alert=True)
            return

        # 删除原报名
        await leave_solitaire(
            session,
            solitaire_id,
            user_id,
        )

        await session.commit()

    # 重新参与（这里可以提示用户输入新的报名信息）
    await q.answer("原报名已删除，请点击「参与接龙」重新报名", show_alert=True)


async def solitaire_refresh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """刷新接龙详情"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat

    data = q.data or ""
    cb = CallbackParser.parse(data)
    if cb.length() < 3:
        return

    solitaire_id = cb.get_int(2)
    if solitaire_id == 0:
        return

    # 使用 PrivateChatContext 解析目标群组并检查权限
    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(
        update, context, chat_index=3
    )
    if target_chat_id is None:
        return  # 错误消息已发送

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        solitaire = await get_solitaire(session, solitaire_id)
        if not solitaire:
            await session.commit()
            await q.edit_message_text("接龙不存在", reply_markup=solitaire_menu_keyboard(target_chat_id if chat.type == "private" else None))
            return

        # 检查截止时间，如果过期则自动结束接龙
        if solitaire.deadline and solitaire.status == SolitaireStatus.active.value:
            now = dt.datetime.now(dt.timezone.utc)
            if now > solitaire.deadline:
                close_result = await close_solitaire(session, solitaire_id)
                if close_result.success:
                    solitaire = close_result.solitaire
                    # 在群组中发送过期通知
                    try:
                        await context.bot.send_message(
                            chat_id=solitaire.chat_id,
                            text=f"⏰ 接龙已截止\n\n{solitaire.title}\n参与人数: {len(solitaire.entries_rel)} 人"
                        )
                    except Exception as e:
                        log.error("solitaire_expired_notification_failed", error=str(e))

        text = format_solitaire_message(solitaire, show_closed=False)
        is_active = solitaire.status == SolitaireStatus.active.value
        await session.commit()

    # 添加异常处理，避免 "Message is not modified" 错误
    from telegram.error import BadRequest
    try:
        await q.edit_message_text(text, reply_markup=solitaire_detail_keyboard(solitaire_id, is_active, target_chat_id if chat.type == "private" else None))
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            log.error("solitaire_refresh_failed", error=str(e))


async def solitaire_close_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """结束接龙"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    data = q.data or ""
    cb = CallbackParser.parse(data)

    # 使用 PrivateChatContext 解析目标群组并检查权限
    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(
        update, context, chat_index=3
    )
    if target_chat_id is None:
        return  # 错误消息已发送

    if cb.length() < 3:
        return

    solitaire_id = cb.get_int(2)
    if solitaire_id == 0:
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        result = await close_solitaire(session, solitaire_id)

        if result.success:
            entries_count = len(result.solitaire.entries_rel)

            await session.commit()

            # 1. 在群组中发送结束通知
            try:
                await context.bot.send_message(
                    chat_id=result.solitaire.chat_id,
                    text=f"🔴 接龙已结束\n\n{result.solitaire.title}\n参与人数: {entries_count} 人"
                )
            except Exception as e:
                log.error("solitaire_group_notification_failed", error=str(e))

            # 2. 更新群组中的原始接龙消息，移除参与按钮
            if result.solitaire.message_id:
                try:
                    group_text = format_solitaire_message(result.solitaire, show_closed=False)
                    await context.bot.edit_message_text(
                        chat_id=result.solitaire.chat_id,
                        message_id=result.solitaire.message_id,
                        text=group_text
                    )
                except Exception as e:
                    log.error("solitaire_update_group_message_failed", error=str(e))

            # 3. 通知管理员：接龙已结束（显示完整的参与人员名单）
            try:
                admin_text = format_solitaire_message(result.solitaire, show_closed=False)
                await context.bot.send_message(
                    chat_id=user.id,
                    text=admin_text
                )
            except Exception as e:
                log.error("solitaire_close_notification_failed", error=str(e))

            text = format_solitaire_message(result.solitaire, show_closed=False)
            await q.edit_message_text(text, reply_markup=solitaire_detail_keyboard(solitaire_id, False, target_chat_id if chat.type == "private" else None))
        else:
            reason_text = {
                "not_found": "接龙不存在",
                "already_closed": "接龙已结束",
                "error": "结束失败",
            }.get(result.reason, "未知错误")
            keyboard = solitaire_menu_keyboard(target_chat_id if chat.type == "private" else None)
            await q.edit_message_text(f"❌ {reason_text}", reply_markup=keyboard)


async def solitaire_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """删除接龙"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat

    data = q.data or ""
    cb = CallbackParser.parse(data)

    # 使用 PrivateChatContext 解析目标群组并检查权限
    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(
        update, context, chat_index=3
    )
    if target_chat_id is None:
        return  # 错误消息已发送

    if cb.length() < 3:
        return

    solitaire_id = cb.get_int(2)
    if solitaire_id == 0:
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        success = await delete_solitaire(session, solitaire_id)
        await session.commit()

        keyboard = solitaire_menu_keyboard(target_chat_id if chat.type == "private" else None)
        if success:
            await q.edit_message_text("✅ 接龙已删除", reply_markup=keyboard)
        else:
            await q.edit_message_text("❌ 接龙不存在", reply_markup=keyboard)


async def solitaire_join_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理接龙参与消息（回复接龙消息）"""
    if update.effective_message is None or update.effective_chat is None or update.effective_user is None:
        return

    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    # 检查是否回复消息
    if not message.reply_to_message:
        return

    # 查找对应的接龙
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        solitaires = await get_chat_solitaires(session, chat.id, active_only=True)

        target_solitaire = None
        for solitaire in solitaires:
            if solitaire.message_id == message.reply_to_message.message_id:
                target_solitaire = solitaire
                break

        if not target_solitaire:
            return  # 不是接龙消息

        # 检查是否已参与（查询数据库）
        from bot.models.core import SolitaireEntry
        from sqlalchemy import select
        existing_stmt = select(SolitaireEntry).where(
            SolitaireEntry.solitaire_id == target_solitaire.id,
            SolitaireEntry.user_id == user.id
        )
        existing_result = await session.execute(existing_stmt)
        if existing_result.scalar_one_or_none():
            # 已参与，更新内容
            result = await update_entry(session, target_solitaire.id, user.id, message.text)

            if result.success:
                await session.commit()

                # 重新查询以获取最新的参与列表
                solitaire = await get_solitaire(session, target_solitaire.id)
                if solitaire:
                    text = format_solitaire_message(solitaire)
                    await message.reply_to_message.edit_text(text)
                await message.reply_text("✅ 已更新你的接龙内容")
            else:
                await session.commit()
                await message.reply_text("❌ 更新失败")
            return

        # 新参与
        content = message.text
        # 构造显示名称：优先 username，否则 first_name + last_name，最后使用 user_id
        if user.username:
            display_name = user.username
        elif user.first_name:
            display_name = user.first_name
            if user.last_name:
                display_name += f" {user.last_name}"
        else:
            display_name = f"用户{user.id}"

        result = await join_solitaire(session, target_solitaire.id, user.id, display_name, content)

        if result.success:
            await session.commit()

            # commit 后使用新 session 查询，避免 session 过期问题
            async with db.session_factory() as new_session:
                from bot.models.core import Solitaire
                from sqlalchemy import select
                from sqlalchemy.orm import selectinload

                stmt = select(Solitaire).options(
                    selectinload(Solitaire.entries_rel)
                ).where(Solitaire.id == target_solitaire.id)
                query_result = await new_session.execute(stmt)
                solitaire = query_result.scalar_one_or_none()

                if solitaire is None:
                    await message.reply_text("❌ 接龙不存在")
                    return
                if solitaire:
                    text = format_solitaire_message(solitaire)
                    await message.reply_to_message.edit_text(text)
            await message.reply_text("✅ 接龙成功！")
        else:
            await session.commit()
            reason_text = {
                "not_found": "接龙不存在",
                "already_closed": "接龙已结束",
                "already_joined": "你已经参与了，请回复更新内容",
                "full": "接龙人数已满",
                "expired": "接龙已截止",
                "insufficient_points": "积分不足，无法参与",
                "error": "参与失败",
            }.get(result.reason, "未知错误")
            await message.reply_text(f"❌ {reason_text}")


# ============================================
# 后台任务
# ============================================
# 已迁移到 bot/tasks/solitaire_task.py
