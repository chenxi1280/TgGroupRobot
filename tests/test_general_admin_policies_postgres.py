"""Owned-feature regressions with real services/transactions and fake Telegram transport."""
import asyncio
import datetime as dt
from types import SimpleNamespace

import pytest
import pytest_asyncio
import test_competitor_admin_lists_postgres as list_tests
from sqlalchemy import func, select

from backend.features.activity.auction_permissions import can_create_auction, creation_policy
from backend.features.activity.services.auction_settings import get_or_create_setting, update_setting
from backend.features.activity.services.engagement_chat import try_claim_chat_reward, update_chat_reward
from backend.features.activity.services.engagement_core import get_or_create_chat_stat
from backend.features.garage.services.alliance_service import AllianceService
from backend.features.points.services.points_extended_levels import PointsExtendedLevelsMixin as Levels
from backend.platform.db.schema.models.core import ChatSettings, PointsAccount, PointsTransaction, TgUser
from backend.platform.db.schema.models.expansion_games import LotterySetting
from backend.platform.db.schema.models.activity import Lottery, LotteryParticipant
from backend.platform.db.schema.models.scheduled_message import ScheduledMessageTask
from backend.platform.db.schema.models.automation import AdCampaign
from backend.shared.services.base import ValidationError
from backend.shared.services.chat_service import get_chat_settings
from test_competitor_admin_lists_postgres import display, data_buttons, URL
from test_admin_routes_postgres import callback_update, command_update
from test_mall_intent_postgres import seed

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not URL, reason="disposable Postgres URL required")]


@pytest_asyncio.fixture
async def runtime():
    async for state in list_tests.runtime.__wrapped__():
        yield state


async def test_create_and_edit_paths_return_actual_details(runtime):
    app, db, transport, _, chat, user = runtime
    await app.process_update(callback_update(app, user, 400, f'sm:add:{chat}'))
    assert '定时消息' in display(transport)['text']
    async with db.session_factory() as s:
        task = await s.scalar(select(ScheduledMessageTask).where(ScheduledMessageTask.chat_id == chat))
        assert task is not None
        key = task.short_id
    await app.process_update(callback_update(app, user, 401, f'sm:edit:{chat}:{key}:title'))
    await app.process_update(command_update(app, user, user, 402, 'owned title'))
    assert 'owned title' in display(transport)['text']
    await app.process_update(callback_update(app, user, 403, f'sm:set:{chat}:{key}:enabled:1'))
    assert '启用失败' in display(transport)['text']
    await app.process_update(callback_update(app, user, 404, f'ads:create:{chat}'))
    assert '轮播消息' in display(transport)['text']
    async with db.session_factory() as s:
        ad = await s.scalar(select(AdCampaign).where(AdCampaign.chat_id==chat))
    await app.process_update(callback_update(app, user, 405, f'ads:item:input:{chat}:{ad.id}:title'))
    await app.process_update(command_update(app, user, user, 406, 'owned advertisement'))
    assert 'owned advertisement' in display(transport)['text']


async def test_explicit_auction_policy_preserves_legacy_and_denies_after_opt_in(runtime):
    app, db, _, _, chat, user = runtime
    async with db.session_factory() as s:
        setting = await get_or_create_setting(s, chat)
        setting.enabled, setting.create_permission = True, 'admin'
        await s.commit()
        assert creation_policy(setting) == 'all'
        assert await can_create_auction(SimpleNamespace(), setting, chat_id=chat, user_id=user)
        await update_setting(s, chat, create_permission='admin')
        await s.commit()
    class NonAdmin:
        async def get_chat_member(self, **kwargs):
            return SimpleNamespace(status='member')
    assert not await can_create_auction(SimpleNamespace(bot=NonAdmin()), setting, chat_id=chat, user_id=user)
    assert await can_create_auction(SimpleNamespace(bot=app.bot), setting, chat_id=chat, user_id=user)
    async with db.session_factory() as s:
        with pytest.raises(ValueError):
            await update_setting(s, chat, create_permission='unexpected')


async def test_level_zero_and_permission_field_allowlist(runtime):
    _, db, _, _, chat, user = runtime
    async with db.session_factory() as s:
        level = await Levels.create_level(s, chat)
        await Levels.update_level(s, level, point_threshold=0, perm_name='allow_photo', perm_value=False)
        setting = await Levels.get_or_create_level_setting(s, chat)
        await Levels.update_level_setting(s, setting, enabled=True)
        await s.commit()
        assert (await Levels.resolve_user_level(s, chat, user)).id == level.id
        with pytest.raises(ValidationError):
            await Levels.update_level(s, level, point_threshold=-1)
        with pytest.raises(ValidationError):
            await Levels.update_level(s, level, perm_name='chat_id', perm_value=True)
        assert level.chat_id == chat


async def test_daily_reward_concurrent_claim_is_once_and_mode_change_keeps_receipt(runtime):
    _, db, _, _, chat, user = runtime
    from backend.features.activity.services.engagement_chat import business_date
    async with db.session_factory() as s:
        await update_chat_reward(s, chat, enabled=True, daily_message_target=1,
            reward_type='daily', reward_points_plan=[10,20,30,40,50,60,70])
        stat = await get_or_create_chat_stat(s, chat, user, biz_date=business_date())
        stat.message_count = 5
        await s.commit()
    async def claim():
        async with db.session_factory() as s:
            try:
                result = await try_claim_chat_reward(s, chat, user)
                await s.commit()
                return result
            except ValidationError:
                return None
    outcomes = await asyncio.gather(claim(),claim(),claim())
    assert sum(x is not None for x in outcomes) == 1
    assert next(x for x in outcomes if x is not None)[0] == 10
    async with db.session_factory() as s:
        await update_chat_reward(s, chat, reward_type='weekly_cycle')
        with pytest.raises(ValidationError, match='已经领取'):
            await try_claim_chat_reward(s, chat, user)
        assert await s.scalar(select(func.count()).select_from(PointsTransaction).where(
            PointsTransaction.chat_id==chat, PointsTransaction.reason=='水群激励奖励')) == 1


async def test_alliance_types_upgrade_without_downgrade_or_duplicate(runtime):
    _, db, _, _, chat, user = runtime
    async with db.session_factory() as s:
        alliance, _ = await AllianceService.create_alliance(s, chat_id=chat, operator_user_id=user, name=f'owned {user}')
        await s.commit()
    async def add(kind):
        async with db.session_factory() as s:
            row = await AllianceService.add_joint_ban_entry(s, chat_id=chat, operator_user_id=user,
                target_user_id=user, punishment_type=kind)
            await s.commit()
            return row.id, row.punishment_type
    first = await add('mute')
    results = await asyncio.gather(add('ban'), add('mute'), add('ban'))
    assert all(x[0] == first[0] for x in results)
    assert (await add('mute'))[1] == 'ban'
    async with db.session_factory() as s:
        await AllianceService.set_joint_ban_enabled(s, chat_id=chat, operator_user_id=user, enabled=True)
        await s.commit()
        assert (await AllianceService.get_joint_ban_hit(s, chat_id=chat, target_user_id=user))[1].punishment_type == 'ban'


async def test_permission_profiles_save_without_applying_and_are_independent(runtime):
    app, db, transport, _, chat, user = runtime
    await app.process_update(callback_update(app, user, 500, f'gperm:{chat}:open:set:photo:1'))
    await app.process_update(callback_update(app, user, 501, f'gperm:{chat}:closed:set:text:0'))
    assert not any(e == 'setChatPermissions' for e,_ in transport.calls)
    from backend.features.group_ops.services.group_permission_profiles import profile_permissions
    async with db.session_factory() as s:
        settings = await s.scalar(select(ChatSettings).where(ChatSettings.chat_id==chat))
    assert profile_permissions(settings, closed=False).can_send_photos is True
    assert profile_permissions(settings, closed=True).can_send_photos is False
    from backend.features.group_ops.group_hooks.control_lock import _apply_group_lock_permissions
    await _apply_group_lock_permissions(SimpleNamespace(application=app, bot=app.bot), chat, False)
    calls = [p for e,p in transport.calls if e=='setChatPermissions']
    assert calls and calls[-1]['use_independent_chat_permissions'] is True


async def test_lottery_no_username_rejected_before_charge(runtime):
    app, db, transport, _, chat, user = runtime
    from telegram import Update
    from backend.features.activity.lottery_router import LotteryRouter
    LotteryRouter().register(app)
    async with db.session_factory() as s:
        lottery = Lottery(chat_id=chat, title='generic lottery', lottery_type='points',
            draw_time=dt.datetime.now(dt.UTC)+dt.timedelta(days=1), participation_cost=10)
        s.add_all([LotterySetting(chat_id=chat, require_username=True), lottery])
        await s.commit()
    update = Update.de_json({'update_id':600,'callback_query':{'id':'600','chat_instance':'test',
        'data':f'join_lottery_{lottery.id}', 'from':{'id':user,'is_bot':False,'first_name':'test'},
        'message':{'message_id':600,'date':1780000000,'chat':{'id':chat,'type':'supergroup','title':'test'}}}}, app.bot)
    await app.process_update(update)
    assert any('用户名' in str(p) for e,p in transport.calls if e=='answerCallbackQuery')
    async with db.session_factory() as s:
        assert await s.scalar(select(func.count()).select_from(LotteryParticipant).where(LotteryParticipant.lottery_id==lottery.id)) == 0
        assert await s.scalar(select(PointsAccount.balance).where(PointsAccount.chat_id==chat, PointsAccount.user_id==user)) == 100


async def test_signin_calendar_streak_and_feedback_are_business_day_scoped(runtime, monkeypatch):
    from backend.features.points.services import points_service_activity as activity
    from backend.features.points.sign_feedback import validate_template
    _, db, _, _, chat, user = runtime
    clock = [dt.datetime(2026,10,20,15,59,tzinfo=dt.UTC)]
    class Clock(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0].astimezone(tz) if tz else clock[0].replace(tzinfo=None)
    monkeypatch.setattr(activity, 'dt', SimpleNamespace(datetime=Clock, timedelta=dt.timedelta, time=dt.time, UTC=dt.UTC, date=dt.date))
    async def sign():
        async with db.session_factory() as s:
            result = await activity.sign_in(s, chat_id=chat, user_id=user, points=5, consecutive_days=2, consecutive_bonus=10)
            await s.commit()
            return result
    one = await sign()
    assert one.success and one.consecutive_days == 1
    assert not (await sign()).success
    clock[0] = dt.datetime(2026,10,20,16,1,tzinfo=dt.UTC)
    two = await sign()
    assert two.success and two.consecutive_days == 2 and two.bonus_points == 10
    assert two.balance == 120
    with pytest.raises(ValueError):
        validate_template('{balance.__class__}')
    with pytest.raises(ValueError):
        validate_template('{unknown}')


async def test_sign_feedback_editor_returns_and_clears_input_without_awarding(runtime):
    app, db, transport, _, chat, user = runtime
    await app.process_update(callback_update(app,user,800,f'signcfg:{chat}:input:template'))
    await app.process_update(command_update(app,user,user,801,'今日获得 {points} 分，余额 {balance}'))
    assert '今日获得' in display(transport)['text']
    await app.process_update(callback_update(app,user,802,f'signcfg:{chat}:input:delete_seconds'))
    await app.process_update(callback_update(app,user,803,f'signcfg:{chat}:view'))
    from backend.platform.db.schema.models.chat import ConversationState
    async with db.session_factory() as s:
        state = await s.scalar(select(ConversationState).where(ConversationState.chat_id==user, ConversationState.user_id==user))
        assert state.state_type == 'selected_chat'
        assert await s.scalar(select(PointsAccount.balance).where(PointsAccount.chat_id==chat,PointsAccount.user_id==user)) == 100


async def test_feedback_counts_users_once_and_has_independent_sign_position(runtime):
    from backend.features.points.sign_feedback import feedback_text
    from backend.platform.db.schema.models.points import SignInLog
    from backend.shared.time_helper import LOCAL_TIMEZONE
    _, db, _, _, chat, user = runtime
    _, other, _ = await seed(db)
    now = dt.datetime.now(dt.UTC)
    today = now.astimezone(LOCAL_TIMEZONE).date()
    start = dt.datetime.combine(today, dt.time.min, tzinfo=LOCAL_TIMEZONE).astimezone(dt.UTC)
    async with db.session_factory() as s:
        settings = await get_chat_settings(s, chat)
        settings.module_config = {"sign_feedback": {"show_count": True, "show_rank": True,
                                                    "template": "总数 {total} 名次 {position}"}}
        s.add_all([SignInLog(chat_id=chat, user_id=user, sign_date=today-dt.timedelta(days=1),
                            created_at=start+dt.timedelta(seconds=1), points_awarded=1),
                   SignInLog(chat_id=chat, user_id=user, sign_date=today,
                            created_at=start+dt.timedelta(seconds=2), points_awarded=1),
                   SignInLog(chat_id=chat, user_id=other, sign_date=today,
                            created_at=start+dt.timedelta(seconds=3), points_awarded=1)])
        await s.flush()
        result = SimpleNamespace(success=True, balance=100, consecutive_days=1, bonus_points=0)
        text = await feedback_text(s, settings, user_id=other, result=result, original="default")
        assert text == "总数 2 名次 2\n今日有效签到人数：2\n今日签到名次：2"


async def test_invalid_permission_callback_does_not_change_configuration(runtime):
    app, db, transport, _, chat, user = runtime
    async with db.session_factory() as s:
        before = (await get_chat_settings(s, chat)).module_config
        await s.commit()
    await app.process_update(callback_update(app,user,900,f'gperm:{chat}:open:set:unknown:1'))
    assert any("无效成员权限" in str(p) for e,p in transport.calls if e=="answerCallbackQuery")
    async with db.session_factory() as s:
        assert (await s.get(ChatSettings, chat)).module_config == before


@pytest.mark.parametrize(("opening","closing","expected"), [
    ("08:00","22:00",True), ("22:00","08:00",False), ("08:00","08:00",None),
    ("24:00","08:00",None), ("08:60","08:00",None), (None,None,None),
])
async def test_group_lock_calendar_handles_cross_midnight_and_invalid_times(monkeypatch, opening, closing, expected):
    from backend.features.group_ops.group_hooks import control_lock
    from backend.platform.scheduler.tasks.group_lock_task import _is_closed_now
    class Clock(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return dt.datetime(2026,10,15,15,0,tzinfo=dt.UTC)
    monkeypatch.setattr(control_lock, "dt", SimpleNamespace(datetime=Clock, UTC=dt.UTC, time=dt.time))
    settings = SimpleNamespace(group_lock_schedule_enabled=True, group_lock_open_time=opening, group_lock_close_time=closing)
    assert control_lock._is_closed_by_schedule(settings) is expected
    assert _is_closed_now(settings) is expected
