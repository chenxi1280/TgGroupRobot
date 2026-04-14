from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def points_level_list_keyboard(setting, levels, chat_id: int) -> InlineKeyboardMarkup:
    enabled = bool(setting.enabled)
    exclude_teacher = bool(setting.exclude_teacher_enabled)
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton("⚙️ 状态：", callback_data=f"adm:lvl:{chat_id}:noop"),
            InlineKeyboardButton("✅ 启动" if enabled else "启动", callback_data=f"adm:lvl:{chat_id}:toggle:enabled:1"),
            InlineKeyboardButton("关闭" if enabled else "❌ 关闭", callback_data=f"adm:lvl:{chat_id}:toggle:enabled:0"),
        ],
        [
            InlineKeyboardButton("👨‍🏫 排除老师：", callback_data=f"adm:lvl:{chat_id}:noop"),
            InlineKeyboardButton("✅ 启动" if exclude_teacher else "启动", callback_data=f"adm:lvl:{chat_id}:toggle:exclude_teacher:1"),
            InlineKeyboardButton("关闭" if exclude_teacher else "❌ 关闭", callback_data=f"adm:lvl:{chat_id}:toggle:exclude_teacher:0"),
        ],
    ]
    if levels:
        rows.extend([[InlineKeyboardButton(f"{level.level_name} / {level.point_threshold}", callback_data=f"adm:lvl:{chat_id}:detail:{level.id}")] for level in levels])
    else:
        rows.append([InlineKeyboardButton("🕒 待配置", callback_data=f"adm:lvl:{chat_id}:noop")])
    rows.append([InlineKeyboardButton("➕ 添加一个等级", callback_data=f"adm:lvl:{chat_id}:add")])
    rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:points:{chat_id}")])
    return InlineKeyboardMarkup(rows)


def points_level_detail_keyboard(level, chat_id: int) -> InlineKeyboardMarkup:
    perms = [
        ("发送文字：", "allow_text", level.allow_text),
        ("发送音频：", "allow_audio", level.allow_audio),
        ("发送图片：", "allow_photo", level.allow_photo),
        ("发送视频：", "allow_video", level.allow_video),
        ("发送贴纸：", "allow_sticker", level.allow_sticker),
        ("发送文件：", "allow_document", level.allow_document),
        ("发送@提到：", "allow_mention", level.allow_mention),
    ]
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton("🏷️ 等级名称：", callback_data=f"adm:lvl:{chat_id}:noop"),
            InlineKeyboardButton(level.level_name or "未配置", callback_data=f"adm:lvl:{chat_id}:edit:name:{level.id}"),
        ],
        [
            InlineKeyboardButton("📏 积分门槛线：", callback_data=f"adm:lvl:{chat_id}:noop"),
            InlineKeyboardButton(str(level.point_threshold), callback_data=f"adm:lvl:{chat_id}:edit:threshold:{level.id}"),
        ],
    ]
    for label, perm, enabled in perms:
        rows.append(
            [
                InlineKeyboardButton(label, callback_data=f"adm:lvl:{chat_id}:noop"),
                InlineKeyboardButton("✅ 允许" if enabled else "允许", callback_data=f"adm:lvl:{chat_id}:perm:{level.id}:{perm}:1"),
                InlineKeyboardButton("不允许" if enabled else "❌ 不允许", callback_data=f"adm:lvl:{chat_id}:perm:{level.id}:{perm}:0"),
            ]
        )
    rows.append([InlineKeyboardButton("🗑 删除此等级", callback_data=f"adm:lvl:{chat_id}:delete_confirm:{level.id}")])
    rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:points_level:{chat_id}")])
    return InlineKeyboardMarkup(rows)
