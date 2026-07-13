from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def build_bottom_home(
    setting, layouts, chat_id: int
) -> tuple[str, InlineKeyboardMarkup]:
    text = "\n".join(
        [
            "⌨️ 底部按钮",
            "",
            f"⚙️ 状态：{'✅ 启用' if setting.enabled else '❌ 关闭'}",
            f"📝 文案：{setting.header_text}",
            f"🔢 按钮数：{len(layouts)}",
            "",
            "提示：底部按钮会同步到 Telegram 输入框下方，用户点击后会发送按钮文字并触发对应功能。",
        ]
    )
    rows = [
        [
            InlineKeyboardButton("⚙️ 状态：", callback_data=f"btm:home:{chat_id}"),
            InlineKeyboardButton(
                "✅ 启用" if setting.enabled else "启用",
                callback_data=f"btm:toggle:{chat_id}:1",
            ),
            InlineKeyboardButton(
                "✅ 关闭" if not setting.enabled else "关闭",
                callback_data=f"btm:toggle:{chat_id}:0",
            ),
        ],
        [
            InlineKeyboardButton(
                "✏️ 文案设置", callback_data=f"btm:text:{chat_id}:edit"
            ),
            InlineKeyboardButton(
                "⌨️ 按钮设置", callback_data=f"btm:layout:{chat_id}:edit"
            ),
        ],
        [
            InlineKeyboardButton(
                "✅ 同步到底部键盘", callback_data=f"btm:generate:{chat_id}:now"
            )
        ],
        [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
    ]
    return text, InlineKeyboardMarkup(rows)


def build_bottom_detail(
    layout, chat_id: int, action_label: str
) -> tuple[str, InlineKeyboardMarkup]:
    text = "\n".join(
        [
            "⌨️ 底部按钮 | 编辑按钮",
            "",
            f"按钮文字：{layout.button_text}",
            f"绑定事件：{action_label}",
            f"点击后发送：{layout.button_text}",
            "",
            "按钮文字展示在输入框下方，绑定事件决定点击后实际执行的功能。",
        ]
    )
    rows = [
        [
            InlineKeyboardButton(
                "✏️ 修改文字", callback_data=f"btm:button:{chat_id}:text:{layout.id}"
            ),
            InlineKeyboardButton(
                "🎯 绑定事件", callback_data=f"btm:button:{chat_id}:events:{layout.id}"
            ),
        ],
        [
            InlineKeyboardButton(
                "⌨️ 自定义触发词",
                callback_data=f"btm:button:{chat_id}:payload:{layout.id}",
            )
        ],
        [
            InlineKeyboardButton(
                "❌ 删除按钮", callback_data=f"btm:button:{chat_id}:delete:{layout.id}"
            ),
            InlineKeyboardButton("🔙 返回", callback_data=f"btm:layout:{chat_id}:edit"),
        ],
    ]
    return text, InlineKeyboardMarkup(rows)


def build_bottom_event_categories(
    layout, categories, chat_id: int, *, custom_category: str, action_label: str
) -> tuple[str, InlineKeyboardMarkup]:
    rows = []
    for index in range(0, len(categories), 2):
        row = []
        for category, label in categories[index : index + 2]:
            if category == custom_category:
                callback_data = f"btm:button:{chat_id}:payload:{layout.id}"
                label = "⌨️ " + label
            else:
                callback_data = f"btm:button:{chat_id}:eventcat:{layout.id}:{category}"
            row.append(InlineKeyboardButton(label, callback_data=callback_data))
        rows.append(row)
    rows.append(
        [
            InlineKeyboardButton(
                "🔙 返回", callback_data=f"btm:button:{chat_id}:detail:{layout.id}"
            )
        ]
    )
    text = "\n".join(
        [
            "⌨️ 底部按钮 | 绑定事件",
            "",
            f"按钮文字：{layout.button_text}",
            f"当前绑定：{action_label}",
            "",
            "选择一个内置功能事件，或使用自定义触发词兼容群内已有入口。",
        ]
    )
    return text, InlineKeyboardMarkup(rows)


def _bottom_event_rows(layout, events, chat_id: int, *, encode_key):
    rows = []
    for index in range(0, len(events), 2):
        row = []
        for event in events[index : index + 2]:
            selected = (
                layout.action_mode == "event" and layout.payload_text == event.key
            )
            callback = f"btm:button:{chat_id}:event:{layout.id}:{encode_key(event.key)}"
            row.append(
                InlineKeyboardButton(
                    ("✅ " if selected else "") + event.label, callback_data=callback
                )
            )
        rows.append(row)
    if not rows:
        rows.append(
            [
                InlineKeyboardButton(
                    "暂无可绑定事件",
                    callback_data=f"btm:button:{chat_id}:events:{layout.id}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                "🔙 返回分类", callback_data=f"btm:button:{chat_id}:events:{layout.id}"
            )
        ]
    )
    return rows


def build_bottom_event_list(
    layout, events, chat_id: int, *, category_label: str, action_label: str, encode_key
) -> tuple[str, InlineKeyboardMarkup]:
    text = "\n".join(
        [
            f"⌨️ 底部按钮 | {category_label}",
            "",
            f"按钮文字：{layout.button_text}",
            f"当前绑定：{action_label}",
            "",
            "选择后会保存为后台事件；如果按钮文字还是“按钮”，会自动改成事件文案。",
        ]
    )
    return text, InlineKeyboardMarkup(
        _bottom_event_rows(layout, events, chat_id, encode_key=encode_key)
    )
