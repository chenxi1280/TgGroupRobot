"""抽奖键盘

提供抽奖管理的键盘生成。
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.keyboards.base.helpers import create_back_button
from bot.keyboards.formatters import format_user_label


def lottery_menu_keyboard(chat_id: int | None = None) -> InlineKeyboardMarkup:
    """抽奖菜单键盘

    Args:
        chat_id: 群组 ID，用于在私聊中操作群组时指定目标群组
    """
    create_callback = f"lot:create:{chat_id}" if chat_id else "lot:create"
    back_button = create_back_button(chat_id, "back_to_menu")

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎁创建通用抽奖", callback_data=create_callback)],
        [back_button],
    ])


def manual_draw_prize_keyboard(
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

        callback_data = f"lot:select_winner:{lottery_id}:{prize_index}:{participant.user_id}:{prize_name}"
        buttons.append([InlineKeyboardButton(label, callback_data=callback_data)])

    # 分页导航
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(
            "⬅️ 上一页",
            callback_data=f"lot:winner_page:{lottery_id}:{prize_index}:{page-1}"
        ))
    if end_idx < len(participants):
        nav_buttons.append(InlineKeyboardButton(
            "下一页 ➡️",
            callback_data=f"lot:winner_page:{lottery_id}:{prize_index}:{page+1}"
        ))

    if nav_buttons:
        buttons.append(nav_buttons)

    buttons.append([InlineKeyboardButton("🔙 返回", callback_data=f"lot:draw_menu:{lottery_id}")])
    return InlineKeyboardMarkup(buttons)


def manual_draw_summary_keyboard(
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
                    callback_data=f"lot:select_prize:{lottery_id}:{prize_index}:{prize['name']}"
                )
            ])

    buttons.append([InlineKeyboardButton("✅ 完成开奖", callback_data=f"lot:complete_manual_draw:{lottery_id}")])
    buttons.append([InlineKeyboardButton("🔙 返回", callback_data="adm:menu:main")])
    return InlineKeyboardMarkup(buttons)


def manual_draw_summary_keyboard_with_winners(
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
            if winner_info:
                buttons.append([
                    InlineKeyboardButton(
                        f"✅ {prize['name']} - {winner_info['name']}",
                        callback_data=f"lot:select_prize:{lottery_id}:{prize_index}:{prize['name']}"
                    )
                ])
            else:
                buttons.append([
                    InlineKeyboardButton(
                        f"🎁 {prize['name']} (未选择)",
                        callback_data=f"lot:select_prize:{lottery_id}:{prize_index}:{prize['name']}"
                    )
                ])

    buttons.append([InlineKeyboardButton("✅ 完成开奖", callback_data=f"lot:complete_manual_draw:{lottery_id}")])
    buttons.append([InlineKeyboardButton("🔙 返回", callback_data="adm:menu:main")])
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
