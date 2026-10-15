"""Remaining generic capabilities: actual routes/transactions and fake HTTP only."""
import asyncio
import datetime as dt
import json
import os
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select
from telegram import Update
from telegram.error import NetworkError
from telegram.ext import Application, MessageHandler, filters
from backend.app.update_pipeline import MessageDispatcher
from backend.features.admin.admin_router import AdminRouter
from backend.features.automation.ads_router import AdsRouter
from backend.features.points.points_router import PointsRouter
from backend.platform.db.runtime.session import create_database
from backend.platform.db.schema.models.admin_effects import AdminEffect, LevelTagState
from backend.platform.db.schema.models.chat import ChatSettings
from backend.platform.db.schema.models.automation import AdCampaign, AdRotationHistory, AdRotationRule
from backend.platform.runtime.chat_shard import install_chat_sharded_processing
from backend.shared.services.chat_service import get_chat_settings
from test_admin_routes_postgres import callback_update, command_update
from test_generic_admin_runtime_postgres import GeneralBoundary
from test_mall_intent_postgres import seed

URL=os.environ.get('TGR_REPAIR_TEST_DATABASE_URL')
pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(not URL,reason='disposable Postgres required')]


class RemainingBoundary(GeneralBoundary):
    def __init__(self):
        super().__init__()
        self.restrict_right=True
    async def do_request(self,url,method,request_data=None,**kwargs):
        endpoint=url.rsplit('/',1)[-1]
        params=request_data.parameters if request_data else {}
        if endpoint in {'banChatMember','unbanChatMember','restrictChatMember'}:
            fault=self.faults.get(endpoint)
            self.calls.append((endpoint,params))
            if fault and endpoint not in self.apply_before_fault:
                return self._fault(fault.pop(0))
            user_id=int(params['user_id'])
            member=self.members[user_id]
            if endpoint=='banChatMember':
                member.update(status='kicked',until_date=0)
            elif endpoint=='unbanChatMember':
                member['status']='left'
            else:
                member.update(status='restricted',is_member=True,until_date=params.get('until_date',0),
                    can_change_info=False,can_invite_users=False,can_pin_messages=False,can_manage_topics=False)
                member.update(params['permissions'])
            if fault:
                return self._fault(fault.pop(0))
            return 200,b'{"ok":true,"result":true}'
        response=await super().do_request(url,method,request_data=request_data,**kwargs)
        if endpoint=='getChatMember' and int(params['user_id'])==999000:
            value=json.loads(response[1])
            value['result']['can_restrict_members']=self.restrict_right
            return response[0],json.dumps(value).encode()
        return response


@pytest_asyncio.fixture
async def runtime():
    db,b=create_database(URL),RemainingBoundary()
    app=Application.builder().token('999000:TEST_TOKEN').request(b).build()
    app.bot_data['db']=db
    for router in (AdminRouter(),AdsRouter(),PointsRouter()):
        router.register(app)
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
    app.bot_data['qa_chats']={chat}
    try:
        yield app,db,b,chat,user
        assert not errors,errors
    finally:
        from sqlalchemy import delete
        async with db.session_factory() as s:
            scopes=app.bot_data['qa_chats']
            for model in (AdminEffect,LevelTagState):
                await s.execute(delete(model).where(model.chat_id.in_(scopes)))
            for row in (await s.scalars(select(ChatSettings).where(ChatSettings.chat_id.in_(scopes)))).all():
                row.module_config={}
                row.group_lock_schedule_enabled=False
            await s.commit()
        await app.shutdown()
        await db.engine.dispose()


def calls(b,endpoint):
    return [p for e,p in b.calls if e==endpoint]


async def extra_chat(runtime):
    app,db,_,_,_=runtime
    chat,user,_=await seed(db)
    async with db.session_factory() as s:
        await get_chat_settings(s,chat)
        await s.commit()
    app.bot_data['qa_chats'].add(chat)
    return chat,user


async def ad_plan(runtime,*,policy='delete_delay',mode='send'):
    from backend.features.automation.ad_delivery_executor import AdDeliveryPlan
    _,db,_,chat,_=runtime
    now=dt.datetime.now(dt.UTC)
    content={'title':'generic','content':'generic notice','last_sent_message_id':12}
    rules={'mode':mode,'delete_policy':policy,'delete_delay_seconds':30,'unpin_previous':True,
        'last_sent_message_id':12,'last_pinned_message_id':12,'next_cursor':1}
    async with db.session_factory() as s:
        ad=AdCampaign(chat_id=chat,title='generic',content='generic notice')
        s.add(ad)
        await s.flush()
        rule=await s.get(AdRotationRule,chat)
        if rule is None:
            s.add(AdRotationRule(chat_id=chat,last_pinned_message_id=12))
        row=AdRotationHistory(chat_id=chat,campaign_id=ad.id,dispatch_key=f'{chat}:{ad.id}',
            scheduled_for=now,content_snapshot=content,rule_snapshot=rules,status='processing',attempt_count=1)
        s.add(row)
        await s.commit()
    return AdDeliveryPlan(history_id=row.id,chat_id=chat,campaign_id=ad.id,content_snapshot=content,rule_snapshot=rules)


async def test_delayed_delete_survives_restart_concurrent_workers_and_keeps_send_success(runtime):
    from backend.features.automation.ad_delivery_executor import TelegramAdDeliveryExecutor
    from backend.features.automation.ad_delivery_repository import SqlAlchemyAdDeliveryStore
    from backend.features.admin.services.effect_runtime import run_pending
    app,db,b,chat,_=runtime
    plan=await ad_plan(runtime)
    outcome=await TelegramAdDeliveryExecutor(app).execute(plan)
    await SqlAlchemyAdDeliveryStore(db).finalize(plan,outcome,now=dt.datetime.now(dt.UTC))
    async with db.session_factory() as s:
        effect=await s.scalar(select(AdminEffect).where(AdminEffect.chat_id==chat))
        due=effect.next_run_at
        assert effect.payload['message_id']==outcome.message_id and effect.status=='pending'
    restarted=SimpleNamespace(bot=app.bot,bot_data={'db':db})
    await run_pending(restarted,now=due-dt.timedelta(seconds=1),chat_id=chat)
    assert not calls(b,'deleteMessage')
    await asyncio.gather(run_pending(restarted,now=due,chat_id=chat),run_pending(restarted,now=due,chat_id=chat))
    await run_pending(restarted,now=due+dt.timedelta(minutes=2),chat_id=chat)
    assert len(calls(b,'sendMessage'))==len(calls(b,'deleteMessage'))==1
    async with db.session_factory() as s:
        row=await s.get(AdRotationHistory,plan.history_id)
        assert row.status=='succeeded' and row.post_actions['delete_delay']=='succeeded'


@pytest.mark.parametrize(('fault','expected'),[(NetworkError('unknown'),'uncertain'),
    ((403,b'{"ok":false,"error_code":403,"description":"Forbidden: no delete right"}'),'permanent_failed'),
    ((429,b'{"ok":false,"error_code":429,"description":"Too Many Requests","parameters":{"retry_after":120}}'),'retryable_failed')])
async def test_cleanup_failure_never_repeats_body_and_unknown_is_not_replayed(runtime,fault,expected):
    from backend.features.automation.ad_delivery_executor import TelegramAdDeliveryExecutor
    from backend.features.automation.ad_delivery_repository import SqlAlchemyAdDeliveryStore
    from backend.features.admin.services.effect_runtime import run_pending
    app,db,b,chat,_=runtime
    plan=await ad_plan(runtime)
    outcome=await TelegramAdDeliveryExecutor(app).execute(plan)
    await SqlAlchemyAdDeliveryStore(db).finalize(plan,outcome,now=dt.datetime.now(dt.UTC))
    async with db.session_factory() as s:
        effect=await s.scalar(select(AdminEffect).where(AdminEffect.chat_id==chat))
        due=effect.next_run_at
    b.faults['deleteMessage']=[fault]
    with pytest.raises(RuntimeError):
        await run_pending(app,now=due,chat_id=chat)
    await run_pending(app,now=due+dt.timedelta(seconds=1),chat_id=chat)
    async with db.session_factory() as s:
        assert (await s.get(AdminEffect,effect.id)).status==expected
        assert (await s.get(AdRotationHistory,plan.history_id)).status=='succeeded'
    assert len(calls(b,'sendMessage'))==len(calls(b,'deleteMessage'))==1


async def test_failed_send_preserves_pre_actions_and_old_pin_fact(runtime):
    from backend.features.automation.ad_delivery_executor import TelegramAdDeliveryExecutor
    from backend.features.automation.ad_delivery_repository import SqlAlchemyAdDeliveryStore
    app,db,b,chat,_=runtime
    plan=await ad_plan(runtime,policy='delete_prev',mode='send_pin')
    b.faults['sendMessage']=[(403,b'{"ok":false,"error_code":403,"description":"Forbidden: send denied"}')]
    outcome=await TelegramAdDeliveryExecutor(app).execute(plan)
    await SqlAlchemyAdDeliveryStore(db).finalize(plan,outcome,now=dt.datetime.now(dt.UTC))
    async with db.session_factory() as s:
        row=await s.get(AdRotationHistory,plan.history_id)
        effects=(await s.scalars(select(AdminEffect).where(AdminEffect.chat_id==chat))).all()
        assert row.status=='permanent_failed' and row.post_actions=={'delete_previous':'succeeded','unpin_previous':'succeeded'}
        assert len(effects)==2 and all(e.status=='succeeded' for e in effects)
        assert (await s.get(AdRotationRule,chat)).last_pinned_message_id is None
    assert len(calls(b,'deleteMessage'))==len(calls(b,'unpinChatMessage'))==1


async def source_config(runtime):
    from backend.features.points.services.points_extended_levels import PointsExtendedLevelsMixin as Levels
    app,db,_,_,_=runtime
    source,user=await extra_chat(runtime)
    async with db.session_factory() as s:
        settings=await s.get(ChatSettings,source)
        settings.sign_points=19
        level=await Levels.create_level(s,source)
        await Levels.update_level(s,level,level_name='高级',point_threshold=0)
        setting=await Levels.get_or_create_level_setting(s,source)
        setting.enabled=True
        settings.module_config={'sign_feedback':{'template':'余额{balance}','show_count':True},
            'group_lock':{'profiles':{'closed':{'can_send_messages':False}},
                'notices':{'closed':{'enabled':True,'text':'群{chat_id}已关群','delete_seconds':30,'buttons':[]}},
                'original_permissions':{'source_only':True}},
            'level_tags':{'enabled':True,'levels':{str(level.id):{'enabled':True,'text':'高级'}}}}
        s.add(LevelTagState(chat_id=source,user_id=user,applied_tag='高级',desired_tag='高级',status='applied'))
        await s.commit()
    return source,level.id


async def test_import_rebuilds_level_ids_and_copies_only_selected_config_with_target_snapshot(runtime):
    from backend.platform.db.schema.models.points import PointsLevel, PointsAccount
    app,db,b,chat,user=runtime
    source,source_level=await source_config(runtime)
    for i,data in enumerate((f'adm:import:{chat}:source:{source}',f'adm:import:{chat}:module:points',
        f'adm:import:{chat}:module:night_mode',f'adm:import:{chat}:module:points_level',f'adm:import:{chat}:apply'),100):
        await app.process_update(callback_update(app,user,i,data))
    async with db.session_factory() as s:
        settings=await s.get(ChatSettings,chat)
        levels=(await s.scalars(select(PointsLevel).where(PointsLevel.chat_id==chat))).all()
        assert len(levels)==1 and levels[0].id!=source_level
        config=settings.module_config
        assert settings.sign_points==19 and config['sign_feedback']['template']=='余额{balance}'
        assert config['level_tags']['levels']=={str(levels[0].id):{'enabled':True,'text':'高级'}}
        assert 'source_only' not in config['group_lock']['original_permissions']
        assert config['group_lock']['original_permissions']['can_send_messages'] is True
        assert not (await s.scalars(select(LevelTagState).where(LevelTagState.chat_id==chat))).all()
        assert (await s.scalar(select(PointsAccount).where(PointsAccount.chat_id==chat))).balance==100
    assert calls(b,'getChat') and not calls(b,'setChatPermissions') and not calls(b,'setChatMemberTag')
    assert all(int(p['chat_id'])>0 for p in calls(b,'sendMessage'))


async def test_import_snapshot_read_failure_rolls_back_entire_selected_copy(runtime):
    app,db,b,chat,user=runtime
    source,_=await source_config(runtime)
    for i,data in enumerate((f'adm:clone:{source}:target:{chat}',f'adm:clone:{source}:module:points',
        f'adm:clone:{source}:module:night_mode'),200):
        await app.process_update(callback_update(app,user,i,data))
    b.faults['getChat']=[(403,b'{"ok":false,"error_code":403,"description":"Forbidden: cannot read"}')]
    await app.process_update(callback_update(app,user,203,f'adm:clone:{source}:apply'))
    async with db.session_factory() as s:
        target=await s.get(ChatSettings,chat)
        assert target.sign_points==5 and target.module_config=={}
    assert not calls(b,'setChatPermissions')


async def alliance_scope(runtime,*,action='mute'):
    from backend.features.garage.services.alliance_service import AllianceService
    app,db,b,chat,user=runtime
    target=user+100
    b.member(target)
    async with db.session_factory() as s:
        await AllianceService.create_alliance(s,chat_id=chat,operator_user_id=user,name=f'generic-{chat}')
        await AllianceService.set_joint_ban_enabled(s,chat_id=chat,operator_user_id=user,enabled=True)
        entry=await AllianceService.add_joint_ban_entry(s,chat_id=chat,operator_user_id=user,target_user_id=target,punishment_type=action)
        await s.commit()
    return target,entry.id


def reply_command(app,user,chat,target,update_id,text):
    raw=command_update(app,user,chat,update_id,text).to_dict()
    raw['message']['reply_to_message']={'message_id':10,'date':1780000000,
        'from':{'id':target,'is_bot':False,'first_name':'target'},'chat':{'id':chat,'type':'supergroup'},'text':'hello'}
    return Update.de_json(raw,app.bot)


async def test_alliance_duplicate_commands_upgrade_and_never_downgrade(runtime):
    app,db,b,chat,user=runtime
    target,_=await alliance_scope(runtime)
    for i,command in enumerate(('team_mute','team_mute','team','team_mute'),300):
        await app.process_update(reply_command(app,user,chat,target,i,command))
    assert len(calls(b,'restrictChatMember'))==len(calls(b,'banChatMember'))==1
    async with db.session_factory() as s:
        rows=(await s.scalars(select(AdminEffect).where(AdminEffect.chat_id==chat,AdminEffect.kind=='alliance_punish'))).all()
        assert len(rows)==2 and all(row.status=='succeeded' and row.result['applied'] for row in rows)


async def test_alliance_concurrent_hit_and_confirmed_local_release_suppress_same_pool_version(runtime):
    from backend.features.group_ops.services.alliance_runtime import process_hit
    from backend.features.admin.services.effect_runtime import run_pending
    app,db,b,chat,user=runtime
    target,_=await alliance_scope(runtime,action='ban')
    context=SimpleNamespace(application=app,bot=app.bot)
    async def hit():
        return await process_hit(context,db,chat=SimpleNamespace(id=chat),user=SimpleNamespace(id=target))
    await asyncio.gather(hit(),hit(),hit())
    assert len(calls(b,'banChatMember'))==1
    async with db.session_factory() as s:
        parent=await s.scalar(select(AdminEffect).where(AdminEffect.chat_id==chat,AdminEffect.kind=='alliance_punish'))
    await app.process_update(callback_update(app,user,400,f'asan:{chat}:ask:{parent.id}'))
    assert not calls(b,'unbanChatMember')
    await app.process_update(callback_update(app,user,401,f'asan:{chat}:confirm:{parent.id}'))
    await run_pending(app,chat_id=chat)
    assert len(calls(b,'unbanChatMember'))==1 and calls(b,'unbanChatMember')[0]['only_if_banned'] is True
    assert await hit() is False
    await app.process_update(callback_update(app,user,402,f'asan:{chat}:confirm:{parent.id}'))
    await run_pending(app,chat_id=chat)
    assert len(calls(b,'unbanChatMember'))==1


@pytest.mark.parametrize('condition',['no_bot_right','target_admin','preexisting','unknown'])
async def test_alliance_roles_preexisting_and_unknown_never_claim_release_ownership(runtime,condition):
    from backend.features.group_ops.services.alliance_runtime import process_hit
    app,db,b,chat,user=runtime
    target,_=await alliance_scope(runtime,action='ban')
    if condition=='no_bot_right':
        b.restrict_right=False
    if condition=='target_admin':
        b.members[target].update(status='creator',is_anonymous=False)
    if condition=='preexisting':
        b.members[target].update(status='kicked',until_date=0)
    if condition=='unknown':
        b.faults['banChatMember']=[NetworkError('unknown')]
        b.apply_before_fault.add('banChatMember')
    assert await process_hit(SimpleNamespace(application=app,bot=app.bot),db,chat=SimpleNamespace(id=chat),user=SimpleNamespace(id=target))
    async with db.session_factory() as s:
        row=await s.scalar(select(AdminEffect).where(AdminEffect.chat_id==chat))
        assert not row.result.get('applied')
        if condition=='unknown':
            assert row.status=='uncertain'
    await app.process_update(callback_update(app,user,500,f'asan:{chat}:confirm:{row.id}'))
    assert not calls(b,'unbanChatMember')
    async with db.session_factory() as s:
        assert not (await s.scalars(select(AdminEffect).where(AdminEffect.chat_id==chat,AdminEffect.kind=='alliance_release'))).all()


async def test_release_foreign_changed_state_is_refused_and_other_chat_cannot_release(runtime):
    from backend.features.group_ops.services.alliance_runtime import process_hit
    from backend.features.admin.services.effect_runtime import run_pending
    app,db,b,chat,user=runtime
    target,_=await alliance_scope(runtime)
    await process_hit(SimpleNamespace(application=app,bot=app.bot),db,chat=SimpleNamespace(id=chat),user=SimpleNamespace(id=target))
    async with db.session_factory() as s:
        parent=await s.scalar(select(AdminEffect).where(AdminEffect.chat_id==chat))
    other,_=await extra_chat(runtime)
    await app.process_update(callback_update(app,user,600,f'asan:{other}:confirm:{parent.id}'))
    b.members[target]['status']='kicked'  # A later ban must survive an older mute release.
    await app.process_update(callback_update(app,user,601,f'asan:{chat}:confirm:{parent.id}'))
    with pytest.raises(RuntimeError):
        await run_pending(app,chat_id=chat)
    assert len(calls(b,'restrictChatMember'))==1 and not calls(b,'unbanChatMember')


@pytest.mark.parametrize('before_restricted',[False,True])
async def test_mute_release_keeps_prior_restriction_and_current_group_limits(runtime,before_restricted):
    from backend.features.group_ops.services.alliance_runtime import process_hit
    from backend.features.admin.services.effect_runtime import run_pending
    app,db,b,chat,user=runtime
    target,_=await alliance_scope(runtime)
    until=int((dt.datetime.now(dt.UTC)+dt.timedelta(hours=1)).timestamp())
    if before_restricted:
        from backend.features.group_ops.services.alliance_effects import SEND_FIELDS
        b.members[target].update(status='restricted',is_member=True,until_date=until,can_change_info=False,
            can_invite_users=False,can_pin_messages=False,can_manage_topics=False,**{key:True for key in SEND_FIELDS})
        b.members[target]['can_send_photos']=False
    context=SimpleNamespace(application=app,bot=app.bot)
    await process_hit(context,db,chat=SimpleNamespace(id=chat),user=SimpleNamespace(id=target))
    async with db.session_factory() as s:
        parent=await s.scalar(select(AdminEffect).where(AdminEffect.chat_id==chat))
        assert parent.result['applied']
    await app.process_update(callback_update(app,user,700,f'asan:{chat}:confirm:{parent.id}'))
    await run_pending(app,chat_id=chat)
    assert len(calls(b,'restrictChatMember'))==2
    restored=calls(b,'restrictChatMember')[-1]
    assert restored['permissions']['can_send_messages'] is True
    assert restored['permissions']['can_send_photos'] is (not before_restricted)
    assert restored['permissions']['can_send_videos'] is False  # Group default omitted => do not expand.
    if before_restricted:
        assert int(restored['until_date'])==until


async def test_pool_removal_cancels_pending_hit_but_does_not_unban_other_chats(runtime):
    from backend.features.garage.services.alliance_service import AllianceService
    from backend.features.group_ops.services.alliance_effects import plan_punishment
    from backend.features.admin.services.effect_runtime import run_pending
    from backend.platform.db.schema.models.alliance import GroupAllianceBanPool
    app,db,b,chat,user=runtime
    target,entry_id=await alliance_scope(runtime,action='ban')
    async with db.session_factory() as s:
        entry=await s.get(GroupAllianceBanPool,entry_id)
        await plan_punishment(s,entry=entry,chat_id=chat)
        await s.commit()
    await app.process_update(callback_update(app,user,800,f'ali:jointban:remove:{chat}:{entry_id}'))
    await run_pending(app,chat_id=chat)
    assert not calls(b,'banChatMember') and not calls(b,'unbanChatMember')
    async with db.session_factory() as s:
        assert not await AllianceService.get_joint_ban_hit(s,chat_id=chat,target_user_id=target)
        row=await s.scalar(select(AdminEffect).where(AdminEffect.chat_id==chat))
        assert row.status=='cancelled'


async def test_exit_cancels_prepared_pool_action_and_preserves_old_remote_punishments(runtime):
    from backend.features.garage.services.alliance_service import AllianceService
    from backend.features.group_ops.services.alliance_effects import plan_punishment
    from backend.features.admin.services.effect_runtime import run_pending
    from backend.platform.db.schema.models.alliance import GroupAllianceBanPool,GroupAllianceMember
    app,db,b,chat,user=runtime
    target,entry_id=await alliance_scope(runtime,action='ban')
    async with db.session_factory() as s:
        await plan_punishment(s,entry=await s.get(GroupAllianceBanPool,entry_id),chat_id=chat)
        member=await s.scalar(select(GroupAllianceMember).where(GroupAllianceMember.chat_id==chat))
        member.status='left'
        await s.commit()
    await run_pending(app,chat_id=chat)
    assert not calls(b,'banChatMember') and not calls(b,'unbanChatMember')
    async with db.session_factory() as s:
        assert await AllianceService.get_joint_ban_hit(s,chat_id=chat,target_user_id=target) is None


async def test_pin_failure_can_retry_only_pin_and_keeps_original_send_once(runtime):
    from backend.features.automation.ad_delivery_executor import TelegramAdDeliveryExecutor
    from backend.features.automation.ad_delivery_repository import SqlAlchemyAdDeliveryStore
    from backend.features.admin.services.effect_runtime import run_pending
    app,db,b,chat,user=runtime
    plan=await ad_plan(runtime,policy='none',mode='send_pin')
    b.faults['pinChatMessage']=[(403,b'{"ok":false,"error_code":403,"description":"Forbidden: no pin right"}')]
    outcome=await TelegramAdDeliveryExecutor(app).execute(plan)
    await SqlAlchemyAdDeliveryStore(db).finalize(plan,outcome,now=dt.datetime.now(dt.UTC))
    async with db.session_factory() as s:
        effect=await s.scalar(select(AdminEffect).where(AdminEffect.chat_id==chat,AdminEffect.payload['action'].astext=='pin'))
        assert effect.status=='permanent_failed'
    await app.process_update(callback_update(app,user,900,f'eff:{chat}:delivery_action:retry:{effect.id}'))
    await run_pending(app,chat_id=chat)
    assert len(calls(b,'pinChatMessage'))==2
    # One primary group send, plus optional private admin UI replies.
    assert len([p for p in calls(b,'sendMessage') if int(p['chat_id'])==chat])==1
    async with db.session_factory() as s:
        row=await s.get(AdRotationHistory,plan.history_id)
        rule=await s.get(AdRotationRule,chat)
        assert row.status=='succeeded' and row.post_actions['pin']=='succeeded'
        assert row.message_id==rule.last_pinned_message_id


async def test_scheduled_failed_send_keeps_durable_delete_fact(runtime):
    import uuid
    from backend.features.automation.scheduled_delivery_executor import ScheduledDeliveryPlan,TelegramScheduledDeliveryExecutor
    from backend.features.automation.scheduled_occurrence_repository import SqlAlchemyScheduledOccurrenceStore
    from backend.platform.db.schema.models.scheduled_message import ScheduledMessageTask,ScheduledMessageLog
    app,db,b,chat,_=runtime
    snapshot={'text':'generic','parse_mode':'none','delete_previous':True,'last_sent_message_id':12,'pin_message':True}
    async with db.session_factory() as s:
        task=ScheduledMessageTask(task_id=uuid.uuid4(),short_id=uuid.uuid4().hex[:8],chat_id=chat,title='generic')
        s.add(task)
        await s.flush()
        row=ScheduledMessageLog(task_id=task.task_id,chat_id=chat,run_key=f'{chat}:previous',scheduled_for=1,
            content_snapshot=snapshot,status='processing',attempt_count=1)
        s.add(row)
        await s.commit()
    plan=ScheduledDeliveryPlan(occurrence_id=row.id,task_id=str(task.task_id),chat_id=chat,snapshot=snapshot)
    b.faults['sendMessage']=[NetworkError('unknown main send')]
    outcome=await TelegramScheduledDeliveryExecutor(app).execute(plan)
    await SqlAlchemyScheduledOccurrenceStore(db).finalize(plan,outcome,now=dt.datetime.now(dt.UTC))
    async with db.session_factory() as s:
        row=await s.get(ScheduledMessageLog,row.id)
        assert row.status=='uncertain' and row.post_actions['delete_previous']=='succeeded'
        assert (await s.scalar(select(AdminEffect).where(AdminEffect.chat_id==chat))).status=='succeeded'
    assert len(calls(b,'deleteMessage'))==1 and not calls(b,'pinChatMessage')


async def test_import_only_selected_module_preserves_unselected_configuration(runtime):
    from backend.shared.services.import_settings_service import apply_import
    from backend.platform.db.schema.models.points import PointsLevel
    app,db,_,chat,user=runtime
    source,_=await source_config(runtime)
    async with db.session_factory() as s:
        target=await s.get(ChatSettings,chat)
        target.module_config={'group_lock':{'original_permissions':{'target':True}},'verification':{'prompt_fail_open':False}}
        await s.commit()
    async with db.session_factory() as s:
        await apply_import(s,source_chat_id=source,target_chat_id=chat,modules=['points'],
            context=SimpleNamespace(bot=app.bot,application=app),actor_user_id=user)
        await s.commit()
    async with db.session_factory() as s:
        target=await s.get(ChatSettings,chat)
        assert target.module_config['group_lock']=={'original_permissions':{'target':True}}
        assert target.module_config['verification']=={'prompt_fail_open':False}
        assert target.module_config['sign_feedback']['show_count'] is True
        assert not (await s.scalars(select(PointsLevel).where(PointsLevel.chat_id==chat))).all()


@pytest.mark.parametrize('source',['ads','scheduled'])
async def test_receipt_commits_pin_before_crash_and_restart_never_resends_body(runtime,source):
    import uuid
    from backend.features.automation.delivery_action_journal import record_receipt
    from backend.features.admin.services.effect_runtime import run_pending
    from backend.features.automation.scheduled_delivery_executor import ScheduledDeliveryPlan
    from backend.platform.db.schema.models.scheduled_message import ScheduledMessageTask,ScheduledMessageLog
    app,db,b,chat,_=runtime
    if source=='ads':
        plan=await ad_plan(runtime,policy='delete_delay',mode='send_pin')
        model,parent_id=AdRotationHistory,plan.history_id
    else:
        snapshot={'text':'generic','pin_message':True}
        async with db.session_factory() as s:
            task=ScheduledMessageTask(task_id=uuid.uuid4(),short_id=uuid.uuid4().hex[:8],chat_id=chat,title='generic')
            s.add(task)
            await s.flush()
            row=ScheduledMessageLog(task_id=task.task_id,chat_id=chat,run_key=f'{chat}:crash-pin',
                scheduled_for=1,content_snapshot=snapshot,status='processing',attempt_count=1)
            s.add(row)
            await s.commit()
        plan=ScheduledDeliveryPlan(occurrence_id=row.id,task_id=str(task.task_id),chat_id=chat,snapshot=snapshot)
        model,parent_id=ScheduledMessageLog,row.id
    # Simulate the precise crash boundary: confirmed receipt committed, executor never returns.
    await record_receipt(app,plan,message_id=77)
    async with db.session_factory() as s:
        effects=(await s.scalars(select(AdminEffect).where(AdminEffect.chat_id==chat))).all()
        assert {e.payload['action'] for e in effects}==({'pin','delete_delay'} if source=='ads' else {'pin'})
        due=max(e.next_run_at for e in effects)
        row=await s.get(model,parent_id)
        row.status='uncertain'
        await s.commit()
    restarted=SimpleNamespace(bot=app.bot,bot_data={'db':db})
    await run_pending(restarted,chat_id=chat,now=due)
    await run_pending(restarted,chat_id=chat,now=due+dt.timedelta(minutes=5))
    assert not calls(b,'sendMessage') and len(calls(b,'pinChatMessage'))==1
    assert len(calls(b,'deleteMessage'))==(1 if source=='ads' else 0)
    async with db.session_factory() as s:
        row=await s.get(model,parent_id)
        assert row.status=='uncertain' and row.post_actions['pin']=='succeeded'


async def test_durable_pin_result_is_not_erased_by_stale_executor_metadata(runtime):
    from backend.features.automation.delivery_action_journal import record_receipt
    from backend.features.admin.services.effect_runtime import run_pending
    from backend.features.automation.ad_delivery_repository import SqlAlchemyAdDeliveryStore
    from backend.platform.delivery import DeliveryOutcome
    app,db,_,chat,_=runtime
    plan=await ad_plan(runtime,policy='none',mode='send_pin')
    await record_receipt(app,plan,message_id=77)
    await run_pending(app,chat_id=chat)
    await SqlAlchemyAdDeliveryStore(db).finalize(plan,DeliveryOutcome.success(message_id=77,
        metadata={'pinned_message_id':None,'post_actions':{'pin':'processing'}}),now=dt.datetime.now(dt.UTC))
    async with db.session_factory() as s:
        row=await s.get(AdRotationHistory,plan.history_id)
        rule=await s.get(AdRotationRule,chat)
        assert row.post_actions['pin']=='succeeded' and row.pinned_message_id==rule.last_pinned_message_id==77
