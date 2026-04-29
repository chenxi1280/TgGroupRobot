from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.admin import admin_handler
from backend.features.admin.ui.points_extended import points_mall_orders_keyboard
from backend.features.garage.services.garage_forward_service import GarageForwardService
from backend.features.garage.services.garage_features_service import GarageAuthService, TeacherSearchService


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None


class _Db:
    def __init__(self):
        self.session_factory = lambda: _Session()


@pytest.mark.asyncio
async def test_points_mall_command_page_uses_return_to_home(monkeypatch):
    rendered: list[tuple[str, object]] = []

    async def fake_set_current_chat(db, user_id: int, chat_id: int):
        return None

    async def fake_get_or_create_mall_setting(session, chat_id: int):
        return SimpleNamespace(entry_command="积分商城")

    async def fake_set_user_state(*args, **kwargs):
        return None

    async def fake_safe_edit(update, *, text, reply_markup):
        rendered.append((text, reply_markup))

    monkeypatch.setattr(admin_handler._admin_handler, "_set_current_chat", fake_set_current_chat)
    monkeypatch.setattr(admin_handler.PointsExtendedService, "get_or_create_mall_setting", fake_get_or_create_mall_setting)
    monkeypatch.setattr(admin_handler, "set_user_state", fake_set_user_state)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=9))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await admin_handler._admin_handler._show_points_mall_command_page(update, context, -100123)

    assert rendered
    text, keyboard = rendered[0]
    assert "当前指令：积分商城" in text
    assert keyboard.inline_keyboard[0][0].callback_data == "adm:menu:points_mall:-100123"


@pytest.mark.asyncio
async def test_points_mall_empty_pages_show_single_page(monkeypatch):
    rendered: list[str] = []

    async def fake_list_products(session, chat_id: int):
        return []

    async def fake_list_recent_orders(session, chat_id: int, limit: int, product_id=None, order_status=None):
        return []

    async def fake_count_orders_by_status(session, *, chat_id: int, product_id=None):
        return {"all": 0, "created": 0, "fulfilled": 0, "canceled": 0, "refunded": 0}

    async def fake_safe_edit(update, *, text, reply_markup):
        rendered.append(text)

    monkeypatch.setattr(admin_handler.PointsExtendedService, "list_products", fake_list_products)
    monkeypatch.setattr(admin_handler.PointsExtendedService, "list_recent_orders", fake_list_recent_orders)
    monkeypatch.setattr(admin_handler.PointsExtendedService, "count_orders_by_status", fake_count_orders_by_status)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace()
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await admin_handler._admin_handler._show_points_mall_products_page(update, context, -100123)
    await admin_handler._admin_handler._show_points_mall_orders_page(update, context, -100123)

    assert rendered[0].endswith("0 条数据，第 1 页/共 1 页")
    assert rendered[1].endswith("0 条数据，第 1 页/共 1 页")


def test_points_mall_orders_keyboard_has_status_tabs_and_short_callbacks():
    keyboard = points_mall_orders_keyboard(
        -100123,
        orders=[SimpleNamespace(order_id=99)],
        product_id=7,
        status="created",
        status_counts={"all": 5, "created": 2, "fulfilled": 1, "canceled": 1, "refunded": 1},
    )
    first_row = keyboard.inline_keyboard[0]
    assert first_row[0].text.startswith("📋 全部")
    assert first_row[1].text.startswith("✅ 🟡 待处理")
    assert first_row[1].callback_data == "adm:mall:-100123:orders_status:c:7"
    detail_btn = keyboard.inline_keyboard[1][0]
    assert detail_btn.callback_data == "adm:mall:-100123:order:detail:99:c:7"


@pytest.mark.asyncio
async def test_garage_forward_menu_marks_selected_mode(monkeypatch):
    rendered: list[object] = []

    async def fake_set_current_chat(db, user_id: int, chat_id: int):
        return None

    async def fake_ensure_setting(session, chat_id: int):
        return SimpleNamespace(enabled=False, sync_mode="keyword", keyword_rules=["榜单"])

    async def fake_list_sources(session, chat_id: int):
        return [SimpleNamespace(id=1, source_name="频道A", source_channel_id=-100888)]

    async def fake_count_audits_by_result(session, *, chat_id: int):
        return {"all": 2, "success": 1, "skipped": 1, "failed": 0}

    async def fake_safe_edit(update, *, text, reply_markup):
        rendered.append(reply_markup)

    monkeypatch.setattr(admin_handler._admin_handler, "_set_current_chat", fake_set_current_chat)
    monkeypatch.setattr(GarageForwardService, "ensure_setting", fake_ensure_setting)
    monkeypatch.setattr(GarageForwardService, "list_sources", fake_list_sources)
    monkeypatch.setattr(GarageForwardService, "count_audits_by_result", fake_count_audits_by_result)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=1))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await admin_handler._admin_handler._show_garage_forward_prompt(update, context, -100123)

    keyboard = rendered[0]
    assert keyboard.inline_keyboard[0][0].text == "⚙️ 状态："
    assert keyboard.inline_keyboard[1][0].text == "⚙️ 模式："
    assert keyboard.inline_keyboard[0][2].text == "❌ 关闭"
    assert keyboard.inline_keyboard[2][1].text == "✅ 关键词"


@pytest.mark.asyncio
async def test_garage_forward_audit_menu_renders_filters(monkeypatch):
    rendered: list[tuple[str, object]] = []

    async def fake_list_audits(session, *, chat_id: int, result: str = "all", limit: int = 20):
        assert chat_id == -100123
        assert result == "success"
        return [
            SimpleNamespace(
                id=9,
                created_at=None,
                source_channel_id=-100888,
                source_message_id=321,
                action="copy",
                result="success",
                reason=None,
            )
        ]

    async def fake_count_audits_by_result(session, *, chat_id: int):
        return {"all": 3, "success": 1, "skipped": 1, "failed": 1}

    async def fake_safe_edit(update, text, reply_markup):
        rendered.append((text, reply_markup))

    monkeypatch.setattr(GarageForwardService, "list_audits", fake_list_audits)
    monkeypatch.setattr(GarageForwardService, "count_audits_by_result", fake_count_audits_by_result)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace()
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await admin_handler._admin_handler._show_garage_forward_audit_menu(update, context, -100123, result="success")

    text, keyboard = rendered[0]
    assert "当前筛选：成功" in text
    assert "✅ #9" in text
    assert keyboard.inline_keyboard[0][1].text.startswith("✅ ✅ 成功")
    assert keyboard.inline_keyboard[-1][0].callback_data == "gfw:home:-100123"


@pytest.mark.asyncio
async def test_garage_auth_and_teacher_search_buttons_use_icons(monkeypatch):
    rendered: list[tuple[str, object]] = []

    async def fake_set_current_chat(db, user_id: int, chat_id: int):
        return None

    async def fake_garage_settings(session, chat_id: int):
        return SimpleNamespace(
            garage_auth_enabled=True,
            garage_auth_badge="🤝",
            garage_limit_enabled=False,
            garage_limit_mode="image_text",
            garage_limit_interval_sec=7200,
            garage_limit_max_count=3,
            garage_summary_partition_by="price",
            garage_summary_only_open_course=False,
        )

    async def fake_teacher_settings(session, chat_id: int):
        return SimpleNamespace(
            tag_search_enabled=True,
            only_open_course_enabled=True,
            attendance_enabled=True,
            attendance_mode="message",
            nearby_search_enabled=True,
            force_location_enabled=False,
            footer_button_label="车库入口",
            delete_mode="delete",
        )

    async def fake_list_certified_teachers(session, chat_id: int):
        return []

    async def fake_list_whitelist(session, chat_id: int):
        return []

    async def fake_list_open_course_teachers(session, chat_id: int):
        return []

    async def fake_safe_edit(update, text, reply_markup):
        rendered.append((text, reply_markup))

    monkeypatch.setattr(admin_handler._admin_handler, "_set_current_chat", fake_set_current_chat)
    monkeypatch.setattr(GarageAuthService, "get_settings", fake_garage_settings)
    monkeypatch.setattr(GarageAuthService, "list_certified_teachers", fake_list_certified_teachers)
    monkeypatch.setattr(GarageAuthService, "list_whitelist", fake_list_whitelist)
    monkeypatch.setattr(TeacherSearchService, "get_setting", fake_teacher_settings)
    monkeypatch.setattr(TeacherSearchService, "list_open_course_teachers", fake_list_open_course_teachers)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=1))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await admin_handler._admin_handler._show_garage_auth_menu(update, context, -100123)
    await admin_handler._admin_handler._show_garage_summary_menu(update, context, -100123)
    await admin_handler._admin_handler._show_teacher_search_menu(update, context, -100123)

    garage_text, garage_keyboard = rendered[0]
    summary_text, summary_keyboard = rendered[1]
    teacher_keyboard = rendered[2][1]
    assert "分区类型" not in garage_text
    assert "只显开课" not in garage_text
    assert garage_keyboard.inline_keyboard[0][0].text == "⚙️ 状态："
    assert garage_keyboard.inline_keyboard[0][1].text == "✅ 启动"
    assert garage_keyboard.inline_keyboard[3][0].text == "📇 生成老师汇总信息"
    assert garage_keyboard.inline_keyboard[3][0].callback_data == "grg:summary:menu:-100123"
    assert garage_keyboard.inline_keyboard[4][0].text == "⚙️ 限制发言："
    assert garage_keyboard.inline_keyboard[5][1].text == "✅ 文+图"
    assert "分组方式：价格" in summary_text
    assert "开课筛选：全部老师" in summary_text
    assert summary_keyboard.inline_keyboard[0][2].text == "✅ 价格"
    assert summary_keyboard.inline_keyboard[1][2].text == "✅ 全部老师"
    assert summary_keyboard.inline_keyboard[2][0].callback_data == "grg:summary:gen:-100123"
    assert teacher_keyboard.inline_keyboard[0][0].text == "标签搜索："
    assert teacher_keyboard.inline_keyboard[1][0].text == "开课打卡："
    assert teacher_keyboard.inline_keyboard[2][0].text == "打卡模式："
    assert teacher_keyboard.inline_keyboard[3][0].text == "只显开课："
    assert all(row[0].text != "底部按钮：" for row in teacher_keyboard.inline_keyboard)
    assert teacher_keyboard.inline_keyboard[7][1].text == "删除"
