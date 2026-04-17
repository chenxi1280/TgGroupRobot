from __future__ import annotations

from types import SimpleNamespace

from backend.features.activity.ui.solitaire import (
    solitaire_detail_keyboard,
    solitaire_list_keyboard,
    solitaire_menu_keyboard,
)


def test_solitaire_keyboards_keep_chat_scope_in_back_and_detail_callbacks() -> None:
    menu = solitaire_menu_keyboard(-100123)
    listing = solitaire_list_keyboard(
        [
            SimpleNamespace(
                id=7,
                title="今晚聚餐",
                status="active",
                entries_rel=[],
                max_participants=0,
            )
        ],
        chat_id=-100123,
    )
    detail = solitaire_detail_keyboard(7, is_active=True, chat_id=-100123)

    assert menu.inline_keyboard[-1][0].callback_data == "adm:menu:main:-100123"
    assert listing.inline_keyboard[0][0].callback_data == "sol:detail:-100123:7"
    assert listing.inline_keyboard[-1][0].callback_data == "adm:menu:solitaire:-100123"
    assert detail.inline_keyboard[0][0].callback_data == "sol:refresh:-100123:7"
    assert detail.inline_keyboard[1][0].callback_data == "sol:delete:-100123:7"
    assert detail.inline_keyboard[-1][0].callback_data == "sol:list:-100123:0"
