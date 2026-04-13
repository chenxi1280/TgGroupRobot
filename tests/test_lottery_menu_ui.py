from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.activity import lottery_handler
from backend.features.activity.ui.lottery import (
    lottery_menu_keyboard,
    lottery_mode_keyboard,
    lottery_type_keyboard,
    manual_draw_prize_keyboard,
    manual_draw_summary_keyboard,
    manual_draw_summary_keyboard_with_winners,
)
from backend.features.activity.services.lottery_service import parse_lottery_config_text


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


def test_manual_draw_keyboards_keep_target_chat_scope():
    participants = [SimpleNamespace(user_id=11, user_info=None)]
    prize_markup = manual_draw_prize_keyboard(-1001, 55, 0, "大奖吗", participants)
    prize_callbacks = {
        button.text: button.callback_data
        for row in prize_markup.inline_keyboard
        for button in row
    }
    assert prize_callbacks["用户11"] == "lot:select_winner:-1001:55:0:11:大奖吗"
    assert prize_callbacks["🔙 返回"] == "lot:draw_menu:-1001:55"

    summary_markup = manual_draw_summary_keyboard(-1001, 55, [{"name": "大奖吗", "quantity": 1}])
    summary_callbacks = {
        button.text: button.callback_data
        for row in summary_markup.inline_keyboard
        for button in row
    }
    assert summary_callbacks["✅ 完成开奖"] == "lot:complete_manual_draw:-1001:55"
    assert summary_callbacks["🔙 返回"] == "lot:detail:-1001:55"


def test_manual_draw_summary_keyboard_marks_string_state_keys():
    prize_name = "大奖吗"
    markup = manual_draw_summary_keyboard_with_winners(
        -1001,
        55,
        [{"name": prize_name, "quantity": 1}],
        {"0": {"name": "Alice", "user_id": 99, "prize_name": prize_name}},
    )
    assert markup.inline_keyboard[0][0].text == f"✅ {prize_name} - Alice"


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


@pytest.mark.asyncio
async def test_manual_draw_select_winner_uses_target_chat_scope_and_open_session(monkeypatch):
    admin_calls: list[int] = []
    rendered: dict[str, object] = {}
    state = SimpleNamespace(state_type="manual_draw", state_data={})

    async def fake_is_user_admin(context, chat_id: int, user_id: int):
        admin_calls.append(chat_id)
        return True

    async def fake_get_user_state(session, chat_id: int, user_id: int):
        return state

    async def fake_get_lottery(session, lottery_id: int):
        return SimpleNamespace(chat_id=-1001, prizes=[{"name": "大奖吗", "quantity": 1}])

    async def fake_safe_edit(update, text: str, reply_markup=None, **kwargs):
        rendered["text"] = text
        rendered["reply_markup"] = reply_markup

    class _Result:
        def scalar_one_or_none(self):
            return SimpleNamespace(first_name="Alice", last_name=None, username=None)

    class _Session:
        def __init__(self):
            self.closed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            self.closed = True

        async def commit(self):
            return None

        async def execute(self, stmt):
            assert not self.closed, "session used after context exit"
            return _Result()

    session = _Session()
    db = SimpleNamespace(session_factory=lambda: session)

    monkeypatch.setattr(lottery_handler, "is_user_admin", fake_is_user_admin)
    monkeypatch.setattr(lottery_handler, "get_user_state", fake_get_user_state)
    monkeypatch.setattr(lottery_handler, "get_lottery", fake_get_lottery)
    monkeypatch.setattr(lottery_handler._lottery_handler.message_helper, "safe_edit", fake_safe_edit)

    class _Q:
        data = "lot:select_winner:-1001:55:0:99:大奖吗"

        async def answer(self, *args, **kwargs):
            return None

    update = SimpleNamespace(
        callback_query=_Q(),
        effective_chat=SimpleNamespace(id=777, type="private"),
        effective_user=SimpleNamespace(id=42),
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": db}))

    await lottery_handler.manual_draw_select_winner_callback(update, context)

    assert admin_calls == [-1001]
    assert state.state_data["winners"]["0"]["user_id"] == 99
    assert rendered["reply_markup"].inline_keyboard[1][0].callback_data == "lot:complete_manual_draw:-1001:55"


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
