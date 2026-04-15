from __future__ import annotations

from backend.shared.ui.common.verification import verification_keyboard


def test_verification_keyboard_uses_compact_callback_format():
    keyboard = verification_keyboard("abc123")
    agree_button = keyboard.inline_keyboard[0][0]
    decline_button = keyboard.inline_keyboard[0][1]

    assert agree_button.callback_data == "vfy:abc123:agree"
    assert agree_button.text == "✅ 同意"
    assert decline_button.callback_data == "vfy:abc123:decline"
    assert decline_button.text == "❌ 不同意"
