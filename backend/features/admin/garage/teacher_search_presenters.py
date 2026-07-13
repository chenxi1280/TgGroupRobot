from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def _toggle_labels(enabled: bool) -> tuple[str, str]:
    return ("✅ 启动", "关闭") if enabled else ("启动", "✅ 关闭")


def _attendance_mode_label(mode: str) -> str:
    return {
        "external": "不在此群打卡",
        "message": "发言就是打卡",
        "keyword": "固定话术打卡",
    }.get(mode, "发言就是打卡")


def _teacher_search_description_lines(setting) -> list[str]:
    lines = [
        "🔎 老师搜索",
        "",
        "根据车库频道信息提供群内搜索功能，需要提前找锅巴洋芋进行车库对接。",
        "",
        "标签搜索：输入车牌名称、地址、服务等信息",
        "开课打卡：按打卡模式记录当天开课",
    ]
    if setting.attendance_enabled:
        lines.append("只显开课：只展示当天开课打卡的老师")
    lines.append("附近搜索：群友发送附近可查询周边老师")
    if getattr(setting, "nearby_search_enabled", False):
        lines.append("强制录入：未录入位置的老师无法正常发言")
    return lines


def _teacher_search_status_lines(setting, open_teacher_count: int) -> list[str]:
    only_open = getattr(setting, "only_open_course_enabled", True)
    mode = getattr(setting, "attendance_mode", "message") or "message"
    lines = [
        "",
        f"标签搜索：{'✅ 启动' if setting.tag_search_enabled else '✅ 关闭'}",
        f"开课打卡：{'✅ 启动' if setting.attendance_enabled else '✅ 关闭'}",
    ]
    if setting.attendance_enabled:
        lines.extend(
            [
                f"打卡模式：{_attendance_mode_label(mode)}",
                f"只显开课：{'✅ 启动' if only_open else '❌ 关闭'}",
            ]
        )
    lines.append(
        f"附近搜索：{'✅ 启动' if setting.nearby_search_enabled else '✅ 关闭'}"
    )
    if getattr(setting, "nearby_search_enabled", False):
        lines.append(
            f"强制录入：{'✅ 启动' if setting.force_location_enabled else '❌ 关闭'}"
        )
    lines.extend(
        [
            f"删除消息：{'不删除' if setting.delete_mode == 'none' else '删除'}",
            f"开课老师：{open_teacher_count} 人",
        ]
    )
    return lines


def _teacher_search_home_text(setting, open_teacher_count: int) -> str:
    lines = _teacher_search_description_lines(setting)
    lines.extend(_teacher_search_status_lines(setting, open_teacher_count))
    return "\n".join(lines)


def _teacher_search_attendance_rows(setting, chat_id: int):
    mode = getattr(setting, "attendance_mode", "message") or "message"
    only_open = getattr(setting, "only_open_course_enabled", True)
    attendance_on, attendance_off = _toggle_labels(setting.attendance_enabled)
    rows = [
        [
            InlineKeyboardButton("开课打卡：", callback_data=f"tsearch:home:{chat_id}"),
            InlineKeyboardButton(
                attendance_on, callback_data=f"tsearch:toggle:attendance:{chat_id}:1"
            ),
            InlineKeyboardButton(
                attendance_off, callback_data=f"tsearch:toggle:attendance:{chat_id}:0"
            ),
        ]
    ]
    if setting.attendance_enabled:
        only_on, only_off = _toggle_labels(only_open)
        rows.extend(
            [
                [
                    InlineKeyboardButton(
                        "打卡模式：", callback_data=f"tsearch:home:{chat_id}"
                    ),
                    InlineKeyboardButton(
                        _attendance_mode_label(mode),
                        callback_data=f"tsearch:attendance_mode:menu:{chat_id}",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "只显开课：", callback_data=f"tsearch:home:{chat_id}"
                    ),
                    InlineKeyboardButton(
                        only_on, callback_data=f"tsearch:toggle:only_open:{chat_id}:1"
                    ),
                    InlineKeyboardButton(
                        only_off, callback_data=f"tsearch:toggle:only_open:{chat_id}:0"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "📝 手动替老师打卡",
                        callback_data=f"tsearch:attendance:manual:{chat_id}",
                    )
                ],
            ]
        )
    return rows


def _teacher_search_nearby_rows(setting, chat_id: int):
    nearby_on, nearby_off = _toggle_labels(setting.nearby_search_enabled)
    rows = [
        [
            InlineKeyboardButton("附近搜索：", callback_data=f"tsearch:home:{chat_id}"),
            InlineKeyboardButton(
                nearby_on, callback_data=f"tsearch:toggle:nearby:{chat_id}:1"
            ),
            InlineKeyboardButton(
                nearby_off, callback_data=f"tsearch:toggle:nearby:{chat_id}:0"
            ),
        ]
    ]
    if getattr(setting, "nearby_search_enabled", False):
        force_on, force_off = _toggle_labels(setting.force_location_enabled)
        rows.append(
            [
                InlineKeyboardButton(
                    "强制录入：", callback_data=f"tsearch:home:{chat_id}"
                ),
                InlineKeyboardButton(
                    force_on, callback_data=f"tsearch:toggle:force_loc:{chat_id}:1"
                ),
                InlineKeyboardButton(
                    force_off, callback_data=f"tsearch:toggle:force_loc:{chat_id}:0"
                ),
            ]
        )
    return rows


def _teacher_search_footer_rows(setting, chat_id: int):
    delete_label = "删除" if setting.delete_mode != "none" else "不删除"
    delete_value = "delete" if setting.delete_mode == "none" else "none"
    return [
        [
            InlineKeyboardButton("删除消息：", callback_data=f"tsearch:home:{chat_id}"),
            InlineKeyboardButton(
                delete_label,
                callback_data=f"tsearch:delete_mode:{chat_id}:{delete_value}",
            ),
        ],
        [
            InlineKeyboardButton(
                "📍 代录老师位置", callback_data=f"tsearch:delegate:start:{chat_id}"
            )
        ],
        [InlineKeyboardButton("返回", callback_data=f"adm:menu:main:{chat_id}")],
    ]


def _teacher_search_home_keyboard(setting, chat_id: int) -> InlineKeyboardMarkup:
    tag_on, tag_off = _toggle_labels(setting.tag_search_enabled)
    rows = [
        [
            InlineKeyboardButton("标签搜索：", callback_data=f"tsearch:home:{chat_id}"),
            InlineKeyboardButton(
                tag_on, callback_data=f"tsearch:toggle:tag:{chat_id}:1"
            ),
            InlineKeyboardButton(
                tag_off, callback_data=f"tsearch:toggle:tag:{chat_id}:0"
            ),
        ]
    ]
    rows.extend(_teacher_search_attendance_rows(setting, chat_id))
    rows.extend(_teacher_search_nearby_rows(setting, chat_id))
    rows.extend(_teacher_search_footer_rows(setting, chat_id))
    return InlineKeyboardMarkup(rows)


def _attendance_keyword_rows(setting, chat_id: int):
    words = (
        (
            "🟡 开课词：",
            "open",
            getattr(setting, "attendance_open_keyword", "开课") or "开课",
        ),
        (
            "🔴 满课词：",
            "full",
            getattr(setting, "attendance_full_keyword", "满课") or "满课",
        ),
        (
            "⚪ 休息词：",
            "rest",
            getattr(setting, "attendance_rest_keyword", "休息") or "休息",
        ),
    )
    rows = []
    for label, key, word in words:
        callback = f"tsearch:attendance_word:{key}:{chat_id}"
        rows.append(
            [
                InlineKeyboardButton(label, callback_data=callback),
                InlineKeyboardButton(word, callback_data=callback),
            ]
        )
    return rows


def _attendance_mode_keyboard(setting, chat_id: int) -> InlineKeyboardMarkup:
    mode = getattr(setting, "attendance_mode", "message") or "message"
    rows = [
        [
            InlineKeyboardButton(
                ("✅ " if mode == "external" else "") + "不在此群打卡",
                callback_data=f"tsearch:attendance_source:menu:{chat_id}",
            )
        ],
        [
            InlineKeyboardButton(
                ("✅ " if mode == "message" else "") + "发言就是打卡",
                callback_data=f"tsearch:attendance_mode:set:{chat_id}:message",
            )
        ],
        [
            InlineKeyboardButton(
                ("✅ " if mode == "keyword" else "") + "固定话术打卡",
                callback_data=f"tsearch:attendance_mode:set:{chat_id}:keyword",
            )
        ],
    ]
    if mode == "keyword":
        rows.extend(_attendance_keyword_rows(setting, chat_id))
    rows.append(
        [InlineKeyboardButton("⬅️ 返回", callback_data=f"tsearch:home:{chat_id}")]
    )
    return InlineKeyboardMarkup(rows)


def build_attendance_source_menu(
    managed_chats, current_source: int | None, chat_id: int
) -> tuple[str, InlineKeyboardMarkup]:
    rows = []
    for source_chat_id, title, _ in managed_chats:
        if int(source_chat_id) == int(chat_id):
            continue
        selected = current_source is not None and int(current_source) == int(
            source_chat_id
        )
        label = ("✅ " if selected else "") + title
        rows.append(
            [
                InlineKeyboardButton(
                    label,
                    callback_data=f"tsearch:attendance_source:set:{chat_id}:{source_chat_id}",
                )
            ]
        )
    has_sources = bool(rows)
    rows.append(
        [
            InlineKeyboardButton(
                "⬅️ 返回", callback_data=f"tsearch:attendance_mode:menu:{chat_id}"
            )
        ]
    )
    text = "🔍 老师搜索 | 关联打卡群\n\n请选择用于打卡的群。当前群只负责搜索，开课状态会读取关联群的打卡记录。"
    if not has_sources:
        text += "\n\n暂无可关联的其他管理群。"
    return text, InlineKeyboardMarkup(rows)


def build_attendance_source_mode_menu(
    title: str, current_mode: str, chat_id: int, *, source_chat_id: int
) -> tuple[str, InlineKeyboardMarkup]:
    text = f"🔍 老师搜索 | 关联打卡群\n\n打卡群：{title}\n\n请选择这个打卡群自己的打卡方式："
    rows = [
        [
            InlineKeyboardButton(
                ("✅ " if current_mode == "message" else "") + "发言就是打卡",
                callback_data=f"tsearch:attendance_source_mode:set:{chat_id}:{source_chat_id}:message",
            )
        ],
        [
            InlineKeyboardButton(
                ("✅ " if current_mode == "keyword" else "") + "固定话术打卡",
                callback_data=f"tsearch:attendance_source_mode:set:{chat_id}:{source_chat_id}:keyword",
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ 返回", callback_data=f"tsearch:attendance_source:menu:{chat_id}"
            )
        ],
    ]
    return text, InlineKeyboardMarkup(rows)


def build_attendance_detail(
    setting, open_teacher_count: int, chat_id: int
) -> tuple[str, InlineKeyboardMarkup]:
    open_count = f"{open_teacher_count} 人"
    lines = [
        "🔎 老师搜索 | 开课详情",
        "",
        f"开课打卡：{'✅ 启动' if setting.attendance_enabled else '❌ 关闭'}",
    ]
    rows = []
    if setting.attendance_enabled:
        lines.append(f"开课老师：{open_count}")
        callback = f"tsearch:open_course:list:{chat_id}:0"
        rows.append(
            [
                InlineKeyboardButton("📚 开课老师", callback_data=callback),
                InlineKeyboardButton(open_count, callback_data=callback),
            ]
        )
    if getattr(setting, "nearby_search_enabled", False):
        force_on, force_off = _toggle_labels(setting.force_location_enabled)
        lines.append(
            f"强制录入：{'✅ 启动' if setting.force_location_enabled else '❌ 关闭'}"
        )
        rows.append(
            [
                InlineKeyboardButton(
                    "强制录入：", callback_data=f"tsearch:attendance:menu:{chat_id}"
                ),
                InlineKeyboardButton(
                    force_on, callback_data=f"tsearch:toggle:force_loc:{chat_id}:1"
                ),
                InlineKeyboardButton(
                    force_off, callback_data=f"tsearch:toggle:force_loc:{chat_id}:0"
                ),
            ]
        )
    rows.append([InlineKeyboardButton("返回", callback_data=f"tsearch:home:{chat_id}")])
    return "\n".join(lines), InlineKeyboardMarkup(rows)
