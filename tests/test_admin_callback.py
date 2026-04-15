from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.admin import callback_flow
from backend.features.admin import admin_handler
from backend.shared.ui.base.helpers import create_back_button


@pytest.mark.asyncio
async def test_group_admin_callback_delegates_points_level_callbacks(monkeypatch):
    calls: list[tuple[str, int]] = []

    class _Session:
        async def commit(self) -> None:
            calls.append(("commit", 1))

    class _SessionContext:
        async def __aenter__(self):
            return _Session()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Db:
        def session_factory(self):
            return _SessionContext()

    async def fake_is_user_admin(context, chat_id: int, user_id: int):
        calls.append(("admin_check", chat_id))
        return True

    async def fake_ensure_chat(session, *, chat_id: int, chat_type: str, title: str):
        calls.append(("ensure_chat", chat_id))

    async def fake_get_chat_settings(session, chat_id: int):
        calls.append(("settings", chat_id))
        return SimpleNamespace(language="zh")

    async def fake_process(update, context, target_chat_id: int):
        calls.append(("process", target_chat_id))

    monkeypatch.setattr(callback_flow, "is_user_admin", fake_is_user_admin)
    monkeypatch.setattr(callback_flow, "ensure_chat", fake_ensure_chat)
    monkeypatch.setattr(callback_flow, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(callback_flow.admin_runtime, "process", fake_process)

    class _Q:
        data = "adm:lvl:-1001:add"

    update = SimpleNamespace(
        callback_query=_Q(),
        effective_chat=SimpleNamespace(id=-1001, type="supergroup", title="群"),
        effective_user=SimpleNamespace(id=42),
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await admin_handler.admin_callback(update, context)

    assert calls == [
        ("admin_check", -1001),
        ("ensure_chat", -1001),
        ("settings", -1001),
        ("commit", 1),
        ("process", -1001),
    ]


@pytest.mark.asyncio
async def test_admin_callback_handles_two_part_action_in_private(monkeypatch):
    called: dict[str, int] = {}

    async def fake_process(update, context, target_chat_id: int):
        called["target_chat_id"] = target_chat_id

    monkeypatch.setattr(admin_handler._admin_handler, "process", fake_process)

    class _Q:
        data = "adm:switch_group"

        async def answer(self, *args, **kwargs):
            return None

    update = SimpleNamespace(
        callback_query=_Q(),
        effective_chat=SimpleNamespace(type="private"),
        effective_user=SimpleNamespace(id=12345),
    )
    context = SimpleNamespace()

    await admin_handler.admin_callback(update, context)

    assert called == {"target_chat_id": 0}


@pytest.mark.asyncio
async def test_admin_callback_handles_legacy_chat_first_menu_callback(monkeypatch):
    called: dict[str, int] = {}

    async def fake_process(update, context, target_chat_id: int):
        called["target_chat_id"] = target_chat_id

    async def fake_require_manage(*args, **kwargs):
        return True, None

    monkeypatch.setattr(admin_handler._admin_handler, "process", fake_process)
    monkeypatch.setattr(admin_handler.PermissionPolicyService, "require_manage", fake_require_manage)

    class _Q:
        data = "adm:menu:-1005566:sm:list"

        async def answer(self, *args, **kwargs):
            return None

    update = SimpleNamespace(
        callback_query=_Q(),
        effective_chat=SimpleNamespace(type="private"),
        effective_user=SimpleNamespace(id=12345),
    )
    context = SimpleNamespace()

    await admin_handler.admin_callback(update, context)

    assert called == {"target_chat_id": -1005566}


@pytest.mark.asyncio
async def test_admin_callback_invalid_private_menu_answers_without_recursion():
    answers: list[tuple[str, bool]] = []

    class _Q:
        data = "adm:menu:sm:list"
        id = "invalid-menu"

        async def answer(self, text: str = "", show_alert: bool = False):
            answers.append((text, show_alert))

    update = SimpleNamespace(
        callback_query=_Q(),
        effective_chat=SimpleNamespace(type="private"),
        effective_user=SimpleNamespace(id=12345),
    )
    context = SimpleNamespace()

    await admin_handler.admin_callback(update, context)

    assert answers == [("❌ 群组参数无效，请返回重试", True)]


def test_create_back_button_uses_admin_menu_order() -> None:
    button = create_back_button(-1005566, "main")

    assert button.callback_data == "adm:menu:main:-1005566"


@pytest.mark.asyncio
async def test_admin_callback_handles_alliance_prefix_in_private(monkeypatch):
    called: dict[str, int] = {}

    async def fake_process(update, context, target_chat_id: int):
        called["target_chat_id"] = target_chat_id

    monkeypatch.setattr(admin_handler._admin_handler, "process", fake_process)

    async def fake_require_manage(*args, **kwargs):
        return True, None

    monkeypatch.setattr(admin_handler.PermissionPolicyService, "require_manage", fake_require_manage)

    class _Q:
        data = "ali:members:-1005566"

        async def answer(self, *args, **kwargs):
            return None

    update = SimpleNamespace(
        callback_query=_Q(),
        effective_chat=SimpleNamespace(type="private"),
        effective_user=SimpleNamespace(id=12345),
    )
    context = SimpleNamespace()

    await admin_handler.admin_callback(update, context)

    assert called == {"target_chat_id": -1005566}


@pytest.mark.asyncio
async def test_admin_callback_handles_garage_forward_prefix_in_private(monkeypatch):
    called: dict[str, int] = {}

    async def fake_process(update, context, target_chat_id: int):
        called["target_chat_id"] = target_chat_id

    monkeypatch.setattr(admin_handler._admin_handler, "process", fake_process)

    async def fake_require_manage(*args, **kwargs):
        return True, None

    monkeypatch.setattr(admin_handler.PermissionPolicyService, "require_manage", fake_require_manage)

    class _Q:
        data = "gfw:home:-1007788"

        async def answer(self, *args, **kwargs):
            return None

    update = SimpleNamespace(
        callback_query=_Q(),
        effective_chat=SimpleNamespace(type="private"),
        effective_user=SimpleNamespace(id=12345),
    )
    context = SimpleNamespace()

    await admin_handler.admin_callback(update, context)

    assert called == {"target_chat_id": -1007788}


@pytest.mark.asyncio
async def test_admin_callback_handles_todo_action_in_private(monkeypatch):
    called: dict[str, int] = {}

    async def fake_process(update, context, target_chat_id: int):
        called["target_chat_id"] = target_chat_id

    monkeypatch.setattr(admin_handler._admin_handler, "process", fake_process)

    async def fake_require_manage(*args, **kwargs):
        return True, None

    monkeypatch.setattr(admin_handler.PermissionPolicyService, "require_manage", fake_require_manage)

    class _Q:
        data = "adm:todo:-1009900:auction"

        async def answer(self, *args, **kwargs):
            return None

    update = SimpleNamespace(
        callback_query=_Q(),
        effective_chat=SimpleNamespace(type="private"),
        effective_user=SimpleNamespace(id=12345),
    )
    context = SimpleNamespace()

    await admin_handler.admin_callback(update, context)

    assert called == {"target_chat_id": -1009900}


@pytest.mark.asyncio
async def test_admin_callback_handles_auction_prefix_in_private(monkeypatch):
    called: dict[str, int] = {}

    async def fake_process(update, context, target_chat_id: int):
        called["target_chat_id"] = target_chat_id

    monkeypatch.setattr(admin_handler._admin_handler, "process", fake_process)

    async def fake_require_manage(*args, **kwargs):
        return True, None

    monkeypatch.setattr(admin_handler.PermissionPolicyService, "require_manage", fake_require_manage)

    class _Q:
        data = "auc:home:-1009900"

        async def answer(self, *args, **kwargs):
            return None

    update = SimpleNamespace(
        callback_query=_Q(),
        effective_chat=SimpleNamespace(type="private"),
        effective_user=SimpleNamespace(id=12345),
    )
    context = SimpleNamespace()

    await admin_handler.admin_callback(update, context)

    assert called == {"target_chat_id": -1009900}


@pytest.mark.asyncio
async def test_admin_callback_handles_bottom_button_prefix_in_private(monkeypatch):
    called: dict[str, int] = {}

    async def fake_process(update, context, target_chat_id: int):
        called["target_chat_id"] = target_chat_id

    monkeypatch.setattr(admin_handler._admin_handler, "process", fake_process)

    async def fake_require_manage(*args, **kwargs):
        return True, None

    monkeypatch.setattr(admin_handler.PermissionPolicyService, "require_manage", fake_require_manage)

    class _Q:
        data = "btm:home:-1009900"

        async def answer(self, *args, **kwargs):
            return None

    update = SimpleNamespace(
        callback_query=_Q(),
        effective_chat=SimpleNamespace(type="private"),
        effective_user=SimpleNamespace(id=12345),
    )
    context = SimpleNamespace()

    await admin_handler.admin_callback(update, context)

    assert called == {"target_chat_id": -1009900}


@pytest.mark.asyncio
async def test_admin_callback_handles_game_prefix_in_private(monkeypatch):
    called: dict[str, int] = {}

    async def fake_process(update, context, target_chat_id: int):
        called["target_chat_id"] = target_chat_id

    monkeypatch.setattr(admin_handler._admin_handler, "process", fake_process)

    async def fake_require_manage(*args, **kwargs):
        return True, None

    monkeypatch.setattr(admin_handler.PermissionPolicyService, "require_manage", fake_require_manage)

    class _Q:
        data = "gm:home:-1009900"

        async def answer(self, *args, **kwargs):
            return None

    update = SimpleNamespace(
        callback_query=_Q(),
        effective_chat=SimpleNamespace(type="private"),
        effective_user=SimpleNamespace(id=12345),
    )
    context = SimpleNamespace()

    await admin_handler.admin_callback(update, context)

    assert called == {"target_chat_id": -1009900}


@pytest.mark.asyncio
async def test_admin_callback_handles_game_detail_prefix_in_private(monkeypatch):
    called: dict[str, int] = {}

    async def fake_process(update, context, target_chat_id: int):
        called["target_chat_id"] = target_chat_id

    monkeypatch.setattr(admin_handler._admin_handler, "process", fake_process)

    async def fake_require_manage(*args, **kwargs):
        return True, None

    monkeypatch.setattr(admin_handler.PermissionPolicyService, "require_manage", fake_require_manage)

    class _Q:
        data = "gm:detail:-1009900:12"

        async def answer(self, *args, **kwargs):
            return None

    update = SimpleNamespace(
        callback_query=_Q(),
        effective_chat=SimpleNamespace(type="private"),
        effective_user=SimpleNamespace(id=12345),
    )
    context = SimpleNamespace()

    await admin_handler.admin_callback(update, context)

    assert called == {"target_chat_id": -1009900}


@pytest.mark.asyncio
async def test_admin_callback_handles_guess_prefix_in_private(monkeypatch):
    called: dict[str, int] = {}

    async def fake_process(update, context, target_chat_id: int):
        called["target_chat_id"] = target_chat_id

    monkeypatch.setattr(admin_handler._admin_handler, "process", fake_process)

    async def fake_require_manage(*args, **kwargs):
        return True, None

    monkeypatch.setattr(admin_handler.PermissionPolicyService, "require_manage", fake_require_manage)

    class _Q:
        data = "guess:home:-1009900"

        async def answer(self, *args, **kwargs):
            return None

    update = SimpleNamespace(
        callback_query=_Q(),
        effective_chat=SimpleNamespace(type="private"),
        effective_user=SimpleNamespace(id=12345),
    )
    context = SimpleNamespace()

    await admin_handler.admin_callback(update, context)

    assert called == {"target_chat_id": -1009900}


@pytest.mark.asyncio
async def test_admin_callback_handles_auction_list_prefix_in_private(monkeypatch):
    called: dict[str, int] = {}

    async def fake_process(update, context, target_chat_id: int):
        called["target_chat_id"] = target_chat_id

    monkeypatch.setattr(admin_handler._admin_handler, "process", fake_process)

    async def fake_require_manage(*args, **kwargs):
        return True, None

    monkeypatch.setattr(admin_handler.PermissionPolicyService, "require_manage", fake_require_manage)

    class _Q:
        data = "auc:list:-1009900:0"

        async def answer(self, *args, **kwargs):
            return None

    update = SimpleNamespace(
        callback_query=_Q(),
        effective_chat=SimpleNamespace(type="private"),
        effective_user=SimpleNamespace(id=12345),
    )
    context = SimpleNamespace()

    await admin_handler.admin_callback(update, context)

    assert called == {"target_chat_id": -1009900}


@pytest.mark.asyncio
async def test_admin_callback_handles_garage_forward_keywords_prefix_in_private(monkeypatch):
    called: dict[str, int] = {}

    async def fake_process(update, context, target_chat_id: int):
        called["target_chat_id"] = target_chat_id

    monkeypatch.setattr(admin_handler._admin_handler, "process", fake_process)

    async def fake_require_manage(*args, **kwargs):
        return True, None

    monkeypatch.setattr(admin_handler.PermissionPolicyService, "require_manage", fake_require_manage)

    class _Q:
        data = "gfw:keywords:input:-1009900"

        async def answer(self, *args, **kwargs):
            return None

    update = SimpleNamespace(
        callback_query=_Q(),
        effective_chat=SimpleNamespace(type="private"),
        effective_user=SimpleNamespace(id=12345),
    )
    context = SimpleNamespace()

    await admin_handler.admin_callback(update, context)

    assert called == {"target_chat_id": -1009900}


@pytest.mark.asyncio
async def test_admin_callback_handles_teacher_search_attendance_prefix_in_private(monkeypatch):
    called: dict[str, int] = {}

    async def fake_process(update, context, target_chat_id: int):
        called["target_chat_id"] = target_chat_id

    monkeypatch.setattr(admin_handler._admin_handler, "process", fake_process)

    async def fake_require_manage(*args, **kwargs):
        return True, None

    monkeypatch.setattr(admin_handler.PermissionPolicyService, "require_manage", fake_require_manage)

    class _Q:
        data = "tsearch:attendance:menu:-1009900"

        async def answer(self, *args, **kwargs):
            return None

    update = SimpleNamespace(
        callback_query=_Q(),
        effective_chat=SimpleNamespace(type="private"),
        effective_user=SimpleNamespace(id=12345),
    )
    context = SimpleNamespace()

    await admin_handler.admin_callback(update, context)

    assert called == {"target_chat_id": -1009900}


@pytest.mark.asyncio
async def test_admin_callback_handles_teacher_search_attendance_mode_prefix_in_private(monkeypatch):
    called: dict[str, int] = {}

    async def fake_process(update, context, target_chat_id: int):
        called["target_chat_id"] = target_chat_id

    monkeypatch.setattr(admin_handler._admin_handler, "process", fake_process)

    async def fake_require_manage(*args, **kwargs):
        return True, None

    monkeypatch.setattr(admin_handler.PermissionPolicyService, "require_manage", fake_require_manage)

    class _Q:
        data = "tsearch:attendance_mode:menu:-1009900"

        async def answer(self, *args, **kwargs):
            return None

    update = SimpleNamespace(
        callback_query=_Q(),
        effective_chat=SimpleNamespace(type="private"),
        effective_user=SimpleNamespace(id=12345),
    )
    context = SimpleNamespace()

    await admin_handler.admin_callback(update, context)

    assert called == {"target_chat_id": -1009900}


@pytest.mark.asyncio
async def test_admin_callback_handles_teacher_search_attendance_source_mode_prefix_in_private(monkeypatch):
    called: dict[str, int] = {}

    async def fake_process(update, context, target_chat_id: int):
        called["target_chat_id"] = target_chat_id

    monkeypatch.setattr(admin_handler._admin_handler, "process", fake_process)

    async def fake_require_manage(*args, **kwargs):
        return True, None

    monkeypatch.setattr(admin_handler.PermissionPolicyService, "require_manage", fake_require_manage)

    class _Q:
        data = "tsearch:attendance_source_mode:set:-1009900:-1008800:message"

        async def answer(self, *args, **kwargs):
            return None

    update = SimpleNamespace(
        callback_query=_Q(),
        effective_chat=SimpleNamespace(type="private"),
        effective_user=SimpleNamespace(id=12345),
    )
    context = SimpleNamespace()

    await admin_handler.admin_callback(update, context)

    assert called == {"target_chat_id": -1009900}


@pytest.mark.asyncio
async def test_admin_callback_handles_teacher_search_delegate_prefix_in_private(monkeypatch):
    called: dict[str, int] = {}

    async def fake_process(update, context, target_chat_id: int):
        called["target_chat_id"] = target_chat_id

    monkeypatch.setattr(admin_handler._admin_handler, "process", fake_process)

    async def fake_require_manage(*args, **kwargs):
        return True, None

    monkeypatch.setattr(admin_handler.PermissionPolicyService, "require_manage", fake_require_manage)

    class _Q:
        data = "tsearch:delegate:start:-1009900"

        async def answer(self, *args, **kwargs):
            return None

    update = SimpleNamespace(
        callback_query=_Q(),
        effective_chat=SimpleNamespace(type="private"),
        effective_user=SimpleNamespace(id=12345),
    )
    context = SimpleNamespace()

    await admin_handler.admin_callback(update, context)

    assert called == {"target_chat_id": -1009900}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "callback_data",
    [
        "tsearch:footer:menu:-1009900",
        "tsearch:footer:text:-1009900",
        "tsearch:footer:link:-1009900",
    ],
)
async def test_admin_callback_handles_teacher_search_footer_prefix_in_private(monkeypatch, callback_data):
    called: dict[str, int] = {}

    async def fake_process(update, context, target_chat_id: int):
        called["target_chat_id"] = target_chat_id

    monkeypatch.setattr(admin_handler._admin_handler, "process", fake_process)

    async def fake_require_manage(*args, **kwargs):
        return True, None

    monkeypatch.setattr(admin_handler.PermissionPolicyService, "require_manage", fake_require_manage)

    class _Q:
        data = callback_data

        async def answer(self, *args, **kwargs):
            return None

    update = SimpleNamespace(
        callback_query=_Q(),
        effective_chat=SimpleNamespace(type="private"),
        effective_user=SimpleNamespace(id=12345),
    )
    context = SimpleNamespace()

    await admin_handler.admin_callback(update, context)

    assert called == {"target_chat_id": -1009900}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "callback_data",
    [
        "ali:jointban:toggle:-1009900:1",
        "ali:jointban:toggle:-1009900:0",
        "ali:invite:show:-1009900",
        "ali:invite:denied:-1009900",
        "gfw:btn_toggle:-1009900:1",
        "gfw:btn_toggle:-1009900:0",
        "gfw:buttons:input:-1009900",
        "gfw:buttons:apply:-1009900",
        "grg:limit:toggle:-1009900:1",
        "grg:limit:toggle:-1009900:0",
        "grg:limit:mode:-1009900:image",
        "grg:limit:mode:-1009900:image_text",
        "grg:limit:mode:-1009900:none",
        "grg:summary:menu:-1009900",
        "grg:summary:partition:-1009900:region",
        "grg:summary:partition:-1009900:price",
        "grg:summary:open:-1009900:1",
        "grg:summary:open:-1009900:0",
        "grg:summary:gen:-1009900",
        "crv:submit_cmd:edit:-1009900",
        "crv:rank_cmd:edit:-1009900",
        "crv:approver:set:-1009900",
        "crv:template:edit:-1009900",
        "qpub:home:-1009900",
        "qpub:clear:-1009900",
        "qpub:send:-1009900",
    ],
)
async def test_admin_callback_handles_nested_private_callback_chat_ids(monkeypatch, callback_data):
    called: dict[str, int] = {}

    async def fake_process(update, context, target_chat_id: int):
        called["target_chat_id"] = target_chat_id

    monkeypatch.setattr(admin_handler._admin_handler, "process", fake_process)

    async def fake_require_manage(*args, **kwargs):
        return True, None

    monkeypatch.setattr(admin_handler.PermissionPolicyService, "require_manage", fake_require_manage)

    class _Q:
        data = callback_data

        async def answer(self, *args, **kwargs):
            return None

    update = SimpleNamespace(
        callback_query=_Q(),
        effective_chat=SimpleNamespace(type="private"),
        effective_user=SimpleNamespace(id=12345),
    )
    context = SimpleNamespace()

    await admin_handler.admin_callback(update, context)

    assert called == {"target_chat_id": -1009900}


@pytest.mark.asyncio
async def test_admin_callback_handles_engagement_prefix_in_private(monkeypatch):
    called: dict[str, int] = {}

    async def fake_process(update, context, target_chat_id: int):
        called["target_chat_id"] = target_chat_id

    monkeypatch.setattr(admin_handler._admin_handler, "process", fake_process)

    async def fake_require_manage(*args, **kwargs):
        return True, None

    monkeypatch.setattr(admin_handler.PermissionPolicyService, "require_manage", fake_require_manage)

    class _Q:
        data = "act:home:-1009900"

        async def answer(self, *args, **kwargs):
            return None

    update = SimpleNamespace(
        callback_query=_Q(),
        effective_chat=SimpleNamespace(type="private"),
        effective_user=SimpleNamespace(id=12345),
    )
    context = SimpleNamespace()

    await admin_handler.admin_callback(update, context)

    assert called == {"target_chat_id": -1009900}
