from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def format_forward_home(setting, sources, audit_counts: dict[str, int]) -> str:
    button_enabled = bool(getattr(setting, "button_template_enabled", False))
    button_configured = bool(getattr(setting, "button_template", None))
    keywords = "、".join(str(item) for item in (setting.keyword_rules or [])[:8])
    lines = [
        "📡 频道同步",
        "",
        "此功能用来同步频道消息，防止频道被炸。",
        "支持自动同步其他频道的消息到当前群。",
        "",
        f"状态：{'✅ 启动' if setting.enabled else '❌ 关闭'}",
        f"同步模式：{_forward_mode_label(setting.sync_mode)}",
        f"关键词规则：{keywords or '未配置'}",
        f"按钮模板：{'✅ 已启用' if button_enabled else '❌ 未启用'} / {'已配置' if button_configured else '未配置'}",
        f"审计统计：✅ 成功 {audit_counts.get('success', 0)}｜🟡 跳过 {audit_counts.get('skipped', 0)}｜❌ 失败 {audit_counts.get('failed', 0)}",
        "同步来源：",
    ]
    if not sources:
        lines.append("└ 暂无来源频道")
    for item in sources:
        lines.append(
            f"└ {item.source_name or item.source_channel_id}（{item.source_channel_id}）"
        )
    return "\n".join(lines)


def _forward_mode_label(mode: str) -> str:
    return {
        "all": "全部",
        "text": "仅文本",
        "media": "仅媒体",
        "keyword": "关键词",
    }.get(mode, mode)


def _forward_mode_rows(setting, chat_id: int) -> list[list[InlineKeyboardButton]]:
    return [
        [
            InlineKeyboardButton("⚙️ 状态：", callback_data=f"gfw:home:{chat_id}"),
            InlineKeyboardButton(
                "✅ 启动" if setting.enabled else "启动",
                callback_data=f"gfw:toggle:{chat_id}:1",
            ),
            InlineKeyboardButton(
                "关闭" if setting.enabled else "❌ 关闭",
                callback_data=f"gfw:toggle:{chat_id}:0",
            ),
        ],
        [
            InlineKeyboardButton("⚙️ 模式：", callback_data=f"gfw:home:{chat_id}"),
            InlineKeyboardButton(
                "✅ 全部" if setting.sync_mode == "all" else "全部",
                callback_data=f"gfw:mode:{chat_id}:all",
            ),
            InlineKeyboardButton(
                "✅ 仅文本" if setting.sync_mode == "text" else "仅文本",
                callback_data=f"gfw:mode:{chat_id}:text",
            ),
        ],
        [
            InlineKeyboardButton(
                "✅ 仅媒体" if setting.sync_mode == "media" else "仅媒体",
                callback_data=f"gfw:mode:{chat_id}:media",
            ),
            InlineKeyboardButton(
                "✅ 关键词" if setting.sync_mode == "keyword" else "关键词",
                callback_data=f"gfw:mode:{chat_id}:keyword",
            ),
        ],
    ]


def _forward_action_rows(
    button_enabled: bool, chat_id: int
) -> list[list[InlineKeyboardButton]]:
    return [
        [
            InlineKeyboardButton("🔘 自动按钮：", callback_data=f"gfw:home:{chat_id}"),
            InlineKeyboardButton(
                "✅ 启用" if button_enabled else "启用",
                callback_data=f"gfw:btn_toggle:{chat_id}:1",
            ),
            InlineKeyboardButton(
                "关闭" if button_enabled else "❌ 关闭",
                callback_data=f"gfw:btn_toggle:{chat_id}:0",
            ),
        ],
        [
            InlineKeyboardButton(
                "✏️ 按钮模板", callback_data=f"gfw:buttons:input:{chat_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "🧷 更新最近按钮", callback_data=f"gfw:buttons:apply:{chat_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "✏️ 关键词规则", callback_data=f"gfw:keywords:input:{chat_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "➕ 添加来源频道", callback_data=f"gfw:source:add:{chat_id}"
            )
        ],
        [InlineKeyboardButton("📜 转发日志", callback_data=f"gfw:audit:{chat_id}:a")],
        [InlineKeyboardButton("⚠️ 失败任务", callback_data=f"gfw:tasks:{chat_id}:a")],
    ]


def build_forward_home_keyboard(setting, sources, chat_id: int) -> InlineKeyboardMarkup:
    button_enabled = bool(getattr(setting, "button_template_enabled", False))
    rows = _forward_mode_rows(setting, chat_id)
    rows.extend(_forward_action_rows(button_enabled, chat_id))
    for item in sources[:10]:
        label = item.source_name or item.source_channel_id
        rows.append(
            [
                InlineKeyboardButton(
                    f"🗑 移除 {label}",
                    callback_data=f"gfw:source:remove:{chat_id}:{item.id}",
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")]
    )
    return InlineKeyboardMarkup(rows)


def format_forward_audits(
    audits, counts: dict[str, int], result: str, *, retention_days: int
) -> str:
    titles = {"all": "全部", "success": "成功", "skipped": "跳过", "failed": "失败"}
    icons = {"success": "✅", "skipped": "🟡", "failed": "❌"}
    lines = [
        "🔁 车库转发 | 转发日志",
        "",
        f"当前筛选：{titles.get(result, '全部')}",
        f"保留策略：自动保留最近 {retention_days} 天日志",
        f"📊 全部 {counts.get('all', 0)}｜✅ 成功 {counts.get('success', 0)}｜🟡 跳过 {counts.get('skipped', 0)}｜❌ 失败 {counts.get('failed', 0)}",
        "",
    ]
    if not audits:
        lines.append("暂无日志记录")
    for item in audits:
        timestamp = item.created_at.strftime("%m-%d %H:%M") if item.created_at else "--"
        lines.append(
            f"{icons.get(item.result, '📄')} #{item.id}｜{timestamp}｜源 {item.source_channel_id}｜消息 {item.source_message_id or '-'}"
        )
        lines.extend(
            [
                f"动作：{item.action}｜结果：{item.result}｜原因：{item.reason or '-'}",
                "",
            ]
        )
    return "\n".join(lines)


def build_forward_audit_keyboard(
    counts: dict[str, int], result: str, chat_id: int, *, retention_days: int
) -> InlineKeyboardMarkup:
    titles = {"all": "全部", "success": "成功", "skipped": "跳过", "failed": "失败"}
    icons = {"all": "📋", "success": "✅", "skipped": "🟡", "failed": "❌"}
    codes = {"all": "a", "success": "s", "skipped": "k", "failed": "f"}
    filter_rows = []
    for pair in (("all", "success"), ("skipped", "failed")):
        row = []
        for value in pair:
            prefix = "✅ " if result == value else ""
            row.append(
                InlineKeyboardButton(
                    f"{prefix}{icons[value]} {titles[value]}({counts.get(value, 0)})",
                    callback_data=f"gfw:audit:{chat_id}:{codes[value]}",
                )
            )
        filter_rows.append(row)
    cleanup_label = f"🧹 清理 {retention_days} 天前{titles.get(result, '全部')}日志"
    filter_rows.append(
        [
            InlineKeyboardButton(
                cleanup_label,
                callback_data=f"gfw:audit_cleanup:{chat_id}:{codes[result]}",
            )
        ]
    )
    filter_rows.append(
        [InlineKeyboardButton("🔙 返回", callback_data=f"gfw:home:{chat_id}")]
    )
    return InlineKeyboardMarkup(filter_rows)
