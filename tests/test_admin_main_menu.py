from __future__ import annotations

from backend.features.admin.ui.admin_main import admin_main_menu
from backend.features.admin.ui.admin_main_text import format_admin_main_menu_text
from backend.features.group_ops.services.group_daily_stats import AdminMenuStats, GroupDayCounts


def test_private_admin_main_menu_has_six_categories_and_scoped_features():
    from backend.features.admin.ui.admin_main_keyboards import ADMIN_CATEGORIES, admin_category_menu
    from backend.features.admin.core.menu_dispatch import ADMIN_MENU_HANDLERS
    keyboard = admin_main_menu(-100123).inline_keyboard
    assert len(keyboard) == 7
    assert keyboard[5][0].callback_data == "draft:list:-100123:0"
    assert len(keyboard[-1]) == 2
    assert all(len(row) == 2 for row in keyboard[:5])
    assert [button.text for row in keyboard[2:5] for button in row] == [
        "群安全", "消息运营", "积分与增长", "活动互动", "车库业务", "系统管理",
    ]
    assert [b.text for row in keyboard[:2] for b in row] == ["自动回复", "定时消息", "轮播广告", "主积分"]
    feature_ids = [feature for _, features in ADMIN_CATEGORIES.values() for _, feature in features]
    assert len(feature_ids) == len(set(feature_ids)) == 38
    assert "solitaire" in feature_ids
    assert all(feature in ADMIN_MENU_HANDLERS for feature in feature_ids)
    for category in ADMIN_CATEGORIES:
        for row in admin_category_menu(category, -100123).inline_keyboard:
            for button in row:
                assert ":-100123" in button.callback_data
                assert len(button.callback_data.encode()) <= 64


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


def test_admin_main_menu_text_uses_configured_announcement() -> None:
    text = format_admin_main_menu_text(
        "桩基俱乐部",
        AdminMenuStats(
            today=GroupDayCounts(),
            yesterday=GroupDayCounts(),
            expires_at_text="永久",
            announcement_text="更新日志：https://example.com/changelog\n新版后台已上线",
        ),
    )

    assert "更新日志：https://example.com/changelog" in text
    assert "新版后台已上线" in text
    assert "保安公告栏 👉 点击关注" not in text


def test_admin_main_menu_text_hides_disabled_announcement() -> None:
    text = format_admin_main_menu_text(
        "桩基俱乐部",
        AdminMenuStats(
            today=GroupDayCounts(),
            yesterday=GroupDayCounts(),
            expires_at_text="永久",
            announcement_text="",
        ),
    )

    assert "保安公告栏 👉 点击关注" not in text
    assert "有效期至：永久" in text
