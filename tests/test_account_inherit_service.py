from __future__ import annotations

from types import SimpleNamespace

import pytest
from telegram.error import BadRequest

from backend.features.invite import account_inherit_handler
from backend.features.invite.account_inherit_handler import _extract_inherit_chat_id
from backend.shared.callback_parser import CallbackParser
from backend.features.invite.services.account_inherit_service import _hash_token, new_inherit_token
from backend.shared.services.base import ValidationError


def test_inherit_token_hash_is_deterministic_and_not_plaintext():
    token = "demo-token"
    hashed = _hash_token(token)
    assert hashed == _hash_token(token)
    assert hashed != token
    assert len(hashed) == 64


def test_new_inherit_token_returns_non_empty_token():
    token = new_inherit_token()
    assert token
    assert len(token) >= 16


def test_extract_inherit_chat_id_supports_token_callbacks():
    assert _extract_inherit_chat_id(CallbackParser.parse("inh:user:-100123")) == -100123
    assert _extract_inherit_chat_id(CallbackParser.parse("inh:toggle:-100123:1")) == -100123
    assert _extract_inherit_chat_id(CallbackParser.parse("inh:token:gen:-100123")) == -100123
    assert _extract_inherit_chat_id(CallbackParser.parse("inh:token:use:-100123")) == -100123


@pytest.mark.asyncio
async def test_render_text_ignores_not_modified_callback():
    class Query:
        id = "render-not-modified"
        data = "inh:user:-100123"
        message = object()

        def __init__(self):
            self.answers = []

        async def edit_message_text(self, **kwargs):
            raise BadRequest("Message is not modified: specified new message content and reply markup are exactly the same")

        async def answer(self, text=None, show_alert=None):
            self.answers.append({"text": text, "show_alert": show_alert})

    query = Query()
    update = SimpleNamespace(callback_query=query, effective_message=None)

    await account_inherit_handler._render_text(update, "same", SimpleNamespace())

    assert query.answers == [{"text": "已是当前页面", "show_alert": False}]


@pytest.mark.asyncio
async def test_token_generate_validation_failure_is_visible(monkeypatch):
    class Session:
        def __init__(self):
            self.rolled_back = False
            self.committed = False

        async def rollback(self):
            self.rolled_back = True

        async def commit(self):
            self.committed = True

    class SessionFactory:
        def __init__(self, session):
            self.session = session

        async def __aenter__(self):
            return self.session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class Query:
        id = "token-generate-failed"
        data = "inh:token:gen:-100123"
        message = object()

        def __init__(self):
            self.edits = []
            self.answers = []

        async def edit_message_text(self, **kwargs):
            self.edits.append(kwargs)

        async def answer(self, text=None, show_alert=None):
            self.answers.append({"text": text, "show_alert": show_alert})

    async def fake_generate_token(session, chat_id, old_user_id):
        raise ValidationError("旧账号当前没有可继承资产。")

    monkeypatch.setattr(account_inherit_handler, "generate_token", fake_generate_token)

    session = Session()
    query = Query()
    update = SimpleNamespace(
        callback_query=query,
        effective_user=SimpleNamespace(id=777),
        effective_message=None,
    )
    context = SimpleNamespace(
        application=SimpleNamespace(
            bot_data={"db": SimpleNamespace(session_factory=lambda: SessionFactory(session))}
        )
    )

    await account_inherit_handler.account_inherit_callback(update, context)

    assert session.rolled_back is True
    assert session.committed is False
    assert query.edits
    assert "继承令牌生成失败" in query.edits[0]["text"]
    assert "旧账号当前没有可继承资产" in query.edits[0]["text"]
    assert query.answers == [{"text": None, "show_alert": None}]


@pytest.mark.asyncio
async def test_handle_account_inherit_input_consumes_token_and_returns_home(monkeypatch):
    calls = {}

    class Session:
        def __init__(self):
            self.committed = False

        async def commit(self):
            self.committed = True

    class Message:
        def __init__(self):
            self.replies = []

        async def reply_text(self, text, **kwargs):
            self.replies.append(text)

    async def fake_consume_token(session, chat_id, new_user_id, *, plain_token):
        calls["consume"] = (chat_id, new_user_id, plain_token)
        return {"main_points": 12, "custom_points": [{"type_id": 3, "balance": 5}]}

    async def fake_clear_user_state(session, *, chat_id, user_id):
        calls["clear"] = (chat_id, user_id)

    async def fake_show_user_inherit_home(update, context, chat_id):
        calls["home"] = chat_id

    monkeypatch.setattr(account_inherit_handler, "consume_token", fake_consume_token)
    monkeypatch.setattr(account_inherit_handler, "clear_user_state", fake_clear_user_state)
    monkeypatch.setattr(account_inherit_handler, "show_user_inherit_home", fake_show_user_inherit_home)

    session = Session()
    message = Message()
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=888),
        effective_message=message,
    )
    state = SimpleNamespace(state_data={"target_chat_id": -100123})

    await account_inherit_handler.handle_account_inherit_input(
        update,
        SimpleNamespace(),
        session,
        state=state,
        message_text="  token-abc  ",
    )

    assert calls["consume"] == (-100123, 888, "token-abc")
    assert calls["clear"] == (888, 888)
    assert session.committed is True
    assert calls["home"] == -100123
    assert message.replies == ["✅ 继承成功\n🌑 主积分：12\n🌐 自定义积分：type#3=5"]
