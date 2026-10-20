"""Page navigation and confirmations via registered handlers and remote test DB."""
import pytest
import pytest_asyncio
from sqlalchemy import select

import test_component_input_postgres as component
import test_remaining_generic_postgres as remaining
from test_component_input_postgres import buttons, rendered
from test_admin_routes_postgres import callback_update, command_update
from backend.features.points.services.points_extended_service import PointsExtendedService
from backend.features.verification.welcome_service import WelcomeService
from backend.platform.db.schema.models.chat import ConversationState
from backend.platform.db.schema.models.welcome import WelcomeMessage

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not remaining.URL, reason="Shanghai isolated DB required")]


@pytest_asyncio.fixture
async def runtime():
    async for value in component.runtime.__wrapped__():
        yield value


async def click(app, user, data):
    await app.process_update(callback_update(app, user, 4100, data))


async def test_level_pages_keep_identity_and_return_position(runtime):
    app, db, b, chat, user = runtime
    async with db.session_factory() as s:
        levels = [await PointsExtendedService.create_level(s, chat) for _ in range(9)]
        for level in levels:
            level.level_name = "同名长标题" * 8
        ids = [level.id for level in levels]
        await s.commit()
    await click(app, user, f"adm:menu:points_level:{chat}")
    records = [x for x in buttons(b) if ":detail:" in x.get("callback_data", "")]
    assert len(records) == 8
    assert len({x['text'] for x in records}) == 8
    await click(app, user, f"adm:lvl:{chat}:page:1")
    assert str(ids[-1]) in rendered(b)['text']
    record = next(x for x in buttons(b) if ":detail:" in x.get("callback_data", ""))
    await click(app, user, record['callback_data'])
    await click(app, user, f'adm:lvl:{chat}:edit:name:{ids[-1]}')
    assert any(x.get('copy_text', {}).get('text') == '同名长标题' * 8 for x in buttons(b))
    await click(app, user, f'adm:lvl:{chat}:detail:{ids[-1]}')
    back = next(x['callback_data'] for x in buttons(b) if "返回" in x['text'])
    await click(app, user, back)
    assert "第 2 页" in rendered(b)['text']
    await click(app, user, f"pts:home:{chat}:display")
    assert any("points_display_rule_enabled" in x.get('callback_data', '') for x in buttons(b))
    await click(app, user, f"pts:home:{chat}:main")
    assert len(rendered(b)['reply_markup']['inline_keyboard']) <= 8


async def test_welcome_delete_cancel_version_change_and_reuse(runtime):
    app, db, b, chat, user = runtime
    async with db.session_factory() as s:
        item = await WelcomeService.create_message(s, chat)
        ident = item.id
        await s.commit()
    entry = f"adm:wel:{chat}:delete:{ident}"
    await click(app, user, entry)
    token = next(x['callback_data'] for x in buttons(b) if x['text'] == '确认执行')
    await click(app, user, f"adm:wel:{chat}:detail:{ident}")
    await click(app, user, token)
    async with db.session_factory() as s:
        assert await s.get(WelcomeMessage, ident) is not None
    await click(app, user, entry)
    token = next(x['callback_data'] for x in buttons(b) if x['text'] == '确认执行')
    async with db.session_factory() as s:
        await WelcomeService.update_field(s, chat, ident, title='并发修改')
        await s.commit()
    await click(app, user, token)
    async with db.session_factory() as s:
        assert (await s.get(WelcomeMessage, ident)).title == '并发修改'
    await click(app, user, entry)
    token = next(x['callback_data'] for x in buttons(b) if x['text'] == '确认执行')
    await click(app, user, token)
    async with db.session_factory() as s:
        assert await s.get(WelcomeMessage, ident) is None
    assert not any(int(p['chat_id']) < 0 for m, p in b.calls if m in {'sendMessage', 'sendPhoto'})


async def test_quick_publish_confirm_exits_input_and_cancel_keeps_draft(runtime):
    app, db, b, chat, user = runtime
    await click(app, user, f'qpub:input:{chat}:text')
    await app.process_update(command_update(app, user, user, 4200, '保留草稿'))
    await click(app, user, f'qpub:input:{chat}:text')
    await click(app, user, f'qpub:clear:{chat}')
    token = next(x['callback_data'] for x in buttons(b) if x['text'] == '确认执行')
    await app.process_update(command_update(app, user, user, 4201, '不能写入'))
    async with db.session_factory() as s:
        state = await s.scalar(select(ConversationState).where(ConversationState.user_id == user, ConversationState.chat_id == user))
        assert state.state_type == 'selected_chat'
    await click(app, user, f'qpub:home:{chat}')
    await click(app, user, token)
    draft = app.user_data[user]['quick_publish_draft'][str(chat)]
    assert draft['text'] == '保留草稿'
    await click(app, user, f'qpub:clear:{chat}')
    token = next(x['callback_data'] for x in buttons(b) if x['text'] == '确认执行')
    await click(app, user, token)
    assert draft['text'] == ''
    assert not any(int(p['chat_id']) < 0 for m, p in b.calls if m in {'sendMessage', 'sendPhoto'})


async def test_points_cancel_after_navigation_cleanup_renders_home_and_ignores_text(runtime):
    from backend.platform.db.schema.models.chat import ChatSettings
    app, db, b, chat, user = runtime
    async with db.session_factory() as s:
        previous = (await s.get(ChatSettings, chat)).points_alias
    await click(app, user, f'pts:edit:points_alias:{chat}')
    await click(app, user, f'pts:home:{chat}')
    assert any(x.get('callback_data') == f'pts:rule:checkin:{chat}' for x in buttons(b))
    from telegram import Update
    raw = command_update(app, user, user, 4400, '取消后不得保存').to_dict()
    raw['message'].pop('entities', None)
    await app.process_update(Update.de_json(raw, app.bot))
    async with db.session_factory() as s:
        assert (await s.get(ChatSettings, chat)).points_alias == previous
    assert 'points_edit_field' not in app.user_data[user]


async def test_bottom_clear_confirmation_cancel_preserves_grid(runtime):
    from backend.platform.db.schema.models.expansion_bottom_button import BottomButtonLayout
    app, db, b, chat, user = runtime
    await click(app, user, f'btm:layout:{chat}:add:1:1')
    async with db.session_factory() as s:
        before = list((await s.scalars(select(BottomButtonLayout).where(BottomButtonLayout.chat_id == chat))).all())
        assert before
    await click(app, user, f'btm:layout:{chat}:clear')
    token = next(x['callback_data'] for x in buttons(b) if x['text'] == '确认执行')
    await click(app, user, f'btm:layout:{chat}:edit')
    await click(app, user, token)
    async with db.session_factory() as s:
        assert len(list((await s.scalars(select(BottomButtonLayout).where(BottomButtonLayout.chat_id == chat))).all())) == len(before)
    await click(app, user, f'btm:layout:{chat}:clear')
    token = next(x['callback_data'] for x in buttons(b) if x['text'] == '确认执行')
    await click(app, user, token)
    async with db.session_factory() as s:
        assert not list((await s.scalars(select(BottomButtonLayout).where(BottomButtonLayout.chat_id == chat))).all())
    assert not any(int(p['chat_id']) < 0 for m, p in b.calls if m in {'sendMessage','sendPhoto'})


async def test_exited_points_conversation_does_not_swallow_next_editors_first_text(runtime):
    from test_component_input_postgres import tasks
    from backend.features.automation.services.scheduled_message_service import ScheduledMessageService
    app, db, b, chat, user = runtime
    task, _ = await tasks(db, chat, user)
    await click(app, user, f'pts:edit:points_alias:{chat}')
    await click(app, user, f'sm:open:{chat}:{task}')
    await click(app, user, f'sm:edit:{chat}:{task}:repeat_custom')
    raw = command_update(app, user, user, 4500, '137').to_dict()
    raw['message'].pop('entities', None)
    from telegram import Update
    await app.process_update(Update.de_json(raw, app.bot))
    async with db.session_factory() as s:
        assert (await ScheduledMessageService.get_task_in_chat_or_404(s, chat, task)).repeat_interval_min == 137


@pytest.mark.parametrize('feature', ['custom', 'welcome'])
async def test_new_ninth_record_returns_to_last_page(runtime, feature):
    app, db, b, chat, user = runtime
    async with db.session_factory() as s:
        for _ in range(8):
            if feature == 'custom':
                await PointsExtendedService.create_custom_point_type(s, chat, user)
            else:
                await WelcomeService.create_message(s, chat)
        await s.commit()
    prefix = 'cpt' if feature == 'custom' else 'wel'
    await click(app, user, f'adm:{prefix}:{chat}:add')
    back = next(x['callback_data'] for x in buttons(b) if '返回' in x['text'])
    await click(app, user, back)
    assert '第 2 页/共 2 页' in rendered(b)['text']
    records = [x for x in buttons(b) if ':detail:' in x.get('callback_data','')]
    assert len(records) == 1
