from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.admin import admin_handler
from backend.features.admin.admin_handler import handle_points_extended_input
from backend.features.points import points_handler as points_handler_module
from backend.features.points.points_handler import PointsHandler, _required_level_permission
from backend.shared.callback_parser import CallbackParser
from backend.features.points.services.points_extended_service import PointsExtendedService
from backend.shared.services.base import ValidationError


class _FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.flushes = 0

    async def commit(self) -> None:
        self.commits += 1

    async def flush(self) -> None:
        self.flushes += 1


class _FakeSessionContext:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeDb:
    def __init__(self, session):
        self._session = session

    def session_factory(self):
        return _FakeSessionContext(self._session)


@pytest.mark.asyncio
async def test_update_product_allows_clearing_optional_fields():
    session = _FakeSession()
    product = SimpleNamespace(
        name="A",
        price_points=1,
        limit_per_user=3,
        stock_total=10,
        stock_left=7,
        fulfiller_user_id=123,
        description="desc",
        sort_weight=0,
        cover_media_type="photo",
        cover_file_id="file",
        updated_at=None,
    )

    await PointsExtendedService.update_product(
        session,
        product,
        limit_per_user=None,
        fulfiller_user_id=None,
        description=None,
        cover_media_type=None,
        cover_file_id=None,
    )

    assert product.limit_per_user is None
    assert product.fulfiller_user_id is None
    assert product.description is None
    assert product.cover_media_type is None
    assert product.cover_file_id is None
    assert session.flushes == 1


@pytest.mark.asyncio
async def test_update_product_stock_total_preserves_consumed_inventory():
    session = _FakeSession()
    product = SimpleNamespace(
        stock_total=10,
        stock_left=6,
        updated_at=None,
    )

    await PointsExtendedService.update_product_stock_total(session, product, stock_total=8)
    assert product.stock_total == 8
    assert product.stock_left == 4

    await PointsExtendedService.update_product_stock_total(session, product, stock_total=2)
    assert product.stock_total == 2
    assert product.stock_left == 0


@pytest.mark.asyncio
async def test_update_mall_setting_supports_notice_and_cover():
    session = _FakeSession()
    setting = SimpleNamespace(
        enabled=False,
        auto_unlist_when_out_of_stock=False,
        entry_command="积分商城",
        redeem_notice_delete_seconds=60,
        cover_media_type=None,
        cover_file_id=None,
        updated_at=None,
    )

    await PointsExtendedService.update_mall_setting(
        session,
        setting,
        enabled=True,
        auto_unlist_when_out_of_stock=True,
        entry_command="商城",
        redeem_notice_delete_seconds=0,
        cover_media_type="photo",
        cover_file_id="abc",
    )

    assert setting.enabled is True
    assert setting.auto_unlist_when_out_of_stock is True
    assert setting.entry_command == "商城"
    assert setting.redeem_notice_delete_seconds == 0
    assert setting.cover_media_type == "photo"
    assert setting.cover_file_id == "abc"
    assert session.flushes == 1


@pytest.mark.asyncio
async def test_handle_points_extended_input_clears_invalid_custom_point_state(monkeypatch):
    clear_calls: list[tuple[int, int]] = []
    replies: list[str] = []

    async def fake_require_manage(*args, **kwargs):
        return True, None

    async def fake_clear_user_state(session, *, chat_id: int, user_id: int):
        clear_calls.append((chat_id, user_id))

    async def fake_clear_private_input_state(session, user_id: int):
        clear_calls.append((user_id, user_id))

    monkeypatch.setattr(admin_handler.PermissionPolicyService, "require_manage", fake_require_manage)
    monkeypatch.setattr(admin_handler, "clear_user_state", fake_clear_user_state)
    monkeypatch.setattr(admin_handler, "clear_private_input_state", fake_clear_private_input_state)

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=42),
        effective_message=SimpleNamespace(reply_text=lambda text: replies.append(text)),
    )

    async def _reply_text(text):
        replies.append(text)

    update.effective_message.reply_text = _reply_text

    context = SimpleNamespace()
    session = _FakeSession()
    state = SimpleNamespace(
        state_type="custom_points_name_input",
        state_data={"target_chat_id": -1001, "type_id": "bad"},
        chat_id=42,
    )

    await handle_points_extended_input(update, context, session, state, "hello")

    assert clear_calls == [(-1001, 42), (42, 42)]
    assert session.commits == 1
    assert any("状态异常" in text for text in replies)


@pytest.mark.asyncio
async def test_handle_points_extended_input_supports_custom_point_deduct(monkeypatch):
    clear_calls: list[tuple[int, int]] = []
    deltas: list[int] = []
    shown: list[tuple[int, int]] = []
    ensured_users: list[int] = []
    replies: list[str] = []

    async def fake_require_manage(*args, **kwargs):
        return True, None

    async def fake_clear_user_state(session, *, chat_id: int, user_id: int):
        clear_calls.append((chat_id, user_id))

    async def fake_clear_private_input_state(session, user_id: int):
        clear_calls.append((user_id, user_id))

    async def fake_get_custom_point_type(session, chat_id: int, type_id: int):
        return SimpleNamespace(id=type_id, name="出击分")

    async def fake_adjust_custom_points(session, **kwargs):
        deltas.append(kwargs["delta"])
        return 88

    async def fake_show_detail(update, context, chat_id: int, type_id: int):
        shown.append((chat_id, type_id))

    async def fake_ensure_user(session, **kwargs):
        ensured_users.append(kwargs["user_id"])

    monkeypatch.setattr(admin_handler.PermissionPolicyService, "require_manage", fake_require_manage)
    monkeypatch.setattr(admin_handler, "clear_user_state", fake_clear_user_state)
    monkeypatch.setattr(admin_handler, "clear_private_input_state", fake_clear_private_input_state)
    monkeypatch.setattr(admin_handler, "ensure_user", fake_ensure_user)
    monkeypatch.setattr(admin_handler.PointsExtendedService, "get_custom_point_type", fake_get_custom_point_type)
    monkeypatch.setattr(admin_handler.PointsExtendedService, "adjust_custom_points", fake_adjust_custom_points)
    monkeypatch.setattr(admin_handler._admin_handler, "_show_custom_point_detail", fake_show_detail)

    async def _reply_text(text):
        replies.append(text)

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=42),
        effective_message=SimpleNamespace(reply_text=_reply_text),
    )
    context = SimpleNamespace()
    session = _FakeSession()
    state = SimpleNamespace(
        state_type="custom_points_adjust_input",
        state_data={"target_chat_id": -1001, "type_id": 7, "mode": "deduct"},
        chat_id=42,
    )

    await handle_points_extended_input(update, context, session, state, "12345 20 管理员扣分")

    assert ensured_users == [12345]
    assert deltas == [-20]
    assert clear_calls == [(-1001, 42), (42, 42)]
    assert shown == [(-1001, 7)]
    assert any("扣除 20 出击分" in text for text in replies)


@pytest.mark.asyncio
async def test_handle_points_extended_input_updates_mall_cover(monkeypatch):
    clear_calls: list[tuple[int, int]] = []
    updates: list[dict] = []
    shown: list[int] = []

    async def fake_require_manage(*args, **kwargs):
        return True, None

    async def fake_clear_user_state(session, *, chat_id: int, user_id: int):
        clear_calls.append((chat_id, user_id))

    async def fake_clear_private_input_state(session, user_id: int):
        clear_calls.append((user_id, user_id))

    async def fake_get_or_create_mall_setting(session, chat_id: int):
        return SimpleNamespace(chat_id=chat_id)

    async def fake_update_mall_setting(session, setting, **kwargs):
        updates.append(kwargs)
        return setting

    async def fake_show_cover(update, context, chat_id: int):
        shown.append(chat_id)

    monkeypatch.setattr(admin_handler.PermissionPolicyService, "require_manage", fake_require_manage)
    monkeypatch.setattr(admin_handler, "clear_user_state", fake_clear_user_state)
    monkeypatch.setattr(admin_handler, "clear_private_input_state", fake_clear_private_input_state)
    monkeypatch.setattr(admin_handler.PointsExtendedService, "get_or_create_mall_setting", fake_get_or_create_mall_setting)
    monkeypatch.setattr(admin_handler.PointsExtendedService, "update_mall_setting", fake_update_mall_setting)
    monkeypatch.setattr(admin_handler._admin_handler, "_show_points_mall_cover_page", fake_show_cover)

    async def _reply_text(text):
        raise AssertionError(f"unexpected reply: {text}")

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=99),
        effective_message=SimpleNamespace(
            reply_text=_reply_text,
            photo=[SimpleNamespace(file_id="photo-file")],
            video=None,
        ),
    )
    context = SimpleNamespace()
    session = _FakeSession()
    state = SimpleNamespace(
        state_type="points_mall_cover_input",
        state_data={"target_chat_id": -2002},
        chat_id=99,
    )

    await handle_points_extended_input(update, context, session, state, "")

    assert updates == [{"cover_media_type": "photo", "cover_file_id": "photo-file"}]
    assert clear_calls == [(-2002, 99), (99, 99)]
    assert shown == [-2002]


@pytest.mark.asyncio
async def test_show_points_mall_menu_uses_configured_entry_command(monkeypatch):
    session = _FakeSession()
    db = _FakeDb(session)
    rendered: list[str] = []

    async def fake_set_current_chat(db, user_id: int, chat_id: int):
        return None

    async def fake_get_or_create_mall_setting(session, chat_id: int):
        return SimpleNamespace(
            entry_command="我的商城",
            enabled=True,
            auto_unlist_when_out_of_stock=False,
            redeem_notice_delete_seconds=0,
        )

    async def fake_safe_edit(update, *, text, reply_markup):
        rendered.append(text)

    monkeypatch.setattr(admin_handler._admin_handler, "_set_current_chat", fake_set_current_chat)
    monkeypatch.setattr(admin_handler.PointsExtendedService, "get_or_create_mall_setting", fake_get_or_create_mall_setting)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=42))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": db}))

    await admin_handler._admin_handler._show_points_mall_menu(update, context, -1001)

    assert rendered
    assert "群里输入 我的商城 唤起商品列表" in rendered[0]


@pytest.mark.asyncio
async def test_handle_points_extended_input_rejects_zero_level_threshold(monkeypatch):
    replies: list[str] = []
    update_calls: list[int] = []

    async def fake_require_manage(*args, **kwargs):
        return True, None

    async def fake_get_level(session, chat_id: int, level_id: int):
        return SimpleNamespace(id=level_id, level_name="一级", point_threshold=1)

    async def fake_update_level(session, level, **kwargs):
        update_calls.append(kwargs["point_threshold"])
        return level

    monkeypatch.setattr(admin_handler.PermissionPolicyService, "require_manage", fake_require_manage)
    monkeypatch.setattr(admin_handler.PointsExtendedService, "get_level", fake_get_level)
    monkeypatch.setattr(admin_handler.PointsExtendedService, "update_level", fake_update_level)

    async def _reply_text(text):
        replies.append(text)

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=42),
        effective_message=SimpleNamespace(reply_text=_reply_text),
    )
    context = SimpleNamespace()
    session = _FakeSession()
    state = SimpleNamespace(
        state_type="points_level_threshold_input",
        state_data={"target_chat_id": -1001, "level_id": 3},
        chat_id=42,
    )

    await handle_points_extended_input(update, context, session, state, "0")

    assert update_calls == []
    assert any("必须大于 0" in text for text in replies)


@pytest.mark.asyncio
async def test_points_handler_replies_when_custom_point_rank_command_is_disabled(monkeypatch):
    replies: list[str] = []

    async def fake_ensure_chat(*args, **kwargs):
        return None

    async def fake_ensure_user(*args, **kwargs):
        return None

    async def fake_get_chat_settings(*args, **kwargs):
        return SimpleNamespace(message_points_enabled=False)

    async def fake_get_mall_setting(*args, **kwargs):
        return SimpleNamespace(enabled=False, entry_command="积分商城")

    async def fake_get_level_setting(*args, **kwargs):
        return SimpleNamespace(enabled=False)

    async def fake_list_custom_point_types(*args, **kwargs):
        return [SimpleNamespace(id=7, name="出击分", rank_command="出击排行", enabled=False)]

    monkeypatch.setattr(points_handler_module, "ensure_chat", fake_ensure_chat)
    monkeypatch.setattr(points_handler_module, "ensure_user", fake_ensure_user)
    monkeypatch.setattr(points_handler_module, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(points_handler_module.PointsExtendedService, "get_or_create_mall_setting", fake_get_mall_setting)
    monkeypatch.setattr(points_handler_module.PointsExtendedService, "get_or_create_level_setting", fake_get_level_setting)
    monkeypatch.setattr(points_handler_module.PointsExtendedService, "list_custom_point_types", fake_list_custom_point_types)

    async def _reply_text(text):
        replies.append(text)

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-1001, type="supergroup", title="群组"),
        effective_user=SimpleNamespace(id=11, username="u", first_name="A", last_name=None, language_code="zh"),
        effective_message=SimpleNamespace(text="出击排行", reply_text=_reply_text),
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(_FakeSession())}))

    handler = PointsHandler()
    await handler.handle_message_points(update, context)

    assert replies == ["出击分 已关闭。"]


@pytest.mark.asyncio
async def test_handle_points_level_prevents_deleting_last_level(monkeypatch):
    alerts: list[str] = []
    detail_calls: list[tuple[int, int]] = []

    async def fake_list_levels(session, chat_id: int):
        return [SimpleNamespace(id=5, level_name="唯一等级", point_threshold=1)]

    async def fake_get_level(session, chat_id: int, level_id: int):
        return SimpleNamespace(id=level_id, level_name="唯一等级", point_threshold=1)

    async def fake_show_detail(update, context, chat_id: int, level_id: int):
        detail_calls.append((chat_id, level_id))

    async def fake_answer(update, text, show_alert=False):
        alerts.append(text)

    monkeypatch.setattr(admin_handler.PointsExtendedService, "list_levels", fake_list_levels)
    monkeypatch.setattr(admin_handler.PointsExtendedService, "get_level", fake_get_level)
    monkeypatch.setattr(admin_handler._admin_handler, "_show_points_level_detail", fake_show_detail)
    monkeypatch.setattr(admin_handler, "answer_callback_query_safely", fake_answer)

    update = SimpleNamespace(callback_query=SimpleNamespace())
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(_FakeSession())}))
    cb = CallbackParser.parse("adm:lvl:-1001:delete:5")

    await admin_handler._admin_handler._handle_points_level(update, context, -1001, cb)

    assert alerts == ["至少保留一个等级，无法删除"]
    assert detail_calls == [(-1001, 5)]


@pytest.mark.asyncio
async def test_handle_points_mall_preview_routes_to_preview_page(monkeypatch):
    preview_calls: list[tuple[int, int]] = []

    async def fake_preview(update, context, chat_id: int, product_id: int):
        preview_calls.append((chat_id, product_id))

    monkeypatch.setattr(admin_handler._admin_handler, "_show_points_mall_product_preview", fake_preview)

    update = SimpleNamespace(callback_query=SimpleNamespace())
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(_FakeSession())}))
    cb = CallbackParser.parse("adm:mall:-1001:product:preview:7")

    await admin_handler._admin_handler._handle_points_mall(update, context, -1001, cb)

    assert preview_calls == [(-1001, 7)]


@pytest.mark.asyncio
async def test_handle_custom_points_clear_confirm_renders_confirmation(monkeypatch):
    rendered: list[str] = []

    async def fake_get_custom_point_type(session, chat_id: int, type_id: int):
        return SimpleNamespace(id=type_id, name="出击分")

    async def fake_safe_edit(update, *, text, reply_markup):
        rendered.append(text)

    monkeypatch.setattr(admin_handler.PointsExtendedService, "get_custom_point_type", fake_get_custom_point_type)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace(callback_query=SimpleNamespace())
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(_FakeSession())}))
    cb = CallbackParser.parse("adm:cpt:-1001:clear_confirm:7")

    await admin_handler._admin_handler._handle_custom_points(update, context, -1001, cb)

    assert rendered
    assert "确认后将把此积分类型下所有用户余额清空" in rendered[0]


@pytest.mark.asyncio
async def test_handle_custom_points_delete_confirm_renders_confirmation(monkeypatch):
    rendered: list[str] = []

    async def fake_get_custom_point_type(session, chat_id: int, type_id: int):
        return SimpleNamespace(id=type_id, name="出击分")

    async def fake_safe_edit(update, *, text, reply_markup):
        rendered.append(text)

    monkeypatch.setattr(admin_handler.PointsExtendedService, "get_custom_point_type", fake_get_custom_point_type)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace(callback_query=SimpleNamespace())
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(_FakeSession())}))
    cb = CallbackParser.parse("adm:cpt:-1001:delete_confirm:7")

    await admin_handler._admin_handler._handle_custom_points(update, context, -1001, cb)

    assert rendered
    assert "确认后将删除该积分类型及其全部余额记录" in rendered[0]


@pytest.mark.asyncio
async def test_handle_points_extended_input_reports_validation_error_for_duplicate_rank(monkeypatch):
    replies: list[str] = []

    async def fake_require_manage(*args, **kwargs):
        return True, None

    async def fake_get_custom_point_type(session, chat_id: int, type_id: int):
        return SimpleNamespace(id=type_id, name="出击分")

    async def fake_update_custom_point_type(session, item, **kwargs):
        raise ValidationError("该排行指令已存在，请更换一个指令。")

    monkeypatch.setattr(admin_handler.PermissionPolicyService, "require_manage", fake_require_manage)
    monkeypatch.setattr(admin_handler.PointsExtendedService, "get_custom_point_type", fake_get_custom_point_type)
    monkeypatch.setattr(admin_handler.PointsExtendedService, "update_custom_point_type", fake_update_custom_point_type)

    async def _reply_text(text):
        replies.append(text)

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=42),
        effective_message=SimpleNamespace(reply_text=_reply_text),
    )
    context = SimpleNamespace()
    session = _FakeSession()
    state = SimpleNamespace(
        state_type="custom_points_rank_input",
        state_data={"target_chat_id": -1001, "type_id": 7},
        chat_id=42,
    )

    await handle_points_extended_input(update, context, session, state, "重复排行")

    assert replies == ["该排行指令已存在，请更换一个指令。"]


@pytest.mark.asyncio
async def test_handle_points_extended_input_reports_validation_error_for_duplicate_threshold(monkeypatch):
    replies: list[str] = []

    async def fake_require_manage(*args, **kwargs):
        return True, None

    async def fake_get_level(session, chat_id: int, level_id: int):
        return SimpleNamespace(id=level_id, level_name="一级", point_threshold=1)

    async def fake_update_level(session, level, **kwargs):
        raise ValidationError("该积分门槛已存在，请重新设置。")

    monkeypatch.setattr(admin_handler.PermissionPolicyService, "require_manage", fake_require_manage)
    monkeypatch.setattr(admin_handler.PointsExtendedService, "get_level", fake_get_level)
    monkeypatch.setattr(admin_handler.PointsExtendedService, "update_level", fake_update_level)

    async def _reply_text(text):
        replies.append(text)

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=42),
        effective_message=SimpleNamespace(reply_text=_reply_text),
    )
    context = SimpleNamespace()
    session = _FakeSession()
    state = SimpleNamespace(
        state_type="points_level_threshold_input",
        state_data={"target_chat_id": -1001, "level_id": 3},
        chat_id=42,
    )

    await handle_points_extended_input(update, context, session, state, "10")

    assert replies == ["该积分门槛已存在，请重新设置。"]


@pytest.mark.asyncio
async def test_points_handler_skips_level_restriction_for_teacher_when_excluded(monkeypatch):
    deleted: list[bool] = []
    replies: list[str] = []
    resolved_levels: list[bool] = []

    async def fake_ensure_chat(*args, **kwargs):
        return None

    async def fake_ensure_user(*args, **kwargs):
        return None

    async def fake_get_chat_settings(*args, **kwargs):
        return SimpleNamespace(message_points_enabled=False)

    async def fake_get_mall_setting(*args, **kwargs):
        return SimpleNamespace(enabled=False, entry_command="积分商城")

    async def fake_get_level_setting(*args, **kwargs):
        return SimpleNamespace(enabled=True, exclude_teacher_enabled=True)

    async def fake_is_teacher_exempt(*args, **kwargs):
        return True

    async def fake_resolve_user_level(*args, **kwargs):
        resolved_levels.append(True)
        return None

    async def fake_list_custom_point_types(*args, **kwargs):
        return []

    monkeypatch.setattr(points_handler_module, "ensure_chat", fake_ensure_chat)
    monkeypatch.setattr(points_handler_module, "ensure_user", fake_ensure_user)
    monkeypatch.setattr(points_handler_module, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(points_handler_module.PointsExtendedService, "get_or_create_mall_setting", fake_get_mall_setting)
    monkeypatch.setattr(points_handler_module.PointsExtendedService, "get_or_create_level_setting", fake_get_level_setting)
    monkeypatch.setattr(points_handler_module.PointsExtendedService, "is_teacher_exempt", fake_is_teacher_exempt)
    monkeypatch.setattr(points_handler_module.PointsExtendedService, "resolve_user_level", fake_resolve_user_level)
    monkeypatch.setattr(points_handler_module.PointsExtendedService, "list_custom_point_types", fake_list_custom_point_types)

    async def _delete():
        deleted.append(True)

    async def _reply_text(text):
        replies.append(text)

    message = SimpleNamespace(
        text="普通文本",
        sticker=None,
        audio=None,
        voice=None,
        video=None,
        photo=None,
        document=None,
        caption=None,
        entities=[],
        caption_entities=[],
        delete=_delete,
        reply_text=_reply_text,
    )
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-1001, type="supergroup", title="群组", send_message=_reply_text),
        effective_user=SimpleNamespace(id=11, username="u", first_name="A", last_name=None, language_code="zh"),
        effective_message=message,
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(_FakeSession())}))

    handler = PointsHandler()
    await handler.handle_message_points(update, context)

    assert deleted == []
    assert replies == []
    assert resolved_levels == []


@pytest.mark.asyncio
async def test_handle_points_mall_orders_routes_with_product_scope(monkeypatch):
    calls: list[tuple[int, int | None, str]] = []

    async def fake_show_orders(update, context, chat_id: int, product_id: int | None = None, status: str = "all"):
        calls.append((chat_id, product_id, status))

    monkeypatch.setattr(admin_handler._admin_handler, "_show_points_mall_orders_page", fake_show_orders)

    update = SimpleNamespace(callback_query=SimpleNamespace())
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(_FakeSession())}))
    cb = CallbackParser.parse("adm:mall:-1001:orders:7")

    await admin_handler._admin_handler._handle_points_mall(update, context, -1001, cb)

    assert calls == [(-1001, 7, "all")]


@pytest.mark.asyncio
async def test_handle_points_mall_orders_status_short_code(monkeypatch):
    calls: list[tuple[int, int | None, str]] = []

    async def fake_show_orders(update, context, chat_id: int, product_id: int | None = None, status: str = "all"):
        calls.append((chat_id, product_id, status))

    monkeypatch.setattr(admin_handler._admin_handler, "_show_points_mall_orders_page", fake_show_orders)

    update = SimpleNamespace(callback_query=SimpleNamespace())
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(_FakeSession())}))
    cb = CallbackParser.parse("adm:mall:-1001:orders_status:c:7")

    await admin_handler._admin_handler._handle_points_mall(update, context, -1001, cb)

    assert calls == [(-1001, 7, "created")]


@pytest.mark.asyncio
async def test_show_points_level_menu_uses_one_page_when_empty(monkeypatch):
    rendered: list[str] = []

    async def fake_set_current_chat(*args, **kwargs):
        return None

    async def fake_get_setting(session, chat_id: int):
        return SimpleNamespace(enabled=False, exclude_teacher_enabled=False)

    async def fake_list_levels(session, chat_id: int):
        return []

    async def fake_safe_edit(update, *, text, reply_markup):
        rendered.append(text)

    monkeypatch.setattr(admin_handler._admin_handler, "_set_current_chat", fake_set_current_chat)
    monkeypatch.setattr(admin_handler.PointsExtendedService, "get_or_create_level_setting", fake_get_setting)
    monkeypatch.setattr(admin_handler.PointsExtendedService, "list_levels", fake_list_levels)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=42))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(_FakeSession())}))

    await admin_handler._admin_handler._show_points_level_menu(update, context, -1001)

    assert rendered
    assert "0 条数据，第 1 页/共 1 页" in rendered[0]


@pytest.mark.asyncio
async def test_handle_points_extended_input_rejects_zero_mall_price(monkeypatch):
    replies: list[str] = []

    async def fake_require_manage(*args, **kwargs):
        return True, None

    async def fake_get_product(session, chat_id: int, product_id: int):
        return SimpleNamespace(product_id=product_id)

    monkeypatch.setattr(admin_handler.PermissionPolicyService, "require_manage", fake_require_manage)
    monkeypatch.setattr(admin_handler.PointsExtendedService, "get_product", fake_get_product)

    async def _reply_text(text):
        replies.append(text)

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=42),
        effective_message=SimpleNamespace(reply_text=_reply_text),
    )
    context = SimpleNamespace()
    session = _FakeSession()
    state = SimpleNamespace(
        state_type="points_mall_product_price_input",
        state_data={"target_chat_id": -1001, "product_id": 9},
        chat_id=42,
    )

    await handle_points_extended_input(update, context, session, state, "0")

    assert replies == ["所需积分必须大于 0。"]


@pytest.mark.asyncio
async def test_handle_points_extended_input_rejects_non_member_fulfiller(monkeypatch):
    replies: list[str] = []

    async def fake_require_manage(*args, **kwargs):
        return True, None

    async def fake_get_product(session, chat_id: int, product_id: int):
        return SimpleNamespace(product_id=product_id)

    async def fake_resolve_user_id(session, raw_value: str):
        return 7788

    async def fake_is_chat_member(session, chat_id: int, user_id: int):
        return False

    monkeypatch.setattr(admin_handler.PermissionPolicyService, "require_manage", fake_require_manage)
    monkeypatch.setattr(admin_handler.PointsExtendedService, "get_product", fake_get_product)
    monkeypatch.setattr(admin_handler.PointsExtendedService, "resolve_user_id", fake_resolve_user_id)
    monkeypatch.setattr(admin_handler.PointsExtendedService, "is_chat_member", fake_is_chat_member)

    async def _reply_text(text):
        replies.append(text)

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=42),
        effective_message=SimpleNamespace(reply_text=_reply_text),
    )
    context = SimpleNamespace()
    session = _FakeSession()
    state = SimpleNamespace(
        state_type="points_mall_fulfiller_input",
        state_data={"target_chat_id": -1001, "product_id": 9},
        chat_id=42,
    )

    await handle_points_extended_input(update, context, session, state, "@not_member")

    assert replies == ["发放人员必须是当前群组成员。"]


@pytest.mark.asyncio
async def test_show_mall_catalog_uses_cover_media_when_available():
    sent: list[tuple[str, str]] = []

    async def reply_photo(*, photo, caption, reply_markup):
        sent.append(("photo", photo))

    async def reply_text(text, reply_markup):
        sent.append(("text", text))

    handler = PointsHandler()
    update = SimpleNamespace(
        callback_query=None,
        effective_message=SimpleNamespace(reply_photo=reply_photo, reply_text=reply_text),
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={}))
    products = [SimpleNamespace(name="商品A", price_points=20, stock_left=5, product_id=1)]
    setting = SimpleNamespace(cover_file_id="cover123", cover_media_type="photo")

    await handler.show_mall_catalog(update, context, -1001, products=products, setting=setting)

    assert sent == [("photo", "cover123")]


def test_required_level_permission_supports_caption_mentions():
    message = SimpleNamespace(
        sticker=None,
        audio=None,
        voice=None,
        video=None,
        photo=None,
        document=None,
        text=None,
        caption="hello",
        entities=[],
        caption_entities=[SimpleNamespace(type="mention")],
    )

    assert _required_level_permission(message) == "allow_mention"
