from __future__ import annotations

from backend.features.admin.ui.admin_main import admin_main_menu
from backend.features.admin.ui.admin_main_text import format_admin_main_menu_text
from backend.features.group_ops.services.group_daily_stats import AdminMenuStats, GroupDayCounts


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
    assert buttons["🩺健康检查"] == "adm:menu:health:-100123"
    assert buttons["📊群组统计"] == "adm:menu:stats:-100123"
    assert buttons["📡频道同步"] == "adm:menu:sync:-100123"
    assert buttons["⚡快捷发布"] == "adm:menu:qpub:-100123"
    assert buttons["🧑‍🍼新成员限制"] == "adm:menu:newmem:-100123"
    assert buttons["🌙夜间管控"] == "adm:menu:night:-100123"
    assert buttons["⌨️命令配置"] == "adm:menu:gcmd:-100123"
    assert buttons["📥导入设置"] == "adm:menu:import:-100123"
    assert buttons["📋克隆"] == "adm:menu:clone:-100123"
    assert buttons["💳续费订阅"] == "adm:menu:renewal:-100123"
    assert buttons["⚙️管理权限"] == "adm:menu:control:-100123"


def test_private_admin_main_menu_groups_buttons_three_per_row():
    keyboard = admin_main_menu(-100123).inline_keyboard

    assert all(len(row) == 3 for row in keyboard)
    assert [button.text for button in keyboard[-1]] == ["🔄切换群", "💳续费订阅", "⚙️管理权限"]
    assert [button.callback_data for button in keyboard[-1]] == [
        "adm:switch_group",
        "adm:menu:renewal:-100123",
        "adm:menu:control:-100123",
    ]


def test_admin_main_menu_text_includes_daily_stats_and_subscription() -> None:
    text = format_admin_main_menu_text(
        "桩基俱乐部",
        AdminMenuStats(
            today=GroupDayCounts(joins=11, leaves=0, signs=3),
            yesterday=GroupDayCounts(joins=0, leaves=2, signs=1),
            expires_at_text="2026-04-22 23:59",
        ),
    )

    assert "正在管理【桩基俱乐部】" in text
    assert "今日：加入(11) 离开(0) 签到(3)" in text
    assert "昨日：加入(0) 离开(2) 签到(1)" in text
    assert "保安公告栏 👉 点击关注 (https://t.me/abaoantips)" in text
    assert "有效期至：2026-04-22 23:59" in text
