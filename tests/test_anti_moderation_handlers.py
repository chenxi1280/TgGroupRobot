from __future__ import annotations

from types import SimpleNamespace

import pytest
from telegram.error import BadRequest
from telegram.ext import ApplicationHandlerStop

import backend.features.moderation.banned_word_handler as banned_word_handler
import backend.features.moderation.banned_word_create as banned_word_create
from backend.features.moderation.banned_word_message import safe_edit_banned_word_message
import backend.features.moderation.anti_flood_handler as anti_flood_handler
import backend.features.moderation.anti_spam_handler as anti_spam_handler
from backend.features.moderation.banned_word_runtime import _parse_banned_word_config_text
from backend.features.moderation.services import banned_word_service
from backend.features.moderation.services.anti_spam_service import SpamViolation
from backend.features.moderation.services.garbage_guard_rules import set_rule_config
from backend.features.moderation.ui.banned_word import banned_word_list_keyboard, banned_word_menu_keyboard


class _Session:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class _SessionFactory:
    def __init__(self, session: _Session) -> None:
        self._session = session

    def __call__(self) -> "_SessionFactory":
        return self

    async def __aenter__(self) -> _Session:
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeUser:
    def __init__(self, user_id: int = 123) -> None:
        self.id = user_id
        self.username = "tester"
        self.first_name = "Test"
        self.last_name = "User"
        self.language_code = "zh"
        self.is_bot = False

    def mention_html(self) -> str:
        return "<a href='tg://user?id=123'>tester</a>"


def test_banned_word_keyboards_use_explicit_admin_back_targets() -> None:
    menu = banned_word_menu_keyboard(-100123)
    words = [
        SimpleNamespace(id=12, is_active=True),
    ]
    listing = banned_word_list_keyboard(words, -100123)

    assert menu.inline_keyboard[-1][0].callback_data == "adm:menu:main:-100123"
    assert listing.inline_keyboard[0][0].callback_data == "banned_word:add:-100123"
    assert listing.inline_keyboard[-1][0].callback_data == "adm:menu:keywords:-100123"


def _build_update(chat_id: int = -100, message_id: int = 42):
    user = _FakeUser()
    chat = SimpleNamespace(id=chat_id, type="supergroup", title="Test Chat")
    message = SimpleNamespace(message_id=message_id, sender_chat=None)
    return SimpleNamespace(effective_chat=chat, effective_message=message, effective_user=user)


def _build_context(session: _Session):
    db = SimpleNamespace(session_factory=_SessionFactory(session))
    return SimpleNamespace(
        application=SimpleNamespace(bot_data={"db": db}),
        bot=SimpleNamespace(),
    )


def _settings_with_rule(rule_id: str, updates: dict[str, object]):
    settings = SimpleNamespace(
        anti_spam_enabled=False,
        anti_spam_rules={},
    )
    set_rule_config(settings, rule_id, updates)
    return settings


def _message_for_rule(rule_id: str):
    user = _FakeUser()
    user.username = "tester"
    user.first_name = "小明"
    message = SimpleNamespace(
        message_id=42,
        sender_chat=None,
        text="普通消息",
        caption=None,
        from_user=user,
        reply_markup=None,
        forward_origin=None,
        forward_from_chat=None,
        forward_from=None,
        forward_date=None,
        deleted=False,
    )

    async def delete():
        message.deleted = True

    message.delete = delete
    if rule_id == "long_message":
        message.text = "x" * 101
    elif rule_id == "long_name":
        user.first_name = "很长很长很长的昵称"
    elif rule_id == "block_links":
        message.text = "visit https://example.com"
    elif rule_id == "block_buttons":
        message.reply_markup = SimpleNamespace(inline_keyboard=[[object()]])
    elif rule_id == "spam_user":
        user.username = None
    elif rule_id == "block_forwards":
        message.forward_origin = SimpleNamespace()
    return message, user


def test_banned_word_prompt_and_parser_use_chinese_labels() -> None:
    prompt = banned_word_create.BANNED_WORD_CREATE_PROMPT
    assert "匹配类型: 包含" in prompt
    assert "惩罚动作: 删除" in prompt
    assert "匹配类型: contains" not in prompt
    assert "惩罚动作: delete" not in prompt

    config = _parse_banned_word_config_text(
        "\n".join(
            [
                "违禁词测试",
                "匹配类型: 包含",
                "惩罚动作: 禁言",
                "禁言时长: 300",
                "删除提醒: 是",
                "提醒消息: 请不要发送违禁词",
            ]
        )
    )

    assert config["match_type"] == "contains"
    assert config["action"] == "mute"
    assert config["notify"] is True
    assert config["notify_message"] == "请不要发送违禁词"


@pytest.mark.asyncio
async def test_banned_word_safe_edit_ignores_not_modified() -> None:
    class _Q:
        data = "banned_word:list:-100123"

        async def edit_message_text(self, text: str, **kwargs) -> None:
            raise BadRequest(
                "Message is not modified: specified new message content and reply markup are exactly the same"
            )

    await safe_edit_banned_word_message(_Q(), "same")


@pytest.mark.asyncio
async def test_banned_word_add_start_ignores_repeated_prompt_edit(monkeypatch) -> None:
    session = _Session()
    update = _build_update(chat_id=123)
    update.effective_chat.type = "private"
    context = _build_context(session)

    class _Q:
        data = "banned_word:add:-100123"

        def __init__(self) -> None:
            self.answers = 0

        async def answer(self, *args, **kwargs) -> None:
            self.answers += 1

        async def edit_message_text(self, text: str, **kwargs) -> None:
            raise BadRequest(
                "Message is not modified: specified new message content and reply markup are exactly the same"
            )

    q = _Q()
    update.callback_query = q

    async def fake_resolve(*args, **kwargs):
        return -100123, "Test Chat"

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(banned_word_create, "_resolve_banned_word_target", fake_resolve)
    monkeypatch.setattr(banned_word_create, "ensure_chat", noop)
    monkeypatch.setattr(banned_word_create, "ensure_user", noop)
    monkeypatch.setattr(banned_word_create, "clear_user_state", noop)
    monkeypatch.setattr(banned_word_create, "set_user_state", noop)

    await banned_word_create.banned_word_add_start_impl(update, context)

    assert q.answers == 1


@pytest.mark.asyncio
async def test_banned_word_list_ignores_not_modified(monkeypatch) -> None:
    session = _Session()
    update = _build_update(chat_id=123)
    update.effective_chat.type = "private"
    context = _build_context(session)

    class _Q:
        data = "banned_word:list:-100123"

        def __init__(self) -> None:
            self.answers = 0

        async def answer(self, *args, **kwargs) -> None:
            self.answers += 1

        async def edit_message_text(self, text: str, **kwargs) -> None:
            raise BadRequest(
                "Message is not modified: specified new message content and reply markup are exactly the same"
            )

    q = _Q()
    update.callback_query = q

    async def fake_get_chat_banned_words(*args, **kwargs):
        return []

    async def fake_get_trigger_stats(*args, **kwargs):
        return 0

    monkeypatch.setattr(banned_word_handler, "get_chat_banned_words", fake_get_chat_banned_words)
    monkeypatch.setattr(banned_word_handler, "get_trigger_stats", fake_get_trigger_stats)

    await banned_word_handler.banned_word_list_callback(update, context)

    assert q.answers == 1


@pytest.mark.asyncio
async def test_banned_word_delete_failure_answers_without_name_error(monkeypatch) -> None:
    session = _Session()
    update = _build_update(chat_id=-100123)
    context = _build_context(session)

    class _Q:
        data = "banned_word_delete_12:-100123"

        def __init__(self) -> None:
            self.answers: list[tuple[str, bool]] = []

        async def answer(self, text: str = "", show_alert: bool = False) -> None:
            self.answers.append((text, show_alert))

    q = _Q()
    update.callback_query = q

    async def fake_delete_banned_word(*args, **kwargs):
        return False

    async def fake_is_user_admin(*args, **kwargs):
        return True

    monkeypatch.setattr(banned_word_handler, "delete_banned_word", fake_delete_banned_word)
    monkeypatch.setattr(banned_word_handler, "is_user_admin", fake_is_user_admin)

    await banned_word_handler.banned_word_delete_callback(update, context)

    assert q.answers == [("删除失败", True)]


@pytest.mark.asyncio
async def test_anti_spam_handler_records_final_action(monkeypatch):
    session = _Session()
    update = _build_update()
    context = _build_context(session)
    recorded: list[dict[str, object]] = []
    executed: list[dict[str, object]] = []

    settings = SimpleNamespace(
        anti_spam_enabled=True,
        anti_spam_action="mute",
        anti_spam_mute_duration=600,
        anti_spam_exempt_admin=False,
        anti_spam_delete_notify=False,
        anti_spam_delete_notify_seconds=30,
    )

    async def fake_get_chat_settings(session, chat_id):
        return settings

    async def fake_should_exempt_admin(*args, **kwargs):
        return False

    async def fake_detect_spam_violation(*args, **kwargs):
        return SpamViolation(blocked=True, rule="spam", detail="hit")

    async def fake_resolve_effective_action(*args, **kwargs):
        return SimpleNamespace(action="delete", fallback_reason="downgraded")

    async def fake_ensure_chat(*args, **kwargs):
        return None

    async def fake_ensure_user(*args, **kwargs):
        return None

    monkeypatch.setattr(
        anti_spam_handler,
        "get_chat_settings",
        fake_get_chat_settings,
    )
    monkeypatch.setattr(anti_spam_handler, "should_exempt_admin", fake_should_exempt_admin)
    monkeypatch.setattr(anti_spam_handler, "detect_spam_violation", fake_detect_spam_violation)
    monkeypatch.setattr(anti_spam_handler, "resolve_effective_action", fake_resolve_effective_action)
    monkeypatch.setattr(anti_spam_handler, "ensure_chat", fake_ensure_chat)
    monkeypatch.setattr(anti_spam_handler, "ensure_user", fake_ensure_user)

    async def fake_record_violation(session, **kwargs):
        recorded.append(kwargs)

    async def fake_execute_spam_punishment(*args, **kwargs):
        executed.append({"args": args, "kwargs": kwargs})
        return True

    async def fake_send_temporary_notice(*args, **kwargs):
        return None

    monkeypatch.setattr(anti_spam_handler, "record_violation", fake_record_violation)
    monkeypatch.setattr(anti_spam_handler, "execute_spam_punishment", fake_execute_spam_punishment)
    monkeypatch.setattr(anti_spam_handler, "send_temporary_notice", fake_send_temporary_notice)

    with pytest.raises(ApplicationHandlerStop):
        await anti_spam_handler.anti_spam_message_handler(update, context)

    assert recorded[0]["action"] == "delete"
    assert executed[0]["args"][3] == "delete"
    assert session.commits == 1


@pytest.mark.asyncio
async def test_long_message_over_100_deletes_and_notices_by_default(monkeypatch):
    session = _Session()
    update = _build_update()
    context = _build_context(session)
    settings = _settings_with_rule("long_message", {"enabled": True, "message_max_length": 100})
    applied_configs: list[dict[str, object]] = []

    update.effective_message = SimpleNamespace(
        message_id=42,
        sender_chat=None,
        text="孩" * 101,
        caption=None,
        deleted=False,
    )

    async def fake_delete():
        update.effective_message.deleted = True

    update.effective_message.delete = fake_delete

    async def fake_get_chat_settings(session, chat_id):
        return settings

    async def fake_should_exempt_admin(*args, **kwargs):
        return False

    async def fake_ensure_chat(*args, **kwargs):
        return None

    async def fake_ensure_user(*args, **kwargs):
        return None

    async def fake_apply_garbage_punishment(context, session, **kwargs):
        config = anti_spam_handler.get_rule_config(kwargs["settings"], kwargs["rule_id"])
        applied_configs.append(config)
        return SimpleNamespace(
            applied=True,
            action_label="删除消息 + 提示消息",
            delete_requested=True,
            delete_applied=True,
            escalation_requested=False,
            escalation_applied=False,
        )

    monkeypatch.setattr(anti_spam_handler, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(anti_spam_handler, "should_exempt_admin", fake_should_exempt_admin)
    monkeypatch.setattr(anti_spam_handler, "ensure_chat", fake_ensure_chat)
    monkeypatch.setattr(anti_spam_handler, "ensure_user", fake_ensure_user)
    monkeypatch.setattr(anti_spam_handler, "apply_garbage_punishment", fake_apply_garbage_punishment)

    with pytest.raises(ApplicationHandlerStop):
        await anti_spam_handler.anti_spam_message_handler(update, context)

    assert applied_configs[0]["delete_message"] is True
    assert applied_configs[0]["notice_enabled"] is True


@pytest.mark.asyncio
async def test_sender_chat_long_message_deletes_without_admin_exemption(monkeypatch):
    session = _Session()
    update = _build_update()
    context = _build_context(session)
    settings = _settings_with_rule("long_message", {"enabled": True, "message_max_length": 100})
    applied_kwargs: list[dict[str, object]] = []

    update.effective_user = SimpleNamespace(
        id=42,
        username="admin",
        first_name="Admin",
        last_name=None,
        language_code="zh",
        is_bot=False,
    )
    update.effective_message = SimpleNamespace(
        message_id=42,
        sender_chat=SimpleNamespace(id=-100777, title="频道身份", username="channel_identity"),
        text="孩" * 101,
        caption=None,
        from_user=None,
        reply_markup=None,
        forward_origin=None,
        forward_from_chat=None,
        forward_from=None,
        forward_date=None,
    )

    async def fake_get_chat_settings(session, chat_id):
        return settings

    async def fake_should_exempt_admin(context, chat_id, user_id, exempt_admin):
        assert user_id is None
        return False

    async def fake_ensure_chat(*args, **kwargs):
        return None

    async def forbidden_ensure_user(*args, **kwargs):
        raise AssertionError("sender_chat messages do not have a real user to persist")

    async def fake_apply_garbage_punishment(context, session, **kwargs):
        applied_kwargs.append(kwargs)
        return SimpleNamespace(
            applied=True,
            action_label="删除消息",
            delete_requested=True,
            delete_applied=True,
            escalation_requested=False,
            escalation_applied=False,
        )

    monkeypatch.setattr(anti_spam_handler, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(anti_spam_handler, "should_exempt_admin", fake_should_exempt_admin)
    monkeypatch.setattr(anti_spam_handler, "ensure_chat", fake_ensure_chat)
    monkeypatch.setattr(anti_spam_handler, "ensure_user", forbidden_ensure_user)
    monkeypatch.setattr(anti_spam_handler, "apply_garbage_punishment", fake_apply_garbage_punishment)

    with pytest.raises(ApplicationHandlerStop):
        await anti_spam_handler.anti_spam_message_handler(update, context)

    assert applied_kwargs[0]["target_user_id"] == 0
    assert applied_kwargs[0]["target_label"] == "频道身份发言"
    assert applied_kwargs[0]["sender_chat_id"] == -100777
    assert applied_kwargs[0]["message_ids"] == [42]


@pytest.mark.asyncio
async def test_explicit_garbage_hit_falls_back_to_delete_even_when_other_action_applies(monkeypatch):
    session = _Session()
    update = _build_update()
    context = _build_context(session)

    class _Message:
        message_id = 42
        sender_chat = None
        text = "x" * 101
        caption = None
        deleted = False

        async def delete(self):
            self.deleted = True

    update.effective_message = _Message()

    settings = SimpleNamespace(
        anti_spam_enabled=False,
        anti_spam_rules={},
    )
    set_rule_config(settings, "long_message", {"enabled": True, "message_max_length": 100, "delete_message": True})

    async def fake_get_chat_settings(session, chat_id):
        return settings

    async def fake_should_exempt_admin(*args, **kwargs):
        return False

    async def fake_ensure_chat(*args, **kwargs):
        return None

    async def fake_ensure_user(*args, **kwargs):
        return None

    async def fake_apply_garbage_punishment(*args, **kwargs):
        return SimpleNamespace(
            applied=True,
            action_label="删除消息 + 禁言成员",
            delete_requested=True,
            delete_applied=False,
        )

    monkeypatch.setattr(anti_spam_handler, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(anti_spam_handler, "should_exempt_admin", fake_should_exempt_admin)
    monkeypatch.setattr(anti_spam_handler, "ensure_chat", fake_ensure_chat)
    monkeypatch.setattr(anti_spam_handler, "ensure_user", fake_ensure_user)
    monkeypatch.setattr(anti_spam_handler, "apply_garbage_punishment", fake_apply_garbage_punishment)

    with pytest.raises(ApplicationHandlerStop):
        await anti_spam_handler.anti_spam_message_handler(update, context)

    assert update.effective_message.deleted is True
    assert session.commits == 1


@pytest.mark.asyncio
async def test_explicit_garbage_hit_notifies_when_non_delete_action_fails(monkeypatch):
    session = _Session()
    update = _build_update()
    sent_messages: list[str] = []

    class _Bot:
        async def send_message(self, chat_id: int, text: str, **kwargs):
            sent_messages.append(text)

    context = _build_context(session)
    context.bot = _Bot()
    update.effective_message = SimpleNamespace(
        message_id=42,
        sender_chat=None,
        text="x" * 101,
        caption=None,
        deleted=False,
    )
    settings = _settings_with_rule(
        "long_message",
        {"enabled": True, "message_max_length": 100, "delete_message": True, "mute_enabled": True},
    )

    async def fake_get_chat_settings(session, chat_id):
        return settings

    async def fake_should_exempt_admin(*args, **kwargs):
        return False

    async def fake_ensure_chat(*args, **kwargs):
        return None

    async def fake_ensure_user(*args, **kwargs):
        return None

    async def fake_apply_garbage_punishment(*args, **kwargs):
        return SimpleNamespace(
            applied=True,
            action_label="删除消息 + 禁言成员",
            delete_requested=True,
            delete_applied=True,
            escalation_requested=True,
            escalation_applied=False,
        )

    monkeypatch.setattr(anti_spam_handler, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(anti_spam_handler, "should_exempt_admin", fake_should_exempt_admin)
    monkeypatch.setattr(anti_spam_handler, "ensure_chat", fake_ensure_chat)
    monkeypatch.setattr(anti_spam_handler, "ensure_user", fake_ensure_user)
    monkeypatch.setattr(anti_spam_handler, "apply_garbage_punishment", fake_apply_garbage_punishment)

    with pytest.raises(ApplicationHandlerStop):
        await anti_spam_handler.anti_spam_message_handler(update, context)

    assert sent_messages == [
        "⚠️ 垃圾防护已命中，但处罚动作没有成功执行。\n"
        "请检查机器人是否仍是管理员，并拥有删除消息/禁言权限；也请重启机器人加载最新代码。"
    ]


@pytest.mark.parametrize(
    ("rule_id", "updates"),
    [
        ("long_message", {"enabled": True, "message_max_length": 100, "delete_message": True}),
        ("long_name", {"enabled": True, "name_max_length": 4, "delete_message": True}),
        ("block_links", {"enabled": True, "delete_message": True}),
        ("block_buttons", {"enabled": True, "delete_message": True}),
        ("spam_user", {"enabled": True, "check_no_username": True, "delete_message": True}),
        ("block_forwards", {"enabled": True, "delete_message": True}),
    ],
)
@pytest.mark.asyncio
async def test_all_message_garbage_rules_stop_and_fallback_delete(monkeypatch, rule_id: str, updates: dict[str, object]):
    session = _Session()
    update = _build_update()
    message, user = _message_for_rule(rule_id)
    update.effective_message = message
    update.effective_user = user
    context = _build_context(session)
    applied_rules: list[str] = []
    applied_configs: list[dict[str, object]] = []

    settings = _settings_with_rule(rule_id, updates)

    async def fake_get_chat_settings(session, chat_id):
        return settings

    async def fake_should_exempt_admin(*args, **kwargs):
        return False

    async def fake_ensure_chat(*args, **kwargs):
        return None

    async def fake_ensure_user(*args, **kwargs):
        return None

    async def fake_apply_garbage_punishment(*args, **kwargs):
        applied_rules.append(kwargs["rule_id"])
        applied_configs.append(anti_spam_handler.get_rule_config(kwargs["settings"], kwargs["rule_id"]))
        return SimpleNamespace(applied=False, action_label="未执行处罚")

    monkeypatch.setattr(anti_spam_handler, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(anti_spam_handler, "should_exempt_admin", fake_should_exempt_admin)
    monkeypatch.setattr(anti_spam_handler, "ensure_chat", fake_ensure_chat)
    monkeypatch.setattr(anti_spam_handler, "ensure_user", fake_ensure_user)
    monkeypatch.setattr(anti_spam_handler, "apply_garbage_punishment", fake_apply_garbage_punishment)

    with pytest.raises(ApplicationHandlerStop):
        await anti_spam_handler.anti_spam_message_handler(update, context)

    assert applied_rules == [rule_id]
    assert applied_configs[0]["delete_message"] is True
    assert applied_configs[0]["notice_enabled"] is True
    assert message.deleted is True


@pytest.mark.asyncio
async def test_manual_warning_stops_and_fallback_deletes_when_actions_fail(monkeypatch):
    session = _Session()
    update = _build_update()
    context = _build_context(session)
    target = _FakeUser(user_id=456)
    update.effective_message = SimpleNamespace(
        message_id=42,
        sender_chat=None,
        text="警告",
        caption=None,
        reply_to_message=SimpleNamespace(message_id=41, from_user=target),
        deleted=False,
    )

    async def delete():
        update.effective_message.deleted = True

    update.effective_message.delete = delete
    settings = _settings_with_rule("manual_warning", {"enabled": True, "delete_message": True, "warn_enabled": False})

    async def fake_get_chat_settings(session, chat_id):
        return settings

    async def fake_should_exempt_admin(context, chat_id, user_id, default):
        return user_id == update.effective_user.id

    async def fake_ensure_chat(*args, **kwargs):
        return None

    async def fake_ensure_user(*args, **kwargs):
        return None

    async def fake_apply_garbage_punishment(*args, **kwargs):
        return SimpleNamespace(applied=False, action_label="未执行处罚")

    monkeypatch.setattr(anti_spam_handler, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(anti_spam_handler, "should_exempt_admin", fake_should_exempt_admin)
    monkeypatch.setattr(anti_spam_handler, "ensure_chat", fake_ensure_chat)
    monkeypatch.setattr(anti_spam_handler, "ensure_user", fake_ensure_user)
    monkeypatch.setattr(anti_spam_handler, "apply_garbage_punishment", fake_apply_garbage_punishment)

    with pytest.raises(ApplicationHandlerStop):
        await anti_spam_handler.anti_spam_message_handler(update, context)

    assert update.effective_message.deleted is True


@pytest.mark.asyncio
async def test_quick_reply_mute_uses_configured_reply_keyword(monkeypatch):
    session = _Session()
    update = _build_update()
    context = _build_context(session)
    target = _FakeUser(user_id=456)
    update.effective_message = SimpleNamespace(
        message_id=42,
        sender_chat=None,
        text="j",
        caption=None,
        reply_to_message=SimpleNamespace(message_id=41, from_user=target),
    )
    settings = _settings_with_rule("quick_reply_actions", {"enabled": True})
    applied: list[dict[str, object]] = []

    async def fake_get_chat_settings(session, chat_id):
        return settings

    async def fake_should_exempt_admin(context, chat_id, user_id, default):
        return user_id == update.effective_user.id

    async def fake_ensure_chat(*args, **kwargs):
        return None

    async def fake_ensure_user(*args, **kwargs):
        return None

    async def fake_apply_quick_reply_action(context, session, **kwargs):
        applied.append(kwargs)
        return SimpleNamespace(applied=True)

    monkeypatch.setattr(anti_spam_handler, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(anti_spam_handler, "should_exempt_admin", fake_should_exempt_admin)
    monkeypatch.setattr(anti_spam_handler, "ensure_chat", fake_ensure_chat)
    monkeypatch.setattr(anti_spam_handler, "ensure_user", fake_ensure_user)
    monkeypatch.setattr(anti_spam_handler, "apply_quick_reply_action", fake_apply_quick_reply_action)

    with pytest.raises(ApplicationHandlerStop):
        await anti_spam_handler.anti_spam_message_handler(update, context)

    assert applied[0]["action"] == "mute"
    assert applied[0]["target_user_id"] == 456
    assert applied[0]["actor_user_id"] == update.effective_user.id
    assert applied[0]["target_message_id"] == 41


@pytest.mark.asyncio
async def test_quick_reply_kick_accepts_uppercase_configured_keyword(monkeypatch):
    session = _Session()
    update = _build_update()
    context = _build_context(session)
    target = _FakeUser(user_id=456)
    update.effective_message = SimpleNamespace(
        message_id=42,
        sender_chat=None,
        text="T",
        caption=None,
        reply_to_message=SimpleNamespace(message_id=41, from_user=target),
    )
    settings = _settings_with_rule("quick_reply_actions", {"enabled": True, "kick_keyword": "t"})
    applied: list[dict[str, object]] = []

    async def fake_get_chat_settings(session, chat_id):
        return settings

    async def fake_should_exempt_admin(context, chat_id, user_id, default):
        return user_id == update.effective_user.id

    async def fake_ensure_chat(*args, **kwargs):
        return None

    async def fake_ensure_user(*args, **kwargs):
        return None

    async def fake_apply_quick_reply_action(context, session, **kwargs):
        applied.append(kwargs)
        return SimpleNamespace(applied=True)

    monkeypatch.setattr(anti_spam_handler, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(anti_spam_handler, "should_exempt_admin", fake_should_exempt_admin)
    monkeypatch.setattr(anti_spam_handler, "ensure_chat", fake_ensure_chat)
    monkeypatch.setattr(anti_spam_handler, "ensure_user", fake_ensure_user)
    monkeypatch.setattr(anti_spam_handler, "apply_quick_reply_action", fake_apply_quick_reply_action)

    with pytest.raises(ApplicationHandlerStop):
        await anti_spam_handler.anti_spam_message_handler(update, context)

    assert applied[0]["action"] == "kick"
    assert applied[0]["target_user_id"] == 456


@pytest.mark.asyncio
async def test_leave_ban_fallbacks_and_notifies_when_delete_and_ban_fail(monkeypatch):
    session = _Session()
    update = _build_update()
    sent_messages: list[str] = []

    class _Bot:
        async def send_message(self, chat_id: int, text: str, **kwargs):
            sent_messages.append(text)

    context = _build_context(session)
    context.bot = _Bot()
    left_user = _FakeUser(user_id=456)
    update.effective_message = SimpleNamespace(
        message_id=42,
        sender_chat=None,
        text=None,
        caption=None,
        left_chat_member=left_user,
        deleted=False,
    )

    async def delete():
        update.effective_message.deleted = True

    update.effective_message.delete = delete
    settings = _settings_with_rule("leave_ban", {"enabled": True, "delete_message": True})

    async def fake_get_chat_settings(session, chat_id):
        return settings

    async def fake_should_exempt_admin(*args, **kwargs):
        return False

    async def fake_ensure_chat(*args, **kwargs):
        return None

    async def fake_ensure_user(*args, **kwargs):
        return None

    async def fake_delete_many(*args, **kwargs):
        return SimpleNamespace(applied=False)

    async def fake_execute_garbage_action_safely(*args, **kwargs):
        return SimpleNamespace(applied=False)

    async def fake_record_violation(*args, **kwargs):
        return None

    monkeypatch.setattr(anti_spam_handler, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(anti_spam_handler, "should_exempt_admin", fake_should_exempt_admin)
    monkeypatch.setattr(anti_spam_handler, "ensure_chat", fake_ensure_chat)
    monkeypatch.setattr(anti_spam_handler, "ensure_user", fake_ensure_user)
    monkeypatch.setattr(anti_spam_handler.ActionExecutor, "delete_many", fake_delete_many)
    monkeypatch.setattr(anti_spam_handler, "execute_garbage_action_safely", fake_execute_garbage_action_safely)
    monkeypatch.setattr(anti_spam_handler, "record_violation", fake_record_violation)

    with pytest.raises(ApplicationHandlerStop):
        await anti_spam_handler.anti_spam_message_handler(update, context)

    assert update.effective_message.deleted is True
    assert sent_messages == [
        "⚠️ 垃圾防护已命中，但处罚动作没有成功执行。\n"
        "请检查机器人是否仍是管理员，并拥有删除消息/禁言权限；也请重启机器人加载最新代码。"
    ]


@pytest.mark.asyncio
async def test_anti_flood_handler_records_final_action(monkeypatch):
    session = _Session()
    update = _build_update(message_id=88)
    context = _build_context(session)
    recorded: list[dict[str, object]] = []
    executed: list[dict[str, object]] = []

    settings = SimpleNamespace(
        anti_flood_enabled=True,
        anti_flood_messages=3,
        anti_flood_seconds=10,
        anti_flood_action="mute",
        anti_flood_mute_duration=600,
        anti_flood_exempt_admin=False,
        anti_flood_cleanup_messages=False,
        anti_flood_delete_notify=False,
        anti_flood_delete_notify_seconds=30,
    )

    class FakeTracker:
        async def add_message(self, *args, **kwargs):
            return None

        async def check_flood(self, *args, **kwargs):
            return SimpleNamespace(is_flooding=True, message_count=4, time_span=3.2, action="none")

    async def fake_get_chat_settings(session, chat_id):
        return settings

    async def fake_should_exempt_admin(*args, **kwargs):
        return False

    async def fake_resolve_effective_action(*args, **kwargs):
        return SimpleNamespace(action="delete", fallback_reason="downgraded")

    async def fake_ensure_chat(*args, **kwargs):
        return None

    async def fake_ensure_user(*args, **kwargs):
        return None

    monkeypatch.setattr(anti_flood_handler, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(anti_flood_handler, "should_exempt_admin", fake_should_exempt_admin)
    monkeypatch.setattr(anti_flood_handler, "get_tracker", lambda: FakeTracker())
    monkeypatch.setattr(anti_flood_handler, "resolve_effective_action", fake_resolve_effective_action)
    monkeypatch.setattr(anti_flood_handler, "ensure_chat", fake_ensure_chat)
    monkeypatch.setattr(anti_flood_handler, "ensure_user", fake_ensure_user)

    async def fake_record_violation(session, **kwargs):
        recorded.append(kwargs)

    async def fake_execute_flood_punishment(*args, **kwargs):
        executed.append({"args": args, "kwargs": kwargs})
        return True

    async def fake_send_temporary_notice(*args, **kwargs):
        return None

    monkeypatch.setattr(anti_flood_handler, "record_violation", fake_record_violation)
    monkeypatch.setattr(anti_flood_handler, "execute_flood_punishment", fake_execute_flood_punishment)
    monkeypatch.setattr(anti_flood_handler, "send_temporary_notice", fake_send_temporary_notice)

    with pytest.raises(ApplicationHandlerStop):
        await anti_flood_handler.anti_flood_message_handler(update, context)

    assert recorded[0]["action"] == "delete"
    assert executed[0]["args"][3] == "delete"
    assert session.commits == 2


@pytest.mark.asyncio
async def test_explicit_flood_uses_garbage_guard_threshold_and_stops_on_failed_action(monkeypatch):
    session = _Session()
    update = _build_update(message_id=88)
    context = _build_context(session)
    checked_args: list[tuple[int, int]] = []
    apply_details: list[str] = []
    applied_configs: list[dict[str, object]] = []

    class _Message:
        message_id = 88
        sender_chat = None
        text = "hello"
        caption = None
        deleted = False

        async def delete(self):
            self.deleted = True

    update.effective_message = _Message()

    settings = SimpleNamespace(
        anti_spam_rules={},
        anti_flood_enabled=False,
        anti_flood_messages=99,
        anti_flood_seconds=99,
        anti_flood_action="mute",
        anti_flood_mute_duration=600,
        anti_flood_exempt_admin=False,
        anti_flood_cleanup_messages=False,
        anti_flood_delete_notify=False,
        anti_flood_delete_notify_seconds=30,
    )
    set_rule_config(settings, "flood", {"enabled": True, "messages": 3, "seconds": 7})
    settings.anti_flood_messages = 99
    settings.anti_flood_seconds = 99

    class FakeTracker:
        async def add_message(self, *args, **kwargs):
            return None

        async def check_flood(self, chat_id, actor_id, max_messages, window_seconds):
            checked_args.append((max_messages, window_seconds))
            return SimpleNamespace(is_flooding=True, message_count=4, time_span=3.2, action="none")

        async def get_and_clear_messages(self, chat_id, actor_id):
            return [88]

    async def fake_get_chat_settings(session, chat_id):
        return settings

    async def fake_should_exempt_admin(*args, **kwargs):
        return False

    async def fake_ensure_chat(*args, **kwargs):
        return None

    async def fake_ensure_user(*args, **kwargs):
        return None

    async def fake_apply_garbage_punishment(*args, **kwargs):
        apply_details.append(kwargs["detail"])
        applied_configs.append(anti_flood_handler.get_rule_config(kwargs["settings"], "flood"))
        return SimpleNamespace(applied=False, action_label="未执行处罚")

    monkeypatch.setattr(anti_flood_handler, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(anti_flood_handler, "should_exempt_admin", fake_should_exempt_admin)
    monkeypatch.setattr(anti_flood_handler, "get_tracker", lambda: FakeTracker())
    monkeypatch.setattr(anti_flood_handler, "ensure_chat", fake_ensure_chat)
    monkeypatch.setattr(anti_flood_handler, "ensure_user", fake_ensure_user)
    monkeypatch.setattr(anti_flood_handler, "apply_garbage_punishment", fake_apply_garbage_punishment)

    with pytest.raises(ApplicationHandlerStop):
        await anti_flood_handler.anti_flood_message_handler(update, context)

    assert checked_args == [(3, 7)]
    assert apply_details == ["3.2 秒内发送 4 条消息，达到刷屏阈值"]
    assert applied_configs[0]["delete_message"] is True
    assert applied_configs[0]["notice_enabled"] is True
    assert update.effective_message.deleted is True
    assert session.commits == 2


@pytest.mark.asyncio
async def test_banned_word_toggle_and_delete_are_chat_scoped(monkeypatch):
    session = _Session()
    update = _build_update(chat_id=-100123)
    context = _build_context(session)

    class _Q:
        data = "banned_word_delete_12:-100123"

        def __init__(self) -> None:
            self.answers: list[tuple[str, bool]] = []
            self.edits: list[str] = []

        async def answer(self, text: str = "", show_alert: bool = False) -> None:
            self.answers.append((text, show_alert))

        async def edit_message_text(self, text: str, reply_markup=None, parse_mode=None) -> None:
            self.edits.append(text)

    q = _Q()
    update.callback_query = q

    deleted_calls: list[dict[str, object]] = []
    toggled_calls: list[dict[str, object]] = []

    async def fake_delete_banned_word(session, word_id: int, *, chat_id: int | None = None):
        deleted_calls.append({"word_id": word_id, "chat_id": chat_id})
        return True

    async def fake_toggle_banned_word(session, word_id: int, *, chat_id: int | None = None):
        toggled_calls.append({"word_id": word_id, "chat_id": chat_id})
        return True

    async def fake_get_chat_banned_words(session, chat_id: int, active_only: bool = False):
        assert chat_id == -100123
        return []

    async def fake_get_trigger_stats(session, chat_id: int):
        assert chat_id == -100123
        return 0

    async def fake_is_user_admin(*args, **kwargs):
        return True

    monkeypatch.setattr(banned_word_handler, "delete_banned_word", fake_delete_banned_word)
    monkeypatch.setattr(banned_word_handler, "toggle_banned_word", fake_toggle_banned_word)
    monkeypatch.setattr(banned_word_handler, "get_chat_banned_words", fake_get_chat_banned_words)
    monkeypatch.setattr(banned_word_handler, "get_trigger_stats", fake_get_trigger_stats)
    monkeypatch.setattr(banned_word_handler, "is_user_admin", fake_is_user_admin)
    async def fake_require_current_chat(*args, **kwargs):
        return -100123

    monkeypatch.setattr(banned_word_handler.PrivateChatContext, "require_current_chat", fake_require_current_chat)

    async def fake_get_banned_word_in_chat(session, chat_id: int, word_id: int):
        assert chat_id == -100123
        assert word_id == 12
        return SimpleNamespace(id=12, chat_id=chat_id, is_active=True, word="bad", match_type="contains", action="delete", notify=True)

    monkeypatch.setattr(banned_word_service, "get_banned_word_in_chat", fake_get_banned_word_in_chat)

    await banned_word_handler.banned_word_delete_callback(update, context)
    assert deleted_calls == [{"word_id": 12, "chat_id": -100123}]
    assert q.answers == [("违禁词已删除", False)]
    assert q.edits

    toggle = banned_word_handler.BannedWordToggleHandler()

    async def fake_toggle_scoped(session, word_id: int, *, chat_id: int | None = None):
        toggled_calls.append({"word_id": word_id, "chat_id": chat_id})
        return True

    monkeypatch.setattr(banned_word_handler, "toggle_banned_word", fake_toggle_scoped)
    await toggle._toggle_word(context, 12, -100123)

    assert toggled_calls == [{"word_id": 12, "chat_id": -100123}]


@pytest.mark.asyncio
async def test_banned_word_service_toggle_delete_use_chat_scope(monkeypatch):
    scoped_calls: list[tuple[str, int, int]] = []

    async def fake_get_banned_word_in_chat(session, chat_id: int, word_id: int):
        scoped_calls.append(("get", chat_id, word_id))
        return SimpleNamespace(id=word_id, chat_id=chat_id, is_active=True)

    async def fake_delete(session, entity):
        scoped_calls.append(("delete", entity.chat_id, entity.id))

    async def fake_update(session, entity, updates):
        scoped_calls.append(("update", entity.chat_id, entity.id))

    monkeypatch.setattr(banned_word_service, "get_banned_word_in_chat", fake_get_banned_word_in_chat)
    monkeypatch.setattr(banned_word_service.ServiceBase, "_delete_entity", fake_delete)
    monkeypatch.setattr(banned_word_service.ServiceBase, "_update_entity", fake_update)

    toggle_result = await banned_word_service.toggle_banned_word(None, 7, chat_id=-100123)
    delete_result = await banned_word_service.delete_banned_word(None, 8, chat_id=-100123)

    assert toggle_result is True
    assert delete_result is True
    assert scoped_calls == [
        ("get", -100123, 7),
        ("update", -100123, 7),
        ("get", -100123, 8),
        ("delete", -100123, 8),
    ]
