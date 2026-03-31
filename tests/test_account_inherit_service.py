from __future__ import annotations

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
