"""Actual registered callbacks on disposable Postgres; Telegram transport is fake."""
import copy

import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.platform.db.schema.models.chat import ChatSettings, ConversationState
from test_admin_routes_postgres import callback_update, command_update
import test_remaining_generic_postgres as remaining

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not remaining.URL, reason='disposable Postgres required')]


@pytest_asyncio.fixture
async def runtime():
    async for value in remaining.runtime.__wrapped__():
        yield value


def last_markup(boundary):
    return [params for endpoint, params in boundary.calls
        if endpoint in {'sendMessage','editMessageText'}][-1]['reply_markup']['inline_keyboard']


async def test_compact_notice_buttons_keep_input_cancel_scope_and_no_group_delivery(runtime):
    app, db, boundary, chat, user = runtime
    await app.process_update(callback_update(app, user, 100, f'gnote:{chat}:closed:view'))
    rows = last_markup(boundary)
    assert [len(row) for row in rows] == [2, 2, 2, 2, 1]
    buttons = {b['text']: b['callback_data'] for row in rows for b in row}
    assert buttons['通知文案'] == f'gnote:{chat}:closed:input:text'
    assert buttons['预览配置'] == f'gnote:{chat}:closed:preview'
    await app.process_update(callback_update(app, user, 101, buttons['通知文案']))
    cancel = last_markup(boundary)[0][0]['callback_data']
    assert cancel == f'gnote:{chat}:closed:view'
    await app.process_update(callback_update(app, user, 102, cancel))
    await app.process_update(command_update(app, user, user, 103, '不应保存的文本'))
    async with db.session_factory() as session:
        settings = await session.get(ChatSettings, chat)
        assert not settings.module_config
        state = await session.scalar(select(ConversationState).where(
            ConversationState.chat_id == user, ConversationState.user_id == user))
        assert state.state_type == 'selected_chat'
    assert not any(int(params['chat_id']) < 0 for endpoint, params in boundary.calls
        if endpoint in {'sendMessage', 'sendPhoto', 'setChatPermissions'})


@pytest.mark.parametrize('mode', ['import', 'clone'])
async def test_compact_module_picker_retains_selections_scope_and_return(runtime, mode):
    app, db, boundary, chat, user = runtime
    await app.process_update(callback_update(app, user, 200, f'adm:{mode}:{chat}:pick_modules'))
    rows = last_markup(boundary)
    rendered = [params for endpoint, params in boundary.calls if endpoint in {'sendMessage', 'editMessageText'}][-1]
    assert f'群：{chat}' in rendered['text'] and '点选切换勾选；返回设置页后再执行。' in rendered['text']
    assert all(len(row) == 2 for row in rows[:-2])
    assert len(rows[-1]) == 1 and '返回' in rows[-1][0]['text']
    selected = rows[0][1]['callback_data']
    assert selected.startswith(f'adm:{mode}:{chat}:module:')
    await app.process_update(callback_update(app, user, 201, selected))
    updated = last_markup(boundary)
    assert updated[0][1]['callback_data'] == selected
    assert updated[0][1]['text'].startswith('✅')
    await app.process_update(callback_update(app, user, 202, updated[-1][0]['callback_data']))
    assert last_markup(boundary)[0][0]['callback_data'].startswith(f'adm:{mode}:{chat}:pick_')
    async with db.session_factory() as session:
        original = copy.deepcopy((await session.get(ChatSettings, chat)).module_config)
    # Revoke the actor before clicking an old compact-page mutation.
    boundary.member(user)
    before = len(boundary.calls)
    selections = copy.deepcopy(dict(app.user_data[user]))
    await app.process_update(callback_update(app, user, 203, selected))
    assert any(endpoint in {'editMessageText', 'sendMessage'} and '需要管理员权限' in params.get('text', '')
        for endpoint, params in boundary.calls[before:])
    assert dict(app.user_data[user]) == selections
    async with db.session_factory() as session:
        assert (await session.get(ChatSettings, chat)).module_config == original
    assert not any(endpoint in {'setChatPermissions', 'banChatMember', 'sendPhoto'} for endpoint, _ in boundary.calls)


async def test_modern_permission_bits_survive_snapshot_save_plan_and_execution(runtime):
    import datetime as dt
    import json
    from backend.features.admin.services.effect_runtime import run_pending
    from backend.features.group_ops.services.lock_plans import plan_phrase
    from backend.platform.db.schema.models.admin_effects import AdminEffect

    app, db, boundary, chat, user = runtime
    boundary.faults['getChat'] = [(200, json.dumps({'ok': True, 'result': {
        'id': chat, 'type': 'supergroup', 'title': 'isolated', 'accent_color_id': 0,
        'max_reaction_count': 1, 'permissions': {'can_send_messages': True,
            'can_pin_messages': True, 'can_react_to_messages': True, 'can_edit_tag': False}}}).encode())]
    for index, (key, value) in enumerate((('pin', 1), ('react', 0), ('tag', 0)), 400):
        await app.process_update(callback_update(app, user, index, f'gperm:{chat}:open:set:{key}:{value}'))
    assert not any(endpoint == 'setChatPermissions' for endpoint, _ in boundary.calls)
    rows = last_markup(boundary)
    assert any(row[0]['text'] == '消息表情回应' and len(row) == 3 for row in rows)
    assert any(row[0]['text'] == '修改自己的标签' and len(row) == 3 for row in rows)
    async with db.session_factory() as session:
        settings = await session.get(ChatSettings, chat)
        cfg = settings.module_config['group_lock']
        assert cfg['original_permissions']['can_react_to_messages'] is True
        assert cfg['original_permissions']['can_edit_tag'] is False
        assert cfg['profiles']['open']['can_react_to_messages'] is False
        assert cfg['profiles']['open']['can_edit_tag'] is False
        settings.group_lock_phrase_enabled = True
        await session.commit()
    now = dt.datetime.now(dt.UTC)
    effect_id = await plan_phrase(db, chat_id=chat, message_id=901, closed=False, now=now, user_id=user)
    # Payload is loaded back by the durable worker, through the real SDK serializer.
    await run_pending(app, now=now, chat_id=chat)
    sent = [params for endpoint, params in boundary.calls if endpoint == 'setChatPermissions']
    assert len(sent) == 1
    assert sent[0]['permissions']['can_send_messages'] is True
    assert sent[0]['permissions']['can_pin_messages'] is True
    assert sent[0]['permissions']['can_react_to_messages'] is False
    assert sent[0]['permissions']['can_edit_tag'] is False
    assert sent[0]['use_independent_chat_permissions'] is True
    async with db.session_factory() as session:
        assert (await session.get(AdminEffect, effect_id)).status == 'succeeded'
    await run_pending(app, now=now, chat_id=chat)
    assert len([1 for endpoint, _ in boundary.calls if endpoint == 'setChatPermissions']) == 1
