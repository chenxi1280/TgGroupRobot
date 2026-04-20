from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from backend.features.activity import lottery_handler
import backend.features.activity.lottery_drawing as lottery_drawing_module
from backend.features.activity.lottery_drawing import LotteryDrawMixin
from backend.features.activity.lottery_creation import (
    _build_config_from_state,
    _format_lottery_wizard_summary,
    _handle_lottery_wizard_message,
    _parse_preset_winner_ids_from_message,
    _point_type_keyboard,
    _prize_action_keyboard,
    _qualification_rules_from_config,
    _reply_next_prompt,
)
from backend.features.activity.lottery_participation import _format_join_success_message
from backend.features.activity.lottery_menus import _format_local_time as _format_lottery_menu_local_time
import backend.features.activity.services.lottery_service_drawing as lottery_service_drawing
import backend.features.activity.services.lottery_service_participation as lottery_service_participation
import backend.platform.scheduler.tasks.lottery_task as lottery_task_module
from backend.features.activity.ui.lottery import (
    lottery_draw_condition_keyboard,
    lottery_menu_keyboard,
    lottery_mode_keyboard,
    lottery_type_keyboard,
    manual_draw_prize_keyboard,
    manual_draw_summary_keyboard,
    manual_draw_summary_keyboard_with_winners,
)
from backend.features.activity.services.lottery_service import (
    format_lottery_announcement_text,
    parse_lottery_config_text,
)
import backend.features.activity.services.lottery_service as lottery_service_module
from backend.platform.scheduler.core.task_config import TASK_CONFIG
from backend.platform.scheduler.tasks.lottery_task import (
    LotteryTask,
    _format_deadline_reminder,
    _format_draw_result_with_close_notice,
    _format_no_participants_announcement,
    _mark_reminder_sent,
    _time_deadline_reminder_key,
)


REAL_CHAT_ID = -1002966682374


def _all_callbacks(markup) -> list[str]:
    return [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data
    ]


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
    assert callbacks["🔙 返回"] == "adm:menu:main:-1001"


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
    assert callbacks["🎁 通用抽奖"] == "lot:draw_cond:-1001:c:t"
    assert callbacks["💰 积分抽奖"] == "lot:draw_cond:-1001:p:t"
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
    assert callbacks["👥 邀请抽奖 | 达标随机"] == "lot:draw_cond:-1001:i:t"
    assert callbacks["👥 邀请抽奖 | 排名入围随机"] == "lot:draw_cond:-1001:i:r"


def test_lottery_draw_condition_keyboard_exposes_full_and_time_triggers():
    rows = [[button.text for button in row] for row in lottery_draw_condition_keyboard(-1001, "points", "threshold_random").inline_keyboard]
    callbacks = {
        button.text: button.callback_data
        for row in lottery_draw_condition_keyboard(-1001, "points", "threshold_random").inline_keyboard
        for button in row
    }
    assert rows == [
        ["👥 满人开奖"],
        ["⏰ 定时开奖"],
        ["🔙 返回"],
    ]
    assert callbacks["👥 满人开奖"] == "lot:create:-1001:p:t:f"
    assert callbacks["⏰ 定时开奖"] == "lot:create:-1001:p:t:d"


def test_lottery_creation_callbacks_stay_under_telegram_limit_for_real_chat_id():
    callbacks = []
    callbacks.extend(_all_callbacks(lottery_type_keyboard(REAL_CHAT_ID)))
    callbacks.extend(_all_callbacks(lottery_mode_keyboard(REAL_CHAT_ID, "invite")))
    callbacks.extend(_all_callbacks(lottery_mode_keyboard(REAL_CHAT_ID, "activity")))
    for lottery_type in ("common", "points", "invite", "activity"):
        callbacks.extend(_all_callbacks(lottery_draw_condition_keyboard(REAL_CHAT_ID, lottery_type, "threshold_random")))
    callbacks.extend(_all_callbacks(lottery_draw_condition_keyboard(REAL_CHAT_ID, "invite", "ranking_random")))

    assert callbacks
    assert all(len(callback.encode()) <= 64 for callback in callbacks)


def test_lottery_wizard_point_type_callbacks_stay_short_and_store_selection():
    markup = _point_type_keyboard(
        REAL_CHAT_ID,
        [
            SimpleNamespace(id=7, name="出击分", enabled=True),
            SimpleNamespace(id=8, name="关闭积分", enabled=False),
        ],
    )
    callbacks = {
        button.text: button.callback_data
        for row in markup.inline_keyboard
        for button in row
    }

    assert callbacks["积分"] == "lot:wiz:-1002966682374:pt:0"
    assert callbacks["出击分"] == "lot:wiz:-1002966682374:pt:7"
    assert "关闭积分" not in callbacks
    assert all(len(callback.encode()) <= 64 for callback in callbacks.values())


def test_lottery_wizard_prize_action_callbacks_allow_multiple_prizes():
    callbacks = _all_callbacks(_prize_action_keyboard(REAL_CHAT_ID))

    assert f"lot:wiz:{REAL_CHAT_ID}:prize:add" in callbacks
    assert f"lot:wiz:{REAL_CHAT_ID}:prize:done" in callbacks
    assert all(len(callback.encode()) <= 64 for callback in callbacks)


def test_lottery_wizard_config_summary_includes_core_fields_and_preset():
    config = _build_config_from_state(
        {
            "target_chat_id": -1001,
            "lottery_type": "points",
            "selection_mode": "threshold_random",
            "draw_trigger": "full_participants",
            "title": "出击分抽奖",
            "max_participants": 100,
            "prizes": [{"name": "1USDT", "quantity": 1, "points_reward": 0}],
            "participation_cost": 10,
            "point_type_id": 7,
            "point_type_name": "出击分",
            "preset_winner_ids": [123456789],
        }
    )

    summary = _format_lottery_wizard_summary(config)

    assert config.point_type_id == 7
    assert config.point_type_name == "出击分"
    assert config.preset_winner_ids == [123456789]
    assert "抽奖名称：出击分抽奖" in summary
    assert "奖品：" in summary
    assert "• 1USDT × 1" in summary
    assert "中奖人数：1" in summary
    assert "扣除积分：10 出击分" in summary
    assert "内定中奖人：123456789" in summary

    rules = _qualification_rules_from_config(config)
    assert rules["point_type_id"] == 7
    assert rules["point_type_name"] == "出击分"
    assert rules["preset_winner_ids"] == [123456789]


def test_lottery_public_announcements_do_not_expose_preset_winners():
    config = _build_config_from_state(
        {
            "target_chat_id": -1001,
            "lottery_type": "common",
            "selection_mode": "threshold_random",
            "draw_trigger": "full_participants",
            "title": "公开抽奖",
            "max_participants": 10,
            "prizes": [{"name": "1USDT", "quantity": 1, "points_reward": 0}],
            "preset_winner_ids": [123456789],
        }
    )

    announcement = format_lottery_announcement_text(config)

    assert "内定" not in announcement
    assert "123456789" not in announcement


def test_lottery_join_success_message_mentions_user_and_count_without_preset():
    message = _format_join_success_message(
        user=SimpleNamespace(id=42, full_name="Alice <A>", username=None),
        lottery=SimpleNamespace(title="测试 <lottery>", max_participants=100),
        participant_count=7,
        full_draw_completed=False,
    )

    assert '<a href="tg://user?id=42">Alice &lt;A&gt;</a>' in message
    assert "抽奖：测试 &lt;lottery&gt;" in message
    assert "当前参与人数：7/100" in message
    assert "内定" not in message


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
async def test_lottery_create_start_routes_short_codes_to_config_flow(monkeypatch):
    rendered: dict[str, object] = {}
    called: dict[str, object] = {}

    async def fake_is_user_admin(context, chat_id: int, user_id: int):
        return True

    async def fake_start(
        update,
        context,
        target_chat_id: int,
        lottery_type: str = "common",
        selection_mode: str = "threshold_random",
        draw_trigger: str = "time_deadline",
    ):
        called["target_chat_id"] = target_chat_id
        called["lottery_type"] = lottery_type
        called["selection_mode"] = selection_mode
        called["draw_trigger"] = draw_trigger

    monkeypatch.setattr(lottery_handler, "is_user_admin", fake_is_user_admin)
    monkeypatch.setattr(lottery_handler._lottery_handler, "start_create_flow", fake_start)

    class _Q:
        data = "lot:create:-1001:c:t:f"

        async def answer(self, *args, **kwargs):
            return None

    update = SimpleNamespace(
        callback_query=_Q(),
        effective_chat=SimpleNamespace(type="private"),
        effective_user=SimpleNamespace(id=42),
    )
    context = SimpleNamespace()

    await lottery_handler.lottery_create_start(update, context)

    assert called == {
        "target_chat_id": -1001,
        "lottery_type": "common",
        "selection_mode": "threshold_random",
        "draw_trigger": "full_participants",
    }


@pytest.mark.asyncio
async def test_lottery_wizard_collects_common_full_draw_fields():
    replies: list[dict[str, object]] = []
    state = SimpleNamespace(
        state_data={
            "step": "title",
            "target_chat_id": -1001,
            "lottery_type": "common",
            "selection_mode": "threshold_random",
            "draw_trigger": "full_participants",
            "qualification_window_days": 7,
            "prizes": [],
            "preset_winner_ids": [],
        }
    )

    class _Message:
        async def reply_text(self, text, reply_markup=None, **kwargs):
            replies.append({"text": text, "reply_markup": reply_markup})

    class _Session:
        async def commit(self):
            return None

    update = SimpleNamespace(effective_message=_Message())
    session = _Session()

    await _handle_lottery_wizard_message(update, SimpleNamespace(), session, state, "春季抽奖|好运连连")
    assert state.state_data["step"] == "prize_name"
    assert state.state_data["title"] == "春季抽奖"
    assert "第一个奖品" in replies[-1]["text"]

    await _handle_lottery_wizard_message(update, SimpleNamespace(), session, state, "1USDT")
    assert state.state_data["step"] == "prize_quantity"
    assert "中奖人数/份数" in replies[-1]["text"]

    await _handle_lottery_wizard_message(update, SimpleNamespace(), session, state, "1")
    assert state.state_data["step"] == "prize_action"
    assert state.state_data["prizes"] == [{"name": "1USDT", "quantity": 1, "points_reward": 0}]
    assert "还需要继续添加奖品吗" in replies[-1]["text"]
    assert replies[-1]["reply_markup"] is not None

    state.state_data["step"] = "draw_param"
    await _handle_lottery_wizard_message(update, SimpleNamespace(), session, state, "100")
    assert state.state_data["step"] == "preset_confirm"
    assert "内定中奖人：未设置" in replies[-1]["text"]
    assert replies[-1]["reply_markup"] is not None


@pytest.mark.asyncio
async def test_lottery_wizard_collects_multiple_prize_tiers():
    replies: list[dict[str, object]] = []
    state = SimpleNamespace(
        state_data={
            "step": "prize_name",
            "target_chat_id": -1001,
            "lottery_type": "common",
            "selection_mode": "threshold_random",
            "draw_trigger": "full_participants",
            "title": "多奖品抽奖",
            "qualification_window_days": 7,
            "prizes": [{"name": "一等奖", "quantity": 1, "points_reward": 0}],
            "preset_winner_ids": [],
        }
    )

    class _Message:
        async def reply_text(self, text, reply_markup=None, **kwargs):
            replies.append({"text": text, "reply_markup": reply_markup})

    class _Session:
        async def commit(self):
            return None

    update = SimpleNamespace(effective_message=_Message())
    session = _Session()

    await _handle_lottery_wizard_message(update, SimpleNamespace(), session, state, "二等奖")
    await _handle_lottery_wizard_message(update, SimpleNamespace(), session, state, "2")

    assert state.state_data["step"] == "prize_action"
    assert state.state_data["prizes"] == [
        {"name": "一等奖", "quantity": 1, "points_reward": 0},
        {"name": "二等奖", "quantity": 2, "points_reward": 0},
    ]
    assert "二等奖 × 2" in replies[-1]["text"]


@pytest.mark.asyncio
async def test_lottery_wizard_time_deadline_prompt_uses_copyable_next_day_example():
    replies: list[dict[str, object]] = []
    state = SimpleNamespace(
        state_data={
            "step": "prize_quantity",
            "target_chat_id": -1001,
            "lottery_type": "common",
            "selection_mode": "threshold_random",
            "draw_trigger": "time_deadline",
            "title": "定时抽奖",
            "qualification_window_days": 7,
            "pending_prize_name": "1USDT",
            "prizes": [],
            "preset_winner_ids": [],
        }
    )

    class _Message:
        async def reply_text(self, text, reply_markup=None, **kwargs):
            replies.append({"text": text, "reply_markup": reply_markup, "kwargs": kwargs})

    class _Session:
        async def commit(self):
            return None

    update = SimpleNamespace(effective_message=_Message())
    await _reply_next_prompt(update, _Session(), state, state.state_data, "draw_param")

    prompt = replies[0]
    assert "直接复制：<code>" in prompt["text"]
    assert prompt["kwargs"]["parse_mode"] == "HTML"
    assert "YYYY-MM-DD" not in prompt["text"]


@pytest.mark.asyncio
async def test_lottery_wizard_rejects_too_many_preset_winners():
    replies: list[str] = []
    state = SimpleNamespace(
        state_data={
            "step": "preset_winners",
            "target_chat_id": -1001,
            "lottery_type": "common",
            "selection_mode": "threshold_random",
            "draw_trigger": "full_participants",
            "title": "抽奖",
            "max_participants": 100,
            "qualification_window_days": 7,
            "prizes": [{"name": "1USDT", "quantity": 1, "points_reward": 0}],
            "preset_winner_ids": [],
        }
    )

    class _Message:
        async def reply_text(self, text, **kwargs):
            replies.append(text)

    class _Session:
        async def commit(self):
            return None

    await _handle_lottery_wizard_message(
        SimpleNamespace(effective_message=_Message()),
        SimpleNamespace(),
        _Session(),
        state,
        "123,456",
    )

    assert any("内定中奖人数不能超过中奖人数" in text for text in replies)
    assert state.state_data["preset_winner_ids"] == []


@pytest.mark.asyncio
async def test_lottery_wizard_resolves_preset_username_from_db():
    class _Scalars:
        def first(self):
            return SimpleNamespace(id=789)

    class _Result:
        def scalars(self):
            return _Scalars()

    class _Session:
        async def execute(self, stmt):
            return _Result()

    ids = await _parse_preset_winner_ids_from_message(
        SimpleNamespace(effective_message=SimpleNamespace(entities=[])),
        SimpleNamespace(bot=None),
        _Session(),
        "@alice",
    )

    assert ids == [789]


@pytest.mark.asyncio
async def test_lottery_wizard_resolves_preset_text_mention_entity():
    entity = SimpleNamespace(type="text_mention", user=SimpleNamespace(id=321))

    ids = await _parse_preset_winner_ids_from_message(
        SimpleNamespace(effective_message=SimpleNamespace(text="Alice", entities=[entity])),
        SimpleNamespace(bot=None),
        SimpleNamespace(),
        "Alice",
    )

    assert ids == [321]


@pytest.mark.asyncio
async def test_lottery_wizard_reports_unresolved_preset_username():
    class _Scalars:
        def first(self):
            return None

    class _Result:
        def scalars(self):
            return _Scalars()

    class _Session:
        async def execute(self, stmt):
            return _Result()

    with pytest.raises(ValueError, match="@missinguser"):
        await _parse_preset_winner_ids_from_message(
            SimpleNamespace(effective_message=SimpleNamespace(entities=[])),
            SimpleNamespace(bot=None),
            _Session(),
            "@missinguser",
        )


@pytest.mark.asyncio
async def test_lottery_create_start_keeps_legacy_long_callback_compatible(monkeypatch):
    called: dict[str, object] = {}

    async def fake_is_user_admin(context, chat_id: int, user_id: int):
        return True

    async def fake_start(
        update,
        context,
        target_chat_id: int,
        lottery_type: str = "common",
        selection_mode: str = "threshold_random",
        draw_trigger: str = "time_deadline",
    ):
        called["target_chat_id"] = target_chat_id
        called["lottery_type"] = lottery_type
        called["selection_mode"] = selection_mode
        called["draw_trigger"] = draw_trigger

    monkeypatch.setattr(lottery_handler, "is_user_admin", fake_is_user_admin)
    monkeypatch.setattr(lottery_handler._lottery_handler, "start_create_flow", fake_start)

    class _Q:
        data = "lot:create:-1001:points:threshold_random:full_participants"

        async def answer(self, *args, **kwargs):
            return None

    update = SimpleNamespace(
        callback_query=_Q(),
        effective_chat=SimpleNamespace(type="private"),
        effective_user=SimpleNamespace(id=42),
    )

    await lottery_handler.lottery_create_start(update, SimpleNamespace())

    assert called == {
        "target_chat_id": -1001,
        "lottery_type": "points",
        "selection_mode": "threshold_random",
        "draw_trigger": "full_participants",
    }


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


def test_parse_full_participants_lottery_allows_preset_winners_without_draw_time():
    config = parse_lottery_config_text(
        "\n".join(
            [
                "满人抽奖|满员后自动开奖",
                "最低积分: 0",
                "参与费用: 0",
                "满员人数: 2",
                "入群天数: 0",
                "内定中奖人: 12345,67890",
                "奖品:",
                "一等奖,1",
                "二等奖,1",
            ]
        ),
        lottery_type="common",
        draw_trigger="full_participants",
    )
    assert config.draw_trigger == "full_participants"
    assert config.max_participants == 2
    assert config.preset_winner_ids == [12345, 67890]


def test_parse_lottery_config_accepts_direct_user_links_for_preset_winners():
    config = parse_lottery_config_text(
        "\n".join(
            [
                "用户链接内定抽奖",
                "最低积分: 0",
                "参与费用: 0",
                "满员人数: 2",
                "入群天数: 0",
                "内定中奖人: tg://user?id=12345, https://t.me/user?id=67890",
                "奖品:",
                "一等奖,2",
            ]
        ),
        lottery_type="common",
        draw_trigger="full_participants",
    )

    assert config.preset_winner_ids == [12345, 67890]


def test_parse_time_deadline_lottery_keeps_deadline_and_preset_winners():
    config = parse_lottery_config_text(
        "\n".join(
            [
                "截止抽奖|到时间截止开奖",
                "开奖时间: 2099-12-31 20:00",
                "最低积分: 0",
                "参与费用: 0",
                "最大人数: 50",
                "入群天数: 0",
                "内定中奖人:",
                "12345",
                "奖品:",
                "一等奖,1",
            ]
        ),
        lottery_type="points",
        draw_trigger="time_deadline",
    )
    assert config.draw_trigger == "time_deadline"
    assert config.draw_time.year == 2099
    assert config.preset_winner_ids == [12345]
    assert "截止开奖时间: 2099-12-31 20:00" in format_lottery_announcement_text(config)


def test_parse_lottery_config_rejects_non_positive_prize_quantity():
    with pytest.raises(ValueError, match="奖品数量必须大于 0"):
        parse_lottery_config_text(
            "\n".join(
                [
                    "坏奖品抽奖",
                    "开奖时间: 2099-12-31 20:00",
                    "最低积分: 0",
                    "参与费用: 0",
                    "最大人数: 50",
                    "入群天数: 0",
                    "奖品:",
                    "一等奖,0",
                ]
            ),
            draw_trigger="time_deadline",
        )


def test_lottery_result_announcement_uses_html_escaping():
    lottery = SimpleNamespace(lottery_type="common", title="A<B")
    winners = [SimpleNamespace(user_id=123, prize_name="1<USDT>", points_reward=0)]
    users = {123: SimpleNamespace(id=123, full_name="Alice & Bob", username=None)}

    announcement = lottery_service_drawing.generate_lottery_announcement(lottery, winners, users)

    assert "【A&lt;B】" in announcement
    assert "1&lt;USDT&gt;" in announcement
    assert '<a href="tg://user?id=123">Alice &amp; Bob</a>' in announcement


def test_lottery_result_announcement_mentions_winner_even_without_user_record():
    lottery = SimpleNamespace(lottery_type="common", title="抽奖")
    winners = [SimpleNamespace(user_id=456, prize_name="1USDT", points_reward=0)]

    announcement = lottery_service_drawing.generate_lottery_announcement(lottery, winners, {})

    assert '<a href="tg://user?id=456">用户456</a>' in announcement


def test_lottery_deadline_reminders_are_idempotent_and_html_safe():
    now = dt.datetime(2026, 4, 19, 14, 0, tzinfo=dt.timezone.utc)
    lottery = SimpleNamespace(
        id=1,
        title="A<B",
        draw_time=now + dt.timedelta(minutes=59),
        max_participants=100,
        qualification_rules={},
    )

    assert _time_deadline_reminder_key(lottery, now) == ("1h", "1 小时内")
    reminder = _format_deadline_reminder(lottery, participant_count=7, label="1 小时内")
    assert "抽奖【A&lt;B】将在 1 小时内 开奖" in reminder
    assert "当前参与人数：7/100" in reminder

    _mark_reminder_sent(lottery, "1h")
    assert lottery.qualification_rules["time_reminders_sent"] == ["1h"]
    assert _time_deadline_reminder_key(
        SimpleNamespace(draw_time=now + dt.timedelta(minutes=4)),
        now,
    ) == ("5m", "5 分钟内")


def test_lottery_deadline_result_messages_include_close_notice():
    lottery = SimpleNamespace(title="A<B")

    assert _format_draw_result_with_close_notice("开奖结果").startswith("⏰ 抽奖已截止，已停止参与。")
    no_participants = _format_no_participants_announcement(lottery)
    assert "抽奖已截止，已停止参与" in no_participants
    assert "抽奖【A&lt;B】开奖结果" in no_participants


def test_lottery_scheduler_runs_every_minute_for_deadline_accuracy():
    assert TASK_CONFIG["lottery"]["interval"] == 60


def test_lottery_admin_menu_formats_deadline_as_beijing_time():
    utc_time = dt.datetime(2099, 12, 31, 12, 0, tzinfo=dt.timezone.utc)

    assert _format_lottery_menu_local_time(utc_time) == "2099-12-31 20:00"


@pytest.mark.asyncio
async def test_lottery_auto_draw_skips_when_pending_lock_is_missing(monkeypatch):
    calls: list[str] = []

    async def fake_lock_pending_lottery(session, lottery_model, lottery_id):
        return None

    async def fake_draw(session, lottery):
        calls.append("draw")
        return []

    monkeypatch.setattr(lottery_task_module, "_lock_pending_lottery", fake_lock_pending_lottery)

    await LotteryTask()._draw_due_lottery(
        app=SimpleNamespace(),
        session=SimpleNamespace(),
        lottery=SimpleNamespace(id=55),
        now=dt.datetime.now(dt.timezone.utc),
        perform_random_draw=fake_draw,
        generate_lottery_announcement=lambda lottery, winners, users: "result",
        distribute_lottery_rewards=lambda session, lottery, winners: None,
        lottery_model=SimpleNamespace,
        user_model=SimpleNamespace,
    )

    assert calls == []


@pytest.mark.asyncio
async def test_lottery_manual_draw_rolls_back_when_group_result_edit_fails(monkeypatch):
    lottery = SimpleNamespace(
        id=55,
        chat_id=-1001,
        status="pending",
        lottery_type="common",
        title="开奖",
        draw_mode="random",
        prizes=[{"name": "一等奖", "quantity": 1}],
        qualification_rules={},
    )
    winner = SimpleNamespace(user_id=123, prize_name="一等奖", points_reward=0)

    async def fake_get_lottery(session, lottery_id):
        return lottery

    async def fake_get_participants(session, lottery_id):
        return [SimpleNamespace(user_id=123)]

    async def fake_get_setting(session, chat_id):
        return SimpleNamespace(result_pin_enabled=False)

    async def fake_draw(session, lottery_obj):
        return [winner]

    async def fake_distribute(session, lottery_obj, winners):
        return None

    monkeypatch.setattr(lottery_drawing_module, "get_lottery", fake_get_lottery)
    monkeypatch.setattr(lottery_drawing_module, "get_lottery_participants", fake_get_participants)
    monkeypatch.setattr(lottery_drawing_module, "get_or_create_lottery_setting", fake_get_setting)
    monkeypatch.setattr(lottery_service_module, "perform_random_draw", fake_draw)
    monkeypatch.setattr(lottery_service_module, "distribute_lottery_rewards", fake_distribute)
    monkeypatch.setattr(
        lottery_service_module,
        "generate_lottery_announcement",
        lambda lottery_obj, winners, users: "开奖结果",
    )

    class _Scalars:
        def all(self):
            return []

    class _Result:
        def scalars(self):
            return _Scalars()

    class _Session:
        def __init__(self):
            self.commits = 0
            self.rollbacks = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def execute(self, stmt):
            return _Result()

        async def commit(self):
            self.commits += 1

        async def rollback(self):
            self.rollbacks += 1

    class _Db:
        def __init__(self, session):
            self._session = session

        def session_factory(self):
            return self._session

    class _MessageHelper:
        async def safe_edit(self, *args, **kwargs):
            return False

    session = _Session()
    handler = LotteryDrawMixin()
    handler.message_helper = _MessageHelper()
    update = SimpleNamespace(effective_chat=SimpleNamespace(id=-1001, type="supergroup"))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db(session)}))

    await handler.handle_draw(update, context, lottery_id=55)

    assert session.rollbacks == 1
    assert session.commits == 0


def test_parse_lottery_config_rejects_more_fixed_winners_than_prizes():
    with pytest.raises(ValueError, match="内定中奖人数不能超过奖品总数量"):
        parse_lottery_config_text(
            "\n".join(
                [
                    "内定抽奖",
                    "开奖时间: 2099-12-31 20:00",
                    "最低积分: 0",
                    "参与费用: 0",
                    "最大人数: 50",
                    "入群天数: 0",
                    "内定中奖人: 123,456",
                    "奖品:",
                    "一等奖,1",
                ]
            ),
            draw_trigger="time_deadline",
        )


@pytest.mark.asyncio
async def test_join_lottery_converts_unique_conflict_to_already_joined():
    lottery = SimpleNamespace(
        id=55,
        status="pending",
        join_start_time=None,
        join_end_time=None,
        min_points=0,
        participation_cost=0,
        qualification_rules={},
        max_participants=10,
        requirement_days=0,
        lottery_type="common",
    )

    class _Result:
        def __init__(self, scalar_one=None, scalar_value=0):
            self._scalar_one = scalar_one
            self._scalar_value = scalar_value

        def scalar_one_or_none(self):
            return self._scalar_one

        def scalar(self):
            return self._scalar_value

    class _Session:
        def __init__(self):
            self.results = [_Result(lottery), _Result(None), _Result(scalar_value=0)]
            self.rolled_back = False

        async def execute(self, stmt):
            return self.results.pop(0)

        def add(self, entity):
            return None

        async def flush(self):
            raise IntegrityError("insert", {}, Exception("duplicate"))

        async def rollback(self):
            self.rolled_back = True

    session = _Session()

    result = await lottery_service_participation.join_lottery(session, 55, 123, 0)

    assert result.success is False
    assert result.reason == "already_joined"
    assert session.rolled_back is True


def test_parse_full_participants_requires_positive_capacity():
    with pytest.raises(ValueError, match="满人开奖必须配置"):
        parse_lottery_config_text(
            "\n".join(
                [
                    "满人抽奖",
                    "最低积分: 0",
                    "参与费用: 0",
                    "最大人数: 0",
                    "入群天数: 0",
                    "奖品:",
                    "一等奖,1",
                ]
            ),
            draw_trigger="full_participants",
        )


@pytest.mark.asyncio
async def test_perform_random_draw_uses_fixed_winners_before_random_participants(monkeypatch):
    async def fake_get_lottery_participants(session, lottery_id: int):
        return [SimpleNamespace(user_id=333, points_balance=0)]

    def fake_shuffle(items):
        return None

    class _Result:
        def scalar_one_or_none(self):
            return None

    class _Session:
        def __init__(self):
            self.added = []

        async def execute(self, stmt):
            return _Result()

        def add(self, entity):
            self.added.append(entity)

        async def flush(self):
            return None

    lottery = SimpleNamespace(
        id=55,
        chat_id=-1001,
        lottery_type="common",
        qualification_rules={"preset_winner_ids": [111]},
        prizes=[{"name": "一等奖", "quantity": 1}, {"name": "二等奖", "quantity": 1}],
    )
    session = _Session()
    monkeypatch.setattr(lottery_service_drawing, "get_lottery_participants", fake_get_lottery_participants)
    monkeypatch.setattr(lottery_service_drawing.random, "shuffle", fake_shuffle)

    winners = await lottery_service_drawing.perform_random_draw(session, lottery)

    assert [(winner.user_id, winner.prize_name) for winner in winners] == [(111, "一等奖"), (333, "二等奖")]


@pytest.mark.asyncio
async def test_perform_random_draw_allows_fixed_winners_without_participants(monkeypatch):
    async def fake_get_lottery_participants(session, lottery_id: int):
        return []

    class _Result:
        def scalar_one_or_none(self):
            return None

    class _Session:
        def __init__(self):
            self.added = []

        async def execute(self, stmt):
            return _Result()

        def add(self, entity):
            self.added.append(entity)

        async def flush(self):
            return None

    lottery = SimpleNamespace(
        id=56,
        chat_id=-1001,
        lottery_type="common",
        qualification_rules={"preset_winner_ids": [111]},
        prizes=[{"name": "一等奖", "quantity": 1}],
    )
    monkeypatch.setattr(lottery_service_drawing, "get_lottery_participants", fake_get_lottery_participants)

    winners = await lottery_service_drawing.perform_random_draw(_Session(), lottery)

    assert [(winner.user_id, winner.prize_name) for winner in winners] == [(111, "一等奖")]
