"""Registered callbacks and inputs with disposable DB and fake Telegram only."""
import pytest
import pytest_asyncio
from sqlalchemy import select

import test_remaining_generic_postgres as remaining
from test_admin_routes_postgres import callback_update, command_update
from backend.features.automation.scheduled_message_router import ScheduledMessageRouter
from backend.features.automation.services.scheduled_message_service import ScheduledMessageService as SM
from backend.platform.db.schema.models.chat import ConversationState

pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(not remaining.URL,reason='disposable DB required')]


@pytest_asyncio.fixture
async def runtime():
    async for runtime in remaining.runtime.__wrapped__():
        ScheduledMessageRouter().register(runtime[0])
        yield runtime


def rendered(boundary):
    return [params for method,params in boundary.calls if method in {'editMessageText','sendMessage'}][-1]


def buttons(boundary):
    return [b for row in rendered(boundary)['reply_markup']['inline_keyboard'] for b in row]


async def tasks(db,chat,user):
    async with db.session_factory() as session:
        rows=[await SM.create_task(session,chat_id=chat,created_by_user_id=user,title=name,enabled=False) for name in ('A','B')]
        await session.commit()
        return [r.short_id for r in rows]


async def test_repeat_input_validation_save_cancel_and_revocation(runtime):
    app,db,b,chat,user=runtime
    task,_=await tasks(db,chat,user)
    edit=f'sm:edit:{chat}:{task}:repeat_custom'
    await app.process_update(callback_update(app,user,1000,edit))
    await app.process_update(command_update(app,user,user,1001,'0'))
    assert '整数分钟' in rendered(b)['text']
    await app.process_update(command_update(app,user,user,1002,'90'))
    async with db.session_factory() as s:
        row=await SM.get_task_in_chat_or_404(s,chat,task)
        assert row.repeat_interval_min==90
    await app.process_update(callback_update(app,user,1003,edit))
    await app.process_update(callback_update(app,user,1004,f'sm:open:{chat}:{task}'))
    await app.process_update(command_update(app,user,user,1005,'120'))
    async with db.session_factory() as s:
        assert (await SM.get_task_in_chat_or_404(s,chat,task)).repeat_interval_min==90
    await app.process_update(callback_update(app,user,1006,edit))
    b.member(user)
    await app.process_update(command_update(app,user,user,1007,'180'))
    async with db.session_factory() as s:
        assert (await SM.get_task_in_chat_or_404(s,chat,task)).repeat_interval_min==90
    assert not any(int(p['chat_id'])<0 for m,p in b.calls if m in {'sendMessage','sendPhoto'})


async def test_date_copy_roundtrip_and_return_exits_input(runtime):
    app,db,b,chat,user=runtime
    task,_=await tasks(db,chat,user)
    await app.process_update(callback_update(app,user,1100,f'sm:edit:{chat}:{task}:start_at'))
    copied=next(x['copy_text']['text'] for x in buttons(b) if 'copy_text' in x)
    await app.process_update(command_update(app,user,user,1101,copied))
    async with db.session_factory() as s:
        before=(await SM.get_task_in_chat_or_404(s,chat,task)).start_at
        assert before is not None
    await app.process_update(callback_update(app,user,1102,f'sm:edit:{chat}:{task}:start_at'))
    await app.process_update(callback_update(app,user,1103,f'sm:edit:{chat}:{task}:time_range'))
    await app.process_update(command_update(app,user,user,1104,'2099-12-31 12:00'))
    async with db.session_factory() as s:
        assert (await SM.get_task_in_chat_or_404(s,chat,task)).start_at==before
        state=await s.scalar(select(ConversationState).where(ConversationState.user_id==user,ConversationState.chat_id==user))
        assert state.state_type=='selected_chat'


async def test_hour_picker_stale_end_cannot_apply_to_another_draft(runtime):
    app,db,b,chat,user=runtime
    first,second=await tasks(db,chat,user)
    await app.process_update(callback_update(app,user,1200,f'sm:set:{chat}:{first}:day_start:22'))
    end=next(x['callback_data'] for x in buttons(b) if x['text']=='06:59')
    await app.process_update(callback_update(app,user,1201,f'sm:set:{chat}:{second}:day_start:9'))
    await app.process_update(callback_update(app,user,1202,end))
    assert '其他任务' in rendered(b)['text']
    async with db.session_factory() as s:
        assert (await SM.get_task_in_chat_or_404(s,chat,first)).day_start_hour==0
        assert (await SM.get_task_in_chat_or_404(s,chat,second)).day_start_hour==0
    await app.process_update(callback_update(app,user,1203,f'sm:set:{chat}:{first}:day_start:22'))
    current=next(x['callback_data'] for x in buttons(b) if x['text']=='06:59')
    await app.process_update(callback_update(app,user,1204,end))
    assert '过期' in rendered(b)['text']
    await app.process_update(callback_update(app,user,1205,current))
    async with db.session_factory() as s:
        row=await SM.get_task_in_chat_or_404(s,chat,first)
        assert (row.day_start_hour,row.day_end_hour)==(22,6)
    assert '次日 06:59' in rendered(b)['text']


async def test_clear_editor_requires_confirmation_and_does_not_save_formal_config(runtime):
    from backend.platform.db.schema.models.chat import ChatSettings, EditDraft
    app,db,b,chat,user=runtime
    async with db.session_factory() as s:
        settings=await s.get(ChatSettings,chat)
        settings.invite_link_buttons=[[{'text':'原链接','url':'https://example.com'}]]
        await s.commit()
    await app.process_update(callback_update(app,user,1300,f'btned:open:invite:{chat}:0'))
    await app.process_update(callback_update(app,user,1301,f'btned:clear:invite:{chat}:0'))
    cancel=next(x['callback_data'] for x in buttons(b) if x['text']=='取消')
    await app.process_update(callback_update(app,user,1302,cancel))
    async with db.session_factory() as s:
        record=await s.scalar(select(EditDraft).where(EditDraft.user_id==user,EditDraft.state_type=='button_layout_draft'))
        assert record.state_data['grid'][0][0]['text']=='原链接'
    await app.process_update(callback_update(app,user,1303,f'btned:clear:invite:{chat}:0'))
    confirm=next(x['callback_data'] for x in buttons(b) if x['text']=='确认清空按钮')
    await app.process_update(callback_update(app,user,1304,confirm))
    async with db.session_factory() as s:
        record=await s.scalar(select(EditDraft).where(EditDraft.user_id==user,EditDraft.state_type=='button_layout_draft'))
        assert record.state_data['grid']==[[]]
        assert (await s.get(ChatSettings,chat)).invite_link_buttons[0][0]['text']=='原链接'
    assert not any(int(p['chat_id'])<0 for m,p in b.calls if m in {'sendMessage','sendPhoto'})


async def test_media_input_rechecks_revoked_permission(runtime):
    from telegram import Update
    app,db,b,chat,user=runtime
    task,_=await tasks(db,chat,user)
    await app.process_update(callback_update(app,user,1400,f'sm:edit:{chat}:{task}:media'))
    b.member(user)
    raw=command_update(app,user,user,1401,'unused').to_dict()
    raw['message'].pop('text')
    raw['message'].pop('entities')
    raw['message']['photo']=[{'file_id':'denied-photo','file_unique_id':'unique','width':480,'height':240}]
    await app.process_update(Update.de_json(raw,app.bot))
    async with db.session_factory() as s:
        assert (await SM.get_task_in_chat_or_404(s,chat,task)).media_file_id is None
    assert '权限已失效' in rendered(b)['text']
