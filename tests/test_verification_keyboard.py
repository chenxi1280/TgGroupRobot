from __future__ import annotations

from bot.keyboards.common.verification import verification_keyboard


def test_verification_keyboard_uses_compact_callback_format():
    keyboard = verification_keyboard("abc123")
    button = keyboard.inline_keyboard[0][0]

    assert button.callback_data == "vfy:abc123"
