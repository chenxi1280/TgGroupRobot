"""Fresh PRD audit: real routes/transactions, no live Telegram transport."""
import asyncio
import datetime as dt
import json
import os

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from telegram import Update
from telegram.ext import Application, MessageHandler, filters

from backend.app.update_pipeline import MessageDispatcher
from backend.features.admin.admin_router import AdminRouter
from backend.features.points.points_router import PointsRouter
from backend.platform.db.runtime.session import create_database
from backend.platform.db.schema.models.admin_effects import AdminEffect
from backend.platform.db.schema.models.chat import ChatSettings
from backend.platform.runtime.chat_shard import install_chat_sharded_processing
from backend.shared.services.chat_service import get_chat_settings
from test_admin_routes_postgres import TelegramBoundary, callback_update, command_update
from test_mall_intent_postgres import seed

URL = os.environ.get('TGR_REPAIR_TEST_DATABASE_URL')
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not URL, reason='disposable Postgres required')]


class AuditBoundary(TelegramBoundary):
    role = 'creator'
    denied_chats = frozenset()

    async def do_request(self, url, method, request_data=None, **kwargs):
        params = request_data.parameters if request_data else {}
        role = 'member' if params.get('chat_id') in self.denied_chats else self.role
        if url.endswith('/getChatMember') and role != 'creator':
            self.calls.append(('getChatMember', params))
            member = {'status':role, 'user':{'id':int(params['user_id']), 'is_bot':False, 'first_name':'QA'}}
            if role == 'administrator':
                member.update(is_anonymous=False, can_be_edited=False, can_manage_chat=True, can_delete_messages=True,
                    can_manage_video_chats=False, can_restrict_members=True, can_promote_members=False,
                    can_change_info=True, can_invite_users=True, can_post_stories=False,
                    can_edit_stories=False, can_delete_stories=False)
            return 200, json.dumps({'ok':True,'result':member}).encode()
        return await super().do_request(url, method, request_data=request_data, **kwargs)


@pytest_asyncio.fixture
async def runtime():
    db, boundary = create_database(URL), AuditBoundary()
    app = Application.builder().token('999000:TEST_TOKEN').request(boundary).build()
    app.bot_data['db'] = db
    AdminRouter().register(app)
    PointsRouter().register(app)
    app.add_handler(MessageHandler(filters.ALL, MessageDispatcher().dispatch))
    errors = []
    async def error(update, context):
        errors.append(repr(context.error))
    app.add_error_handler(error)
    install_chat_sharded_processing(app)
    await app.initialize()
    chat, user, _ = await seed(db)
    async with db.session_factory() as s:
        await get_chat_settings(s, chat)
        await s.commit()
    try:
        yield app, db, boundary, chat, user
        assert not errors, errors
        assert all(int(p['chat_id']) > 0 for e,p in boundary.calls if e in {'sendMessage','sendPhoto'})
    finally:
        await app.shutdown()
        await db.engine.dispose()


def text_update(app, user, update_id, text):
    raw = command_update(app,user,user,update_id,text).to_dict()
    raw['message'].pop('entities',None)
    return Update.de_json(raw,app.bot)


def rendered(boundary):
    return [p['text'] for e,p in boundary.calls if e in {'sendMessage','editMessageText'}][-1]


@pytest.mark.parametrize('field', ['all_enabled','sign_enabled','message_points_enabled','invite_points_enabled',
    'points_display_rule_enabled','points_speech_rank_enabled','points_personal_speech_enabled'])
async def test_all_points_switches_use_real_registered_routes(runtime, field):
    app,db,b,chat,user = runtime
    for i,value in enumerate((0,1)):
        await app.process_update(callback_update(app,user,100+i,f'pts:toggle:{field}:{chat}:{value}'))
        assert '配置已更新' in rendered(b)
        async with db.session_factory() as s:
            settings = await s.get(ChatSettings,chat)
            names = ['sign_enabled','message_points_enabled','invite_points_enabled'] if field == 'all_enabled' else [field]
            assert all(getattr(settings,name) is bool(value) for name in names)


@pytest.mark.parametrize(('field','persisted'), [('message_daily_limit','message_points_daily_limit'),
    ('invite_daily_limit','invite_points_daily_limit'), ('message_min_length','message_min_length')])
async def test_points_limits_persist_and_zero_clears(runtime, field, persisted):
    app,db,b,chat,user = runtime
    for i,value in enumerate(('7','0')):
        await app.process_update(callback_update(app,user,200+i*2,f'pts:edit:{field}:{chat}'))
        await app.process_update(text_update(app,user,201+i*2,value))
        assert '配置已更新' in rendered(b)
        async with db.session_factory() as s:
            assert getattr(await s.get(ChatSettings,chat),persisted) == (7 if value == '7' else None)
        assert 'points_edit_field' not in app.user_data[user]


@pytest.mark.parametrize(('field','value'), [('sign_points','-1'),('message_points','-5'),
    ('invite_points','2147483648'),('sign_consecutive','7,-10'),('points_alias','a'*33)])
async def test_invalid_points_values_do_not_modify_db(runtime, field, value):
    app,db,b,chat,user = runtime
    async with db.session_factory() as s:
        row = await s.get(ChatSettings,chat)
        before = {c.key:getattr(row,c.key) for c in ChatSettings.__table__.columns}
    await app.process_update(callback_update(app,user,300,f'pts:edit:{field}:{chat}'))
    await app.process_update(text_update(app,user,301,value))
    assert '输入格式错误' in rendered(b)
    async with db.session_factory() as s:
        row = await s.get(ChatSettings,chat)
        assert {c.key:getattr(row,c.key) for c in ChatSettings.__table__.columns} == before
    await app.process_update(callback_update(app,user,302,f'pts:home:{chat}'))
    await app.process_update(text_update(app,user,303,'999'))
    assert 'points_edit_field' not in app.user_data[user]


async def test_points_old_buttons_follow_policy_and_recheck_input_revocation(runtime):
    app,db,b,chat,user = runtime
    b.role='administrator'  # No can_promote_members; default policy must deny.
    await app.process_update(callback_update(app,user,400,f'pts:edit:sign_points:{chat}'))
    assert 'points_edit_field' not in app.user_data[user]
    async with db.session_factory() as s:
        settings=await s.get(ChatSettings,chat)
        settings.control_permission_policy='all_admins'
        await s.commit()
    await app.process_update(callback_update(app,user,401,f'pts:edit:sign_points:{chat}'))
    assert app.user_data[user]['points_edit_field']=='sign_points'
    b.role='member'
    await app.process_update(text_update(app,user,402,'999'))
    assert '已退出编辑' in rendered(b)
    assert 'points_edit_field' not in app.user_data[user]
    async with db.session_factory() as s:
        assert (await s.get(ChatSettings,chat)).sign_points==5


@pytest.mark.parametrize('data', ['pts:toggle:chat_id:{chat}:1', 'pts:toggle:verification_enabled:{chat}:1',
    'pts:toggle:sign_enabled:{chat}:2', 'pts:edit:control_permission_policy:{chat}'])
async def test_forged_points_fields_never_mutate_configuration(runtime, data):
    app,db,b,chat,user=runtime
    await app.process_update(callback_update(app,user,500,data.format(chat=chat)))
    assert '无效积分' in rendered(b)
    assert 'points_edit_field' not in app.user_data[user]
    async with db.session_factory() as s:
        row=await s.get(ChatSettings,chat)
        assert row.sign_enabled and row.control_permission_policy=='can_promote_members'


async def test_points_exit_renders_requested_menu_and_plain_text_is_not_saved(runtime):
    app,db,b,chat,user=runtime
    await app.process_update(callback_update(app,user,600,f'pts:edit:sign_points:{chat}'))
    await app.process_update(callback_update(app,user,601,f'adm:menu:night:{chat}'))
    assert '夜间管控' in rendered(b)
    await app.process_update(text_update(app,user,602,'999'))
    async with db.session_factory() as s:
        assert (await s.get(ChatSettings,chat)).sign_points==5


async def test_stale_config_snapshots_merge_independent_modules_and_keys(runtime):
    from backend.shared.services.module_config_service import update_module_config
    _,db,_,chat,_=runtime
    async with db.session_factory() as a, db.session_factory() as b:
        left,right=await a.get(ChatSettings,chat),await b.get(ChatSettings,chat)
        await update_module_config(a,left,module='group_lock',patch={'notices':{'closed':{'enabled':True}}})
        await a.commit()
        await update_module_config(b,right,module='verification',patch={'prompt_fail_open':False})
        await b.commit()
        assert right.module_config['group_lock']['notices']['closed']['enabled']
    loaded=asyncio.Barrier(3)
    async def writer(module,key):
        async with db.session_factory() as s:
            row=await s.get(ChatSettings,chat)
            await loaded.wait()
            await update_module_config(s,row,module=module,patch={key:True})
            await s.commit()
    await asyncio.gather(writer('level_tags','enabled'),writer('group_lock','second'),writer('level_tags','third'))
    async with db.session_factory() as s:
        config=(await s.get(ChatSettings,chat)).module_config
        assert config['verification']=={'prompt_fail_open':False}
        assert config['level_tags']=={'enabled':True,'third':True}
        assert config['group_lock']['second'] and config['group_lock']['notices']['closed']['enabled']


async def test_effect_crash_does_not_starve_other_group_and_started_lease_is_unknown(runtime):
    from backend.features.admin.services.effect_runtime import run_pending
    from backend.features.group_ops.services.lock_plans import plan_schedule
    from test_generic_admin_runtime_postgres import NOW, configure_lock
    app,db,b,chat,_=runtime
    second,_,_=await seed(db)
    async with db.session_factory() as s:
        await get_chat_settings(s,second)
        await s.commit()
    await configure_lock(db,chat,notice=False)
    await configure_lock(db,second,notice=False)
    await plan_schedule(db,now=NOW,chat_id=chat)
    await plan_schedule(db,now=NOW,chat_id=second)
    async with db.session_factory() as s:
        first_id=await s.scalar(select(AdminEffect.id).where(AdminEffect.chat_id==chat))
    trigger=f'audit_effect_{first_id}'
    async with db.engine.begin() as conn:
        await conn.execute(text(f"CREATE FUNCTION bot.{trigger}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'audit finalize failure'; END $$"))
        await conn.execute(text(f"CREATE TRIGGER {trigger} BEFORE UPDATE ON bot.admin_effects FOR EACH ROW WHEN (NEW.id = {first_id} AND NEW.status = 'succeeded') EXECUTE FUNCTION bot.{trigger}()"))
    try:
        with pytest.raises(RuntimeError,match='failures'):
            await run_pending(app,now=NOW)
    finally:
        async with db.engine.begin() as conn:
            await conn.execute(text(f'DROP TRIGGER {trigger} ON bot.admin_effects'))
            await conn.execute(text(f'DROP FUNCTION bot.{trigger}()'))
    async with db.session_factory() as s:
        failed=await s.scalar(select(AdminEffect).where(AdminEffect.chat_id==chat))
        healthy=await s.scalar(select(AdminEffect).where(AdminEffect.chat_id==second))
        assert failed.status=='processing' and failed.started_at is not None
        assert healthy.status=='succeeded'
    with pytest.raises(RuntimeError,match='failures'):
        await run_pending(app,now=NOW+dt.timedelta(seconds=121),chat_id=chat)
    assert len([p for e,p in b.calls if e=='setChatPermissions' and int(p['chat_id'])==chat])==1


async def test_manual_retry_preserves_server_rate_limit_deadline(runtime):
    app,db,b,chat,user=runtime
    deadline=dt.datetime.now(dt.UTC)+dt.timedelta(hours=1)
    async with db.session_factory() as s:
        row=AdminEffect(effect_key=f'rate-{chat}',chat_id=chat,kind='lock_notice',payload={},
            status='retryable_failed',attempts=1,next_run_at=deadline,error='telegram_rate_limited')
        s.add(row)
        await s.commit()
        effect_id=row.id
    await app.process_update(callback_update(app,user,700,f'eff:{chat}:lock_notice:retry:{effect_id}'))
    async with db.session_factory() as s:
        row=await s.get(AdminEffect,effect_id)
        assert row.status=='retryable_failed' and row.next_run_at==deadline and row.attempts==1
    assert not [1 for e,_ in b.calls if e=='sendPhoto']


@pytest.mark.parametrize('mode', ['import','clone'])
async def test_transfer_checks_peer_at_selection_and_again_at_execution(runtime, mode):
    app,db,b,chat,user=runtime
    peer,_,_=await seed(db)
    async with db.session_factory() as s:
        settings=await get_chat_settings(s,peer)
        settings.sign_points=17
        await s.commit()
    op='source' if mode=='import' else 'target'
    b.denied_chats={peer}
    await app.process_update(callback_update(app,user,800,f'adm:{mode}:{chat}:{op}:{peer}'))
    assert any('另一端群组' in p.get('text','') for e,p in b.calls)
    b.denied_chats=frozenset()
    await app.process_update(callback_update(app,user,801,f'adm:{mode}:{chat}:{op}:{peer}'))
    await app.process_update(callback_update(app,user,802,f'adm:{mode}:{chat}:module:points'))
    b.denied_chats={peer}
    await app.process_update(callback_update(app,user,803,f'adm:{mode}:{chat}:apply'))
    async with db.session_factory() as s:
        assert (await s.get(ChatSettings,chat)).sign_points==5
        assert (await s.get(ChatSettings,peer)).sign_points==17
    b.denied_chats=frozenset()
    await app.process_update(callback_update(app,user,804,f'adm:{mode}:{chat}:apply'))
    assert ('导入完成' if mode=='import' else '克隆完成') in rendered(b)
    async with db.session_factory() as s:
        assert (await s.get(ChatSettings,chat)).sign_points==(17 if mode=='import' else 5)
        assert (await s.get(ChatSettings,peer)).sign_points==(17 if mode=='import' else 5)


async def test_bidirectional_transfer_locks_in_stable_order_and_missing_target_is_error(runtime):
    from backend.shared.services.import_settings_service import apply_import
    from backend.shared.services.base import ValidationError
    _,db,_,chat,_=runtime
    peer,_,_=await seed(db)
    async with db.session_factory() as s:
        other=await get_chat_settings(s,peer)
        other.sign_points=17
        await s.commit()
    async def copy(source,target):
        async with db.session_factory() as s:
            await apply_import(s,source_chat_id=source,target_chat_id=target,modules=['points'])
            await s.commit()
    await asyncio.wait_for(asyncio.gather(copy(chat,peer),copy(peer,chat)),timeout=5)
    async with db.session_factory() as s:
        assert (await s.get(ChatSettings,chat)).sign_points==(await s.get(ChatSettings,peer)).sign_points
        with pytest.raises(ValidationError,match='不存在'):
            await apply_import(s,source_chat_id=chat,target_chat_id=-1,modules=['points'])
        with pytest.raises(ValidationError,match='无效'):
            await apply_import(s,source_chat_id=chat,target_chat_id=peer,modules=['unknown'])


@pytest.mark.parametrize('state_type', ['bottom_button_text_input','game_wait_auto_start_time',
    'guess_wait_rake_ratio','engagement_wait_chat_target','quick_publish_input'])
async def test_own_admin_input_revocation_exits_before_mutation(runtime, state_type):
    from backend.platform.state.state_service import set_user_state, get_user_state
    app,db,b,chat,user=runtime
    async with db.session_factory() as s:
        await set_user_state(s,user,user,state_type=state_type,state_data={'target_chat_id':chat,'field':'text'})
        await s.commit()
    b.role='member'
    await app.process_update(text_update(app,user,900,'10'))
    assert '已退出' in rendered(b)
    assert not app.user_data[user].get('quick_publish_draft')
    async with db.session_factory() as s:
        state=await get_user_state(s,chat_id=user,user_id=user)
        assert state is None or state.state_type=='selected_chat'
    assert not [1 for e,_ in b.calls if e in {'setChatPermissions','setChatMemberTag','restrictChatMember'}]


async def test_private_input_crash_rolls_back_partial_flush_and_keeps_retry_state(runtime):
    from types import SimpleNamespace
    from backend.platform.telegram.private_config_handler import PrivateConfigHandler
    from backend.platform.state.state_service import set_user_state, get_user_state
    app,db,b,chat,user=runtime
    async with db.session_factory() as s:
        await set_user_state(s,user,user,state_type='sign_feedback_input',state_data={'target_chat_id':chat,'key':'template'})
        await s.commit()
    async def fail_after_flush(update,context,session,**kwargs):
        row=await session.get(ChatSettings,chat)
        row.sign_points=999
        await session.flush()
        raise RuntimeError('injected after partial write')
    update=text_update(app,user,1000,'new setting')
    async with db.session_factory() as s:
        state=await get_user_state(s,chat_id=user,user_id=user)
        await PrivateConfigHandler()._execute_handler(fail_after_flush,update,SimpleNamespace(application=app),
            session=s,state=state,message_text='new setting',state_type=state.state_type)
        await s.commit()  # Same caller contract as MessageDispatcher.
    async with db.session_factory() as s:
        assert (await s.get(ChatSettings,chat)).sign_points==5
        assert (await get_user_state(s,chat_id=user,user_id=user)).state_type=='sign_feedback_input'
    assert '配置处理失败' in rendered(b)
    await app.process_update(text_update(app,user,1001,'重试 {balance}'))
    async with db.session_factory() as s:
        assert (await s.get(ChatSettings,chat)).module_config['sign_feedback']['template']=='重试 {balance}'


async def test_all_38_own_entries_reject_revoked_actor(runtime):
    from backend.features.admin.feature_registry import FEATURE_REGISTRATIONS
    app,db,b,chat,user=runtime
    b.role='member'
    for i,feature in enumerate(FEATURE_REGISTRATIONS,1100):
        await app.process_update(callback_update(app,user,i,f'adm:menu:{feature}:{chat}'))
        assert '需要管理员权限' in rendered(b),feature
    async with db.session_factory() as s:
        assert (await s.get(ChatSettings,chat)).module_config=={}


async def test_ads_input_database_failure_rolls_back_new_item_and_can_retry(runtime):
    from backend.features.automation.ads_router import AdsRouter
    from backend.features.automation.services.ad_rotation_service import get_or_create_rotation_rule
    from backend.platform.db.schema.models.automation import AdCampaign
    from backend.platform.state.state_service import set_user_state
    app,db,b,chat,user=runtime
    AdsRouter().register(app)
    async with db.session_factory() as s:
        await get_or_create_rotation_rule(s,chat)
        await set_user_state(s,user,user,state_type='ads_create_config',state_data={'target_chat_id':chat})
        await s.commit()
    trigger=f'audit_ads_{user}'
    async with db.engine.begin() as conn:
        await conn.execute(text(f"CREATE FUNCTION bot.{trigger}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'audit rule failure'; END $$"))
        await conn.execute(text(f"CREATE TRIGGER {trigger} BEFORE UPDATE ON bot.ad_rotation_rules FOR EACH ROW WHEN (NEW.chat_id = {chat}) EXECUTE FUNCTION bot.{trigger}()"))
    config='atomic title\n推送间隔: 3小时\n内容:\ngeneric content'
    try:
        await app.process_update(text_update(app,user,1200,config))
        assert '处理失败' in rendered(b)
        async with db.session_factory() as s:
            assert not (await s.scalars(select(AdCampaign).where(AdCampaign.chat_id==chat))).all()
    finally:
        async with db.engine.begin() as conn:
            await conn.execute(text(f'DROP TRIGGER {trigger} ON bot.ad_rotation_rules'))
            await conn.execute(text(f'DROP FUNCTION bot.{trigger}()'))
    await app.process_update(text_update(app,user,1201,config))
    async with db.session_factory() as s:
        ads=(await s.scalars(select(AdCampaign).where(AdCampaign.chat_id==chat))).all()
        assert len(ads)==1 and ads[0].title=='atomic title'


@pytest.mark.parametrize('command', ['team','team_mute'])
async def test_alliance_commands_share_current_management_policy_before_punishment(runtime, command):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from backend.features.group_ops.group_hooks.moderation import _process_alliance_reply_ban
    from backend.platform.db.schema.models.alliance import GroupAllianceBanPool
    app,db,b,chat,user=runtime
    b.role='administrator'
    message=SimpleNamespace(reply_to_message=SimpleNamespace(from_user=SimpleNamespace(id=user+1)),reply_text=AsyncMock())
    handled=await _process_alliance_reply_ban(SimpleNamespace(bot=app.bot,application=app),db,
        SimpleNamespace(id=chat),user=SimpleNamespace(id=user),message=message,message_text=command)
    assert handled and '无权' in message.reply_text.call_args.args[0]
    assert not [1 for e,_ in b.calls if e in {'banChatMember','restrictChatMember'}]
    async with db.session_factory() as s:
        assert not (await s.scalars(select(GroupAllianceBanPool).where(GroupAllianceBanPool.source_chat_id==chat))).all()
