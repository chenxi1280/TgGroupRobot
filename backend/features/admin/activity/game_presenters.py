from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def _game_toggle_rows(setting, chat_id: int) -> list[list[InlineKeyboardButton]]:
    return [
        [
            InlineKeyboardButton("🎲 快三", callback_data=f"gm:home:{chat_id}"),
            InlineKeyboardButton(
                "✅ 启动" if setting.k3_enabled else "启动",
                callback_data=f"gm:toggle:{chat_id}:k3:1",
            ),
            InlineKeyboardButton(
                "✅ 关闭" if not setting.k3_enabled else "关闭",
                callback_data=f"gm:toggle:{chat_id}:k3:0",
            ),
        ],
        [
            InlineKeyboardButton("🃏 黑杰克", callback_data=f"gm:home:{chat_id}"),
            InlineKeyboardButton(
                "✅ 启动" if setting.blackjack_enabled else "启动",
                callback_data=f"gm:toggle:{chat_id}:blackjack:1",
            ),
            InlineKeyboardButton(
                "✅ 关闭" if not setting.blackjack_enabled else "关闭",
                callback_data=f"gm:toggle:{chat_id}:blackjack:0",
            ),
        ],
    ]


def _game_config_rows(
    setting, chat_id: int, points_chat_label: str
) -> list[list[InlineKeyboardButton]]:
    return [
        [
            InlineKeyboardButton(
                "🔗 关联积分", callback_data=f"gm:points:{chat_id}:menu"
            ),
            InlineKeyboardButton(
                points_chat_label, callback_data=f"gm:points:{chat_id}:menu"
            ),
        ],
        [
            InlineKeyboardButton(
                "💧 抽水比例", callback_data=f"gm:rake:{chat_id}:ratio"
            ),
            InlineKeyboardButton(
                "👤 抽水归属", callback_data=f"gm:rake:{chat_id}:owner"
            ),
        ],
        [
            InlineKeyboardButton("⏰ 定时启停", callback_data=f"gm:home:{chat_id}"),
            InlineKeyboardButton(
                "✅ 启动" if setting.auto_schedule_enabled else "启动",
                callback_data=f"gm:auto:{chat_id}:toggle:1",
            ),
            InlineKeyboardButton(
                "✅ 关闭" if not setting.auto_schedule_enabled else "关闭",
                callback_data=f"gm:auto:{chat_id}:toggle:0",
            ),
        ],
        [
            InlineKeyboardButton(
                "🕒 启动时间", callback_data=f"gm:auto:{chat_id}:start_time"
            ),
            InlineKeyboardButton(
                "🌙 关停时间", callback_data=f"gm:auto:{chat_id}:stop_time"
            ),
        ],
    ]


def _game_footer_rows(setting, chat_id: int) -> list[list[InlineKeyboardButton]]:
    delete_mark = " ✅" if setting.delete_game_message_mode == "delete" else ""
    keep_mark = " ✅" if setting.delete_game_message_mode == "keep" else ""
    return [
        [
            InlineKeyboardButton(
                "🧹 删除游戏消息：", callback_data=f"gm:home:{chat_id}"
            ),
            InlineKeyboardButton(
                "🗑 删除" + delete_mark, callback_data=f"gm:delete_mode:{chat_id}:delete"
            ),
            InlineKeyboardButton(
                "💾 不删除" + keep_mark, callback_data=f"gm:delete_mode:{chat_id}:keep"
            ),
        ],
        [
            InlineKeyboardButton("📋 最近牌局", callback_data=f"gm:rounds:{chat_id}"),
            InlineKeyboardButton("📘 指令帮助", callback_data=f"gm:help:{chat_id}"),
        ],
        [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
    ]


def build_game_menu_keyboard(
    setting, chat_id: int, points_chat_label: str
) -> InlineKeyboardMarkup:
    rows = _game_toggle_rows(setting, chat_id)
    rows.extend(_game_config_rows(setting, chat_id, points_chat_label))
    rows.extend(_game_footer_rows(setting, chat_id))
    return InlineKeyboardMarkup(rows)


def build_game_points_keyboard(
    managed_chats, chat_id: int, current_source: int | None
) -> InlineKeyboardMarkup:
    is_self = current_source is None or int(current_source) == int(chat_id)
    label = ("✅ " if is_self else "") + "本群分"
    rows = [[InlineKeyboardButton(label, callback_data=f"gm:points:{chat_id}:self")]]
    for source_chat_id, title, _ in managed_chats:
        if int(source_chat_id) == int(chat_id):
            continue
        selected = current_source is not None and int(current_source) == int(
            source_chat_id
        )
        prefix = "✅ " if selected else ""
        rows.append(
            [
                InlineKeyboardButton(
                    f"{prefix}主群分：{title}"[:60],
                    callback_data=f"gm:points:{chat_id}:set:{source_chat_id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"gm:home:{chat_id}")])
    return InlineKeyboardMarkup(rows)


def format_game_points_text(current_label: str, has_alternative: bool) -> str:
    text = "\n".join(
        [
            "🔗 游戏 | 关联积分",
            "",
            f"当前使用：{current_label}",
            "",
            "如果小群/内部群/工兵群需要使用大群积分进行游戏，请选择主群分。",
        ]
    )
    if not has_alternative:
        text += "\n\n暂无可关联的其他管理群。"
    return text


def format_game_round_detail(round_obj, participants) -> str:
    result_data = round_obj.result_data or {}
    lines = [
        "🎮 牌局详情",
        "",
        f"🆔 局号：{round_obj.id}",
        f"🎯 类型：{round_obj.game_type}",
        f"📌 状态：{round_obj.status}",
        f"🕒 创建时间：{round_obj.created_at.strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    if round_obj.game_type == "k3":
        lines.append(f"🎲 开奖结果：{result_data.get('dice') or '未开奖'}")
        if result_data.get("label"):
            lines.append(f"🏷 结果标签：{result_data.get('label')}")
    if round_obj.game_type == "blackjack":
        lines.append(f"🃏 玩家牌：{result_data.get('player_cards') or []}")
        lines.append(f"🤖 庄家牌：{result_data.get('dealer_cards') or []}")
    lines.extend(["", "👥 参与情况："])
    if not participants:
        lines.append("• 暂无参与记录")
    for participant in participants:
        lines.append(
            f"• 用户 {participant.user_id} | 下注 {participant.bet_points} | "
            f"状态 {participant.status} | 结算 {participant.payout_points}"
        )
    return "\n".join(lines)
