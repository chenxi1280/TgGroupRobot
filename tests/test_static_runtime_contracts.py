from __future__ import annotations

from types import SimpleNamespace
from typing import get_type_hints

from backend.features.moderation.auto_reply_helpers import _build_auto_reply_markup
from backend.features.moderation.banned_word_menu import BannedWordMenuHandler
from backend.shared.i18n.strings import t


def test_auto_reply_markup_annotation_resolves_at_runtime() -> None:
    hints = get_type_hints(_build_auto_reply_markup)

    assert "return" in hints


def test_banned_word_item_uses_shared_labels() -> None:
    word = SimpleNamespace(
        id=7,
        word="spam",
        is_active=True,
        match_type="contains",
        action="delete",
        notify=False,
    )

    text = BannedWordMenuHandler()._format_word_item(word)

    assert "包含" in text
    assert "删除消息" in text


def test_i18n_format_failure_returns_template() -> None:
    assert t("zh-CN", "points.balance") == "你在本群的积分余额：{balance}"
