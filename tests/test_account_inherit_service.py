from __future__ import annotations

from bot.handlers.account_inherit_handler import _extract_inherit_chat_id
from bot.utils.callback_parser import CallbackParser
from bot.services.integration.account_inherit_service import _hash_token, new_inherit_token


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
