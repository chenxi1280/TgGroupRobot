from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.features.automation.services.scheduled_message_service import ScheduledMessageService
from backend.features.automation.ui.scheduled_message import sm_detail_keyboard, sm_list_keyboard
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.scheduled_message import ScheduledMessageTask
from backend.platform.telegram.errors import build_public_error_text
from backend.shared.time_helper import format_timestamp, get_interval_description


class ScheduledMessageListMixin:
    async def show_list(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        page: int = 0,
    ) -> None:
        if not await self._check_permission(update, context, target_chat_id):
            await self.message_helper.safe_edit(update, text="❌ 需要管理员权限")
            return

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            tasks = await ScheduledMessageService.list_tasks(session, target_chat_id)
            await session.commit()

        total_count = len(tasks)
        page_size = 10
        total_pages = max(1, (total_count + page_size - 1) // page_size)
        current_page = min(max(page, 0), total_pages - 1)

        if not tasks:
            keyboard = sm_list_keyboard([], target_chat_id, current_page, page_size=page_size)
            edited = await self.message_helper.safe_edit(
                update,
                text="⏰ 定时消息\n\n0 条数据，第 1 页/共 1 页\n\n暂无任务，点击「添加一条」开始。",
                reply_markup=keyboard,
            )
            if not edited:
                await self.message_helper.safe_reply(
                    update,
                    text="⏰ 定时消息\n\n0 条数据，第 1 页/共 1 页\n\n暂无任务，点击「添加一条」开始。",
                    reply_markup=keyboard,
                )
            return

        text = self._format_task_list(tasks, current_page, page_size)
        keyboard = sm_list_keyboard(tasks, target_chat_id, current_page, page_size=page_size)
        edited = await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)
        if not edited:
            await self.message_helper.safe_reply(update, text=text, reply_markup=keyboard)

    def _format_task_list(
        self,
        tasks: list[ScheduledMessageTask],
        page: int,
        page_size: int,
    ) -> str:
        total_count = len(tasks)
        total_pages = max(1, (total_count + page_size - 1) // page_size)
        current_page = min(max(page, 0), total_pages - 1)
        start_idx = current_page * page_size
        end_idx = start_idx + page_size
        page_tasks = tasks[start_idx:end_idx]

        lines = [
            "⏰ 定时消息",
            "",
            f"{total_count} 条数据，第 {current_page + 1} 页/共 {total_pages} 页",
        ]

        for task in page_tasks:
            status = "启用" if task.enabled else "关闭"
            interval_desc = get_interval_description(task.repeat_interval_min)
            next_run = format_timestamp(task.next_run_at) if task.next_run_at else "(未设置)"
            end_at = format_timestamp(task.end_at) if task.end_at else "无限制"
            lines.extend(
                [
                    "",
                    f"#{task.short_id} {task.title}",
                    f"状态: {status} | 重复: {interval_desc}",
                    f"终止: {end_at}",
                    f"下次: {next_run}",
                ]
            )

        return "\n".join(lines)

    async def show_detail(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        task_id: str,
        toast: str | None = None,
    ) -> None:
        if not await self._check_permission(update, context, target_chat_id):
            await self.message_helper.safe_edit(update, text="❌ 需要管理员权限")
            return

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            try:
                task = await ScheduledMessageService.get_task_in_chat_or_404(
                    session,
                    target_chat_id,
                    task_id,
                )
            except Exception as exc:
                await session.rollback()
                await self.message_helper.safe_edit(
                    update,
                    text=f"❌ {build_public_error_text(exc, fallback='任务不可用')}",
                )
                return
            await session.commit()

        text = self._format_task_detail(task, toast=toast)
        keyboard = sm_detail_keyboard(task, target_chat_id)
        edited = await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)
        if not edited:
            await self.message_helper.safe_reply(update, text=text, reply_markup=keyboard)

    def _format_task_detail(self, task: ScheduledMessageTask, toast: str | None = None) -> str:
        lines = []
        if toast:
            lines.append(toast)
            lines.append("")

        lines.append(f"⚙️ {task.title}")
        lines.append("")

        status_icon = "🟢" if task.enabled else "🔴"
        lines.append(f"{status_icon} 状态: {'启用' if task.enabled else '关闭'}")

        interval_desc = get_interval_description(task.repeat_interval_min)
        lines.append(f"⏰ 重复: {interval_desc}")

        if task.day_start_hour == 0 and task.day_end_hour == 23:
            lines.append("🕐 时段: 全天")
        else:
            lines.append(f"🕐 时段: {task.day_start_hour:02d}:00-{task.day_end_hour:02d}:00")

        if task.start_at and task.end_at:
            lines.append(f"📅 有效期: {format_timestamp(task.start_at)} ~ {format_timestamp(task.end_at)}")
        elif task.start_at:
            lines.append(f"📅 开始: {format_timestamp(task.start_at)}")
        elif task.end_at:
            lines.append(f"📅 终止: {format_timestamp(task.end_at)}")

        if task.next_run_at:
            lines.append(f"⏭️ 下次: {format_timestamp(task.next_run_at)}")

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

        lines.append("")
        lines.append("⚙️ 选项:")
        options = []
        if task.delete_previous:
            options.append("删除上条")
        if task.pin_message:
            options.append("置顶")
        lines.append(" | ".join(options) if options else "无")
        return "\n".join(lines)
