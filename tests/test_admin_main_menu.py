from __future__ import annotations

from bot.keyboards.admin.admin_main import admin_main_menu


def test_private_admin_main_menu_routes_real_and_todo_features():
    keyboard = admin_main_menu(-100123).inline_keyboard
    buttons = {
        button.text: button.callback_data
        for row in keyboard
        for button in row
    }

    assert buttons["💰拍卖"] == "adm:menu:auction:-100123"
    assert buttons["🎮游戏"] == "adm:menu:game:-100123"
    assert buttons["⚽竞猜"] == "adm:menu:guess:-100123"
    assert buttons["✨促活工具"] == "adm:menu:engagement:-100123"
    assert buttons["💥炸号继承"] == "adm:menu:inherit:-100123"
    assert buttons["⌨️底部按钮"] == "adm:menu:bottom_button:-100123"
