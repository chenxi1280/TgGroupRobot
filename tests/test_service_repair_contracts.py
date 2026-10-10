from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.ext import Application, CommandHandler

from backend.features.admin.admin_handler import admin_command
from backend.features.admin.admin_router import AdminRouter
from backend.features.admin.runtime import ADM_ACTION_HANDLERS, PREFIX_HANDLERS, admin_runtime
from backend.features.points.services.points_extended_service import PointsExtendedService
from backend.shared.callback_parser import CallbackParser


@pytest.mark.parametrize('handler_name', [*PREFIX_HANDLERS.values(), *ADM_ACTION_HANDLERS.values()])
def test_real_admin_dispatch_signatures_accept_runtime_arguments(handler_name):
    handler = getattr(admin_runtime, handler_name)
    inspect.signature(handler).bind(None, None, -1001, callback_data=CallbackParser.parse('adm:menu:main:-1001'))


def test_admin_router_registers_command_handler_instead_of_callback():
    app = Application.builder().token('123:local-contract-test').build()
    AdminRouter().register(app)
    handlers = [handler for group in app.handlers.values() for handler in group]
    commands = [handler for handler in handlers if isinstance(handler, CommandHandler) and 'admin' in handler.commands]
    assert len(commands) == 1
    assert commands[0].callback is admin_command


@pytest.mark.asyncio
@pytest.mark.parametrize('setting', [None, SimpleNamespace(enabled=False)])
async def test_closed_or_missing_mall_rejects_before_product_or_points_access(setting):
    result = SimpleNamespace(scalar_one_or_none=lambda: setting)
    session = SimpleNamespace(execute=AsyncMock(return_value=result), add=AsyncMock(), flush=AsyncMock())
    success, message, order = await PointsExtendedService.redeem_product(
        session, chat_id=-1001, product_id=1, buyer_user_id=1,
    )
    assert (success, message, order) == (False, '商城已关闭', None)
    assert session.execute.await_count == 1
    statement = session.execute.call_args.args[0]
    assert statement._for_update_arg is not None
    session.add.assert_not_called()
    session.flush.assert_not_awaited()


def test_feature_registry_matches_actual_typed_menu_and_adapter_registry():
    from backend.features.admin.feature_registry import FEATURE_REGISTRATIONS
    from backend.shared.message_editor_adapter import MESSAGE_EDITOR_ADAPTERS
    menu = admin_runtime._menu_dispatch()
    assert len(FEATURE_REGISTRATIONS) == 38
    for feature, registration in FEATURE_REGISTRATIONS.items():
        assert feature in menu
        inspect.signature(menu[feature]).bind(None, None, -1001)
        assert registration.entry == f"adm:menu:{feature}:{{chat_id}}"
        if registration.message_adapter:
            assert registration.message_adapter in MESSAGE_EDITOR_ADAPTERS


def test_private_registry_adapters_bind_real_handler_signatures():
    import inspect
    from backend.platform.telegram.private_config_registry import build_private_config_handlers
    from backend.platform.telegram.private_config_adapters import _resolve_attr
    failures = []
    for state_name, handler in build_private_config_handlers().items():
        closure = inspect.getclosurevars(handler).nonlocals
        if 'module_path' not in closure:
            continue
        target = _resolve_attr(closure['module_path'], closure['func_name'])
        try:
            if handler.__qualname__.startswith('full_args_handler.'):
                inspect.signature(target).bind(None, None, None, state=None, message_text='')
            else:
                inspect.signature(target).bind(None, None)
        except TypeError as exc:
            failures.append((state_name, str(exc)))
    assert not failures


@pytest.mark.asyncio
async def test_private_full_adapter_passes_keyword_only_input(monkeypatch):
    from backend.platform.telegram import private_config_adapters as adapters
    received = []
    async def target(update, context, session, *, state, message_text):
        received.append((state, message_text))
    monkeypatch.setattr(adapters, '_resolve_attr', lambda *args: target)
    handler = adapters.full_args_handler('test', 'input')
    await handler(None, None, None, state='draft', message_text='body')
    assert received == [('draft', 'body')]
