from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def lottery_menu_keyboard(chat_id: int | None = None) -> InlineKeyboardMarkup:
    """抽奖菜单键盘

    Args:
        chat_id: 群组ID，用于在私聊中操作群组时指定目标群组
    """
    # 构建创建抽奖的回调数据
    if chat_id:
        create_callback = f"lot:create:{chat_id}"
        back_callback = f"adm:back_to_menu:{chat_id}"
    else:
        create_callback = "lot:create"
        back_callback = "adm:menu:main"

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🎁创建通用抽奖", callback_data=create_callback)],
            [InlineKeyboardButton("返回", callback_data=back_callback)],
        ]
    )


def manual_draw_prize_keyboard(lottery_id: int, prize_index: int, prize_name: str, participants: list, page: int = 0, page_size: int = 8) -> InlineKeyboardMarkup:
    """手动选择中奖人键盘"""
    buttons = []
    start_idx = page * page_size
    end_idx = start_idx + page_size

    for participant in participants[start_idx:end_idx]:
        # participant 是 LotteryParticipant 对象，包含 user_info 属性
        user_info = participant.user_info
        if user_info:
            label = f"{user_info.first_name or user_info.last_name or user_info.username or f'用户{participant.user_id}'}"
        else:
            label = f"用户{participant.user_id}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"lot:select_winner:{lottery_id}:{prize_index}:{participant.user_id}:{prize_name}")])

    # 分页导航
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"lot:winner_page:{lottery_id}:{prize_index}:{page-1}"))
    if end_idx < len(participants):
        nav_buttons.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"lot:winner_page:{lottery_id}:{prize_index}:{page+1}"))

    if nav_buttons:
        buttons.append(nav_buttons)

    buttons.append([InlineKeyboardButton("🔙 返回", callback_data=f"lot:draw_menu:{lottery_id}")])
    return InlineKeyboardMarkup(buttons)


def manual_draw_summary_keyboard(lottery_id: int, prizes: list) -> InlineKeyboardMarkup:
    """手动开奖汇总键盘"""
    buttons = []
    for i, prize in enumerate(prizes):
        quantity = prize.get("quantity", 1)
        for j in range(quantity):
            prize_index = i * 10 + j
            buttons.append([InlineKeyboardButton(f"🎁 {prize['name']} (未选择)", callback_data=f"lot:select_prize:{lottery_id}:{prize_index}:{prize['name']}")])

    buttons.append([InlineKeyboardButton("✅ 完成开奖", callback_data=f"lot:complete_manual_draw:{lottery_id}")])
    buttons.append([InlineKeyboardButton("🔙 返回", callback_data="adm:menu:main")])
    return InlineKeyboardMarkup(buttons)


def manual_draw_summary_keyboard_with_winners(lottery_id: int, prizes: list, winners: dict) -> InlineKeyboardMarkup:
    """手动开奖汇总键盘（已选择部分中奖人）"""
    buttons = []
    for i, prize in enumerate(prizes):
        quantity = prize.get("quantity", 1)
        for j in range(quantity):
            prize_index = i * 10 + j
            winner_info = winners.get(prize_index)
            if winner_info:
                buttons.append([InlineKeyboardButton(f"✅ {prize['name']} - {winner_info['name']}", callback_data=f"lot:select_prize:{lottery_id}:{prize_index}:{prize['name']}")])
            else:
                buttons.append([InlineKeyboardButton(f"🎁 {prize['name']} (未选择)", callback_data=f"lot:select_prize:{lottery_id}:{prize_index}:{prize['name']}")])

    buttons.append([InlineKeyboardButton("✅ 完成开奖", callback_data=f"lot:complete_manual_draw:{lottery_id}")])
    buttons.append([InlineKeyboardButton("🔙 返回", callback_data="adm:menu:main")])
    return InlineKeyboardMarkup(buttons)


def get_join_keyboard(lottery_id: int) -> InlineKeyboardMarkup:
    """获取参与抽奖的键盘

    Args:
        lottery_id: 抽奖ID

    Returns:
        参与抽奖的按钮键盘
    """
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🎯 参与抽奖", callback_data=f"join_lottery_{lottery_id}")],
        ]
    )

