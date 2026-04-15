from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.admin import admin_handler
from backend.shared.ui.base.helpers import create_back_button


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
