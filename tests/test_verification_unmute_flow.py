from __future__ import annotations

from types import SimpleNamespace
import pytest

from backend.features.verification.verification_handler import (
    _extract_unmute_target_user_id,
    _extract_unmute_name_token,
    _resolve_username_to_user_id,
)
from backend.shared.ui.common.verification import verification_timeout_help_keyboard


def test_timeout_help_keyboard_callback_data():
    keyboard = verification_timeout_help_keyboard(123456)
    first = keyboard.inline_keyboard[0][0]
    second = keyboard.inline_keyboard[1][0]

    assert first.callback_data == "vfy_help:appeal:123456"
    assert second.text == "🛡️ 协助处理"
    assert second.callback_data == "vfy_help:unmute:123456"


def test_extract_unmute_target_prefers_reply_user():
    message = SimpleNamespace(
        reply_to_message=SimpleNamespace(from_user=SimpleNamespace(id=888)),
        entities=[],
    )

    target = _extract_unmute_target_user_id(message, "解封")

    assert target == 888


def test_extract_unmute_target_from_numeric_mention():
    message = SimpleNamespace(
        reply_to_message=None,
        entities=[],
    )

    target = _extract_unmute_target_user_id(message, "请解封 @123456789")

    assert target == 123456789


@pytest.mark.asyncio
async def test_resolve_username_to_user_id_supports_plain_username_after_keyword():
    class _Bot:
        async def get_chat(self, chat_ref: str):
            assert chat_ref == "@Augusti"
            return SimpleNamespace(id=24680)

    context = SimpleNamespace(bot=_Bot())
    result = await _resolve_username_to_user_id(context, "解封 Augusti")

    assert result == 24680


def test_extract_unmute_name_token_plain_name():
    assert _extract_unmute_name_token("解封 Augusti") == "Augusti"
    assert _extract_unmute_name_token("解封 @Augusti") == "Augusti"
