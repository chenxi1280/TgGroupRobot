"""定时消息任务 Handler

提供定时消息任务的交互处理。
"""
from __future__ import annotations

import structlog
import json
import traceback
import uuid
from telegram import Update
from telegram.ext import ContextTypes

from bot.db.session import Database
from bot.handlers.base.base_handler import BaseHandler
from bot.handlers.base.chat_resolver import ChatResolver
from bot.services.scheduled_message_service import ScheduledMessageService
from bot.services.state.state_service import (
    clear_user_state,
    set_user_state,
    get_user_state,
)
from bot.services.core.permission_service import is_user_admin
from bot.models.enums import ConversationStateType
from bot.models.scheduled_message import ScheduledMessageTask
from bot.utils.callback_parser import CallbackParser
from bot.keyboards.integration.scheduled_message import (
    sm_list_keyboard,
    sm_detail_keyboard,
    sm_repeat_keyboard,
    sm_day_period_start_keyboard,
    sm_day_period_end_keyboard,
    sm_confirm_delete_keyboard,
    sm_edit_text_keyboard,
    sm_edit_media_keyboard,
    sm_edit_buttons_keyboard,
)
from bot.utils.time_helper import format_timestamp

log = structlog.get_logger(__name__)


class ScheduledMessageHandler(BaseHandler):
    """定时消息任务 Handler"""

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
        """处理定时消息回调（用于 BaseHandler 抽象方法）"""
        # ScheduledMessageHandler 不使用 process 方法，直接调用各个方法
        pass

    async def _check_permission(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> bool:
        """检查管理员权限

        Args:
            update: Telegram 更新对象
            context: 上下文对象
            chat_id: 群组 ID

        Returns:
            是否有权限
        """
        if update.effective_user is None:
            return False

        return await is_user_admin(context, chat_id, update.effective_user.id)

    async def show_list(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        page: int = 0,
    ) -> None:
        """显示任务列表"""
        # 检查权限
        if not await self._check_permission(update, context, target_chat_id):
            await self.message_helper.safe_edit(
                update,
                text="❌ 需要管理员权限",
            )
            return

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            tasks = await ScheduledMessageService.list_tasks(session, target_chat_id)
            await session.commit()

        if not tasks:
            keyboard = sm_list_keyboard([], target_chat_id, page)
            await self.message_helper.safe_edit(
                update,
                text="📋 定时消息列表\n\n暂无任务，点击「添加任务」开始",
                reply_markup=keyboard,
            )
            return

        text = f"📋 定时消息列表\n\n共 {len(tasks)} 个任务"
        keyboard = sm_list_keyboard(tasks, target_chat_id, page)
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def show_detail(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        task_id: str,
        toast: str | None = None,
    ) -> None:
        """显示任务详情

        Args:
            update: Telegram 更新对象
            context: 上下文对象
            target_chat_id: 群组 ID
            task_id: 任务 ID
            toast: 可选的提示信息（显示在详情页顶部）
        """
        # 检查权限
        if not await self._check_permission(update, context, target_chat_id):
            await self.message_helper.safe_edit(
                update,
                text="❌ 需要管理员权限",
            )
            return

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            try:
                task = await ScheduledMessageService.get_task_by_id_or_404(session, task_id)
            except Exception as e:
                await session.rollback()
                await self.message_helper.safe_edit(
                    update,
                    text=f"❌ {str(e)}",
                )
                return
            await session.commit()

        # 显示任务详情
        text = self._format_task_detail(task, toast=toast)
        keyboard = sm_detail_keyboard(task, target_chat_id)
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    def _format_task_detail(self, task: ScheduledMessageTask, toast: str | None = None) -> str:
        """格式化任务详情

        Args:
            task: 任务对象
            toast: 可选的提示信息（显示在顶部）

        Returns:
            格式化后的详情文本
        """
        lines = []

        # 如果有 toast 提示，显示在第一行
        if toast:
            lines.append(toast)
            lines.append("")

        lines.append(f"⚙️ {task.title}")
        lines.append("")

        # 状态
        status_icon = "🟢" if task.enabled else "🔴"
        lines.append(f"{status_icon} 状态: {'启用' if task.enabled else '关闭'}")

        # 重复间隔
        from bot.utils.time_helper import get_interval_description
        interval_desc = get_interval_description(task.repeat_interval_min)
        lines.append(f"⏰ 重复: {interval_desc}")

        # 时段
        if task.day_start_hour == 0 and task.day_end_hour == 23:
            lines.append("🕐 时段: 全天")
        else:
            lines.append(f"🕐 时段: {task.day_start_hour:02d}:00-{task.day_end_hour:02d}:00")

        # 日期范围
        if task.start_at and task.end_at:
            lines.append(f"📅 有效期: {format_timestamp(task.start_at)} ~ {format_timestamp(task.end_at)}")
        elif task.start_at:
            lines.append(f"📅 开始: {format_timestamp(task.start_at)}")
        elif task.end_at:
            lines.append(f"📅 终止: {format_timestamp(task.end_at)}")

        # 下次运行时间
        if task.next_run_at:
            lines.append(f"⏭️ 下次: {format_timestamp(task.next_run_at)}")

        # 内容
        lines.append("")
        lines.append("📝 内容:")

        if task.text:
            text_preview = task.text[:200] + "..." if len(task.text) > 200 else task.text
            lines.append(text_preview)
        else:
            lines.append("(无文本)")

        if task.media_type != "none":
            lines.append(f"🎬 媒体: {task.media_type}")

        if task.buttons:
            lines.append(f"🔗 按钮: {len(task.buttons)} 行")

        # 选项
        lines.append("")
        lines.append("⚙️ 选项:")

        options = []
        if task.delete_previous:
            options.append("删除上条")
        if task.pin_message:
            options.append("置顶")

        if options:
            lines.append(" | ".join(options))
        else:
            lines.append("无")

        return "\n".join(lines)

    async def create_task(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
    ) -> None:
        """创建新任务"""
        # 检查权限
        if not await self._check_permission(update, context, target_chat_id):
            await self.message_helper.safe_edit(
                update,
                text="❌ 需要管理员权限",
            )
            return

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            try:
                task = await ScheduledMessageService.create_task(
                    session,
                    chat_id=target_chat_id,
                    created_by_user_id=update.effective_user.id if update.effective_user else 0,
                    title="新定时消息",
                    enabled=False,  # 默认禁用，等待用户配置
                )
            except Exception as e:
                await session.rollback()
                await self.message_helper.safe_edit(
                    update,
                    text=f"❌ 创建失败: {str(e)}",
                )
                return
            await session.commit()

        # 跳转到详情页
        await self.show_detail(update, context, target_chat_id, str(task.task_id))

    async def set_field(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        task_id: str,
        field: str,
        value: str,
    ) -> None:
        """设置任务字段

        Args:
            update: Telegram 更新对象
            context: 上下文对象
            target_chat_id: 群组 ID
            task_id: 任务 ID
            field: 字段名
            value: 字段值
        """
        # 检查权限
        if not await self._check_permission(update, context, target_chat_id):
            await self.message_helper.safe_edit(
                update,
                text="❌ 需要管理员权限",
            )
            return

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            try:
                # 处理不同类型的字段
                if field == "enabled":
                    value_bool = value == "1"
                    task = await ScheduledMessageService.toggle_task_enabled(session, task_id, value_bool)
                elif field == "delete_previous":
                    value_bool = value == "1"
                    task = await ScheduledMessageService.update_task_toggle_option(
                        session, task_id, "delete_previous", value_bool
                    )
                elif field == "pin_message":
                    value_bool = value == "1"
                    task = await ScheduledMessageService.update_task_toggle_option(
                        session, task_id, "pin_message", value_bool
                    )
                elif field == "repeat":
                    value_int = int(value)
                    task = await ScheduledMessageService.update_task_repeat(session, task_id, value_int)
                elif field == "day_start":
                    value_int = int(value)
                    # 保存开始时间到状态，然后让用户选择结束时间
                    # 在私聊场景下，状态保存到私聊ID，目标群组ID保存到 state_data 中
                    state_chat_id = update.effective_chat.id if update.effective_chat else target_chat_id
                    await set_user_state(
                        session,
                        state_chat_id,
                        update.effective_user.id if update.effective_user else 0,
                        ConversationStateType.sm_edit_day_start,
                        {"task_id": task_id, "start_hour": value_int, "target_chat_id": target_chat_id},
                    )
                    await session.commit()

                    # 显示结束时间选择键盘
                    keyboard = sm_day_period_end_keyboard(target_chat_id, task_id, value_int)
                    await self.message_helper.safe_edit(
                        update,
                        text="请选择时段结束时间",
                        reply_markup=keyboard,
                    )
                    return
                elif field == "day_end":
                    value_int = int(value)
                    # 从状态中获取开始时间
                    # 在私聊场景下，使用私聊ID查询状态
                    state_chat_id = update.effective_chat.id if update.effective_chat else target_chat_id
                    state = await get_user_state(
                        session,
                        state_chat_id,
                        update.effective_user.id if update.effective_user else 0,
                    )
                    if not state or "start_hour" not in state.state_data:
                        await session.rollback()
                        await self.message_helper.safe_edit(
                            update,
                            text="❌ 状态错误，请重新开始",
                        )
                        return

                    start_hour = state.state_data["start_hour"]
                    task = await ScheduledMessageService.update_task_day_period(
                        session, task_id, start_hour, value_int
                    )

                    # 清除状态
                    await clear_user_state(
                        session,
                        state_chat_id,
                        update.effective_user.id if update.effective_user else 0,
                    )
                else:
                    await session.rollback()
                    await self.message_helper.safe_edit(
                        update,
                        text=f"❌ 未知字段: {field}",
                    )
                    return

            except Exception as e:
                await session.rollback()
                log.error(
                    "设置任务字段失败",
                    task_id=task_id,
                    field=field,
                    error=str(e),
                    traceback=traceback.format_exc(),
                )
                await self.message_helper.safe_edit(
                    update,
                    text=f"❌ 设置失败: {str(e)}",
                )
                # 确保清理可能设置的 FSM 状态
                state_chat_id = update.effective_chat.id if update.effective_chat else target_chat_id
                async with db.session_factory() as cleanup_session:
                    await clear_user_state(
                        cleanup_session,
                        state_chat_id,
                        update.effective_user.id if update.effective_user else 0,
                    )
                    await cleanup_session.commit()
                return

            await session.commit()

        # 返回详情页
        await self.show_detail(update, context, target_chat_id, task_id)

    async def edit_field(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        task_id: str,
        field: str,
    ) -> None:
        """编辑任务字段（进入 FSM 状态）

        Args:
            update: Telegram 更新对象
            context: 上下文对象
            target_chat_id: 群组 ID
            task_id: 任务 ID
            field: 字段名
        """
        # 检查权限
        if not await self._check_permission(update, context, target_chat_id):
            await self.message_helper.safe_edit(
                update,
                text="❌ 需要管理员权限",
            )
            return

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            try:
                task = await ScheduledMessageService.get_task_by_id_or_404(session, task_id)
            except Exception as e:
                await session.rollback()
                await self.message_helper.safe_edit(
                    update,
                    text=f"❌ {str(e)}",
                )
                return

            # 根据字段类型设置 FSM 状态和提示文本
            if field == "text":
                state_type = ConversationStateType.sm_edit_text
                text = "✏️ 编辑文本\n\n请输入新的文本内容，或输入 /clear 清空文本"
                keyboard = sm_edit_text_keyboard(target_chat_id, task_id)
            elif field == "media":
                state_type = ConversationStateType.sm_edit_media
                text = "🎬 编辑媒体\n\n请发送图片/视频/文档/贴纸/动画"
                keyboard = sm_edit_media_keyboard(target_chat_id, task_id)
            elif field == "buttons":
                state_type = ConversationStateType.sm_edit_buttons
                text = "🔗 编辑按钮\n\n请输入按钮配置（JSON 格式）\n\n格式示例:\n[\n  [{\"text\":\"按钮1\",\"url\":\"https://...\"}],\n  [{\"text\":\"按钮2\",\"url\":\"https://...\"}]\n]\n\n或输入 /clear 清空按钮"
                keyboard = sm_edit_buttons_keyboard(target_chat_id, task_id)
            elif field == "repeat":
                # 重复间隔不需要 FSM，直接显示选择键盘
                await session.commit()
                keyboard = sm_repeat_keyboard(target_chat_id, task_id)
                await self.message_helper.safe_edit(
                    update,
                    text="⏰ 选择重复间隔",
                    reply_markup=keyboard,
                )
                return
            elif field == "day_period":
                # 时段需要两步选择
                state_type = ConversationStateType.sm_edit_day_start
                text = "🕐 选择时段开始时间"
                keyboard = sm_day_period_start_keyboard(target_chat_id, task_id)
            elif field == "start_at":
                state_type = ConversationStateType.sm_edit_start_at
                text = "📅 设置开始时间\n\n请输入日期时间（格式：YYYY-MM-DD HH:MM）\n例如：2024-01-01 08:00\n\n或输入 /clear 清空开始时间"
                keyboard = sm_edit_text_keyboard(target_chat_id, task_id)
            elif field == "end_at":
                state_type = ConversationStateType.sm_edit_end_at
                text = "📅 设置终止时间\n\n请输入日期时间（格式：YYYY-MM-DD HH:MM）\n例如：2024-12-31 23:59\n\n或输入 /clear 清空终止时间"
                keyboard = sm_edit_text_keyboard(target_chat_id, task_id)
            else:
                await session.rollback()
                await self.message_helper.safe_edit(
                    update,
                    text=f"❌ 未知字段: {field}",
                )
                return

            # 设置 FSM 状态
            # 在私聊场景下，状态保存到私聊ID，目标群组ID保存到 state_data 中
            state_chat_id = update.effective_chat.id if update.effective_chat else target_chat_id
            await set_user_state(
                session,
                state_chat_id,
                update.effective_user.id if update.effective_user else 0,
                state_type,
                {"task_id": task_id, "target_chat_id": target_chat_id},
            )
            await session.commit()

        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def confirm_delete(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        task_id: str,
    ) -> None:
        """确认删除任务"""
        # 检查权限
        if not await self._check_permission(update, context, target_chat_id):
            await self.message_helper.safe_edit(
                update,
                text="❌ 需要管理员权限",
            )
            return

        keyboard = sm_confirm_delete_keyboard(target_chat_id, task_id)
        await self.message_helper.safe_edit(
            update,
            text=f"⚠️ 确认删除任务？\n\n此操作不可撤销",
            reply_markup=keyboard,
        )

    async def delete_task(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        task_id: str,
    ) -> None:
        """执行删除任务"""
        # 检查权限
        if not await self._check_permission(update, context, target_chat_id):
            await self.message_helper.safe_edit(
                update,
                text="❌ 需要管理员权限",
            )
            return

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            try:
                await ScheduledMessageService.delete_task(session, task_id)
            except Exception as e:
                await session.rollback()
                await self.message_helper.safe_edit(
                    update,
                    text=f"❌ 删除失败: {str(e)}",
                )
                return
            await session.commit()

        await self.show_list(update, context, target_chat_id)

    async def cancel_delete(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        task_id: str,
    ) -> None:
        """取消删除任务"""
        await self.show_detail(update, context, target_chat_id, task_id)

    async def cancel_operation(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        task_id: str | None = None,
    ) -> None:
        """取消当前操作，清理 FSM 状态

        Args:
            update: Telegram 更新对象
            context: 上下文对象
            target_chat_id: 目标群组 ID
            task_id: 任务 ID（可选）
        """
        # 清理 FSM 状态
        if update.effective_user:
            db: Database = context.application.bot_data["db"]
            async with db.session_factory() as session:
                # 使用私聊ID清理状态
                state_chat_id = update.effective_chat.id if update.effective_chat else target_chat_id
                await clear_user_state(
                    session,
                    state_chat_id,
                    update.effective_user.id,
                )
                await session.commit()

        # 如果有 task_id，返回详情页；否则返回列表页
        if task_id:
            await self.show_detail(update, context, target_chat_id, task_id)
        else:
            await self.show_list(update, context, target_chat_id)

    async def handle_fsm_input(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        user_id: int,
        text: str,
    ) -> None:
        """处理 FSM 状态下的用户输入

        Args:
            update: Telegram 更新对象
            context: 上下文对象
            target_chat_id: 群组 ID
            user_id: 用户 ID
            text: 用户输入的文本
        """
        # 添加日志：方法被调用
        log.info(
            "=== handle_fsm_input CALLED ===",
            target_chat_id=target_chat_id,
            user_id=user_id,
            text_preview=text[:50],
        )

        db: Database = context.application.bot_data["db"]
        state = None  # 在外层声明，便于后续访问

        async with db.session_factory() as session:
            # 在私聊场景下，使用私聊ID查询状态
            state_chat_id = update.effective_chat.id if update.effective_chat else target_chat_id
            state = await get_user_state(session, state_chat_id, user_id)

            # 添加日志：状态查询结果
            log.info(
                "handle_fsm_input_state_result",
                state_found=state is not None,
                state_type=state.state_type if state else None,
            )

            if not state:
                log.warning("handle_fsm_input_no_state")
                await session.commit()
                return

            task_id = state.state_data.get("task_id")
            if not task_id:
                log.warning("handle_fsm_input_no_task_id")
                await clear_user_state(session, state_chat_id, user_id)
                await session.commit()
                return

            # 添加日志：准备更新数据
            log.info(
                "handle_fsm_input_updating",
                task_id=task_id,
                state_type=state.state_type,
            )

            try:
                # 根据状态类型处理输入（使用字符串比较，因为从数据库读取的是字符串）
                state_type_str = str(state.state_type) if state.state_type else ""

                if state_type_str == "sm_edit_text" or state_type_str == str(ConversationStateType.sm_edit_text):
                    if text.strip() == "/clear":
                        await ScheduledMessageService.update_task_text(session, task_id, None)
                    else:
                        await ScheduledMessageService.update_task_text(session, task_id, text)

                elif state_type_str == "sm_edit_buttons" or state_type_str == str(ConversationStateType.sm_edit_buttons):
                    if text.strip() == "/clear":
                        await ScheduledMessageService.update_task_buttons(session, task_id, [])
                    else:
                        # 解析 JSON
                        try:
                            buttons = json.loads(text)
                            if not isinstance(buttons, list):
                                raise ValueError("按钮必须是数组")
                            await ScheduledMessageService.update_task_buttons(session, task_id, buttons)
                        except Exception as e:
                            await session.rollback()
                            await update.effective_message.reply_text(
                                f"❌ JSON 格式错误: {str(e)}\n\n请重新输入"
                            )
                            return

                elif state_type_str == "sm_edit_start_at" or state_type_str == str(ConversationStateType.sm_edit_start_at):
                    if text.strip() == "/clear":
                        await ScheduledMessageService.update_task_start_at(session, task_id, None)
                    else:
                        result = await ScheduledMessageService.update_task_start_at(session, task_id, text.strip())
                        if not result:
                            await session.rollback()
                            await update.effective_message.reply_text(
                                "❌ 日期时间格式错误，应为: YYYY-MM-DD HH:MM\n\n请重新输入"
                            )
                            return

                elif state_type_str == "sm_edit_end_at" or state_type_str == str(ConversationStateType.sm_edit_end_at):
                    if text.strip() == "/clear":
                        await ScheduledMessageService.update_task_end_at(session, task_id, None)
                    else:
                        result = await ScheduledMessageService.update_task_end_at(session, task_id, text.strip())
                        if not result:
                            await session.rollback()
                            await update.effective_message.reply_text(
                                "❌ 日期时间格式错误，应为: YYYY-MM-DD HH:MM\n\n请重新输入"
                            )
                            return

                else:
                    log.warning("handle_fsm_input_unknown_state", state_type=state_type_str)
                    await session.rollback()
                    await update.effective_message.reply_text("❌ 未知状态")
                    return

                # 清除 FSM 状态（使用私聊ID）
                await clear_user_state(session, state_chat_id, user_id)
                await session.commit()

                # 添加日志：更新成功，即将显示详情页
                log.info("handle_fsm_input_update_success")

            except Exception as e:
                await session.rollback()
                log.error(
                    "handle_fsm_input_exception",
                    error=str(e),
                    traceback=traceback.format_exc(),
                )
                await update.effective_message.reply_text(f"❌ 操作失败: {str(e)}")
                return

        # 根据操作类型确定 toast 提示
        toast_msg = None
        if state:
            state_type_str = str(state.state_type) if state.state_type else ""
            if state_type_str == "sm_edit_text" or state_type_str == str(ConversationStateType.sm_edit_text):
                toast_msg = "✅ 文本已保存"
            elif state_type_str == "sm_edit_buttons" or state_type_str == str(ConversationStateType.sm_edit_buttons):
                toast_msg = "✅ 按钮已保存"
            elif state_type_str == "sm_edit_start_at" or state_type_str == str(ConversationStateType.sm_edit_start_at):
                toast_msg = "✅ 开始时间已保存"
            elif state_type_str == "sm_edit_end_at" or state_type_str == str(ConversationStateType.sm_edit_end_at):
                toast_msg = "✅ 终止时间已保存"

        # 添加日志：即将调用 show_detail
        log.info(
            "handle_fsm_input_showing_detail",
            task_id=task_id,
            toast_msg=toast_msg,
        )

        # 返回任务详情
        await self.show_detail(update, context, target_chat_id, task_id, toast=toast_msg)

        # 添加日志：handle_fsm_input 完成
        log.info("handle_fsm_input_completed")

    async def handle_media_input(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        user_id: int,
    ) -> None:
        """处理媒体输入（照片、视频等）

        Args:
            update: Telegram 更新对象
            context: 上下文对象
            target_chat_id: 群组 ID
            user_id: 用户 ID
        """
        if update.effective_message is None:
            return

        # 确定媒体类型和文件 ID
        media_type = "none"
        file_id = None

        if update.effective_message.photo:
            media_type = "photo"
            file_id = update.effective_message.photo[-1].file_id
        elif update.effective_message.video:
            media_type = "video"
            file_id = update.effective_message.video.file_id
        elif update.effective_message.document:
            media_type = "document"
            file_id = update.effective_message.document.file_id
        elif update.effective_message.sticker:
            media_type = "sticker"
            file_id = update.effective_message.sticker.file_id
        elif update.effective_message.animation:
            media_type = "animation"
            file_id = update.effective_message.animation.file_id
        else:
            await update.effective_message.reply_text("❌ 不支持的媒体类型")
            return

        # 获取任务 ID
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            # 在私聊场景下，使用私聊ID查询状态
            state_chat_id = update.effective_chat.id if update.effective_chat else target_chat_id
            state = await get_user_state(session, state_chat_id, user_id)
            if not state or state.state_type != ConversationStateType.sm_edit_media:
                await session.commit()
                return

            task_id = state.state_data.get("task_id")
            if not task_id:
                await clear_user_state(session, state_chat_id, user_id)
                await session.commit()
                return

            # 更新媒体
            try:
                await ScheduledMessageService.update_task_media(session, task_id, media_type, file_id)
                await clear_user_state(session, state_chat_id, user_id)
                await session.commit()
            except Exception as e:
                await session.rollback()
                log.error("更新任务媒体失败", task_id=task_id, error=str(e))
                await update.effective_message.reply_text(f"❌ 操作失败: {str(e)}")
                return

        # 返回任务详情
        await self.show_detail(update, context, target_chat_id, task_id, toast="✅ 媒体已保存")


# 创建单例实例
_scheduled_message_handler = ScheduledMessageHandler()


# ==================== 适配器函数（供 Router 注册）====================

async def sm_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """定时消息回调处理器"""
    if update.callback_query is None or update.effective_message is None:
        return

    try:
        # 使用静态方法解析回调数据
        # 格式: sm:action:chat_id:task_id:...
        parser = CallbackParser.parse(update.callback_query.data)

        # 解析参数
        # parts[0] = "sm"
        # parts[1] = action ("list", "open", "add", "set", "edit", etc.)
        # parts[2] = chat_id
        # parts[3] = task_id 或 page（取决于 action）
        action = parser.get(1)
        target_chat_id = parser.get_int(2)

        # 路由到不同的方法
        if action == "list":
            page = parser.get_int(3, default=0)
            await _scheduled_message_handler.show_list(
                update, context, target_chat_id, page
            )
        elif action == "open":
            task_id = parser.get(3)
            await _scheduled_message_handler.show_detail(
                update, context, target_chat_id, task_id
            )
        elif action == "add":
            await _scheduled_message_handler.create_task(
                update, context, target_chat_id
            )
        elif action == "set":
            task_id = parser.get(3)
            field = parser.get(4)
            value = parser.get(5)
            await _scheduled_message_handler.set_field(
                update, context, target_chat_id, task_id, field, value
            )
        elif action == "edit":
            task_id = parser.get(3)
            field = parser.get(4)
            await _scheduled_message_handler.edit_field(
                update, context, target_chat_id, task_id, field
            )
        elif action == "del_confirm":
            task_id = parser.get(3)
            await _scheduled_message_handler.confirm_delete(
                update, context, target_chat_id, task_id
            )
        elif action == "del_do":
            task_id = parser.get(3)
            await _scheduled_message_handler.delete_task(
                update, context, target_chat_id, task_id
            )
        elif action == "del_cancel":
            task_id = parser.get(3)
            await _scheduled_message_handler.cancel_delete(
                update, context, target_chat_id, task_id
            )
        else:
            await update.callback_query.answer(
                text="❌ 未知的操作",
                show_alert=True,
            )

    except Exception as e:
        log.error("处理定时消息回调失败", error=str(e), callback_data=update.callback_query.data)
        await update.callback_query.answer(
            text=f"❌ 操作失败: {str(e)}",
            show_alert=True,
        )
