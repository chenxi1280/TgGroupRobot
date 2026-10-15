"""Real registration, database and workers; all Telegram HTTP is local/fake."""
import asyncio
import datetime as dt
import json
import os
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from telegram import Update
from telegram.error import NetworkError
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from backend.app.update_pipeline import MessageDispatcher
from backend.features.admin.admin_router import AdminRouter
from backend.features.automation.ads_router import AdsRouter
from backend.features.group_ops.start_handler import start_command
from backend.platform.db.runtime.session import create_database
from backend.platform.db.schema.models.admin_effects import AdminEffect, LevelTagState, NoticeConsent
from backend.platform.db.schema.models.chat import ChatSettings, ConversationState
from backend.platform.db.schema.models.automation import AdCampaign
from backend.platform.runtime.chat_shard import install_chat_sharded_processing
from backend.shared.services.chat_service import get_chat_settings
from test_admin_routes_postgres import TelegramBoundary, callback_update, command_update
from test_mall_intent_postgres import seed

URL = os.environ.get('TGR_REPAIR_TEST_DATABASE_URL')
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not URL, reason='disposable Postgres required')]
NOW = dt.datetime(2026,10,15,15,0,tzinfo=dt.UTC)  # 23:00 Shanghai


class GeneralBoundary(TelegramBoundary):
    def __init__(self):
        super().__init__()
        self.members = {}
        self.faults = {}
        self.apply_before_fault = set()
        self.tag_right = True
    async def do_request(self, url, method, request_data=None, **kwargs):
        endpoint = url.rsplit('/',1)[-1]
        params = request_data.parameters if request_data else {}
        fault = self.faults.get(endpoint)
        if fault and endpoint not in self.apply_before_fault:
            self.calls.append((endpoint,params))
            return self._fault(fault.pop(0))
        if endpoint == 'getChatMember' and int(params['user_id']) in self.members:
            self.calls.append((endpoint,params))
            result = self.members[int(params['user_id'])]
            return 200, json.dumps({'ok':True,'result':result}).encode()
        if endpoint == 'getChatMember' and int(params['user_id']) == 999000:
            self.calls.append((endpoint,params))
            return 200,json.dumps({'ok':True,'result':{'status':'administrator','is_anonymous':False,
                'can_be_edited':False,'can_manage_chat':True,'can_delete_messages':True,
                'can_manage_video_chats':False,'can_restrict_members':True,'can_promote_members':False,
                'can_change_info':True,'can_invite_users':True,'can_post_stories':False,
                'can_edit_stories':False,'can_delete_stories':False,'can_manage_tags':self.tag_right,
                'user':{'id':999000,'is_bot':True,'first_name':'test'}}}).encode()
        if endpoint == 'setChatMemberTag':
            self.calls.append((endpoint,params))
            self.members[int(params['user_id'])]['tag'] = params.get('tag','')
            if fault:
                return self._fault(fault.pop(0))
            return 200,b'{"ok":true,"result":true}'
        return await super().do_request(url,method,request_data=request_data,**kwargs)
    def _fault(self, fault):
        if isinstance(fault,Exception):
            raise fault
        return fault
    def member(self, user_id, *, tag=''):
        self.members[user_id]={'status':'member','tag':tag,'user':{'id':user_id,'is_bot':False,'first_name':'member'}}


@pytest_asyncio.fixture
async def runtime():
    db=create_database(URL)
    boundary=GeneralBoundary()
    app=Application.builder().token('999000:TEST_TOKEN').request(boundary).build()
    app.bot_data['db']=db
    AdminRouter().register(app)
    AdsRouter().register(app)
    app.add_handler(CommandHandler('start',start_command))
    app.add_handler(MessageHandler(filters.ALL,MessageDispatcher().dispatch))
    errors=[]
    async def error(update,context):
        errors.append(repr(context.error))
    app.add_error_handler(error)
    install_chat_sharded_processing(app)
    await app.initialize()
    chat,user,_=await seed(db)
    async with db.session_factory() as s:
        await get_chat_settings(s,chat)
        await s.commit()
    try:
        yield app,db,boundary,chat,user
        assert not errors,errors
    finally:
        from sqlalchemy import delete
        async with db.session_factory() as s:
            for model in (AdminEffect, LevelTagState, NoticeConsent):
                await s.execute(delete(model).where(model.chat_id==chat))
            settings=await s.get(ChatSettings,chat)
            settings.module_config={}
            settings.group_lock_schedule_enabled=False
            for ad in (await s.scalars(select(AdCampaign).where(AdCampaign.chat_id==chat))).all():
                ad.enabled=False
            await s.commit()
        await app.shutdown()
        await db.engine.dispose()


def calls(boundary, endpoint):
    return [p for e,p in boundary.calls if e==endpoint]


async def configure_lock(db, chat, *, notice=True):
    async with db.session_factory() as s:
        settings=await s.get(ChatSettings,chat)
        settings.group_lock_schedule_enabled=True
        settings.group_lock_open_time='08:00'
        settings.group_lock_close_time='22:00'
        settings.night_mode_start_time=None
        settings.night_mode_end_time=None
        settings.group_lock_phrase_enabled=True
        settings.module_config={'group_lock':{'profiles':{'closed':{'can_send_messages':False,'can_send_photos':False},
            'open':{'can_send_messages':True,'can_send_photos':True}},'notices':{'closed':{
                'enabled':notice,'text':'群{chat_id}已{state}','delete_seconds':30,'cover':'fake-photo',
                'buttons':[[{'text':'文档','url':'https://example.com'}]]}}}}
        await s.commit()


async def test_schedule_concurrency_restart_notice_and_persistent_cleanup(runtime):
    from backend.features.group_ops.services.lock_plans import plan_schedule
    from backend.features.admin.services.effect_runtime import run_pending
    app,db,b,chat,_=runtime
    await configure_lock(db,chat)
    await asyncio.gather(plan_schedule(db,now=NOW,chat_id=chat),plan_schedule(db,now=NOW,chat_id=chat))
    async with db.session_factory() as s:
        assert await s.scalar(select(func.count()).select_from(AdminEffect).where(AdminEffect.chat_id==chat))==1
    await asyncio.gather(run_pending(app,now=NOW,chat_id=chat),run_pending(app,now=NOW,chat_id=chat))
    assert len(calls(b,'setChatPermissions'))==1
    app.bot_data.pop('group_lock_state',None)
    await plan_schedule(db,now=NOW,chat_id=chat)
    await run_pending(app,now=NOW,chat_id=chat)
    assert len(calls(b,'setChatPermissions'))==1
    photos=calls(b,'sendPhoto')
    assert len(photos)==1 and photos[0]['caption']==f'群{chat}已关群'
    assert photos[0]['reply_markup']['inline_keyboard'][0][0]['text']=='文档'
    await run_pending(app,now=NOW+dt.timedelta(seconds=31),chat_id=chat)
    assert len(calls(b,'deleteMessage'))==1
    await run_pending(app,now=NOW+dt.timedelta(seconds=60),chat_id=chat)
    assert len(calls(b,'sendPhoto'))==len(calls(b,'deleteMessage'))==1
    async with db.session_factory() as s:
        rows=list((await s.scalars(select(AdminEffect).where(AdminEffect.chat_id==chat))).all())
        assert len(rows)==3 and all(row.status=='succeeded' for row in rows)


async def test_permission_failure_never_enqueues_success_notice_and_reports_failure(runtime):
    from backend.features.group_ops.services.lock_plans import plan_schedule
    from backend.features.admin.services.effect_runtime import run_pending
    app,db,b,chat,_=runtime
    await configure_lock(db,chat)
    b.faults['setChatPermissions']=[(403,b'{"ok":false,"error_code":403,"description":"Forbidden: missing rights"}')]
    await plan_schedule(db,now=NOW,chat_id=chat)
    with pytest.raises(RuntimeError):
        await run_pending(app,now=NOW,chat_id=chat)
    assert not calls(b,'sendPhoto')
    async with db.session_factory() as s:
        rows=list((await s.scalars(select(AdminEffect).where(AdminEffect.chat_id==chat))).all())
        assert len(rows)==1 and rows[0].status=='permanent_failed'


async def test_notice_network_unknown_does_not_replay_or_undo_permissions(runtime):
    from backend.features.group_ops.services.lock_plans import plan_schedule
    from backend.features.admin.services.effect_runtime import run_pending
    app,db,b,chat,_=runtime
    await configure_lock(db,chat)
    await plan_schedule(db,now=NOW,chat_id=chat)
    await run_pending(app,now=NOW,chat_id=chat)
    b.faults['sendPhoto']=[NetworkError('lost after sending')]
    with pytest.raises(RuntimeError):
        await run_pending(app,now=NOW,chat_id=chat)
    await run_pending(app,now=NOW+dt.timedelta(minutes=5),chat_id=chat)
    assert len(calls(b,'setChatPermissions'))==len(calls(b,'sendPhoto'))==1
    async with db.session_factory() as s:
        notice=await s.scalar(select(AdminEffect).where(AdminEffect.chat_id==chat,AdminEffect.kind=='lock_notice'))
        assert notice.status=='uncertain'
        assert not await s.scalar(select(AdminEffect.id).where(AdminEffect.chat_id==chat,AdminEffect.kind=='notice_delete'))


async def test_schedule_skips_missed_boundary_and_cancels_old_plan(runtime):
    from backend.features.group_ops.services.lock_plans import plan_schedule
    from backend.features.admin.services.effect_runtime import run_pending
    app,db,b,chat,_=runtime
    await configure_lock(db,chat)
    await plan_schedule(db,now=NOW,chat_id=chat)
    next_day=NOW+dt.timedelta(hours=10) # 09:00, opens at08:00
    await plan_schedule(db,now=next_day,chat_id=chat)
    await run_pending(app,now=next_day,chat_id=chat)
    assert len(calls(b,'setChatPermissions'))==1
    assert calls(b,'setChatPermissions')[0]['permissions']['can_send_messages'] is True
    assert not calls(b,'sendPhoto')
    async with db.session_factory() as s:
        rows=list((await s.scalars(select(AdminEffect).where(AdminEffect.chat_id==chat).order_by(AdminEffect.id))).all())
        assert [r.status for r in rows]==['cancelled','succeeded']


async def test_expired_claims_distinguish_before_and_after_remote_start(runtime):
    from backend.features.admin.services.effect_store import claim,enqueue
    from backend.features.admin.services.effect_runtime import run_pending
    app,db,b,chat,_=runtime
    async with db.session_factory() as s:
        ids=[]
        for started in (False,True):
            i=await enqueue(s,key=f'{chat}:lease:{started}',chat_id=chat,kind='group_lock',payload={},due=NOW)
            row=await s.get(AdminEffect,i)
            row.status='processing'
            row.lease_until=NOW-dt.timedelta(seconds=1)
            row.started_at=NOW-dt.timedelta(minutes=3) if started else None
            ids.append(i)
        await s.commit()
    assert (await claim(db,ids[0],now=NOW)).status=='processing'
    assert await claim(db,ids[1],now=NOW) is None
    async with db.session_factory() as s:
        assert (await s.get(AdminEffect,ids[1])).status=='uncertain'
    assert not calls(b,'setChatPermissions')


async def setup_tag(db, chat):
    from backend.features.points.services.points_extended_levels import PointsExtendedLevelsMixin as Levels
    async with db.session_factory() as s:
        level=await Levels.create_level(s,chat)
        await Levels.update_level(s,level,level_name='Level1',point_threshold=0)
        setting=await Levels.get_or_create_level_setting(s,chat)
        await Levels.update_level_setting(s,setting,enabled=True)
        settings=await s.get(ChatSettings,chat)
        settings.module_config={'level_tags':{'enabled':True,'levels':{str(level.id):{'enabled':True,'text':'Level1'}}}}
        await s.commit()
        return level.id


async def test_tag_lifecycle_upgrade_disable_and_foreign_label_protection(runtime):
    from backend.features.points.services.level_tags import reconcile_tags
    from backend.features.points.services.points_extended_levels import PointsExtendedLevelsMixin as Levels
    from backend.platform.db.schema.models.points import PointsAccount
    app,db,b,chat,user=runtime
    await setup_tag(db,chat)
    b.member(user)
    await reconcile_tags(app,now=NOW)
    assert b.members[user]['tag']=='Level1' and len(calls(b,'setChatMemberTag'))==1
    async with db.session_factory() as s:
        second=await Levels.create_level(s,chat)
        await Levels.update_level(s,second,level_name='Level2',point_threshold=200)
        settings=await s.get(ChatSettings,chat)
        settings.module_config={'level_tags':{'enabled':True,'levels':{
            str(second.id):{'enabled':True,'text':'Level2'}}}}
        account=await s.scalar(select(PointsAccount).where(PointsAccount.chat_id==chat,PointsAccount.user_id==user))
        account.balance=200
        await s.commit()
    await reconcile_tags(app,now=NOW+dt.timedelta(minutes=1))
    assert b.members[user]['tag']=='Level2'
    async with db.session_factory() as s:
        settings=await s.get(ChatSettings,chat)
        settings.module_config={'level_tags':{'enabled':False}}
        await s.commit()
    await reconcile_tags(app,now=NOW+dt.timedelta(minutes=2))
    assert b.members[user]['tag']==''
    b.members[user]['tag']='Verified'
    async with db.session_factory() as s:
        settings=await s.get(ChatSettings,chat)
        settings.module_config={'level_tags':{'enabled':True,'levels':{str(second.id):{'enabled':True,'text':'Level2'}}}}
        await s.commit()
    count=len(calls(b,'setChatMemberTag'))
    await reconcile_tags(app,now=NOW+dt.timedelta(minutes=3))
    assert b.members[user]['tag']=='Verified' and len(calls(b,'setChatMemberTag'))==count
    async with db.session_factory() as s:
        state=await s.get(LevelTagState,(chat,user))
        assert state.status=='conflict' and state.error=='foreign_tag_preserved'


async def test_tag_unknown_is_read_back_without_repeating_write_and_missing_right_is_explicit(runtime):
    from backend.features.points.services.level_tags import reconcile_tags
    app,db,b,chat,user=runtime
    await setup_tag(db,chat)
    b.member(user)
    b.apply_before_fault.add('setChatMemberTag')
    b.faults['setChatMemberTag']=[NetworkError('response lost after tag set')]
    with pytest.raises(RuntimeError):
        await reconcile_tags(app,now=NOW)
    async with db.session_factory() as s:
        assert (await s.get(LevelTagState,(chat,user))).status=='uncertain'
    await reconcile_tags(app,now=NOW+dt.timedelta(minutes=1))
    assert len(calls(b,'setChatMemberTag'))==1
    async with db.session_factory() as s:
        state=await s.get(LevelTagState,(chat,user))
        assert state.status=='applied' and state.applied_tag=='Level1'
        settings=await s.get(ChatSettings,chat)
        settings.module_config={'level_tags':{'enabled':False}}
        await s.commit()
    b.tag_right=False
    with pytest.raises(RuntimeError):
        await reconcile_tags(app,now=NOW+dt.timedelta(minutes=2))
    assert len(calls(b,'setChatMemberTag'))==1 and b.members[user]['tag']=='Level1'
    async with db.session_factory() as s:
        state=await s.get(LevelTagState,(chat,user))
        assert state.status=='permanent_failed' and 'can_manage_tags' in state.error


async def create_reminder(db, chat, user, *, now=NOW, consent=True):
    async with db.session_factory() as s:
        ad=AdCampaign(chat_id=chat,title='generic reminder',content='generic',enabled=True,
            end_time=now+dt.timedelta(days=2),expiry_notice={'enabled':True,'recipient':user,
                'advance_days':3,'time':'10:00','text':'广告{ad_id} {title} 于{expiry}到期，群{chat_id}'})
        s.add(ad)
        await s.flush()
        s.add(NoticeConsent(chat_id=chat,ad_id=ad.id,user_id=user,version='testconsent',enabled=consent))
        await s.commit()
        return ad.id


async def test_expiry_consent_dedup_end_change_revoke_and_unknown(runtime):
    from backend.features.automation.services.ad_expiry import plan_reminders
    from backend.features.admin.services.effect_runtime import run_pending
    app,db,b,chat,user=runtime
    ad_id=await create_reminder(db,chat,user,consent=False)
    await plan_reminders(db,now=NOW)
    assert not calls(b,'sendMessage')
    async with db.session_factory() as s:
        assert not await s.scalar(select(AdminEffect.id).where(AdminEffect.chat_id==chat))
        consent=await s.get(NoticeConsent,(chat,ad_id,user))
        consent.enabled=True
        await s.commit()
    await asyncio.gather(plan_reminders(db,now=NOW),plan_reminders(db,now=NOW))
    await asyncio.gather(run_pending(app,now=NOW,chat_id=chat),run_pending(app,now=NOW,chat_id=chat))
    assert len(calls(b,'sendMessage'))==1 and calls(b,'sendMessage')[0]['chat_id']==user
    await plan_reminders(db,now=NOW)
    await run_pending(app,now=NOW+dt.timedelta(minutes=5),chat_id=chat)
    assert len(calls(b,'sendMessage'))==1
    tomorrow=NOW+dt.timedelta(days=1)
    await plan_reminders(db,now=tomorrow)
    async with db.session_factory() as s:
        ad=await s.get(AdCampaign,ad_id)
        ad.end_time+=dt.timedelta(days=1)
        await s.commit()
    await plan_reminders(db,now=tomorrow)
    b.faults['sendMessage']=[NetworkError('lost')]
    with pytest.raises(RuntimeError):
        await run_pending(app,now=tomorrow,chat_id=chat)
    await run_pending(app,now=tomorrow+dt.timedelta(minutes=10),chat_id=chat)
    assert len(calls(b,'sendMessage'))==2
    async with db.session_factory() as s:
        statuses=list((await s.scalars(select(AdminEffect.status).where(AdminEffect.chat_id==chat))).all())
        assert sorted(statuses)==sorted(['succeeded','cancelled','uncertain'])
        consent=await s.get(NoticeConsent,(chat,ad_id,user))
        consent.enabled=False
        await s.commit()
    await plan_reminders(db,now=tomorrow+dt.timedelta(days=1))
    async with db.session_factory() as s:
        assert await s.scalar(select(func.count()).select_from(AdminEffect).where(AdminEffect.chat_id==chat))==3


async def test_private_config_input_exit_preview_snapshot_and_consent_cannot_be_forged(runtime):
    app,db,b,chat,user=runtime
    await app.process_update(callback_update(app,user,100,f'gperm:{chat}:open:set:photo:1'))
    assert not calls(b,'setChatPermissions')
    async with db.session_factory() as s:
        cfg=(await s.get(ChatSettings,chat)).module_config
        assert cfg['group_lock']['original_permissions']['can_send_photos'] is True
    await app.process_update(callback_update(app,user,101,f'gnote:{chat}:closed:input:text'))
    await app.process_update(command_update(app,user,user,102,'通知 {chat_id} {state}'))
    await app.process_update(callback_update(app,user,103,f'gnote:{chat}:closed:input:delete_seconds'))
    await app.process_update(callback_update(app,user,104,f'gnote:{chat}:closed:view'))
    await app.process_update(command_update(app,user,user,105,'777'))
    async with db.session_factory() as s:
        cfg=(await s.get(ChatSettings,chat)).module_config
        assert cfg['group_lock']['notices']['closed']['delete_seconds']==0
        state=await s.scalar(select(ConversationState).where(ConversationState.chat_id==user,ConversationState.user_id==user))
        assert state.state_type=='selected_chat'
    await app.process_update(callback_update(app,user,106,f'gnote:{chat}:closed:preview'))
    assert not any(int(p['chat_id'])<0 for p in calls(b,'sendMessage')+calls(b,'sendPhoto'))
    ad_id=await create_reminder(db,chat,user,consent=False)
    await app.process_update(callback_update(app,user,110,f'anote:{chat}:{ad_id}:set:enabled:1'))
    assert any('尚未' in str(p) for p in calls(b,'answerCallbackQuery'))
    await app.process_update(command_update(app,user,user,111,f'/start ncons_{ad_id}_testconsent'))
    await app.process_update(callback_update(app,user,112,f'ncons:{chat}:{ad_id}:bad:1'))
    async with db.session_factory() as s:
        assert not (await s.get(NoticeConsent,(chat,ad_id,user))).enabled
    await app.process_update(callback_update(app,user,113,f'ncons:{chat}:{ad_id}:testconsent:1'))
    async with db.session_factory() as s:
        assert (await s.get(NoticeConsent,(chat,ad_id,user))).enabled
    await app.process_update(callback_update(app,user,114,f'ncons:{chat}:{ad_id}:testconsent:0'))
    async with db.session_factory() as s:
        assert not (await s.get(NoticeConsent,(chat,ad_id,user))).enabled


async def test_ad_rules_recheck_permissions_and_foreign_edit_target_is_rejected(runtime):
    app,db,b,chat,user=runtime
    other,_,_=await seed(db)
    async with db.session_factory() as s:
        ad=AdCampaign(chat_id=other,title='foreign',content='generic',enabled=True)
        s.add(ad)
        await s.commit()
    await app.process_update(callback_update(app,user,201,f'ads:item:input:{chat}:{ad.id}:title'))
    await app.process_update(command_update(app,user,user,202,'must not overwrite'))
    async with db.session_factory() as s:
        assert (await s.get(AdCampaign,ad.id)).title=='foreign'
    from backend.platform.state.state_service import set_user_state
    async with db.session_factory() as s:
        await set_user_state(s,user,user,state_type='ads_item_edit_title',state_data={'target_chat_id':chat,'item_id':ad.id})
        await s.commit()
    await app.process_update(command_update(app,user,user,203,'stale state overwrite'))
    async with db.session_factory() as s:
        assert (await s.get(AdCampaign,ad.id)).title=='foreign'
    b.member(user)
    await app.process_update(callback_update(app,user,204,f'ads:rules:set:{chat}:enabled:1'))
    await app.process_update(callback_update(app,user,205,f'ads:rules:input:{chat}:start'))
    from backend.platform.db.schema.models.automation import AdRotationRule
    async with db.session_factory() as s:
        rule=await s.get(AdRotationRule,chat)
        assert rule is None or not rule.enabled
        state=await s.scalar(select(ConversationState).where(ConversationState.chat_id==user,ConversationState.user_id==user))
        assert state is None or not state.state_type.startswith('ads_')


async def test_database_finalize_failure_is_unknown_after_lease_not_a_second_remote_send(runtime):
    from sqlalchemy import text
    from backend.features.group_ops.services.lock_plans import plan_schedule
    from backend.features.admin.services.effect_runtime import run_pending
    app,db,b,chat,_=runtime
    await configure_lock(db,chat)
    ids=await plan_schedule(db,now=NOW,chat_id=chat)
    trigger=f'fail_effect_{ids[0]}'
    async with db.engine.begin() as conn:
        await conn.execute(text(f"CREATE FUNCTION bot.{trigger}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'injected finalize failure'; END $$"))
        await conn.execute(text(f"CREATE TRIGGER {trigger} BEFORE UPDATE ON bot.admin_effects FOR EACH ROW WHEN (NEW.id = {ids[0]} AND NEW.status = 'succeeded') EXECUTE FUNCTION bot.{trigger}()"))
    try:
        with pytest.raises(RuntimeError):
            await run_pending(app,now=NOW,chat_id=chat)
        assert len(calls(b,'setChatPermissions'))==1
        assert not calls(b,'sendPhoto')
    finally:
        async with db.engine.begin() as conn:
            await conn.execute(text(f'DROP TRIGGER {trigger} ON bot.admin_effects'))
            await conn.execute(text(f'DROP FUNCTION bot.{trigger}()'))
    with pytest.raises(RuntimeError):
        await run_pending(app,now=NOW+dt.timedelta(minutes=3),chat_id=chat)
    assert len(calls(b,'setChatPermissions'))==1
    async with db.session_factory() as s:
        row=await s.get(AdminEffect,ids[0])
        assert row.status=='uncertain' and 'lease_expired_after' in row.error
        assert not await s.scalar(select(AdminEffect.id).where(AdminEffect.chat_id==chat,AdminEffect.kind=='lock_notice'))


async def test_phrase_identity_deduplicates_and_manual_cancel_is_not_resurrected(runtime):
    from backend.features.group_ops.services.lock_plans import plan_phrase
    from backend.features.admin.services.effect_runtime import run_pending
    from backend.features.automation.services.ad_expiry import plan_reminders
    app,db,b,chat,user=runtime
    await configure_lock(db,chat,notice=False)
    first=await plan_phrase(db,chat_id=chat,message_id=555,closed=True,now=NOW,user_id=user)
    second=await plan_phrase(db,chat_id=chat,message_id=555,closed=True,now=NOW,user_id=user)
    assert first==second
    await run_pending(app,now=NOW,chat_id=chat)
    await plan_phrase(db,chat_id=chat,message_id=555,closed=True,now=NOW,user_id=user)
    await run_pending(app,now=NOW,chat_id=chat)
    assert len(calls(b,'setChatPermissions'))==1
    await create_reminder(db,chat,user)
    await plan_reminders(db,now=NOW)
    async with db.session_factory() as s:
        job=await s.scalar(select(AdminEffect).where(AdminEffect.chat_id==chat,AdminEffect.kind=='ad_expiry'))
    await app.process_update(callback_update(app,user,300,f'eff:{chat}:ad_expiry:cancel:{job.id}'))
    await plan_reminders(db,now=NOW)
    await run_pending(app,now=NOW,chat_id=chat)
    assert not [p for p in calls(b,'sendMessage') if '广告' in p.get('text','') and '到期，群' in p.get('text','')]
    async with db.session_factory() as s:
        assert (await s.get(AdminEffect,job.id)).status=='cancelled'


@pytest.mark.parametrize('text',['','A'*17,'等级😀','<b>{x}</b>\n','A\u200dB','✈'])
async def test_invalid_tag_is_rejected_locally(text):
    from backend.features.points.services.level_tags import validate_tag
    with pytest.raises(ValueError):
        validate_tag(text)


async def test_tag_unknown_without_matching_remote_state_is_not_retried(runtime):
    from backend.features.points.services.level_tags import reconcile_tags
    app,db,b,chat,user=runtime
    await setup_tag(db,chat)
    b.member(user)
    b.faults['setChatMemberTag']=[NetworkError('unknown without visible change')]
    with pytest.raises(RuntimeError):
        await reconcile_tags(app,now=NOW)
    await reconcile_tags(app,now=NOW+dt.timedelta(minutes=1))
    assert len(calls(b,'setChatMemberTag'))==1
    async with db.session_factory() as s:
        assert (await s.get(LevelTagState,(chat,user))).status=='uncertain'


async def test_level_tag_configuration_exit_and_role_recheck(runtime):
    app,db,b,chat,user=runtime
    level_id=await setup_tag(db,chat)
    await app.process_update(callback_update(app,user,400,f'ltag:{chat}:{level_id}:input'))
    await app.process_update(command_update(app,user,user,401,'新标签'))
    await app.process_update(callback_update(app,user,402,f'ltag:{chat}:{level_id}:input'))
    await app.process_update(callback_update(app,user,403,f'ltag:{chat}:{level_id}:view'))
    await app.process_update(command_update(app,user,user,404,'退出后不可写'))
    async with db.session_factory() as s:
        cfg=(await s.get(ChatSettings,chat)).module_config
        assert cfg['level_tags']['levels'][str(level_id)]['text']=='新标签'
    b.member(user)
    await app.process_update(callback_update(app,user,405,f'ltag:{chat}:0:set:0'))
    async with db.session_factory() as s:
        assert (await s.get(ChatSettings,chat)).module_config['level_tags']['enabled'] is True


async def test_explicit_rate_limit_waits_for_due_time_for_notice_and_tags(runtime):
    from backend.features.admin.services.effect_runtime import run_pending
    from backend.features.automation.services.ad_expiry import plan_reminders
    from backend.features.points.services.level_tags import reconcile_tags
    app,db,b,chat,user=runtime
    await create_reminder(db,chat,user)
    await plan_reminders(db,now=NOW)
    b.faults['sendMessage']=[(429,b'{"ok":false,"error_code":429,"description":"Too Many Requests","parameters":{"retry_after":120}}')]
    with pytest.raises(RuntimeError):
        await run_pending(app,now=NOW,chat_id=chat)
    await run_pending(app,now=NOW+dt.timedelta(seconds=60),chat_id=chat)
    assert len(calls(b,'sendMessage'))==1
    await run_pending(app,now=NOW+dt.timedelta(seconds=121),chat_id=chat)
    assert len(calls(b,'sendMessage'))==2
    await setup_tag(db,chat)
    b.member(user)
    b.faults['setChatMemberTag']=[(429,b'{"ok":false,"error_code":429,"description":"Too Many Requests","parameters":{"retry_after":120}}')]
    with pytest.raises(RuntimeError):
        await reconcile_tags(app,now=NOW)
    await reconcile_tags(app,now=NOW+dt.timedelta(seconds=60))
    assert len(calls(b,'setChatMemberTag'))==1
    await reconcile_tags(app,now=NOW+dt.timedelta(seconds=121))
    assert len(calls(b,'setChatMemberTag'))==2 and b.members[user]['tag']=='Level1'


async def test_all_tag_switch_combinations_and_threshold_boundaries(runtime):
    from backend.features.points.services.level_tags import reconcile_tags
    from backend.features.points.services.points_extended_levels import PointsExtendedLevelsMixin as Levels
    from backend.platform.db.schema.models.points import PointsAccount
    app,db,b,chat,user=runtime
    first=await setup_tag(db,chat)
    b.member(user)
    async with db.session_factory() as s:
        level=await Levels.create_level(s,chat)
        await Levels.update_level(s,level,level_name='Level2',point_threshold=200)
        await s.commit()
    step=0
    for global_on,level_on in [(False,False),(False,True),(True,False),(True,True)]:
        for balance in [-1,0,199,200,201,100]:
            async with db.session_factory() as s:
                settings=await s.get(ChatSettings,chat)
                settings.module_config={'level_tags':{'enabled':global_on,'levels':{
                    str(first):{'enabled':level_on,'text':'Level1'},str(level.id):{'enabled':level_on,'text':'Level2'}}}}
                account=await s.scalar(select(PointsAccount).where(PointsAccount.chat_id==chat,PointsAccount.user_id==user))
                account.balance=balance
                await s.commit()
            await reconcile_tags(app,now=NOW+dt.timedelta(minutes=step))
            expected='' if not(global_on and level_on) or balance<0 else ('Level2' if balance>=200 else 'Level1')
            assert b.members[user]['tag']==expected
            step+=1


async def test_durable_history_reaches_old_failed_rows_and_refuses_unknown_replay(runtime):
    app,db,b,chat,user=runtime
    async with db.session_factory() as s:
        rows=[]
        for i in range(25):
            rows.append(AdminEffect(effect_key=f'{chat}:history:{i}',chat_id=chat,kind='lock_notice',payload={},
                status='uncertain' if i==0 else 'permanent_failed',attempts=1,next_run_at=NOW,error='synthetic'))
        s.add_all(rows)
        await s.commit()
    await app.process_update(callback_update(app,user,500,f'eff:{chat}:lock_notice:list:3'))
    edits=calls(b,'editMessageText')
    assert '共25条，第4页' in edits[-1]['text'] and f'#{rows[0].id} ' in edits[-1]['text']
    await app.process_update(callback_update(app,user,501,f'eff:{chat}:lock_notice:retry:{rows[0].id}'))
    async with db.session_factory() as s:
        assert (await s.get(AdminEffect,rows[0].id)).status=='uncertain'
    await app.process_update(callback_update(app,user,502,f'eff:{chat}:lock_notice:retry:{rows[1].id}'))
    async with db.session_factory() as s:
        assert (await s.get(AdminEffect,rows[1].id)).status=='pending'


async def test_original_permission_read_failure_keeps_profile_disabled(runtime):
    app,db,b,chat,user=runtime
    b.faults['getChat']=[(403,b'{"ok":false,"error_code":403,"description":"Forbidden: read denied"}')]
    await app.process_update(callback_update(app,user,600,f'gperm:{chat}:open:set:photo:1'))
    async with db.session_factory() as s:
        assert not (await s.get(ChatSettings,chat)).module_config.get('group_lock')
    assert not calls(b,'setChatPermissions')
    assert any('无法读回' in str(p) for p in calls(b,'answerCallbackQuery'))


async def test_notice_button_input_and_photo_preview_stay_private(runtime):
    app,db,b,chat,user=runtime
    await app.process_update(callback_update(app,user,610,f'gnote:{chat}:open:input:buttons'))
    await app.process_update(command_update(app,user,user,611,'帮助|https://example.com；规则|https://example.org'))
    async with db.session_factory() as s:
        cfg=(await s.get(ChatSettings,chat)).module_config['group_lock']['notices']['open']
        assert len(cfg['buttons'])==1 and len(cfg['buttons'][0])==2
    await app.process_update(callback_update(app,user,612,f'gnote:{chat}:open:input:cover'))
    raw=command_update(app,user,user,613,'photo').to_dict()
    raw['message'].pop('text',None)
    raw['message'].pop('entities',None)
    raw['message']['photo']=[{'file_id':'test-cover','file_unique_id':'test-cover-unique','width':10,'height':10}]
    await app.process_update(Update.de_json(raw,app.bot))
    await app.process_update(callback_update(app,user,614,f'gnote:{chat}:open:preview'))
    assert calls(b,'sendPhoto')[-1]['chat_id']==user
    assert calls(b,'sendPhoto')[-1]['photo']=='test-cover'
    assert not any(int(p['chat_id'])<0 for p in calls(b,'sendMessage')+calls(b,'sendPhoto'))


async def test_unsupported_tag_endpoint_is_explicit_failure_without_role_changes(runtime):
    from backend.features.points.services.level_tags import reconcile_tags
    app,db,b,chat,user=runtime
    await setup_tag(db,chat)
    b.member(user)
    b.faults['setChatMemberTag']=[(404,b'{"ok":false,"error_code":404,"description":"Not Found"}')]
    with pytest.raises(RuntimeError):
        await reconcile_tags(app,now=NOW)
    async with db.session_factory() as s:
        state=await s.get(LevelTagState,(chat,user))
        assert state.status=='permanent_failed' and state.applied_tag is None
    assert not calls(b,'promoteChatMember')
    await reconcile_tags(app,now=NOW+dt.timedelta(minutes=1))
    assert len(calls(b,'setChatMemberTag'))==1


async def test_ad_notice_draft_version_tracks_ad_not_unrelated_chat_setting(runtime):
    from backend.platform.state.draft_versions import version_for_state
    _,db,_,chat,user=runtime
    ad_id=await create_reminder(db,chat,user)
    async with db.session_factory() as s:
        data={'prefix':'anote','target':str(ad_id),'target_chat_id':chat,'key':'text'}
        first=await version_for_state(s,'generic_notice_input',data,chat_id=chat)
        ad=await s.get(AdCampaign,ad_id)
        ad.expiry_notice={**ad.expiry_notice,'text':'changed template'}
        await s.flush()
        second=await version_for_state(s,'generic_notice_input',data,chat_id=chat)
        assert first!=second


@pytest.mark.parametrize(('command_cleanup','notice_seconds'), [('delete',0),('keep',30)])
async def test_trigger_command_and_notice_cleanup_are_independent(runtime, command_cleanup, notice_seconds):
    from backend.features.group_ops.group_hooks.control_lock import _process_group_lock_controls
    from backend.features.admin.services.effect_runtime import run_pending
    app,db,b,chat,user=runtime
    await configure_lock(db,chat)
    async with db.session_factory() as s:
        settings=await s.get(ChatSettings,chat)
        settings.group_lock_schedule_enabled=False
        settings.group_lock_delete_notice_mode=command_cleanup
        cfg=settings.module_config
        cfg['group_lock']['notices']['closed']['delete_seconds']=notice_seconds
        settings.module_config=dict(cfg)
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(settings,'module_config')
        await s.commit()
    update=command_update(app,user,chat,700,'关群')
    handled=await _process_group_lock_controls(SimpleNamespace(bot=app.bot,application=app),update.effective_chat,
        update.effective_user,message=update.effective_message,settings=settings,is_admin=True,message_text='关群')
    assert handled
    now=dt.datetime.now(dt.UTC)
    await run_pending(app,now=now,chat_id=chat)
    command_deletes=[p for p in calls(b,'deleteMessage') if p['message_id']==700]
    assert len(command_deletes)==(1 if command_cleanup=='delete' else 0)
    async with db.session_factory() as s:
        cleanups=list((await s.scalars(select(AdminEffect).where(AdminEffect.chat_id==chat,AdminEffect.kind=='notice_delete'))).all())
        assert len(cleanups)==(1 if notice_seconds else 0)
        assert all(row.payload['message_id']!=700 for row in cleanups)
