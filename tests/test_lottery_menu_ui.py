from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot.handlers import lottery_handler
from bot.keyboards.activity.lottery import lottery_menu_keyboard, lottery_mode_keyboard, lottery_type_keyboard
from bot.services.activity.lottery_service import parse_lottery_config_text


def test_lottery_menu_keyboard_exposes_all_real_flows():
    rows = [[button.text for button in row] for row in lottery_menu_keyboard(-1001).inline_keyboard]
    callbacks = {
        button.text: button.callback_data
        for row in lottery_menu_keyboard(-1001).inline_keyboard
        for button in row
    }

    assert rows == [
        ["🚀 发起抽奖活动", "📋 活动列表"],
        ["⚙️ 抽奖设置"],
        ["🔙 返回"],
    ]
    assert callbacks["🚀 发起抽奖活动"] == "lot:create_menu:-1001"
    assert callbacks["📋 活动列表"] == "lot:list:-1001:all:all:0"
    assert callbacks["⚙️ 抽奖设置"] == "lot:settings:-1001"


def test_lottery_type_keyboard_lists_four_types():
    rows = [[button.text for button in row] for row in lottery_type_keyboard(-1001).inline_keyboard]
    callbacks = {
        button.text: button.callback_data
        for row in lottery_type_keyboard(-1001).inline_keyboard
        for button in row
    }
    assert rows == [
        ["🎁 通用抽奖", "💰 积分抽奖"],
        ["👥 邀请抽奖", "🔥 群活跃抽奖"],
        ["🔙 返回"],
    ]
    assert callbacks["👥 邀请抽奖"] == "lot:mode_menu:-1001:invite"
    assert callbacks["🔥 群活跃抽奖"] == "lot:mode_menu:-1001:activity"


def test_lottery_mode_keyboard_exposes_threshold_and_ranking_modes():
    rows = [[button.text for button in row] for row in lottery_mode_keyboard(-1001, "invite").inline_keyboard]
    callbacks = {
        button.text: button.callback_data
        for row in lottery_mode_keyboard(-1001, "invite").inline_keyboard
        for button in row
    }
    assert rows == [
        ["👥 邀请抽奖 | 达标随机"],
        ["👥 邀请抽奖 | 排名入围随机"],
        ["🔙 返回"],
    ]
    assert callbacks["👥 邀请抽奖 | 达标随机"] == "lot:create:-1001:invite:threshold_random"
    assert callbacks["👥 邀请抽奖 | 排名入围随机"] == "lot:create:-1001:invite:ranking_random"


@pytest.mark.asyncio
async def test_lottery_create_start_routes_points_type_to_config_flow(monkeypatch):
    rendered: dict[str, object] = {}
    called: dict[str, object] = {}

    async def fake_is_user_admin(context, chat_id: int, user_id: int):
        return True

    async def fake_start(update, context, target_chat_id: int, lottery_type: str = "common", selection_mode: str = "threshold_random"):
        called["target_chat_id"] = target_chat_id
        called["lottery_type"] = lottery_type
        called["selection_mode"] = selection_mode

    monkeypatch.setattr(lottery_handler, "is_user_admin", fake_is_user_admin)
    monkeypatch.setattr(lottery_handler._lottery_handler, "start_create_flow", fake_start)

    class _Q:
        data = "lot:create:-1001:points"

        async def answer(self, *args, **kwargs):
            return None

    update = SimpleNamespace(
        callback_query=_Q(),
        effective_chat=SimpleNamespace(type="private"),
        effective_user=SimpleNamespace(id=42),
    )
    context = SimpleNamespace()

    await lottery_handler.lottery_create_start(update, context)

    assert called == {"target_chat_id": -1001, "lottery_type": "points", "selection_mode": "threshold_random"}


def test_parse_invite_lottery_config_requires_invite_threshold():
    config = parse_lottery_config_text(
        "\n".join(
            [
                "邀请冲榜抽奖|邀请达到门槛可参与",
                "开奖时间: 2099-12-31 20:00",
                "最低积分: 0",
                "参与费用: 0",
                "最大人数: 100",
                "入群天数: 0",
                "邀请人数: 3",
                "统计天数: 7",
                "奖品:",
                "一等奖,1",
            ]
        ),
        lottery_type="invite",
    )
    assert config.lottery_type == "invite"
    assert config.required_invites == 3
    assert config.qualification_window_days == 7


def test_parse_activity_lottery_config_requires_message_threshold():
    config = parse_lottery_config_text(
        "\n".join(
            [
                "活跃抽奖|最近发言达标即可参与",
                "开奖时间: 2099-12-31 20:00",
                "最低积分: 0",
                "参与费用: 0",
                "最大人数: 200",
                "入群天数: 0",
                "活跃消息数: 300",
                "统计天数: 10",
                "奖品:",
                "一等奖,1",
            ]
        ),
        lottery_type="activity",
    )
    assert config.lottery_type == "activity"
    assert config.required_activity_count == 300
    assert config.qualification_window_days == 10


def test_parse_ranking_invite_lottery_requires_finalist_limit():
    config = parse_lottery_config_text(
        "\n".join(
            [
                "邀请排行抽奖|先按排行入围再随机开奖",
                "开奖时间: 2099-12-31 20:00",
                "最低积分: 0",
                "参与费用: 0",
                "最大人数: 0",
                "入群天数: 0",
                "邀请人数: 3",
                "统计天数: 7",
                "入围人数: 10",
                "奖品:",
                "一等奖,1",
            ]
        ),
        lottery_type="invite",
        selection_mode="ranking_random",
    )
    assert config.selection_mode == "ranking_random"
    assert config.finalist_limit == 10
