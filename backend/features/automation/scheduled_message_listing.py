from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.features.automation.services.scheduled_message_service import ScheduledMessageService
from backend.features.automation.ui.scheduled_message import sm_detail_keyboard, sm_list_keyboard
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.scheduled_message import ScheduledMessageTask
from backend.platform.telegram.errors import build_public_error_text
from backend.shared.time_helper import format_timestamp, get_interval_description
from backend.shared.ui.message_config_panel import (
    WAITING_VALUE,
    PanelField,
    button_status,
    format_completion_lines,
    format_panel,
    media_status,
    summarize_text,
)
_FORMAT_TASK_DETAIL_THRESHOLD_23 = 23


def _task_detail_footer(task: ScheduledMessageTask, *, has_payload: bool) -> list[str]:
    period = (
        "全天"
        if task.day_start_hour == 0 and task.day_end_hour == _FORMAT_TASK_DETAIL_THRESHOLD_23
        else f"{task.day_start_hour:02d}:00-{task.day_end_hour:02d}:00"
    )
    lines = [
        f"⚙️ 状态: {'✅ 启用' if task.enabled else '❌ 关闭'}",
        f"📌 置顶: {'✅ 启用' if task.pin_message else '❌ 关闭'}",
        f"🧹 删除上条: {'✅ 启用' if task.delete_previous else '❌ 关闭'}",
        f"🕐 时段: {period}",
    ]
    if task.next_run_at:
        lines.append(f"⏭️ 下次: {format_timestamp(task.next_run_at)}")
    lines.extend(format_completion_lines(
        [("文本或封面", has_payload)],
        next_step="预览效果 → 启用",
        test_step="到目标群确认定时发送结果",
    ))
    return lines


def _task_detail_fields(task: ScheduledMessageTask, *, title: str, has_media: bool) -> list[PanelField]:
    start_text = format_timestamp(task.start_at) if task.start_at else WAITING_VALUE
    end_text = format_timestamp(task.end_at) if task.end_at else WAITING_VALUE
    return [
        PanelField("📮", "标题备注", title),
        PanelField("🏞️", "封面设置", media_status(has_media=has_media, media_type=task.media_type)),
        PanelField("📄", "文本内容", summarize_text(task.text, limit=180)),
        PanelField("⭕", "设置按钮", button_status(task.buttons)),
        PanelField("⏰", "开始时间", start_text),
        PanelField("⏰", "结束时间", end_text),
        PanelField("⌛", "重复间隔", get_interval_description(task.repeat_interval_min)),
    ]



class ScheduledMessageListMixin:
    async def show_list(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        *, page: int = 0,
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
        *, task_id: str,
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
        title_value = str(task.title or "").strip()
        if not title_value or title_value == "定时消息":
            title_value = WAITING_VALUE
        has_media = task.media_type != "none" and bool(task.media_file_id)
        has_text = bool(str(task.text or "").strip())
        return format_panel(
            "⏱️ 定时消息",
            _task_detail_fields(task, title=title_value, has_media=has_media),
            footer=_task_detail_footer(task, has_payload=has_text or has_media),
            toast=toast,
        )
