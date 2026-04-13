from __future__ import annotations

from types import SimpleNamespace

from backend.features.verification.verification_handler import _collect_join_spam_signals
from backend.features.verification.verification_service import (
    SELF_REVIEW_EXPECTED_ANSWER,
    build_self_review_question,
    is_self_review_question,
    render_self_review_question,
)


def test_collect_join_spam_signals_flags_suspicious_new_member() -> None:
    user = SimpleNamespace(
        username=None,
        first_name="广告推广88888",
        last_name="",
    )

    signals = _collect_join_spam_signals(user)

    assert "no_username" in signals
    assert "many_digits" in signals
    assert "promo_keyword" in signals


def test_self_review_question_helpers_round_trip() -> None:
    question = build_self_review_question()

    assert is_self_review_question(question) is True
    assert render_self_review_question(question) == f"请发送：{SELF_REVIEW_EXPECTED_ANSWER}"

