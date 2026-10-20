from __future__ import annotations

from backend.shared.ui.admin_keyboard import admin_keyboard
from backend.shared.ui.menu_layout import page_navigation, navigation_row

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def points_level_list_keyboard(setting, levels, chat_id: int, *, page: int = 0, total: int | None = None) -> InlineKeyboardMarkup:
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
    rows.extend([[InlineKeyboardButton(f"#{level.id} {level.level_name[:20]} · ≥{level.point_threshold}",
                                     callback_data=f"adm:lvl:{chat_id}:detail:{level.id}")] for level in levels])
    rows.extend(page_navigation(page, len(levels) if total is None else total,
                                lambda value: f"adm:lvl:{chat_id}:page:{value}"))
    rows.append([InlineKeyboardButton("添加等级", callback_data=f"adm:lvl:{chat_id}:add"),
                 InlineKeyboardButton("全局标签", callback_data=f"ltag:{chat_id}:0:view")])
    rows.append(navigation_row(f"adm:menu:category_growth:{chat_id}", refresh=f"adm:lvl:{chat_id}:page:{page}"))
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
            InlineKeyboardButton("修改名称", callback_data=f"adm:lvl:{chat_id}:edit:name:{level.id}"),
        ],
        [
            InlineKeyboardButton("📏 积分门槛线：", callback_data=f"adm:lvl:{chat_id}:noop"),
            InlineKeyboardButton("修改门槛", callback_data=f"adm:lvl:{chat_id}:edit:threshold:{level.id}"),
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
    rows.append([InlineKeyboardButton("本级标签", callback_data=f"ltag:{chat_id}:{level.id}:view")])
    rows.append([InlineKeyboardButton("🗑 删除此等级", callback_data=f"adm:lvl:{chat_id}:delete_confirm:{level.id}")])
    rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:points_level:{chat_id}")])
    return admin_keyboard(rows)
