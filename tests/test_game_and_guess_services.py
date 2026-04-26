from __future__ import annotations

import datetime as dt
from decimal import Decimal
from types import SimpleNamespace

import pytest

from backend.features.activity import game_panels, guess_handler
from backend.features.admin import admin_handler
from backend.shared.services.base import ValidationError
from backend.shared.callback_parser import CallbackParser
from backend.features.activity.services import game_blackjack
from backend.features.activity.services.game_service import (
    classify_k3_result,
    format_blackjack_help,
    format_k3_help,
    is_k3_round_joinable,
    k3_guess_label,
    parse_blackjack_bet,
    parse_k3_command,
    parse_ratio as parse_game_ratio,
    validate_hhmm,
    format_game_menu_text,
    format_blackjack_round_text,
)
from backend.features.activity.services.guess_service import format_event_preview, parse_deadline, parse_options, parse_ratio as parse_guess_ratio
from backend.features.activity.services.guess_service_runtime import build_settlement_plan
from backend.features.admin.activity.guess_input import handle_guess_admin_input


def _guess_bet(user_id: int, option_key: str, bet_points: int):
    return SimpleNamespace(user_id=user_id, option_key=option_key, bet_points=bet_points)


class _GuessInputSession:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class _GuessInputMessage:
    def __init__(self, *, photo=None, document=None) -> None:
        self.photo = photo or []
        self.document = document
        self.replies: list[str] = []

    async def reply_text(self, text: str) -> None:
        self.replies.append(text)


class _PanelSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self) -> None:
        return None

    async def execute(self, stmt):
        return SimpleNamespace(scalar=lambda: 0)


@pytest.mark.asyncio
async def test_guess_reserved_sign_keyword_does_not_consume_sign_text():
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-1001, type="supergroup"),
        effective_user=SimpleNamespace(id=42),
        effective_message=SimpleNamespace(message_id=9, text="签到", caption=None),
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": None}))

    handled = await guess_handler.guess_message_handler(update, context)

    assert handled is False


class _PanelDb:
    def __init__(self) -> None:
        self.session_factory = lambda: _PanelSession()


class _GuessPublishSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class _GuessPublishSessionContext:
    def __init__(self, session: _GuessPublishSession) -> None:
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _GuessPublishDb:
    def __init__(self, session: _GuessPublishSession) -> None:
        self.session = session

    def session_factory(self):
        return _GuessPublishSessionContext(self.session)


class _GuessPublishBot:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_message(self, **kwargs):
        self.sent.append(kwargs)
        return SimpleNamespace(message_id=99)


class _FlushSession:
    def __init__(self) -> None:
        self.flushes = 0

    async def flush(self) -> None:
        self.flushes += 1


def test_game_ratio_parsing():
    assert parse_game_ratio("0.1") == "0.1"
    with pytest.raises(ValidationError):
        parse_game_ratio("1.5")


def test_game_time_validation():
    assert validate_hhmm("23:05") == "23:05"
    with pytest.raises(ValidationError):
        validate_hhmm("25:00")


def test_k3_parser_accepts_chinese_alias_and_extended_options():
    assert parse_k3_command("快三 对子 100") == ("对子", 100)
    assert parse_k3_command("快3 半顺号 50") == ("半顺号", 50)
    assert k3_guess_label("豹子") == "豹子通杀"
    with pytest.raises(ValidationError):
        parse_k3_command("快三 大 501")
    with pytest.raises(ValidationError):
        parse_blackjack_bet("黑杰克 501")


def test_k3_result_classifies_extended_plays():
    assert set(classify_k3_result([1, 1, 2])["winning_keys"]) == {"small", "even", "pair"}
    assert set(classify_k3_result([1, 2, 3])["winning_keys"]) == {"small", "even", "straight"}
    assert set(classify_k3_result([1, 3, 5])["winning_keys"]) == {"small", "odd", "misc_six"}
    assert classify_k3_result([6, 6, 6])["winning_keys"] == ["triple"]


def test_k3_round_joinable_requires_future_deadline():
    now = dt.datetime(2026, 1, 1, 12, 0, tzinfo=dt.UTC)

    assert is_k3_round_joinable(SimpleNamespace(settle_at=now + dt.timedelta(seconds=1)), now)
    assert not is_k3_round_joinable(SimpleNamespace(settle_at=now), now)
    assert not is_k3_round_joinable(SimpleNamespace(settle_at=now - dt.timedelta(seconds=1)), now)
    assert not is_k3_round_joinable(SimpleNamespace(settle_at=None), now)


@pytest.mark.asyncio
async def test_blackjack_natural_beats_dealer_drawn_twenty_one(monkeypatch):
    point_changes: list[tuple[int, int, int, str]] = []

    async def fake_setting(session, chat_id: int):
        return SimpleNamespace(rake_ratio="0", rake_owner_user_id=None)

    async def fake_change_points(
        session,
        chat_id: int,
        user_id: int,
        amount: int,
        txn_type: str,
        reason: str | None = None,
    ):
        point_changes.append((chat_id, user_id, amount, reason or ""))
        return True, amount

    monkeypatch.setattr(game_blackjack, "get_or_create_setting", fake_setting)
    monkeypatch.setattr(game_blackjack, "change_points", fake_change_points)

    round_obj = SimpleNamespace(
        chat_id=-1001,
        status="player_turn",
        settle_at=dt.datetime.now(dt.UTC),
        result_data={
            "player_cards": [1, 10],
            "dealer_cards": [7, 7],
            "deck": [7],
            "points_chat_id": -1001,
        },
    )
    participant = SimpleNamespace(
        user_id=42,
        bet_points=100,
        status="active",
        payout_points=0,
        choice_data={"player_cards": [1, 10], "dealer_cards": [7, 7], "points_chat_id": -1001},
    )

    outcome = await game_blackjack.finalize_blackjack_round(_FlushSession(), round_obj, participant, "stand")

    assert participant.status == "won"
    assert participant.payout_points == 250
    assert "获得 250 积分" in outcome
    assert round_obj.result_data["dealer_cards"] == [7, 7]
    assert point_changes == [(-1001, 42, 250, "黑杰克获胜")]


@pytest.mark.asyncio
async def test_blackjack_dealer_natural_beats_player_non_natural_twenty_one(monkeypatch):
    point_changes: list[tuple[int, int, int, str]] = []

    async def fake_setting(session, chat_id: int):
        return SimpleNamespace(rake_ratio="0", rake_owner_user_id=None)

    async def fake_change_points(
        session,
        chat_id: int,
        user_id: int,
        amount: int,
        txn_type: str,
        reason: str | None = None,
    ):
        point_changes.append((chat_id, user_id, amount, reason or ""))
        return True, amount

    monkeypatch.setattr(game_blackjack, "get_or_create_setting", fake_setting)
    monkeypatch.setattr(game_blackjack, "change_points", fake_change_points)

    round_obj = SimpleNamespace(
        chat_id=-1001,
        status="player_turn",
        settle_at=dt.datetime.now(dt.UTC),
        result_data={
            "player_cards": [10, 5, 6],
            "dealer_cards": [1, 10],
            "deck": [],
            "points_chat_id": -1001,
        },
    )
    participant = SimpleNamespace(
        user_id=42,
        bet_points=100,
        status="active",
        payout_points=0,
        choice_data={"player_cards": [10, 5, 6], "dealer_cards": [1, 10], "points_chat_id": -1001},
    )

    outcome = await game_blackjack.finalize_blackjack_round(_FlushSession(), round_obj, participant, "stand")

    assert participant.status == "lost"
    assert participant.payout_points == 0
    assert outcome == "❌ 本局失败"
    assert point_changes == []


def test_group_game_help_hides_admin_rake_ratio():
    assert "抽水比例" not in format_k3_help(True, "0.1")
    assert "抽水比例" not in format_blackjack_help(True, "0.1")


@pytest.mark.asyncio
async def test_group_game_panels_show_user_tips_without_admin_rake(monkeypatch):
    async def fake_setting(session, chat_id: int):
        return SimpleNamespace(k3_enabled=True, blackjack_enabled=True, points_source_chat_id=None)

    async def fake_points_label(session, chat_id: int, points_source_chat_id):
        return "本群分"

    async def fake_active_k3_round(session, chat_id: int):
        return None

    monkeypatch.setattr(game_panels, "get_or_create_setting", fake_setting)
    monkeypatch.setattr(game_panels, "get_game_points_chat_label", fake_points_label)
    monkeypatch.setattr(game_panels, "get_active_k3_round", fake_active_k3_round)

    k3_text = await game_panels.build_k3_panel_text(_PanelDb(), -1001)
    blackjack_text = await game_panels.build_blackjack_panel_text(_PanelDb(), -1001)

    assert "选择对应的玩法按钮进行下注" in k3_text
    assert "└ 指令：快三规则 快三统计" in k3_text
    assert "选择对应的积分按钮进行下注" in blackjack_text
    assert "└ 指令：黑杰克规则 黑杰克统计" in blackjack_text
    assert "抽水比例" not in k3_text
    assert "抽水比例" not in blackjack_text


def test_guess_options_parser_accepts_lines():
    options = parse_options("1:红队\n2:蓝队")
    assert options == [{"key": "1", "label": "红队"}, {"key": "2", "label": "蓝队"}]


def test_guess_deadline_parser_accepts_minutes():
    target = parse_deadline("30")
    assert target > dt.datetime.now(dt.UTC)


def test_guess_ratio_parser_rejects_invalid():
    assert parse_guess_ratio("0.2") == "0.2"
    with pytest.raises(ValidationError):
        parse_guess_ratio("-0.1")


def test_guess_no_banker_split_rounds_up_per_winner():
    bets = [_guess_bet(user_id, "A", 1) for user_id in range(1, 11)]
    bets.append(_guess_bet(99, "B", 1))

    plan = build_settlement_plan(
        bets,
        winner_option="A",
        mode="no_banker",
        banker_user_id=None,
        public_pool=0,
        rake_ratio=Decimal("0"),
        rake_owner_user_id=None,
    )

    assert plan.loser_total == 1
    assert plan.winner_count == 10
    assert plan.system_subsidy == 9
    assert set(plan.winner_payouts.values()) == {2}


def test_guess_banker_mode_balances_losers_winners_and_rake_to_banker():
    bets = [_guess_bet(1, "A", 100), _guess_bet(2, "B", 100)]

    plan = build_settlement_plan(
        bets,
        winner_option="A",
        mode="banker",
        banker_user_id=9,
        public_pool=0,
        rake_ratio=Decimal("0.1"),
        rake_owner_user_id=88,
    )

    assert plan.winner_payouts == {1: 190}
    assert plan.rake_payouts == {}
    assert plan.banker_delta == 10


def test_guess_banker_mode_can_charge_banker_negative_for_winner_rights():
    bets = [_guess_bet(1, "A", 50)]

    plan = build_settlement_plan(
        bets,
        winner_option="A",
        mode="banker",
        banker_user_id=9,
        public_pool=20,
        rake_ratio=Decimal("0"),
        rake_owner_user_id=None,
    )

    assert plan.winner_payouts == {1: 120}
    assert plan.banker_delta == -70


def test_guess_banker_no_winner_does_not_credit_public_pool_to_banker():
    bets = [_guess_bet(2, "B", 30)]

    plan = build_settlement_plan(
        bets,
        winner_option="A",
        mode="banker",
        banker_user_id=9,
        public_pool=100,
        rake_ratio=Decimal("0"),
        rake_owner_user_id=None,
    )

    assert plan.winner_payouts == {}
    assert plan.banker_delta == 30


@pytest.mark.asyncio
async def test_guess_admin_title_input_saves_draft_and_refreshes_menu(monkeypatch):
    saved: list[tuple[int, int, str, dict]] = []
    cleared: list[tuple[int, int]] = []
    shown: list[dict] = []

    async def fake_clear_private_admin_state(session, *, target_chat_id: int, user_id: int) -> None:
        cleared.append((target_chat_id, user_id))

    async def fake_set_user_state(session, chat_id: int, user_id: int, state_type: str, state_data: dict):
        saved.append((chat_id, user_id, state_type, state_data))

    class _Admin:
        async def _show_guess_create_menu(self, update, context, target_chat_id: int, draft: dict) -> None:
            shown.append(dict(draft))

    monkeypatch.setattr("backend.features.admin.activity.guess_input.clear_private_admin_state", fake_clear_private_admin_state)
    monkeypatch.setattr("backend.features.admin.activity.guess_input.set_user_state", fake_set_user_state)
    monkeypatch.setattr("backend.features.admin.activity.guess_input.admin_handler_instance", lambda: _Admin())

    message = _GuessInputMessage()
    update = SimpleNamespace(effective_user=SimpleNamespace(id=42), effective_message=message)
    session = _GuessInputSession()
    state = SimpleNamespace(state_type="guess_wait_title", state_data={"target_chat_id": -1001})

    handled = await handle_guess_admin_input(update, SimpleNamespace(), session, state, "世界杯决赛", target_chat_id=-1001)

    assert handled is True
    assert cleared == [(-1001, 42)]
    assert saved == [(42, 42, "guess_wait_title", {"target_chat_id": -1001, "title": "世界杯决赛"})]
    assert shown == [{"target_chat_id": -1001, "title": "世界杯决赛"}]
    assert session.commits == 1
    assert message.replies == []


@pytest.mark.asyncio
async def test_guess_admin_cover_input_accepts_photo_and_image_document(monkeypatch):
    saved: list[dict] = []

    async def fake_clear_private_admin_state(session, *, target_chat_id: int, user_id: int) -> None:
        return None

    async def fake_set_user_state(session, chat_id: int, user_id: int, state_type: str, state_data: dict):
        saved.append(dict(state_data))

    class _Admin:
        async def _show_guess_create_menu(self, update, context, target_chat_id: int, draft: dict) -> None:
            return None

    monkeypatch.setattr("backend.features.admin.activity.guess_input.clear_private_admin_state", fake_clear_private_admin_state)
    monkeypatch.setattr("backend.features.admin.activity.guess_input.set_user_state", fake_set_user_state)
    monkeypatch.setattr("backend.features.admin.activity.guess_input.admin_handler_instance", lambda: _Admin())

    state = SimpleNamespace(state_type="guess_wait_cover", state_data={"target_chat_id": -1001, "title": "比赛"})

    photo_message = _GuessInputMessage(photo=[SimpleNamespace(file_id="small"), SimpleNamespace(file_id="large")])
    photo_update = SimpleNamespace(effective_user=SimpleNamespace(id=42), effective_message=photo_message)
    await handle_guess_admin_input(photo_update, SimpleNamespace(), _GuessInputSession(), state, "", target_chat_id=-1001)

    document_message = _GuessInputMessage(document=SimpleNamespace(file_id="doc-image", mime_type="image/png"))
    document_update = SimpleNamespace(effective_user=SimpleNamespace(id=42), effective_message=document_message)
    await handle_guess_admin_input(document_update, SimpleNamespace(), _GuessInputSession(), state, "", target_chat_id=-1001)

    assert saved[0]["cover_file_id"] == "large"
    assert saved[1]["cover_file_id"] == "doc-image"
    assert photo_message.replies == []
    assert document_message.replies == []


@pytest.mark.asyncio
async def test_guess_publish_uses_default_command_keyword(monkeypatch):
    created: list[dict] = []
    cleared: list[tuple[int, int]] = []
    shown: list[tuple[int, int]] = []
    answered: list[str] = []

    async def fake_get_user_state(session, chat_id: int, user_id: int):
        return SimpleNamespace(
            state_type="guess_wait_title",
            state_data={
                "target_chat_id": -1001,
                "title": "周末竞猜",
                "options": [{"key": "1", "label": "主胜"}, {"key": "2", "label": "客胜"}],
                "deadline_at": (dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)).isoformat(),
            },
        )

    async def fake_create_guess_event(session, chat_id: int, creator_user_id: int, draft: dict):
        created.append(dict(draft))
        return SimpleNamespace(id=7, announcement_message_id=None)

    async def fake_clear_private_admin_state(session, *, target_chat_id: int, user_id: int) -> None:
        cleared.append((target_chat_id, user_id))

    async def fake_show_guess_event_detail(update, context, chat_id: int, event_id: int) -> None:
        shown.append((chat_id, event_id))

    async def fake_answer(update, text: str, show_alert: bool = False):
        answered.append(text)

    monkeypatch.setattr("backend.features.admin.activity.guess.get_user_state", fake_get_user_state)
    monkeypatch.setattr("backend.features.admin.activity.guess.create_guess_event", fake_create_guess_event)
    monkeypatch.setattr("backend.features.admin.activity.guess.clear_private_admin_state", fake_clear_private_admin_state)
    monkeypatch.setattr("backend.features.admin.activity.guess.format_event_runtime", lambda event: "runtime text")
    monkeypatch.setattr("backend.features.admin.activity.guess.answer_callback_query_safely", fake_answer)
    monkeypatch.setattr(admin_handler._admin_handler, "_show_guess_event_detail", fake_show_guess_event_detail)

    session = _GuessPublishSession()
    bot = _GuessPublishBot()
    update = SimpleNamespace(effective_user=SimpleNamespace(id=42))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _GuessPublishDb(session)}), bot=bot)

    await admin_handler._admin_handler._handle_guess(
        update,
        context,
        -1001,
        CallbackParser.parse("guess:create:-1001:publish"),
    )

    assert created and created[0]["command_keyword"] == "竞猜"
    assert bot.sent == [{"chat_id": -1001, "text": "runtime text", "parse_mode": "Markdown"}]
    assert cleared == [(-1001, 42)]
    assert shown == [(-1001, 7)]
    assert answered == []
    assert session.commits == 1
    assert session.rollbacks == 0


def test_guess_preview_uses_waiting_placeholders():
    text = format_event_preview({})

    assert "⚽ 竞猜活动" in text
    assert "📮 活动名字: 【等待设置】" in text
    assert "🏞️ 封面设置: 【等待设置】" in text
    assert "📋 活动说明: 【等待设置】" in text
    assert "👾 本局庄家: 无庄" in text
    assert "🧧 公共奖池: 0" in text
    assert "📻 竞猜选项: 【等待设置】" in text
    assert "🔎 群内指令: 【等待设置】" in text
    assert "⏰ 截止时间: 【等待设置】" in text
    assert "🔗 重复下注: 禁止" in text
    assert "配置进度:" in text
    assert "必填完成: 0/3" in text
    assert "下一步: 预览无误后发布到群" in text


def test_formatters_include_icons():
    game_text = format_game_menu_text(
        "测试群",
        k3_enabled=True,
        blackjack_enabled=False,
        rake_ratio="0.1",
        rake_owner="@dealer",
        auto_schedule_enabled=True,
        auto_start_time="08:00",
        auto_stop_time="23:00",
        delete_mode="keep",
    )
    assert "🎮 游戏" in game_text
    assert "至少开启一个玩法" in game_text
    assert "到群里发送 快三/黑杰克" in game_text
    guess_preview = format_event_preview(
        {
            "title": "周末竞猜",
            "description": "猜胜负",
            "mode": "no_banker",
            "public_pool": 100,
            "command_keyword": "竞猜",
            "deadline_at": "23:00",
            "allow_repeat_bet": False,
            "options": [{"key": "1", "label": "主胜"}, {"key": "2", "label": "客胜"}],
        }
    )
    assert "⚽ 竞猜" in guess_preview
    assert "必填完成: 3/3" in guess_preview


def test_blackjack_round_text_guides_next_action_when_active():
    participant = SimpleNamespace(
        bet_points=100,
        choice_data={"player_cards": [10, 7], "dealer_cards": [6, 10]},
    )

    text = format_blackjack_round_text(participant)

    assert "要牌 / 停牌" in text
    assert "超时会自动停牌结算" in text
