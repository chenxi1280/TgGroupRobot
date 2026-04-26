"""抽奖键盘

提供抽奖管理的键盘生成。
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from backend.features.activity.services.lottery_service_parsing import (
    encode_draw_trigger,
    encode_lottery_type,
    encode_selection_mode,
)
from backend.shared.ui.base.helpers import create_back_button
from backend.shared.ui.formatters import format_user_label


def lottery_menu_keyboard(chat_id: int | None = None) -> InlineKeyboardMarkup:
    """抽奖菜单键盘

    Args:
        chat_id: 群组 ID，用于在私聊中操作群组时指定目标群组
    """
    create_menu_callback = f"lot:create_menu:{chat_id}" if chat_id else "lot:create_menu"
    list_callback = f"lot:list:{chat_id}:all:all:0" if chat_id else "lot:list:all:all:0"
    setting_callback = f"lot:settings:{chat_id}" if chat_id else "lot:settings"
    back_button = create_back_button(chat_id, "main")

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🚀 发起抽奖活动", callback_data=create_menu_callback),
            InlineKeyboardButton("📋 活动列表", callback_data=list_callback),
        ],
        [InlineKeyboardButton("⚙️ 抽奖设置", callback_data=setting_callback)],
        [back_button],
    ])


def lottery_type_keyboard(chat_id: int | None = None) -> InlineKeyboardMarkup:
    common_type = encode_lottery_type("common")
    points_type = encode_lottery_type("points")
    subscribe_type = encode_lottery_type("subscribe")
    threshold_mode = encode_selection_mode("threshold_random")
    create_callback = f"lot:draw_cond:{chat_id}:{common_type}:{threshold_mode}" if chat_id else f"lot:draw_cond:{common_type}:{threshold_mode}"
    points_callback = f"lot:draw_cond:{chat_id}:{points_type}:{threshold_mode}" if chat_id else f"lot:draw_cond:{points_type}:{threshold_mode}"
    subscribe_callback = f"lot:draw_cond:{chat_id}:{subscribe_type}:{threshold_mode}" if chat_id else f"lot:draw_cond:{subscribe_type}:{threshold_mode}"
    invite_callback = f"lot:mode_menu:{chat_id}:invite" if chat_id else "lot:mode_menu:invite"
    activity_callback = f"lot:mode_menu:{chat_id}:activity" if chat_id else "lot:mode_menu:activity"
    back_callback = f"adm:menu:lottery:{chat_id}" if chat_id else "adm:menu:lottery"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎁 通用抽奖", callback_data=create_callback),
            InlineKeyboardButton("💰 积分抽奖", callback_data=points_callback),
        ],
        [
            InlineKeyboardButton("👥 邀请抽奖", callback_data=invite_callback),
            InlineKeyboardButton("🔥 群活跃抽奖", callback_data=activity_callback),
        ],
        [InlineKeyboardButton("📣 强制订阅抽奖", callback_data=subscribe_callback)],
        [InlineKeyboardButton("🔙 返回", callback_data=back_callback)],
    ])


def lottery_mode_keyboard(chat_id: int, lottery_type: str) -> InlineKeyboardMarkup:
    type_label = "👥 邀请抽奖" if lottery_type == "invite" else "🔥 群活跃抽奖"
    type_code = encode_lottery_type(lottery_type)
    threshold_mode = encode_selection_mode("threshold_random")
    ranking_mode = encode_selection_mode("ranking_random")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{type_label} | 达标随机", callback_data=f"lot:draw_cond:{chat_id}:{type_code}:{threshold_mode}")],
        [InlineKeyboardButton(f"{type_label} | 排名入围随机", callback_data=f"lot:draw_cond:{chat_id}:{type_code}:{ranking_mode}")],
        [InlineKeyboardButton("🔙 返回", callback_data=f"lot:create_menu:{chat_id}")],
    ])


def lottery_draw_condition_keyboard(chat_id: int, lottery_type: str, selection_mode: str) -> InlineKeyboardMarkup:
    type_code = encode_lottery_type(lottery_type)
    mode_code = encode_selection_mode(selection_mode)
    full_trigger = encode_draw_trigger("full_participants")
    deadline_trigger = encode_draw_trigger("time_deadline")
    if selection_mode == "ranking_random":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("⏰ 定时开奖", callback_data=f"lot:create:{chat_id}:{type_code}:{mode_code}:{deadline_trigger}")],
            [InlineKeyboardButton("🔙 返回", callback_data=f"lot:create_menu:{chat_id}")],
        ])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 满人开奖", callback_data=f"lot:create:{chat_id}:{type_code}:{mode_code}:{full_trigger}")],
        [InlineKeyboardButton("⏰ 定时开奖", callback_data=f"lot:create:{chat_id}:{type_code}:{mode_code}:{deadline_trigger}")],
        [InlineKeyboardButton("🔙 返回", callback_data=f"lot:create_menu:{chat_id}")],
    ])


def manual_draw_prize_keyboard(
    target_chat_id: int,
    lottery_id: int,
    prize_index: int,
    prize_name: str,
    participants: list,
    page: int = 0,
    page_size: int = 8,
) -> InlineKeyboardMarkup:
    """手动选择中奖人键盘

    Args:
        lottery_id: 抽奖 ID
        prize_index: 奖品索引
        prize_name: 奖品名称
        participants: 参与者列表
        page: 当前页码
        page_size: 每页数量
    """
    buttons = []
    start_idx = page * page_size
    end_idx = start_idx + page_size

    for participant in participants[start_idx:end_idx]:
        # 使用 format_user_label 格式化用户名
        user_info = participant.user_info if hasattr(participant, 'user_info') else None
        label = format_user_label(user_info, participant.user_id)

        callback_data = f"lot:select_winner:{target_chat_id}:{lottery_id}:{prize_index}:{participant.user_id}:{prize_name}"
        buttons.append([InlineKeyboardButton(label, callback_data=callback_data)])

    # 分页导航
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(
            "⬅️ 上一页",
            callback_data=f"lot:winner_page:{target_chat_id}:{lottery_id}:{prize_index}:{page-1}"
        ))
    if end_idx < len(participants):
        nav_buttons.append(InlineKeyboardButton(
            "下一页 ➡️",
            callback_data=f"lot:winner_page:{target_chat_id}:{lottery_id}:{prize_index}:{page+1}"
        ))

    if nav_buttons:
        buttons.append(nav_buttons)

    buttons.append([InlineKeyboardButton("🔙 返回", callback_data=f"lot:draw_menu:{target_chat_id}:{lottery_id}")])
    return InlineKeyboardMarkup(buttons)


def manual_draw_summary_keyboard(
    target_chat_id: int,
    lottery_id: int,
    prizes: list,
) -> InlineKeyboardMarkup:
    """手动开奖汇总键盘

    Args:
        lottery_id: 抽奖 ID
        prizes: 奖品列表
    """
    buttons = []
    for i, prize in enumerate(prizes):
        quantity = prize.get("quantity", 1)
        for j in range(quantity):
            prize_index = i * 10 + j
            buttons.append([
                InlineKeyboardButton(
                    f"🎁 {prize['name']} (未选择)",
                    callback_data=f"lot:select_prize:{target_chat_id}:{lottery_id}:{prize_index}:{prize['name']}"
                )
            ])

    buttons.append([InlineKeyboardButton("✅ 完成开奖", callback_data=f"lot:complete_manual_draw:{target_chat_id}:{lottery_id}")])
    buttons.append([InlineKeyboardButton("🔙 返回", callback_data=f"lot:detail:{target_chat_id}:{lottery_id}")])
    return InlineKeyboardMarkup(buttons)


def manual_draw_summary_keyboard_with_winners(
    target_chat_id: int,
    lottery_id: int,
    prizes: list,
    winners: dict,
) -> InlineKeyboardMarkup:
    """手动开奖汇总键盘（已选择部分中奖人）

    Args:
        lottery_id: 抽奖 ID
        prizes: 奖品列表
        winners: 中奖者映射字典
    """
    buttons = []
    for i, prize in enumerate(prizes):
        quantity = prize.get("quantity", 1)
        for j in range(quantity):
            prize_index = i * 10 + j
            winner_info = winners.get(prize_index)
            if winner_info is None:
                winner_info = winners.get(str(prize_index))
            if winner_info:
                buttons.append([
                    InlineKeyboardButton(
                        f"✅ {prize['name']} - {winner_info['name']}",
                        callback_data=f"lot:select_prize:{target_chat_id}:{lottery_id}:{prize_index}:{prize['name']}"
                    )
                ])
            else:
                buttons.append([
                    InlineKeyboardButton(
                        f"🎁 {prize['name']} (未选择)",
                        callback_data=f"lot:select_prize:{target_chat_id}:{lottery_id}:{prize_index}:{prize['name']}"
                    )
                ])

    buttons.append([InlineKeyboardButton("✅ 完成开奖", callback_data=f"lot:complete_manual_draw:{target_chat_id}:{lottery_id}")])
    buttons.append([InlineKeyboardButton("🔙 返回", callback_data=f"lot:detail:{target_chat_id}:{lottery_id}")])
    return InlineKeyboardMarkup(buttons)


def get_join_keyboard(lottery_id: int) -> InlineKeyboardMarkup:
    """获取参与抽奖的键盘

    Args:
        lottery_id: 抽奖 ID

    Returns:
        参与抽奖的按钮键盘
    """
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎯 参与抽奖", callback_data=f"join_lottery_{lottery_id}")],
    ])
