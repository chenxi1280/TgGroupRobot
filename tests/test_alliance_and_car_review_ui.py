from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.admin import admin_handler


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None

    async def get(self, model, pk):
        return None


class _Db:
    def __init__(self):
        self.session_factory = lambda: _Session()


@pytest.mark.asyncio
async def test_alliance_menu_shows_member_count_and_joint_ban_status(monkeypatch):
    rendered: list[tuple[str, object]] = []

    async def fake_set_current_chat(db, user_id: int, chat_id: int):
        return None

    async def fake_get_alliance_by_chat(session, chat_id: int):
        return SimpleNamespace(alliance_id=3, name="测试联盟", owner_chat_id=chat_id)

    async def fake_get_setting(session, chat_id: int):
        return SimpleNamespace(joint_ban_enabled=False)

    async def fake_list_members(session, alliance_id: int):
        return [
            (SimpleNamespace(chat_id=-1001), SimpleNamespace(title="A群")),
            (SimpleNamespace(chat_id=-1002), SimpleNamespace(title="B群")),
        ]

    async def fake_safe_edit(update, text, reply_markup):
        rendered.append((text, reply_markup))

    monkeypatch.setattr(admin_handler._admin_handler, "_set_current_chat", fake_set_current_chat)
    from backend.features.garage.services.alliance_service import AllianceService

    monkeypatch.setattr(AllianceService, "get_alliance_by_chat", fake_get_alliance_by_chat)
    monkeypatch.setattr(AllianceService, "get_setting", fake_get_setting)
    monkeypatch.setattr(AllianceService, "list_members", fake_list_members)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=7))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await admin_handler._admin_handler._show_alliance_menu(update, context, -100123)

    text, keyboard = rendered[0]
    assert "👥 联盟成员：2 个" in text
    assert "联合封禁状态：❌ 关闭" in text
    assert keyboard.inline_keyboard[1][0].text == "📋 联合封禁名单"
    assert keyboard.inline_keyboard[2][0].text == "⚙️ 联合封禁："
    assert keyboard.inline_keyboard[2][2].text == "✅ 关闭"


@pytest.mark.asyncio
async def test_alliance_joint_ban_menu_lists_entries(monkeypatch):
    rendered: list[tuple[str, object]] = []

    async def fake_get_alliance_by_chat(session, chat_id: int):
        return SimpleNamespace(alliance_id=3, name="测试联盟", owner_chat_id=chat_id)

    async def fake_list_joint_ban_entries(session, *, chat_id: int, limit: int = 10):
        assert chat_id == -100123
        assert limit == 10
        return [
            SimpleNamespace(
                id=12,
                target_user_id=5566,
                source_chat_id=-1009,
                reason="reply_t_command",
                created_at=None,
            )
        ]

    async def fake_safe_edit(update, text, reply_markup):
        rendered.append((text, reply_markup))

    from backend.features.garage.services.alliance_service import AllianceService

    monkeypatch.setattr(AllianceService, "get_alliance_by_chat", fake_get_alliance_by_chat)
    monkeypatch.setattr(AllianceService, "list_joint_ban_entries", fake_list_joint_ban_entries)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace()
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await admin_handler._admin_handler._show_alliance_joint_ban_menu(update, context, -100123)

    text, keyboard = rendered[0]
    assert "联合封禁名单" in text
    assert "用户 5566" in text
    assert "原因：reply_t_command" in text
    assert keyboard.inline_keyboard[0][0].callback_data == "ali:jointban:remove:-100123:12"


@pytest.mark.asyncio
async def test_car_review_menu_uses_dynamic_labels_and_real_subpages(monkeypatch):
    rendered: list[tuple[str, object]] = []

    async def fake_set_current_chat(db, user_id: int, chat_id: int):
        return None

    async def fake_get_setting(session, chat_id: int):
        return SimpleNamespace(
            enabled=True,
            review_mode="simple",
            teacher_lookup_mode="contains",
            auto_refresh_board_enabled=False,
            submit_command="提交报告",
            rank_command="出击排行",
            publish_to_main_group=True,
            publish_to_comment_group=False,
            publish_to_bound_channel=True,
            approver_user_id=None,
            reward_points=88,
        )

    async def fake_list_fields(session, chat_id: int):
        return [
            SimpleNamespace(field_label="人照", field_key="photo_score", enabled=True),
            SimpleNamespace(field_label="颜值", field_key="face_score", enabled=False),
        ]

    async def fake_list_reports(session, chat_id: int, limit: int = 20):
        return [
            SimpleNamespace(report_id=11, teacher_user_id=101, author_user_id=201, report_status="pending"),
            SimpleNamespace(report_id=10, teacher_user_id=102, author_user_id=202, report_status="approved"),
        ]

    async def fake_safe_edit(update, text, reply_markup):
        rendered.append((text, reply_markup))

    monkeypatch.setattr(admin_handler._admin_handler, "_set_current_chat", fake_set_current_chat)
    from backend.features.garage.services.garage_features_service import CarReviewService

    monkeypatch.setattr(CarReviewService, "get_setting", fake_get_setting)
    monkeypatch.setattr(CarReviewService, "list_custom_fields", fake_list_fields)
    monkeypatch.setattr(CarReviewService, "list_recent_reports", fake_list_reports)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=7))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await admin_handler._admin_handler._show_car_review_menu(update, context, -100123)

    text, keyboard = rendered[0]
    assert "最近报告：2 条（待审核 1 条）" in text
    assert "本周出击排行" in text
    assert keyboard.inline_keyboard[0][1].text == "✅ 启动"
    assert keyboard.inline_keyboard[1][2].text == "✅ 简易"
    assert keyboard.inline_keyboard[2][2].text == "✅ 关闭"
    assert keyboard.inline_keyboard[3][2].text == "✅ 包含"
    assert keyboard.inline_keyboard[4][1].callback_data == "crv:submit_cmd:edit:-100123"
    assert keyboard.inline_keyboard[7][0].callback_data == "crv:fields:-100123"
    assert keyboard.inline_keyboard[8][0].callback_data == "crv:reports:-100123"
    assert len(keyboard.inline_keyboard[4]) == 2
    assert len(keyboard.inline_keyboard[8]) == 2


@pytest.mark.asyncio
async def test_car_review_fields_and_reports_pages_render_lists(monkeypatch):
    rendered: list[tuple[str, object]] = []

    async def fake_list_fields(session, chat_id: int):
        return [SimpleNamespace(field_label="服务", field_key="service_score", enabled=True, sort_order=3)]

    async def fake_list_reports(session, chat_id: int, *, status: str = "all", limit: int = 10):
        return [SimpleNamespace(report_id=3, teacher_user_id=1001, author_user_id=2002, report_status="pending")]

    async def fake_count_reports_by_status(session, chat_id: int):
        return {"all": 1, "pending": 1, "approved": 0, "published": 0, "rejected": 0}

    async def fake_safe_edit(update, text, reply_markup):
        rendered.append((text, reply_markup))

    from backend.features.garage.services.garage_features_service import CarReviewService

    monkeypatch.setattr(CarReviewService, "list_custom_fields", fake_list_fields)
    monkeypatch.setattr(CarReviewService, "list_reports", fake_list_reports)
    monkeypatch.setattr(CarReviewService, "count_reports_by_status", fake_count_reports_by_status)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace()
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await admin_handler._admin_handler._show_car_review_fields_menu(update, context, -100123)
    await admin_handler._admin_handler._show_car_review_reports_menu(update, context, -100123)

    assert "服务（键：service_score｜排序：3｜✅ 启用）" in rendered[0][0]
    assert "报告#3｜老师 1001" in rendered[1][0]
    assert rendered[1][1].inline_keyboard[2][0].callback_data == "crv:report:-100123:detail:3:0"


@pytest.mark.asyncio
async def test_car_review_report_detail_pending_shows_approve_and_reject(monkeypatch):
    rendered: list[tuple[str, object]] = []

    async def fake_get_report(session, chat_id: int, report_id: int):
        return SimpleNamespace(
            report_id=report_id,
            teacher_user_id=1001,
            author_user_id=2002,
            report_status="pending",
            scores={"total_score": 9.2},
            review_text="老师服务很好",
        )

    async def fake_list_logs(session, *, chat_id: int, report_id: int, limit: int = 8):
        return [SimpleNamespace(created_at=None, action="submitted", operator_user_id=2002)]

    async def fake_safe_edit(update, text, reply_markup):
        rendered.append((text, reply_markup))

    from backend.features.garage.services.garage_features_service import CarReviewService

    monkeypatch.setattr(CarReviewService, "get_report", fake_get_report)
    monkeypatch.setattr(CarReviewService, "list_audit_logs", fake_list_logs)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace()
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await admin_handler._admin_handler._show_car_review_report_detail(update, context, -100123, 9, status="pending")

    text, keyboard = rendered[0]
    assert "报告编号：9" in text
    assert keyboard.inline_keyboard[0][0].callback_data == "crv:report:-100123:approve:9:p"
    assert keyboard.inline_keyboard[0][1].callback_data == "crv:report:-100123:reject:9:p"


@pytest.mark.asyncio
async def test_car_review_publish_menu_uses_iconized_basic_mode_row(monkeypatch):
    rendered: list[object] = []

    async def fake_get_setting(session, chat_id: int):
        return SimpleNamespace(
            publish_to_main_group=True,
            publish_to_comment_group=False,
            publish_to_bound_channel=True,
        )

    async def fake_safe_edit(update, text, reply_markup):
        rendered.append(reply_markup)

    from backend.features.garage.services.garage_features_service import CarReviewService

    monkeypatch.setattr(CarReviewService, "get_setting", fake_get_setting)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace()
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await admin_handler._admin_handler._show_car_review_publish_menu(update, context, -100123)

    keyboard = rendered[0]
    assert keyboard.inline_keyboard[0][0].text == "🖼️ 首图发送：默认开启"
    assert keyboard.inline_keyboard[-1][0].text == "🔙 返回"
