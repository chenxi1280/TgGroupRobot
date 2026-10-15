"""Real registered routes and PostgreSQL, with only Telegram transport replaced."""
import os
import secrets
import time
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from telegram.ext import Application, MessageHandler, filters

from backend.app.update_pipeline import MessageDispatcher
from backend.features.admin.admin_router import AdminRouter
from backend.features.admin.list_queries import search_page
from backend.features.automation.ads_router import AdsRouter
from backend.features.automation.scheduled_message_router import ScheduledMessageRouter
from backend.features.moderation.auto_reply_router import AutoReplyRouter
from backend.platform.db.runtime.session import create_database
from backend.platform.db.schema.models.core import AutoReplyRule, AdCampaign, ConversationState, EditDraft
from backend.platform.db.schema.models.scheduled_message import ScheduledMessageTask, ScheduledMessageLog
from backend.platform.runtime.chat_shard import install_chat_sharded_processing
from backend.platform.state.state_service import set_user_state
from test_admin_routes_postgres import TelegramBoundary, callback_update, command_update
from test_mall_intent_postgres import seed

URL = os.environ.get('TGR_REPAIR_TEST_DATABASE_URL')
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not URL, reason='disposable Postgres URL required')]


@pytest_asyncio.fixture
async def runtime():
    db = create_database(URL)
    transport = TelegramBoundary()
    app = Application.builder().token('999000:TEST_TOKEN').request(transport).build()
    app.bot_data['db'] = db
    for router in (AdminRouter(), AdsRouter(), AutoReplyRouter(), ScheduledMessageRouter()):
        router.register(app)
    app.add_handler(MessageHandler(filters.ALL, MessageDispatcher().dispatch))
    errors = []
    async def error(update, context):
        errors.append(repr(context.error))
    app.add_error_handler(error)
    install_chat_sharded_processing(app)
    await app.initialize()
    try:
        chat, user, _ = await seed(db)
        yield app, db, transport, errors, chat, user
        assert not errors, errors
        sends = [params for endpoint, params in transport.calls if endpoint in {'sendMessage', 'sendPhoto'}]
        assert all(int(params['chat_id']) > 0 for params in sends), sends
    finally:
        await app.shutdown()
        await db.engine.dispose()


def display(transport):
    return [p for e,p in transport.calls if e in {'sendMessage','editMessageText'}][-1]


def data_buttons(transport):
    return [b['callback_data'] for row in display(transport)['reply_markup']['inline_keyboard'] for b in row if 'callback_data' in b]


async def create_items(db, chat, *, count=25):
    async with db.session_factory() as s:
        tasks, ads = [], []
        for i in range(count):
            label = f'Alpha{i:04}'
            s.add(AutoReplyRule(chat_id=chat, keywords=[label], reply_content='generic', match_type='exact', is_active=i % 2 == 0, sort_order=i))
            ads.append(AdCampaign(chat_id=chat, title=label, content='generic', enabled=i % 2 == 0))
            tasks.append(ScheduledMessageTask(task_id=uuid.uuid4(), short_id=secrets.token_hex(4), chat_id=chat, title=label, enabled=i % 2 == 0))
        s.add_all([*tasks, *ads])
        await s.commit()
        return tasks, ads


async def test_search_paging_special_characters_and_scope(runtime):
    _, db, _, _, chat, _ = runtime
    await create_items(db, chat, count=1000)
    other_chat, _, _ = await seed(db)
    await create_items(db, other_chat, count=3)
    async with db.session_factory() as s:
        for feature in ('autoreply', 'scheduled', 'ads'):
            seen, timings = set(), []
            for page in range(125):
                start = time.monotonic()
                items, total, actual = await search_page(s, feature, chat_id=chat, query='aLPHa', status='all', page=page)
                timings.append(time.monotonic()-start)
                assert total == 1000 and actual == page
                seen.update(str(getattr(item, 'task_id', None) or item.id) for item in items)
                assert all(item.chat_id == chat for item in items)
            assert len(seen) == 1000 and sorted(timings)[118] < 2
            items, total, page = await search_page(s, feature, chat_id=chat, query='%', status='all', page=99)
            assert not items and total == 0 and page == 0
            _, total, _ = await search_page(s, feature, chat_id=chat, query='Alpha', status='enabled', page=0)
            assert total == 500
        s.add(AutoReplyRule(chat_id=chat, keywords=['literal_%'], reply_content='generic', match_type='exact'))
        await s.commit()
        assert (await search_page(s, 'autoreply', chat_id=chat, query='_%', status='all', page=0))[1] == 1
        assert (await search_page(s, 'autoreply', chat_id=chat, query='[', status='all', page=0))[1] == 0


async def test_search_return_retains_query_page_and_draft(runtime):
    app, db, transport, _, chat, user = runtime
    tasks, ads = await create_items(db, chat)
    async with db.session_factory() as s:
        await set_user_state(s, user, user, state_type='welcome_text_input', state_data={'target_chat_id':chat, 'document_id':1})
        await s.commit()
    await app.process_update(callback_update(app, user, 1, f'mlist:scheduled:{chat}:search:0'))
    await app.process_update(command_update(app, user, user, 2, 'Alpha'))
    assert '25 条' in display(transport)['text']
    await app.process_update(callback_update(app, user, 3, f'mlist:scheduled:{chat}:list:2'))
    detail = next(x for x in data_buttons(transport) if x.startswith('sm:open:'))
    await app.process_update(callback_update(app, user, 4, detail))
    back = f'mlist:scheduled:{chat}:list:2'
    assert back in data_buttons(transport)
    await app.process_update(callback_update(app, user, 5, back))
    assert '第 3 页' in display(transport)['text'] and 'Alpha' in display(transport)['text']
    await app.process_update(callback_update(app, user, 6, f'ads:detail:{chat}:{ads[0].id}'))
    assert '轮播消息' in display(transport)['text']
    async with db.session_factory() as s:
        state = await s.scalar(select(ConversationState).where(ConversationState.chat_id == user, ConversationState.user_id == user))
        assert state.state_type == 'selected_chat'
        drafts = list((await s.execute(select(EditDraft).where(EditDraft.user_id==user))).scalars())
        assert any(d.state_type=='welcome_text_input' for d in drafts)
        assert all(d.state_type!='admin_list_search_input' for d in drafts)


async def test_summary_unknown_preserves_success_and_refresh_is_read_only(runtime):
    app, db, transport, _, chat, user = runtime
    tasks, _ = await create_items(db, chat, count=1)
    task = tasks[0]
    import datetime as dt
    now = dt.datetime.now(dt.UTC)
    async with db.session_factory() as s:
        for status in ('succeeded', 'uncertain'):
            s.add(ScheduledMessageLog(task_id=task.task_id, chat_id=chat, run_key=uuid.uuid4().hex,
                scheduled_for=int(now.timestamp()), status=status, content_snapshot={},
                sent_at=now if status=='succeeded' else None, send_started_at=now))
        await s.commit()
    for i in range(2):
        await app.process_update(callback_update(app, user, i+100, f'sm:list:{chat}:0'))
        text = display(transport)['text']
        assert '结果未知，待核实' in text and '最近成功：未知' not in text
    async with db.session_factory() as s:
        assert await s.scalar(select(func.count()).select_from(ScheduledMessageLog).where(ScheduledMessageLog.chat_id==chat)) == 2


async def test_shortcut_and_category_return_to_their_source(runtime):
    app, _, transport, _, chat, user = runtime
    for i, feature in enumerate(('autoreply','scheduled','ads','points')):
        await app.process_update(callback_update(app, user, 200+i, f'adm:menu:{feature}:{chat}:home'))
        assert f'adm:menu:main:{chat}' in data_buttons(transport)
        await app.process_update(callback_update(app, user, 300+i, f'adm:menu:{feature}:{chat}:category'))
        category = 'growth' if feature == 'points' else 'messages'
        assert f'adm:menu:category_{category}:{chat}' in data_buttons(transport)


async def test_revoked_permission_cannot_read_search_or_fall_back_to_selected_group(runtime):
    import json
    from backend.features.group_ops.services.chat_group_service import set_user_current_chat
    app, db, transport, _, chat, user = runtime
    await create_items(db, chat, count=1)
    selected, _, _ = await seed(db)
    await set_user_current_chat(db, user, selected)
    await app.process_update(callback_update(app, user, 700, f'mlist:ads:{chat}:search:0'))
    original = transport.do_request
    async def deny_target(url, method, request_data=None, **kwargs):
        params = request_data.parameters if request_data else {}
        if url.endswith('/getChatMember') and int(params['chat_id']) == chat:
            return 200, json.dumps({'ok':True,'result':{'status':'member','user':{'id':user,'is_bot':False,'first_name':'test'}}}).encode()
        return await original(url, method, request_data=request_data, **kwargs)
    transport.do_request = deny_target
    transport.calls.clear()
    await app.process_update(command_update(app, user, user, 701, 'Alpha'))
    assert '权限已失效' in display(transport)['text']
    transport.calls.clear()
    await app.process_update(callback_update(app, user, 702, f'ads:menu:{chat}'))
    assert not any(e in {'editMessageText','sendMessage'} for e,_ in transport.calls)
    assert any('管理权限' in str(p) for e,p in transport.calls if e=='answerCallbackQuery')


async def test_query_database_failure_has_retry_clear_and_return_without_losing_filter(runtime, monkeypatch):
    from sqlalchemy.exc import OperationalError
    from backend.features.admin import list_browser
    app, _, transport, _, chat, user = runtime
    app.user_data[user]['admin_list_queries'] = {f'{chat}:scheduled': {'query':'preserve', 'status':'enabled','page':2}}
    async def database_failed(*args, **kwargs):
        raise OperationalError('query', {}, Exception('injected database boundary failure'))
    monkeypatch.setattr(list_browser, 'search_page', database_failed)
    await app.process_update(callback_update(app,user,800,f'mlist:scheduled:{chat}:list:2'))
    assert '查询暂时失败' in display(transport)['text']
    assert data_buttons(transport) == [f'mlist:scheduled:{chat}:list:0',
                                      f'mlist:scheduled:{chat}:clear:0', f'adm:menu:category_messages:{chat}']
    assert app.user_data[user]['admin_list_queries'][f'{chat}:scheduled']['query'] == 'preserve'
