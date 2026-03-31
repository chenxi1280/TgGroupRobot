"""定时消息任务键盘

提供定时消息任务管理的键盘生成。
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.keyboards.base.helpers import create_back_button
from bot.keyboards.formatters import StatusIcons
from bot.utils.time_helper import format_timestamp, get_interval_description


def sm_list_keyboard(
    tasks: list,
    chat_id: int,
    page: int = 0,
    page_size: int = 10,
) -> InlineKeyboardMarkup:
    """定时消息任务列表键盘

    Args:
        tasks: 任务列表
        chat_id: 群组 ID
        page: 当前页码
        page_size: 每页数量
    """
    buttons = []
    start_idx = page * page_size
    end_idx = start_idx + page_size

    for task in tasks[start_idx:end_idx]:
        buttons.append([
            InlineKeyboardButton(f"🔢 编号:{task.short_id}", callback_data=f"sm:open:{chat_id}:{task.short_id}"),
            InlineKeyboardButton(
                "❌ 关闭" if task.enabled else "✅ 启用",
                callback_data=f"sm:set:{chat_id}:{task.short_id}:enabled:{0 if task.enabled else 1}",
            ),
            InlineKeyboardButton("✏️ 修改", callback_data=f"sm:open:{chat_id}:{task.short_id}"),
            InlineKeyboardButton("🗑 删除", callback_data=f"sm:del_confirm:{chat_id}:{task.short_id}"),
        ])

    # 分页导航
    nav_buttons = []
    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton("⬅️ 上一页", callback_data=f"sm:list:{chat_id}:{page-1}")
        )
    if end_idx < len(tasks):
        nav_buttons.append(
            InlineKeyboardButton("下一页 ➡️", callback_data=f"sm:list:{chat_id}:{page+1}")
        )

    if nav_buttons:
        buttons.append(nav_buttons)

    # 底部按钮
    buttons.extend([
        [InlineKeyboardButton("➕ 添加一条", callback_data=f"sm:add:{chat_id}")],
        [create_back_button(chat_id, "back_to_menu")],
    ])

    return InlineKeyboardMarkup(buttons)


def sm_detail_keyboard(task, chat_id: int) -> InlineKeyboardMarkup:
    """定时消息任务详情键盘

    Args:
        task: 任务对象
        chat_id: 群组 ID
    """
    # 状态显示
    enabled_icon = "🟢" if task.enabled else "🔴"
    enabled_label = f"{enabled_icon} 状态: {'启用' if task.enabled else '关闭'}"

    # 重复间隔
    interval_desc = get_interval_description(task.repeat_interval_min)

    # 时段
    if task.day_start_hour == 0 and task.day_end_hour == 23:
        period_desc = "全天"
    else:
        period_desc = f"{task.day_start_hour:02d}:00-{task.day_end_hour:02d}:00"

    # 日期范围
    if task.start_at and task.end_at:
        date_range = f"{format_timestamp(task.start_at)} ~ {format_timestamp(task.end_at)}"
    elif task.start_at:
        date_range = f"从 {format_timestamp(task.start_at)} 开始"
    elif task.end_at:
        date_range = f"至 {format_timestamp(task.end_at)} 截止"
    else:
        date_range = "无限制"

    # 内容预览
    content_preview = []
    if task.text:
        text_preview = task.text[:30] + "..." if len(task.text) > 30 else task.text
        content_preview.append(f"📝 {text_preview}")
    if task.media_type != "none":
        content_preview.append(f"🎬 {task.media_type}")
    if task.buttons:
        content_preview.append(f"🔗 {len(task.buttons)} 行按钮")

    # 发送选项
    options = []
    if task.delete_previous:
        options.append("删除上条")
    if task.pin_message:
        options.append("置顶")
    options_desc = " | ".join(options) if options else "无"

    buttons = [
        # 第1行：3个开关
        [
            InlineKeyboardButton(
                f"{'🟢' if task.enabled else '🔴'} 启用",
                callback_data=f"sm:set:{chat_id}:{task.short_id}:enabled:{1 if not task.enabled else 0}"
            ),
            InlineKeyboardButton(
                f"{'✅' if task.delete_previous else '❌'} 删除上条",
                callback_data=f"sm:set:{chat_id}:{task.short_id}:delete_previous:{1 if not task.delete_previous else 0}"
            ),
            InlineKeyboardButton(
                f"{'📌' if task.pin_message else '⬜'} 置顶",
                callback_data=f"sm:set:{chat_id}:{task.short_id}:pin_message:{1 if not task.pin_message else 0}"
            ),
        ],
        # 第2行：文本编辑
        [
            InlineKeyboardButton(
                f"📝 文本: {text_preview if task.text else '(空)'}",
                callback_data=f"sm:edit:{chat_id}:{task.short_id}:text"
            ),
        ],
        # 第3行：媒体编辑
        [
            InlineKeyboardButton(
                f"🎬 媒体: {task.media_type}",
                callback_data=f"sm:edit:{chat_id}:{task.short_id}:media"
            ),
        ],
        # 第4行：按钮编辑
        [
            InlineKeyboardButton(
                f"🔗 按钮: {len(task.buttons)} 行",
                callback_data=f"sm:edit:{chat_id}:{task.short_id}:buttons"
            ),
        ],
        # 第5行：重复间隔
        [
            InlineKeyboardButton(
                f"⏰ 重复: {interval_desc}",
                callback_data=f"sm:edit:{chat_id}:{task.short_id}:repeat"
            ),
        ],
        # 第6行：时段
        [
            InlineKeyboardButton(
                f"🕐 时段: {period_desc}",
                callback_data=f"sm:edit:{chat_id}:{task.short_id}:day_period"
            ),
        ],
        # 第7-8行：日期范围
        [
            InlineKeyboardButton(
                f"📅 开始: {format_timestamp(task.start_at) if task.start_at else '(未设置)'}",
                callback_data=f"sm:edit:{chat_id}:{task.short_id}:start_at"
            ),
        ],
        [
            InlineKeyboardButton(
                f"📅 终止: {format_timestamp(task.end_at) if task.end_at else '(未设置)'}",
                callback_data=f"sm:edit:{chat_id}:{task.short_id}:end_at"
            ),
        ],
        # 最后：删除 + 返回
        [
            InlineKeyboardButton("🗑️ 删除任务", callback_data=f"sm:del_confirm:{chat_id}:{task.short_id}"),
            create_back_button(chat_id, "sm:list"),
        ],
    ]

    return InlineKeyboardMarkup(buttons)


def sm_repeat_keyboard(chat_id: int, task_id: str) -> InlineKeyboardMarkup:
    """重复间隔选择键盘

    Args:
        chat_id: 群组 ID
        task_id: 任务 ID
    """
    buttons = [
        # 按小时
        [
            InlineKeyboardButton("1 小时", callback_data=f"sm:set:{chat_id}:{task_id}:repeat:60"),
            InlineKeyboardButton("2 小时", callback_data=f"sm:set:{chat_id}:{task_id}:repeat:120"),
            InlineKeyboardButton("3 小时", callback_data=f"sm:set:{chat_id}:{task_id}:repeat:180"),
        ],
        [
            InlineKeyboardButton("4 小时", callback_data=f"sm:set:{chat_id}:{task_id}:repeat:240"),
            InlineKeyboardButton("6 小时", callback_data=f"sm:set:{chat_id}:{task_id}:repeat:360"),
            InlineKeyboardButton("8 小时", callback_data=f"sm:set:{chat_id}:{task_id}:repeat:480"),
        ],
        [
            InlineKeyboardButton("12 小时", callback_data=f"sm:set:{chat_id}:{task_id}:repeat:720"),
            InlineKeyboardButton("24 小时", callback_data=f"sm:set:{chat_id}:{task_id}:repeat:1440"),
        ],
        # 按分钟
        [
            InlineKeyboardButton("10 分钟", callback_data=f"sm:set:{chat_id}:{task_id}:repeat:10"),
            InlineKeyboardButton("15 分钟", callback_data=f"sm:set:{chat_id}:{task_id}:repeat:15"),
        ],
        [
            InlineKeyboardButton("20 分钟", callback_data=f"sm:set:{chat_id}:{task_id}:repeat:20"),
            InlineKeyboardButton("30 分钟", callback_data=f"sm:set:{chat_id}:{task_id}:repeat:30"),
        ],
        # 返回
        [
            InlineKeyboardButton("🔙 返回", callback_data=f"sm:open:{chat_id}:{task_id}")
        ],
    ]

    return InlineKeyboardMarkup(buttons)


def sm_day_period_start_keyboard(chat_id: int, task_id: str) -> InlineKeyboardMarkup:
    """时段开始小时选择键盘

    Args:
        chat_id: 群组 ID
        task_id: 任务 ID
    """
    buttons = []
    row = []

    for hour in range(24):
        label = f"{hour:02d}:00"
        row.append(
            InlineKeyboardButton(label, callback_data=f"sm:set:{chat_id}:{task_id}:day_start:{hour}")
        )

        if len(row) == 4:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    # 返回按钮
    buttons.append([
        InlineKeyboardButton("🔙 返回", callback_data=f"sm:open:{chat_id}:{task_id}")
    ])

    return InlineKeyboardMarkup(buttons)


def sm_day_period_end_keyboard(chat_id: int, task_id: str, start_hour: int) -> InlineKeyboardMarkup:
    """时段结束小时选择键盘

    Args:
        chat_id: 群组 ID
        task_id: 任务 ID
        start_hour: 开始小时
    """
    buttons = []
    row = []

    for hour in range(24):
        label = f"{hour:02d}:00"
        row.append(
            InlineKeyboardButton(label, callback_data=f"sm:set:{chat_id}:{task_id}:day_end:{hour}")
        )

        if len(row) == 4:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    # 提示信息
    hint = f"已选择开始时间: {start_hour:02d}:00，请选择结束时间"
    buttons.insert(0, [InlineKeyboardButton(hint, callback_data="_noop")])

    # 返回按钮
    buttons.append([
        InlineKeyboardButton("🔙 返回", callback_data=f"sm:open:{chat_id}:{task_id}")
    ])

    return InlineKeyboardMarkup(buttons)


def sm_confirm_delete_keyboard(chat_id: int, task_id: str) -> InlineKeyboardMarkup:
    """确认删除键盘

    Args:
        chat_id: 群组 ID
        task_id: 任务 ID
    """
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ 确认删除", callback_data=f"sm:del_do:{chat_id}:{task_id}"),
            InlineKeyboardButton("❌ 取消", callback_data=f"sm:del_cancel:{chat_id}:{task_id}"),
        ],
    ])


def sm_edit_text_keyboard(chat_id: int, task_id: str) -> InlineKeyboardMarkup:
    """编辑文本键盘

    Args:
        chat_id: 群组 ID
        task_id: 任务 ID
    """
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔙 返回", callback_data=f"sm:open:{chat_id}:{task_id}")
        ],
    ])


def sm_edit_media_keyboard(chat_id: int, task_id: str) -> InlineKeyboardMarkup:
    """编辑媒体键盘

    Args:
        chat_id: 群组 ID
        task_id: 任务 ID
    """
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔙 返回", callback_data=f"sm:open:{chat_id}:{task_id}")
        ],
    ])


def sm_edit_buttons_keyboard(chat_id: int, task_id: str) -> InlineKeyboardMarkup:
    """编辑按钮键盘

    Args:
        chat_id: 群组 ID
        task_id: 任务 ID
    """
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔙 返回", callback_data=f"sm:open:{chat_id}:{task_id}")
        ],
    ])
