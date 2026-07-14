from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError
from telegram.error import NetworkError

from backend.features.activity import lottery_handler
import backend.features.activity.lottery_message_callbacks as lottery_message_callbacks
import backend.features.activity.lottery_creation as lottery_creation_module
import backend.features.activity.lottery_drawing as lottery_drawing_module
import backend.features.activity.lottery_participation as lottery_participation_module
from backend.features.activity.lottery_message_callbacks import lottery_cancel_callback_impl
from backend.features.activity.lottery_drawing import LotteryDrawMixin
from backend.features.activity.lottery_creation import (
    _build_config_from_state,
    _format_lottery_wizard_summary,
    _handle_lottery_wizard_message,
    _lottery_draft_required_items,
    _parse_preset_winner_ids_from_message,
    _point_type_keyboard,
    _prize_action_keyboard,
    _qualification_rules_from_config,
    _reply_next_prompt,
    _reply_preset_confirm,
)
from backend.features.activity.lottery_participation import _format_join_success_message
from backend.features.activity.lottery_participation import _join_error_message
from backend.features.activity.lottery_menus import _format_local_time as _format_lottery_menu_local_time
from backend.features.activity.services.lottery_subscription import (
    check_lottery_subscribe_membership,
    parse_lottery_subscribe_targets,
    validate_lottery_subscribe_targets,
)
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
from backend.platform.db.schema.models.core import TgUser
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


def test_lottery_type_keyboard_lists_five_types():
    rows = [[button.text for button in row] for row in lottery_type_keyboard(-1001).inline_keyboard]
    callbacks = {
        button.text: button.callback_data
        for row in lottery_type_keyboard(-1001).inline_keyboard
        for button in row
    }
    assert rows == [
        ["🎁 通用抽奖", "💰 积分抽奖"],
        ["👥 邀请抽奖", "🔥 群活跃抽奖"],
        ["📣 强制订阅抽奖"],
        ["🔙 返回"],
    ]
    assert callbacks["🎁 通用抽奖"] == "lot:draw_cond:-1001:c:t"
    assert callbacks["💰 积分抽奖"] == "lot:draw_cond:-1001:p:t"
    assert callbacks["👥 邀请抽奖"] == "lot:mode_menu:-1001:invite"
    assert callbacks["🔥 群活跃抽奖"] == "lot:mode_menu:-1001:activity"
    assert callbacks["📣 强制订阅抽奖"] == "lot:draw_cond:-1001:s:t"


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
    for lottery_type in ("common", "points", "invite", "activity", "subscribe"):
        callbacks.extend(_all_callbacks(lottery_draw_condition_keyboard(REAL_CHAT_ID, lottery_type, "threshold_random")))
    callbacks.extend(_all_callbacks(lottery_draw_condition_keyboard(REAL_CHAT_ID, "invite", "ranking_random")))

    assert callbacks
    assert all(len(callback.encode()) <= 64 for callback in callbacks)


@pytest.mark.asyncio
async def test_lottery_cancel_returns_to_lottery_menu_in_private_context():
    calls: list[tuple[str, int, int | None]] = []

    class _Query:
        data = f"lottery:cancel:{REAL_CHAT_ID}"

        async def answer(self):
            calls.append(("answer", 0, None))

        async def edit_message_text(self, text, **kwargs):
            calls.append(("edit", 0, None))

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def commit(self):
            calls.append(("commit", 0, None))

    class _Db:
        def session_factory(self):
            return _Session()

    class _Handler:
        async def show_menu(self, update, context, target_chat_id):
            calls.append(("show_lottery_menu", target_chat_id, None))

    async def _clear_user_state(session, chat_id, user_id):
        calls.append(("clear_state", chat_id, user_id))

    update = SimpleNamespace(
        callback_query=_Query(),
        effective_chat=SimpleNamespace(id=777, type="private"),
        effective_user=SimpleNamespace(id=42),
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await lottery_cancel_callback_impl(
        update,
        context,
        handler=_Handler(),
        clear_user_state_fn=_clear_user_state,
    )

    assert ("clear_state", 42, 42) in calls
    assert ("show_lottery_menu", REAL_CHAT_ID, None) in calls
    assert not any(call[0] == "edit" for call in calls)


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
    assert callbacks["🔙 返回上级"] == "lot:wiz:-1002966682374:back"
    assert callbacks["❌ 取消配置"] == "lottery:cancel:-1002966682374"
    assert "关闭积分" not in callbacks
    assert all(len(callback.encode()) <= 64 for callback in callbacks.values())


def test_lottery_wizard_prize_action_callbacks_allow_multiple_prizes():
    callbacks = _all_callbacks(_prize_action_keyboard(REAL_CHAT_ID))

    assert f"lot:wiz:{REAL_CHAT_ID}:prize:add" in callbacks
    assert f"lot:wiz:{REAL_CHAT_ID}:prize:done" in callbacks
    assert f"lot:wiz:{REAL_CHAT_ID}:back" in callbacks
    assert f"lottery:cancel:{REAL_CHAT_ID}" in callbacks
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
    assert "配置进度:" in summary
    assert "下一步: 确认无误后发布到群" in summary
    assert "测试: 发布后用测试账号点击参与" in summary

    rules = _qualification_rules_from_config(config)
    assert rules["point_type_id"] == 7
    assert rules["point_type_name"] == "出击分"
    assert rules["preset_winner_ids"] == [123456789]


def test_lottery_wizard_config_summary_includes_assigned_preset_prize():
    config = _build_config_from_state(
        {
            "target_chat_id": -1001,
            "lottery_type": "common",
            "selection_mode": "threshold_random",
            "draw_trigger": "full_participants",
            "title": "指定奖品抽奖",
            "max_participants": 100,
            "prizes": [{"name": "一等奖", "quantity": 1, "points_reward": 0}, {"name": "二等奖", "quantity": 1, "points_reward": 0}],
            "preset_winner_ids": [123456789],
            "preset_winner_assignments": [{"user_id": 123456789, "prize_name": "二等奖"}],
        }
    )

    summary = _format_lottery_wizard_summary(config)
    rules = _qualification_rules_from_config(config)

    assert "• 二等奖 × 1（内定：123456789）" in summary
    assert "• 一等奖 × 1（随机）" in summary
    assert "内定中奖人：123456789（二等奖）" in summary
    assert rules["preset_winner_assignments"] == [{"user_id": 123456789, "prize_name": "二等奖"}]


def test_lottery_progress_always_uses_four_required_steps():
    cases = [
        (
            "common",
            {
                "lottery_type": "common",
                "selection_mode": "threshold_random",
                "draw_trigger": "full_participants",
                "title": "普通抽奖",
                "prizes": [{"name": "1USDT", "quantity": 1}],
                "max_participants": 10,
            },
            ("参与条件（无额外要求）", True),
        ),
        (
            "points",
            {
                "lottery_type": "points",
                "selection_mode": "threshold_random",
                "draw_trigger": "full_participants",
                "title": "积分抽奖",
                "prizes": [{"name": "1USDT", "quantity": 1}],
                "max_participants": 10,
            },
            ("参与扣分", False),
        ),
        (
            "invite",
            {
                "lottery_type": "invite",
                "selection_mode": "threshold_random",
                "draw_trigger": "full_participants",
                "title": "邀请抽奖",
                "prizes": [{"name": "1USDT", "quantity": 1}],
                "max_participants": 10,
                "required_invites": 3,
            },
            ("邀请门槛", True),
        ),
        (
            "activity",
            {
                "lottery_type": "activity",
                "selection_mode": "threshold_random",
                "draw_trigger": "full_participants",
                "title": "活跃抽奖",
                "prizes": [{"name": "1USDT", "quantity": 1}],
                "max_participants": 10,
                "required_activity_count": 200,
            },
            ("活跃门槛", True),
        ),
        (
            "subscribe",
            {
                "lottery_type": "subscribe",
                "selection_mode": "threshold_random",
                "draw_trigger": "full_participants",
                "title": "订阅抽奖",
                "prizes": [{"name": "1USDT", "quantity": 1}],
                "max_participants": 10,
                "subscribe_targets": [{"target": "@channel_a", "label": "@channel_a"}],
            },
            ("关注目标", True),
        ),
        (
            "ranking",
            {
                "lottery_type": "invite",
                "selection_mode": "ranking_random",
                "draw_trigger": "time_deadline",
                "title": "邀请排行抽奖",
                "prizes": [{"name": "1USDT", "quantity": 1}],
                "draw_time": "2099-12-31T12:00:00+00:00",
                "finalist_limit": 10,
            },
            ("排行入围条件", True),
        ),
    ]

    for _case_name, data, expected_condition in cases:
        items = _lottery_draft_required_items(data)
        assert len(items) == 4
        assert items[-1] == expected_condition


def test_lottery_wizard_public_summary_hides_preset_winners():
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

    summary = _format_lottery_wizard_summary(config, include_sensitive=False)

    assert "抽奖名称：公开抽奖" in summary
    assert "中奖人数：1" in summary
    assert "内定" not in summary
    assert "123456789" not in summary


@pytest.mark.asyncio
async def test_lottery_wizard_group_confirm_does_not_echo_preset_winners():
    replies: list[dict[str, object]] = []
    state = SimpleNamespace(
        state_data={
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

    class _Message:
        async def reply_text(self, text, **kwargs):
            replies.append({"text": text, **kwargs})

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-1001, type="supergroup"),
        effective_message=_Message(),
    )

    class _Session:
        async def commit(self):
            return None

    await _reply_preset_confirm(update, _Session(), state, data=state.state_data)

    assert replies
    assert "抽奖名称：公开抽奖" in replies[-1]["text"]
    assert "内定" not in replies[-1]["text"]
    assert "123456789" not in replies[-1]["text"]
    button_texts = [
        button.text
        for row in replies[-1]["reply_markup"].inline_keyboard
        for button in row
    ]
    assert "✅ 确认发布抽奖" in button_texts
    assert "🔙 返回上级" in button_texts
    assert "❌ 取消配置" in button_texts
    assert all("内定" not in text for text in button_texts)


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


def test_lottery_ranking_announcement_explains_no_manual_join():
    config = _build_config_from_state(
        {
            "target_chat_id": -1001,
            "lottery_type": "invite",
            "selection_mode": "ranking_random",
            "draw_trigger": "time_deadline",
            "title": "邀请榜抽奖",
            "draw_time": "2099-12-31T12:00:00+00:00",
            "required_invites": 0,
            "finalist_limit": 10,
            "prizes": [{"name": "1USDT", "quantity": 1, "points_reward": 0}],
        }
    )

    announcement = format_lottery_announcement_text(config)

    assert "无需点击参与" in announcement
    assert "继续完成对应的邀请或活跃任务" in announcement


def test_subscribe_lottery_config_stores_per_lottery_targets():
    config = parse_lottery_config_text(
        "\n".join(
            [
                "关注后抽奖|先关注指定频道再参与",
                "开奖时间: 2099-12-31 20:00",
                "关注目标: @channel_a",
                "最低积分: 0",
                "参与费用: 0",
                "最大人数: 100",
                "入群天数: 0",
                "奖品:",
                "一等奖,1",
            ]
        ),
        lottery_type="subscribe",
    )

    summary = _format_lottery_wizard_summary(config)
    rules = _qualification_rules_from_config(config)
    announcement = format_lottery_announcement_text(config)

    assert config.lottery_type == "subscribe"
    assert config.subscribe_targets == [{"target": "@channel_a", "label": "@channel_a", "url": "https://t.me/channel_a"}]
    assert rules["requires_lottery_subscribe"] is True
    assert rules["subscribe_check_mode"] == "all"
    assert rules["subscribe_targets"] == config.subscribe_targets
    assert "📣 强制订阅抽奖" in summary
    assert "订阅目标：@channel_a" in summary
    assert "📣 参与条件: 需先关注：@channel_a" in announcement


def test_subscribe_lottery_config_requires_own_target():
    with pytest.raises(ValueError, match="必须配置关注目标"):
        parse_lottery_config_text(
            "\n".join(
                [
                    "关注后抽奖",
                    "开奖时间: 2099-12-31 20:00",
                    "奖品:",
                    "一等奖,1",
                ]
            ),
            lottery_type="subscribe",
        )


def test_parse_lottery_subscribe_targets_accepts_private_invite_format():
    targets = parse_lottery_subscribe_targets("@channel_a, https://t.me/group_b\n-1001234567890|https://t.me/+invite")

    assert targets == [
        {"target": "@channel_a", "label": "@channel_a", "url": "https://t.me/channel_a"},
        {"target": "@group_b", "label": "@group_b", "url": "https://t.me/group_b"},
        {"target": -1001234567890, "label": "-1001234567890", "url": "https://t.me/+invite"},
    ]


@pytest.mark.asyncio
async def test_validate_lottery_subscribe_targets_requires_bot_admin_and_resolves_label():
    class _Bot:
        id = 777

        async def get_chat(self, chat_id):
            assert chat_id == "@channel_a"
            return SimpleNamespace(type="channel", title="频道A", username="channel_a")

        async def get_chat_member(self, chat_id, user_id):
            assert (chat_id, user_id) == ("@channel_a", 777)
            return SimpleNamespace(status="administrator")

    targets = parse_lottery_subscribe_targets("@channel_a")

    validated = await validate_lottery_subscribe_targets(SimpleNamespace(bot=_Bot()), targets)

    assert validated == [{"target": "@channel_a", "label": "频道A", "url": "https://t.me/channel_a"}]


@pytest.mark.asyncio
async def test_lottery_subscribe_membership_uses_per_lottery_targets_only():
    calls: list[tuple[object, int]] = []

    class _Bot:
        async def get_chat_member(self, chat_id, user_id):
            calls.append((chat_id, user_id))
            status = {"@channel_a": "member", "@channel_b": "left"}[chat_id]
            return SimpleNamespace(status=status)

    context = SimpleNamespace(bot=_Bot())
    targets = parse_lottery_subscribe_targets("@channel_a,https://t.me/channel_b")

    allowed, reason = await check_lottery_subscribe_membership(context, targets, 42, check_mode="all")

    assert allowed is False
    assert "本抽奖要求" in reason
    assert calls == [("@channel_a", 42), ("@channel_b", 42)]

    allowed, reason = await check_lottery_subscribe_membership(context, targets, 42, check_mode="any")

    assert allowed is True
    assert reason is None


@pytest.mark.asyncio
async def test_lottery_subscribe_membership_requires_target():
    context = SimpleNamespace(bot=SimpleNamespace())

    allowed, reason = await check_lottery_subscribe_membership(context, [], 42)

    assert allowed is False
    assert "缺少订阅目标" in reason


@pytest.mark.asyncio
async def test_lottery_subscribe_notice_auto_deletes_after_30_seconds(monkeypatch):
    scheduled: list[tuple[object, int, str]] = []
    sent_messages: list[dict] = []
    answers: list[tuple[str, bool]] = []
    lottery = SimpleNamespace(
        id=55,
        chat_id=-1001,
        lottery_type="subscribe",
        qualification_rules={
            "requires_lottery_subscribe": True,
            "subscribe_check_mode": "all",
            "subscribe_targets": [{"target": "@channel_a", "label": "频道A", "url": "https://t.me/channel_a"}],
        },
    )

    async def fake_get_lottery(session, lottery_id):
        return lottery

    def fake_schedule(context, message, seconds, *, name):
        scheduled.append((message, seconds, name))

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def rollback(self):
            return None

        async def commit(self):
            return None

    class _Db:
        def session_factory(self):
            return _Session()

    sent_notice = SimpleNamespace(message_id=900)

    class _Bot:
        async def get_chat_member(self, chat_id, user_id):
            assert (chat_id, user_id) == ("@channel_a", 42)
            return SimpleNamespace(status="left")

        async def send_message(self, **kwargs):
            sent_messages.append(kwargs)
            return sent_notice

    class _Query:
        message = SimpleNamespace(message_id=777)

        async def answer(self, text, show_alert=False):
            answers.append((text, show_alert))

    monkeypatch.setattr(lottery_participation_module, "get_lottery", fake_get_lottery)
    monkeypatch.setattr(lottery_participation_module, "_schedule_message_delete", fake_schedule)

    handler = lottery_participation_module.LotteryParticipationMixin()
    update = SimpleNamespace(
        callback_query=_Query(),
        effective_chat=SimpleNamespace(id=-1001, type="supergroup"),
        effective_user=SimpleNamespace(id=42),
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}), bot=_Bot())

    await handler.handle_join(update, context, lottery_id=55)

    assert answers and answers[0][1] is True
    assert sent_messages and sent_messages[0]["reply_markup"] is not None
    assert scheduled == [(sent_notice, 30, "activity.lottery_subscribe_notice_delete")]


@pytest.mark.asyncio
async def test_join_lottery_callback_respects_command_disable(monkeypatch):
    answers: list[tuple[str, bool]] = []
    joined: list[int] = []

    class _Session:
        async def commit(self):
            return None

    class _Db:
        def session_factory(self):
            return self

        async def __aenter__(self):
            return _Session()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Query:
        data = "join_lottery_55"

        async def answer(self, text: str | None = None, show_alert: bool = False):
            answers.append((text or "", show_alert))

    class _Handler:
        message_helper = SimpleNamespace(safe_edit=lambda *args, **kwargs: None)

        async def handle_join(self, update, context, lottery_id: int):
            joined.append(lottery_id)

    async def fake_enabled(session, chat_id: int, command_key: str):
        assert (chat_id, command_key) == (-1001, "lottery")
        return False

    monkeypatch.setattr(lottery_message_callbacks, "is_group_text_command_enabled", fake_enabled)

    update = SimpleNamespace(
        callback_query=_Query(),
        effective_chat=SimpleNamespace(id=-1001, type="supergroup"),
        effective_user=SimpleNamespace(id=42),
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await lottery_message_callbacks.join_lottery_callback_impl(update, context, handler=_Handler())

    assert answers == [("抽奖入口已关闭。", True)]
    assert joined == []


def test_lottery_join_success_message_mentions_user_and_count_without_preset():
    message = _format_join_success_message(
        user=SimpleNamespace(id=42, first_name="Alice <A>", last_name=None, username=None),
        lottery=SimpleNamespace(title="测试 <lottery>", max_participants=100),
        participant_count=7,
        full_draw_completed=False,
    )

    assert '<a href="tg://user?id=42">Alice &lt;A&gt;</a>' in message
    assert "抽奖：测试 &lt;lottery&gt;" in message
    assert "当前参与人数：7/100" in message
    assert "请留意原抽奖公告" in message
    assert "内定" not in message


def test_lottery_join_errors_explain_recovery_actions():
    lottery = SimpleNamespace(min_points=0, participation_cost=10, requirement_days=3)

    assert "继续邀请新成员" in _join_error_message("insufficient_invites", lottery=lottery, point_type_name="积分")
    assert "继续发言互动" in _join_error_message("insufficient_activity", lottery=lottery, point_type_name="积分")
    assert "无需手动参与" in _join_error_message("ranking_auto_selection", lottery=lottery, point_type_name="积分")


def test_manual_draw_keyboards_keep_target_chat_scope():
    participants = [SimpleNamespace(user_id=11, user_info=None)]
    prize_markup = manual_draw_prize_keyboard(-1001, 55, 0, prize_name="大奖吗", participants=participants)
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
        winners={"0": {"name": "Alice", "user_id": 99, "prize_name": prize_name}},
    )
    assert markup.inline_keyboard[0][0].text == f"✅ {prize_name} - Alice"


@pytest.mark.asyncio
async def test_lottery_create_start_routes_short_codes_to_config_flow(monkeypatch):
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

    await _handle_lottery_wizard_message(update, SimpleNamespace(), session, state=state, text="春季抽奖|好运连连")
    assert state.state_data["step"] == "prize_name"
    assert state.state_data["title"] == "春季抽奖"
    assert "本步只输入奖品名称，不要带中奖人数" in replies[-1]["text"]
    assert "完整示例：1USDT" in replies[-1]["text"]
    first_prompt_buttons = [
        button.text
        for row in replies[-1]["reply_markup"].inline_keyboard
        for button in row
    ]
    assert first_prompt_buttons == ["🔙 返回上级", "❌ 取消配置"]

    await _handle_lottery_wizard_message(update, SimpleNamespace(), session, state=state, text="1USDT")
    assert state.state_data["step"] == "prize_quantity"
    assert "本步只输入「1USDT」的中奖人数/份数，不要再输入奖品名称" in replies[-1]["text"]
    assert "格式：正整数" in replies[-1]["text"]
    assert "完整示例：1" in replies[-1]["text"]

    await _handle_lottery_wizard_message(update, SimpleNamespace(), session, state=state, text="1")
    assert state.state_data["step"] == "prize_action"
    assert state.state_data["prizes"] == [{"name": "1USDT", "quantity": 1, "points_reward": 0}]
    assert "如果还有别的奖品，点击“添加下一个奖品”" in replies[-1]["text"]
    assert "这里不用发送文字" in replies[-1]["text"]
    assert replies[-1]["reply_markup"] is not None

    state.state_data["step"] = "draw_param"
    await _handle_lottery_wizard_message(update, SimpleNamespace(), session, state=state, text="100")
    assert state.state_data["step"] == "preset_confirm"
    assert "内定中奖人：未设置" in replies[-1]["text"]
    assert replies[-1]["reply_markup"] is not None


@pytest.mark.asyncio
async def test_subscribe_lottery_wizard_prompts_prize_before_subscribe_target(monkeypatch):
    replies: list[dict[str, object]] = []
    state = SimpleNamespace(
        state_data={
            "step": "title",
            "target_chat_id": -1001,
            "lottery_type": "subscribe",
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

    async def fake_validate_lottery_subscribe_targets(context, targets):
        return targets

    monkeypatch.setattr(
        lottery_creation_module,
        "validate_lottery_subscribe_targets",
        fake_validate_lottery_subscribe_targets,
    )

    update = SimpleNamespace(effective_message=_Message())
    session = _Session()

    await _handle_lottery_wizard_message(update, SimpleNamespace(), session, state=state, text="关注后抽奖")
    assert state.state_data["step"] == "prize_name"
    assert "本步只输入奖品名称，不要带中奖人数" in replies[-1]["text"]
    assert "本步只输入本次抽奖要求关注的频道/群组" not in replies[-1]["text"]
    assert "下一步: 填写中奖人数/份数" in replies[-1]["text"]

    await _handle_lottery_wizard_message(update, SimpleNamespace(), session, state=state, text="1USDT")
    await _handle_lottery_wizard_message(update, SimpleNamespace(), session, state=state, text="1")
    state.state_data["step"] = "draw_param"
    await _handle_lottery_wizard_message(update, SimpleNamespace(), session, state=state, text="100")

    assert state.state_data["step"] == "subscribe_targets"
    assert "本步只输入本次抽奖要求关注的频道/群组" in replies[-1]["text"]
    assert "下一步: 确认配置并发布" in replies[-1]["text"]

    await _handle_lottery_wizard_message(update, SimpleNamespace(), session, state=state, text="@channel_a")

    assert state.state_data["step"] == "preset_confirm"
    assert state.state_data["subscribe_targets"] == [
        {"target": "@channel_a", "label": "@channel_a", "url": "https://t.me/channel_a"}
    ]
    assert "📣 强制订阅抽奖" in replies[-1]["text"]
    assert "订阅目标：@channel_a" in replies[-1]["text"]


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

    await _handle_lottery_wizard_message(update, SimpleNamespace(), session, state=state, text="二等奖")
    await _handle_lottery_wizard_message(update, SimpleNamespace(), session, state=state, text="2")

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
    await _reply_next_prompt(update, _Session(), state, data=state.state_data, next_step="draw_param")

    prompt = replies[0]
    assert "格式：YYYY-MM-DD HH:MM" in prompt["text"]
    assert "完整示例：<code>" in prompt["text"]
    assert prompt["kwargs"]["parse_mode"] == "HTML"


@pytest.mark.asyncio
async def test_lottery_wizard_commits_next_step_before_sending_prompt():
    events: list[tuple[str, int | None]] = []

    class _Session:
        commits = 0

        async def commit(self):
            self.commits += 1
            events.append(("commit", self.commits))

    session = _Session()
    state = SimpleNamespace(
        state_data={
            "step": "prize_name",
            "target_chat_id": -1001,
            "lottery_type": "common",
            "selection_mode": "threshold_random",
            "draw_trigger": "full_participants",
            "title": "测试抽奖",
            "qualification_window_days": 7,
            "prizes": [],
            "preset_winner_ids": [],
        }
    )

    class _Message:
        async def reply_text(self, text, **kwargs):
            events.append(("reply", session.commits))
            raise NetworkError("httpx.ConnectError")

    update = SimpleNamespace(effective_message=_Message())
    data = dict(state.state_data)
    data["pending_prize_name"] = "1USDT"

    with pytest.raises(NetworkError):
        await _reply_next_prompt(update, session, state, data=data, next_step="prize_quantity")

    assert events == [("commit", 1), ("reply", 1)]
    assert state.state_data["step"] == "prize_quantity"
    assert state.state_data["pending_prize_name"] == "1USDT"


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
        state=state,
        text="123,456",
    )

    assert any("内定中奖人数不能超过中奖人数" in text for text in replies)
    assert state.state_data["preset_winner_ids"] == []


@pytest.mark.asyncio
async def test_lottery_wizard_rejects_duplicate_prize_name():
    replies: list[str] = []
    state = SimpleNamespace(
        state_data={
            "step": "prize_name",
            "target_chat_id": -1001,
            "lottery_type": "common",
            "selection_mode": "threshold_random",
            "draw_trigger": "full_participants",
            "title": "抽奖",
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
        state=state,
        text="1USDT",
    )

    assert any("奖品名称不能重复：1USDT" in text for text in replies)
    assert state.state_data["step"] == "prize_name"


@pytest.mark.asyncio
async def test_lottery_wizard_accepts_assigned_preset_winner(monkeypatch):
    replies: list[dict[str, object]] = []
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
            "prizes": [{"name": "一等奖", "quantity": 1, "points_reward": 0}, {"name": "二等奖", "quantity": 1, "points_reward": 0}],
            "preset_winner_ids": [],
        }
    )

    class _Message:
        async def reply_text(self, text, reply_markup=None, **kwargs):
            replies.append({"text": text, "reply_markup": reply_markup})

    class _Session:
        async def commit(self):
            return None

    async def fake_resolve_username(session, context, username):
        return 67890

    monkeypatch.setattr(lottery_creation_module, "_resolve_username_to_user_id", fake_resolve_username)

    await _handle_lottery_wizard_message(
        SimpleNamespace(effective_message=_Message()),
        SimpleNamespace(bot=None),
        _Session(),
        state=state,
        text="一等奖: 12345\n二等奖: @alice",
    )

    assert state.state_data["step"] == "preset_confirm"
    assert state.state_data["preset_winner_ids"] == [12345, 67890]
    assert state.state_data["preset_winner_assignments"] == [
        {"user_id": 12345, "prize_name": "一等奖"},
        {"user_id": 67890, "prize_name": "二等奖"},
    ]
    assert "• 一等奖 × 1（内定：12345）" in replies[-1]["text"]
    assert "• 二等奖 × 1（内定：67890）" in replies[-1]["text"]
    assert "内定中奖人：12345（一等奖）, 67890（二等奖）" in replies[-1]["text"]


@pytest.mark.asyncio
async def test_lottery_wizard_requires_prize_assignment_for_multiple_prizes():
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
            "prizes": [{"name": "一等奖", "quantity": 1, "points_reward": 0}, {"name": "二等奖", "quantity": 1, "points_reward": 0}],
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
        SimpleNamespace(bot=None),
        _Session(),
        state=state,
        text="@yangyuyan",
    )

    assert any("多个奖品时，请逐个奖品设置内定中奖人" in text for text in replies)
    assert any("奖品名称: 随机" in text for text in replies)
    assert state.state_data["step"] == "preset_winners"
    assert state.state_data["preset_winner_ids"] == []


@pytest.mark.asyncio
async def test_lottery_wizard_rejects_malformed_assigned_preset_winner():
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
        SimpleNamespace(bot=None),
        _Session(),
        state=state,
        text="1ustd @yangyuyan",
    )

    assert any("内定中奖奖品不存在：1ustd" in text for text in replies)
    assert any("奖品名称: 用户" in text for text in replies)
    assert state.state_data["step"] == "preset_winners"
    assert state.state_data["preset_winner_ids"] == []


@pytest.mark.asyncio
async def test_lottery_wizard_requires_colon_for_assigned_preset_winner():
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
        SimpleNamespace(bot=None),
        _Session(),
        state=state,
        text="1USDT @yangyuyan",
    )

    assert any("指定奖品请使用格式：1USDT: 用户" in text for text in replies)
    assert state.state_data["step"] == "preset_winners"
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
        value="@alice",
    )

    assert ids == [789]


@pytest.mark.asyncio
async def test_lottery_wizard_resolves_preset_text_mention_entity():
    entity = SimpleNamespace(type="text_mention", user=SimpleNamespace(id=321))

    ids = await _parse_preset_winner_ids_from_message(
        SimpleNamespace(effective_message=SimpleNamespace(text="Alice", entities=[entity])),
        SimpleNamespace(bot=None),
        SimpleNamespace(),
        value="Alice",
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
            value="@missinguser",
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
                "内定中奖人:",
                "一等奖: 12345",
                "二等奖: 67890",
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
    assert config.preset_winner_assignments == [
        {"user_id": 12345, "prize_name": "一等奖"},
        {"user_id": 67890, "prize_name": "二等奖"},
    ]


def test_parse_lottery_config_requires_prize_assignment_for_multiple_prizes():
    with pytest.raises(ValueError, match="多个奖品时，请逐个奖品设置内定中奖人"):
        parse_lottery_config_text(
            "\n".join(
                [
                    "多奖品抽奖",
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


def test_parse_lottery_config_accepts_preset_winner_prize_assignments():
    config = parse_lottery_config_text(
        "\n".join(
            [
                "指定奖品抽奖",
                "开奖时间: 2099-12-31 20:00",
                "最低积分: 0",
                "参与费用: 0",
                "最大人数: 50",
                "入群天数: 0",
                "内定中奖人:",
                "一等奖: 12345",
                "二等奖: 67890",
                "奖品:",
                "一等奖,1",
                "二等奖,1",
            ]
        )
    )

    assert config.preset_winner_ids == [12345, 67890]
    assert config.preset_winner_assignments == [
        {"user_id": 12345, "prize_name": "一等奖"},
        {"user_id": 67890, "prize_name": "二等奖"},
    ]


def test_parse_lottery_config_rejects_duplicate_prize_names():
    with pytest.raises(ValueError, match="奖品名称不能重复：一等奖"):
        parse_lottery_config_text(
            "\n".join(
                [
                    "重复奖品抽奖",
                    "开奖时间: 2099-12-31 20:00",
                    "最低积分: 0",
                    "参与费用: 0",
                    "最大人数: 50",
                    "入群天数: 0",
                    "奖品:",
                    "一等奖,1",
                    "一等奖,1",
                ]
            )
        )


def test_parse_lottery_config_rejects_malformed_assigned_preset_winner():
    with pytest.raises(ValueError, match="内定中奖奖品不存在：1ustd"):
        parse_lottery_config_text(
            "\n".join(
                [
                    "指定奖品抽奖",
                    "开奖时间: 2099-12-31 20:00",
                    "最低积分: 0",
                    "参与费用: 0",
                    "最大人数: 50",
                    "入群天数: 0",
                    "内定中奖人: 1ustd @yangyuyan",
                    "奖品:",
                    "1USDT,1",
                ]
            ),
            allow_unresolved_winner_refs=True,
        )


def test_parse_lottery_config_requires_colon_for_assigned_preset_winner():
    with pytest.raises(ValueError, match="指定奖品请使用格式：1USDT: 用户"):
        parse_lottery_config_text(
            "\n".join(
                [
                    "指定奖品抽奖",
                    "开奖时间: 2099-12-31 20:00",
                    "最低积分: 0",
                    "参与费用: 0",
                    "最大人数: 50",
                    "入群天数: 0",
                    "内定中奖人: 1USDT @yangyuyan",
                    "奖品:",
                    "1USDT,1",
                ]
            ),
            allow_unresolved_winner_refs=True,
        )


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
    users = {123: SimpleNamespace(id=123, first_name="Alice & Bob", last_name=None, username=None)}

    announcement = lottery_service_drawing.generate_lottery_announcement(lottery, winners, users)

    assert "【A&lt;B】" in announcement
    assert "1&lt;USDT&gt;" in announcement
    assert '<a href="tg://user?id=123">Alice &amp; Bob</a>' in announcement


def test_lottery_result_announcement_mentions_winner_even_without_user_record():
    lottery = SimpleNamespace(lottery_type="common", title="抽奖")
    winners = [SimpleNamespace(user_id=456, prize_name="1USDT", points_reward=0)]

    announcement = lottery_service_drawing.generate_lottery_announcement(lottery, winners, {})

    assert '<a href="tg://user?id=456">用户456</a>' in announcement


def test_lottery_result_announcement_supports_tg_user_name_fields():
    lottery = SimpleNamespace(lottery_type="common", title="抽奖")
    winners = [SimpleNamespace(user_id=789, prize_name="1USDT", points_reward=0)]
    users = {
        789: TgUser(
            id=789,
            first_name="Alice",
            last_name="Bob",
            username=None,
        )
    }

    announcement = lottery_service_drawing.generate_lottery_announcement(lottery, winners, users)

    assert '<a href="tg://user?id=789">Alice Bob</a>' in announcement


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

    result_text = _format_draw_result_with_close_notice("开奖结果", participant_count=7)
    assert result_text.startswith("⏰ 抽奖已结束，已停止参与。")
    assert "本次参与人数：7" in result_text
    no_participants = _format_no_participants_announcement(lottery, participant_count=0)
    assert "抽奖已结束，已停止参与" in no_participants
    assert "本次参与人数：0" in no_participants
    assert "抽奖【A&lt;B】开奖结果" in no_participants
    assert "调整门槛后重新发起" in no_participants


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
async def test_lottery_auto_draw_falls_back_to_direct_send_and_completes(monkeypatch):
    now = dt.datetime.now(dt.timezone.utc)
    lottery = SimpleNamespace(
        id=55,
        chat_id=-1001,
        message_id=777,
        status="pending",
        draw_time=now - dt.timedelta(minutes=1),
        title="自动开奖",
        qualification_rules={"draw_trigger": "time_deadline"},
    )
    direct_calls: list[dict] = []

    async def fake_lock_pending_lottery(session, lottery_model, lottery_id):
        return lottery

    async def fake_send_lottery_message(app, lottery_obj, text):
        raise NetworkError("reply failed")

    async def fake_draw(session, lottery_obj):
        return []

    class _CountResult:
        def scalar(self):
            return 3

    class _Session:
        def __init__(self):
            self.commits = 0
            self.rollbacks = 0

        async def execute(self, stmt):
            return _CountResult()

        async def commit(self):
            self.commits += 1

        async def rollback(self):
            self.rollbacks += 1

    class _Bot:
        async def send_message(self, **kwargs):
            direct_calls.append(kwargs)
            return SimpleNamespace(message_id=99)

    monkeypatch.setattr(lottery_task_module, "_lock_pending_lottery", fake_lock_pending_lottery)
    monkeypatch.setattr(lottery_task_module, "_send_lottery_message", fake_send_lottery_message)
    session = _Session()

    await LotteryTask()._draw_due_lottery(
        app=SimpleNamespace(bot=_Bot()),
        session=session,
        lottery=lottery,
        now=now,
        perform_random_draw=fake_draw,
        generate_lottery_announcement=lambda lottery_obj, winners, users: "result",
        distribute_lottery_rewards=lambda session, lottery_obj, winners: None,
        lottery_model=SimpleNamespace,
        user_model=SimpleNamespace,
    )

    assert direct_calls == [
        {
            "chat_id": -1001,
            "text": _format_no_participants_announcement(lottery, participant_count=3),
            "parse_mode": "HTML",
            "reply_markup": None,
        }
    ]
    assert lottery.status == "completed"
    assert session.commits == 1
    assert session.rollbacks == 0


@pytest.mark.asyncio
async def test_lottery_auto_draw_keeps_pending_when_all_announcement_sends_fail(monkeypatch):
    now = dt.datetime.now(dt.timezone.utc)
    lottery = SimpleNamespace(
        id=56,
        chat_id=-1001,
        message_id=777,
        status="pending",
        draw_time=now - dt.timedelta(minutes=1),
        title="自动开奖",
        qualification_rules={"draw_trigger": "time_deadline"},
    )

    async def fake_lock_pending_lottery(session, lottery_model, lottery_id):
        return lottery

    async def fake_send_lottery_message(app, lottery_obj, text):
        raise NetworkError("reply failed")

    async def fake_draw(session, lottery_obj):
        return []

    class _CountResult:
        def scalar(self):
            return 0

    class _Session:
        def __init__(self):
            self.commits = 0
            self.rollbacks = 0

        async def execute(self, stmt):
            return _CountResult()

        async def commit(self):
            self.commits += 1

        async def rollback(self):
            self.rollbacks += 1

    class _Bot:
        async def send_message(self, **kwargs):
            raise NetworkError("direct failed")

    monkeypatch.setattr(lottery_task_module, "_lock_pending_lottery", fake_lock_pending_lottery)
    monkeypatch.setattr(lottery_task_module, "_send_lottery_message", fake_send_lottery_message)
    session = _Session()

    await LotteryTask()._draw_due_lottery(
        app=SimpleNamespace(bot=_Bot()),
        session=session,
        lottery=lottery,
        now=now,
        perform_random_draw=fake_draw,
        generate_lottery_announcement=lambda lottery_obj, winners, users: "result",
        distribute_lottery_rewards=lambda session, lottery_obj, winners: None,
        lottery_model=SimpleNamespace,
        user_model=SimpleNamespace,
    )

    assert lottery.status == "pending"
    assert session.commits == 0
    assert session.rollbacks == 1


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

    result = await lottery_service_participation.join_lottery(session, 55, 123, points_balance=0)

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
async def test_perform_random_draw_honors_assigned_preset_prize(monkeypatch):
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
        id=58,
        chat_id=-1001,
        lottery_type="common",
        qualification_rules={
            "preset_winner_ids": [111],
            "preset_winner_assignments": [{"user_id": 111, "prize_name": "二等奖"}],
        },
        prizes=[{"name": "一等奖", "quantity": 1}, {"name": "二等奖", "quantity": 1}],
    )
    session = _Session()
    monkeypatch.setattr(lottery_service_drawing, "get_lottery_participants", fake_get_lottery_participants)
    monkeypatch.setattr(lottery_service_drawing.random, "shuffle", fake_shuffle)

    winners = await lottery_service_drawing.perform_random_draw(session, lottery)

    assert [(winner.user_id, winner.prize_name) for winner in winners] == [(111, "二等奖"), (333, "一等奖")]


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


@pytest.mark.asyncio
async def test_perform_random_draw_filters_preset_and_participants_by_eligible_users(monkeypatch):
    async def fake_get_lottery_participants(session, lottery_id: int):
        return [SimpleNamespace(user_id=222, points_balance=0), SimpleNamespace(user_id=333, points_balance=0)]

    def fake_shuffle(items):
        return None

    class _Session:
        def __init__(self):
            self.added = []

        def add(self, entity):
            self.added.append(entity)

        async def flush(self):
            return None

    lottery = SimpleNamespace(
        id=57,
        chat_id=-1001,
        lottery_type="common",
        qualification_rules={"preset_winner_ids": [111]},
        prizes=[{"name": "一等奖", "quantity": 1}, {"name": "二等奖", "quantity": 1}],
    )
    monkeypatch.setattr(lottery_service_drawing, "get_lottery_participants", fake_get_lottery_participants)
    monkeypatch.setattr(lottery_service_drawing.random, "shuffle", fake_shuffle)

    winners = await lottery_service_drawing.perform_random_draw(_Session(), lottery, eligible_user_ids={333})

    assert [(winner.user_id, winner.prize_name) for winner in winners] == [(333, "一等奖")]
