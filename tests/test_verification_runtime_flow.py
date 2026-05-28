from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.verification import verification_callbacks, verification_handler, verification_messages
from backend.platform.scheduler.tasks import verification_timeout_task


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def commit(self):
        return None

    async def flush(self):
        return None

    async def get(self, model, pk):
        return None


class _Db:
    def __init__(self, session: _Session | None = None) -> None:
        self._session = session or _Session()

    def session_factory(self):
        return self._session


class _Bot:
    async def send_message(self, **kwargs):
        return None

    async def restrict_chat_member(self, **kwargs):
        return None


def _member(user_id: int = 99):
    return SimpleNamespace(
        id=user_id,
        username="newbie",
        first_name="New",
        last_name=None,
        language_code="zh-CN",
        mention_html=lambda: "<a>New</a>",
    )


def _join_update(member=None):
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=-100123, type="supergroup", title="测试群"),
        effective_message=SimpleNamespace(new_chat_members=[member or _member()]),
    )


def _settings(**overrides):
    defaults = {
        "welcome_enabled": False,
        "welcome_message": None,
        "language": "zh-CN",
        "verification_enabled": True,
        "verification_timeout_seconds": 60,
        "verification_mode": "button",
        "verification_restrict_can_send": False,
        "verification_timeout_action": "mute",
        "verification_mute_duration": 86400,
        "verification_direct_mute_duration": 0,
        "join_self_review_enabled": False,
        "invite_link_notify": False,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.mark.asyncio
async def test_burst_guard_stops_spam_and_verification(monkeypatch):
    recorded: list[tuple[int, int]] = []

    async def fake_get_chat_settings(session, chat_id: int):
        return _settings()

    async def fake_noop(*args, **kwargs):
        return None

    async def fail_send_for_mode(*args, **kwargs):
        raise AssertionError("burst guard should stop join welcome")

    async def fake_burst_guard(*args, **kwargs):
        return True

    async def fake_record_join(session, chat_id: int, count: int = 1):
        recorded.append((chat_id, count))

    async def fail_join_spam_guard(*args, **kwargs):
        raise AssertionError("burst guard should stop spam guard")

    async def fail_create_challenge(*args, **kwargs):
        raise AssertionError("burst guard should stop verification challenge creation")

    monkeypatch.setattr(verification_handler, "ensure_chat", fake_noop)
    monkeypatch.setattr(verification_handler, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(verification_handler, "ensure_user", fake_noop)
    monkeypatch.setattr(verification_handler, "_upsert_chat_member_join", fake_noop)
    monkeypatch.setattr(verification_handler, "record_group_join_event", fake_record_join)
    monkeypatch.setattr(verification_handler.WelcomeService, "send_for_mode", fail_send_for_mode)
    monkeypatch.setattr(verification_handler, "_handle_join_burst_guard", fake_burst_guard)
    monkeypatch.setattr(verification_handler, "_handle_join_spam_guard", fail_join_spam_guard)
    monkeypatch.setattr(verification_handler, "create_or_replace_challenge", fail_create_challenge)

    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}), bot=_Bot(), user_data={})

    await verification_handler.new_members_handler(_join_update(), context)

    assert recorded == [(-100123, 1)]


@pytest.mark.asyncio
async def test_verification_restrict_failure_does_not_send_challenge_prompt(monkeypatch):
    challenge = SimpleNamespace(token="token-1", solved=False, timeout_handled=False)

    async def fake_get_chat_settings(session, chat_id: int):
        return _settings(verification_mode="button")

    async def fake_noop(*args, **kwargs):
        return None

    async def fake_false(*args, **kwargs):
        return False

    async def fake_send_for_mode(*args, **kwargs):
        return False

    async def fake_create_challenge(*args, **kwargs):
        return challenge


    class _RestrictFailBot:
        def __init__(self) -> None:
            self.messages: list[dict] = []

        async def restrict_chat_member(self, **kwargs):
            raise RuntimeError("restrict denied")

        async def send_message(self, **kwargs):
            self.messages.append(kwargs)
            return None

    monkeypatch.setattr(verification_handler, "ensure_chat", fake_noop)
    monkeypatch.setattr(verification_handler, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(verification_handler, "ensure_user", fake_noop)
    monkeypatch.setattr(verification_handler, "_upsert_chat_member_join", fake_noop)
    monkeypatch.setattr(verification_handler, "record_group_join_event", fake_noop)
    monkeypatch.setattr(verification_handler, "_handle_join_burst_guard", fake_false)
    monkeypatch.setattr(verification_handler, "_handle_join_spam_guard", fake_false)
    monkeypatch.setattr(verification_handler, "_track_invite_for_member", fake_noop)
    monkeypatch.setattr(verification_handler.WelcomeService, "send_for_mode", fake_send_for_mode)
    monkeypatch.setattr(verification_handler, "create_or_replace_challenge", fake_create_challenge)

    bot = _RestrictFailBot()
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}), bot=bot, user_data={})

    await verification_handler.new_members_handler(_join_update(), context)

    assert challenge.solved is True
    assert challenge.timeout_handled is True
    assert bot.messages == []


@pytest.mark.asyncio
async def test_invite_notify_sends_for_new_invite_even_without_points_award(monkeypatch):
    link = SimpleNamespace(id=77, chat_id=-100123, created_by_user_id=555, member_count=0)

    class _LinkResult:
        def scalar_one_or_none(self):
            return link

    class _InviteSession(_Session):
        async def execute(self, stmt):
            return _LinkResult()

    sent: list[dict] = []

    class _InviteBot:
        async def send_message(self, **kwargs):
            sent.append(kwargs)

    async def fake_track_and_award_invite(session, **kwargs):
        return True, False, "invite_points_disabled"

    monkeypatch.setattr(verification_handler, "track_and_award_invite", fake_track_and_award_invite)

    context = SimpleNamespace(
        application=SimpleNamespace(
            bot_data={"invite_join_hints": {(-100123, 99): {"invite_link": "https://t.me/+demo"}}}
        ),
        bot=_InviteBot(),
        user_data={},
    )
    settings = _settings(invite_link_notify=True)

    await verification_handler._track_invite_for_member(
        context,
        _InviteSession(),
        SimpleNamespace(id=-100123, title="测试群"),
        _member(),
        settings,
    )

    assert link.member_count == 1
    assert sent == [
        {
            "chat_id": 555,
            "text": "🎉 恭喜！您邀请的 New 加入了群组 测试群",
        }
    ]


@pytest.mark.asyncio
async def test_spam_guard_stops_self_review_when_verification_disabled(monkeypatch):
    tracked: list[int] = []

    async def fake_get_chat_settings(session, chat_id: int):
        return _settings(verification_enabled=False, join_self_review_enabled=True)

    async def fake_noop(*args, **kwargs):
        return None

    async def fail_send_for_mode(*args, **kwargs):
        raise AssertionError("spam guard should stop join welcome")

    async def fake_burst_guard(*args, **kwargs):
        return False

    async def fake_join_spam_guard(*args, **kwargs):
        return True

    async def fake_track(context, session, chat, member, settings):
        tracked.append(member.id)

    async def fail_self_review(*args, **kwargs):
        raise AssertionError("spam guard should stop self review")

    monkeypatch.setattr(verification_handler, "ensure_chat", fake_noop)
    monkeypatch.setattr(verification_handler, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(verification_handler, "ensure_user", fake_noop)
    monkeypatch.setattr(verification_handler, "_upsert_chat_member_join", fake_noop)
    monkeypatch.setattr(verification_handler, "record_group_join_event", fake_noop)
    monkeypatch.setattr(verification_handler.WelcomeService, "send_for_mode", fail_send_for_mode)
    monkeypatch.setattr(verification_handler, "_handle_join_burst_guard", fake_burst_guard)
    monkeypatch.setattr(verification_handler, "_handle_join_spam_guard", fake_join_spam_guard)
    monkeypatch.setattr(verification_handler, "_track_invite_for_member", fake_track)
    monkeypatch.setattr(verification_handler, "_start_self_review_if_needed", fail_self_review)

    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}), bot=_Bot(), user_data={})

    await verification_handler.new_members_handler(_join_update(), context)

    assert tracked == []


@pytest.mark.asyncio
async def test_agreement_decline_marks_challenge_and_applies_punishment(monkeypatch):
    marked: list[tuple[int, int]] = []
    punished: list[tuple[int, int, str | None]] = []
    edited: list[str] = []

    settings = _settings(verification_timeout_action="kick")
    challenge = SimpleNamespace(chat_id=-100123, user_id=99)

    async def fake_get_chat_settings(session, chat_id: int):
        return settings

    async def fake_get_challenge_by_token(session, token: str):
        return challenge

    async def fake_mark(session, chat_id: int, user_id: int):
        marked.append((chat_id, user_id))

    async def fake_punish(context, chat_id: int, user_id: int, settings, *, action=None, mute_seconds=None):
        punished.append((chat_id, user_id, action))
        return "kick"

    class _Query:
        data = "vfy:token-1:decline"

        async def answer(self):
            return None

        async def edit_message_text(self, text: str):
            edited.append(text)

    monkeypatch.setattr(verification_callbacks, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(verification_callbacks, "get_challenge_by_token", fake_get_challenge_by_token)
    monkeypatch.setattr(verification_callbacks, "mark_challenge_released", fake_mark)
    monkeypatch.setattr(verification_callbacks, "apply_verification_punishment", fake_punish)

    update = SimpleNamespace(
        callback_query=_Query(),
        effective_chat=SimpleNamespace(id=-100123),
        effective_user=SimpleNamespace(id=99),
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await verification_callbacks.verify_callback(update, context)

    assert marked == [(-100123, 99)]
    assert punished == [(-100123, 99, None)]
    assert edited == ["❌ 已选择不同意，已按本群配置处理。"]


@pytest.mark.asyncio
async def test_agreement_decline_keeps_challenge_when_punishment_fails(monkeypatch):
    marked: list[tuple[int, int]] = []
    answers: list[tuple[str | None, bool | None]] = []
    settings = _settings(verification_timeout_action="kick")
    challenge = SimpleNamespace(chat_id=-100123, user_id=99)

    async def fake_get_chat_settings(session, chat_id: int):
        return settings

    async def fake_get_challenge_by_token(session, token: str):
        return challenge

    async def fake_mark(session, chat_id: int, user_id: int):
        marked.append((chat_id, user_id))

    async def fail_punish(*args, **kwargs):
        raise RuntimeError("missing permission")

    class _Query:
        data = "vfy:token-1:decline"

        async def answer(self, text=None, show_alert=None):
            answers.append((text, show_alert))

        async def edit_message_text(self, text: str):
            raise AssertionError("message should not be edited when punishment fails")

    monkeypatch.setattr(verification_callbacks, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(verification_callbacks, "get_challenge_by_token", fake_get_challenge_by_token)
    monkeypatch.setattr(verification_callbacks, "mark_challenge_released", fake_mark)
    monkeypatch.setattr(verification_callbacks, "apply_verification_punishment", fail_punish)

    update = SimpleNamespace(
        callback_query=_Query(),
        effective_chat=SimpleNamespace(id=-100123),
        effective_user=SimpleNamespace(id=99),
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await verification_callbacks.verify_callback(update, context)

    assert marked == []
    assert answers == [("处理失败，请检查机器人禁言/踢人权限", True)]


@pytest.mark.asyncio
async def test_math_wrong_answer_applies_configured_punishment(monkeypatch):
    marked: list[tuple[int, int]] = []
    punished: list[str | None] = []
    replies: list[str] = []

    settings = _settings(verification_mode="math", verification_wrong_action="kick")
    challenge = SimpleNamespace(question="1 + 1 = ?", solved=False)

    async def fake_get_chat_settings(session, chat_id: int):
        return settings

    async def fake_get_challenge(session, chat_id: int, user_id: int):
        return challenge

    async def fake_solve_by_answer(session, chat_id: int, user_id: int, answer: str):
        return None

    async def fake_mark(session, chat_id: int, user_id: int):
        marked.append((chat_id, user_id))

    async def fake_punish(context, chat_id: int, user_id: int, settings, *, action=None, mute_seconds=None):
        punished.append(action)
        return "kick"

    async def fake_manual_unmute(*args, **kwargs):
        return False

    message = SimpleNamespace(
        text="3",
        reply_text=lambda text: _async_append(replies, text),
    )
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-100123, type="supergroup"),
        effective_user=SimpleNamespace(id=99),
        effective_message=message,
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}), bot=_Bot())

    monkeypatch.setattr(verification_messages, "try_admin_manual_unmute", fake_manual_unmute)
    monkeypatch.setattr(verification_messages, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(verification_messages, "get_challenge", fake_get_challenge)
    monkeypatch.setattr(verification_messages, "solve_by_answer", fake_solve_by_answer)
    monkeypatch.setattr(verification_messages, "mark_challenge_released", fake_mark)
    monkeypatch.setattr(verification_messages, "apply_verification_punishment", fake_punish)

    await verification_messages.verify_message_handler(update, context)

    assert marked == [(-100123, 99)]
    assert punished == ["kick"]
    assert replies == ["❌ 答案错误，已按本群配置处理。"]


@pytest.mark.asyncio
async def test_math_wrong_answer_keeps_challenge_when_punishment_fails(monkeypatch):
    marked: list[tuple[int, int]] = []
    replies: list[str] = []
    settings = _settings(verification_mode="math", verification_wrong_action="kick")
    challenge = SimpleNamespace(question="1 + 1 = ?", solved=False)

    async def fake_get_chat_settings(session, chat_id: int):
        return settings

    async def fake_get_challenge(session, chat_id: int, user_id: int):
        return challenge

    async def fake_solve_by_answer(session, chat_id: int, user_id: int, answer: str):
        return None

    async def fake_mark(session, chat_id: int, user_id: int):
        marked.append((chat_id, user_id))

    async def fail_punish(*args, **kwargs):
        raise RuntimeError("missing permission")

    async def fake_manual_unmute(*args, **kwargs):
        return False

    message = SimpleNamespace(
        text="3",
        reply_text=lambda text: _async_append(replies, text),
    )
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-100123, type="supergroup"),
        effective_user=SimpleNamespace(id=99),
        effective_message=message,
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}), bot=_Bot())

    monkeypatch.setattr(verification_messages, "try_admin_manual_unmute", fake_manual_unmute)
    monkeypatch.setattr(verification_messages, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(verification_messages, "get_challenge", fake_get_challenge)
    monkeypatch.setattr(verification_messages, "solve_by_answer", fake_solve_by_answer)
    monkeypatch.setattr(verification_messages, "mark_challenge_released", fake_mark)
    monkeypatch.setattr(verification_messages, "apply_verification_punishment", fail_punish)

    await verification_messages.verify_message_handler(update, context)

    assert marked == []
    assert replies == ["❌ 处理失败，请检查机器人禁言/踢人权限。"]


@pytest.mark.asyncio
async def test_timeout_none_unrestricts_and_releases_challenge(monkeypatch):
    challenge = SimpleNamespace(
        verification_type="math",
        question="1 + 1 = ?",
        chat_id=-100123,
        user_id=99,
        solved=False,
        timeout_handled=False,
    )
    settings = _settings(verification_timeout_action="none")
    restrict_calls: list[dict] = []

    async def fake_expired(session):
        return [challenge]

    async def fake_get_chat_settings(session, chat_id: int):
        return settings

    class _BotWithRestrict:
        async def restrict_chat_member(self, **kwargs):
            restrict_calls.append(kwargs)

    monkeypatch.setattr(verification_timeout_task, "get_expired_challenges", fake_expired)
    monkeypatch.setattr(verification_timeout_task, "get_chat_settings", fake_get_chat_settings)

    app = SimpleNamespace(bot_data={"db": _Db()}, bot=_BotWithRestrict())

    await verification_timeout_task.check_verification_timeouts(app)

    assert challenge.solved is True
    assert challenge.timeout_handled is True
    assert restrict_calls[0]["chat_id"] == -100123
    assert restrict_calls[0]["user_id"] == 99
    assert restrict_calls[0]["permissions"].can_send_messages is True


async def _async_append(target: list[str], value: str) -> None:
    target.append(value)
