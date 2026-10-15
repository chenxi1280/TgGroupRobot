"""Close specific local acceptance gaps; never infer real-client delivery."""
import asyncio
import datetime as dt
import secrets
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from backend.features.admin.list_queries import SPECS, normalize_query, search_page
from backend.platform.db.schema.models.chat import ChatSettings
from backend.platform.db.schema.models.points import PointsAccount, PointsTransaction, SignInLog, UserDailyStats
import test_remaining_generic_postgres as remaining
from test_remaining_generic_postgres import ad_plan, URL
from test_competitor_admin_lists_postgres import create_items
from test_admin_routes_postgres import callback_update

pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(not URL,reason='disposable Postgres required')]


@pytest_asyncio.fixture
async def runtime():
    async for value in remaining.runtime.__wrapped__():
        yield value


def display(b):
    return [p for e,p in b.calls if e in {'sendMessage','editMessageText'}][-1]


@pytest.mark.parametrize('feature',['autoreply','scheduled','ads'])
async def test_chinese_literal_id_length_and_deleted_last_page_keep_scope(runtime,feature):
    app,db,b,chat,user=runtime
    await create_items(db,chat,count=17)
    spec=SPECS[feature]
    async with db.session_factory() as s:
        items,_,_=await search_page(s,feature,chat_id=chat,query='',status='all',page=0)
        item=items[0]
        key=getattr(item,spec.key.key)
        if feature=='autoreply':
            item.keywords=['中文_%','x'*100]
        else:
            item.title='中文_%'
        await s.commit()
        assert (await search_page(s,feature,chat_id=chat,query='中文_%',status='all',page=0))[1]==1
        assert (await search_page(s,feature,chat_id=chat,query=f'#{key}',status='all',page=0))[1]==1
        assert normalize_query('中'*100)=='中'*100
        with pytest.raises(ValueError):
            normalize_query('中'*101)
        last=(await search_page(s,feature,chat_id=chat,query='',status='all',page=2))[0][0]
        last_key=getattr(last,spec.key.key)
    await app.process_update(callback_update(app,user,100,f'mlist:{feature}:{chat}:list:2'))
    assert '第 3 页' in display(b)['text']
    async with db.session_factory() as s:
        await s.execute(delete(spec.model).where(spec.model.chat_id==chat,spec.key==last_key))
        await s.commit()
    await app.process_update(callback_update(app,user,101,f'mlist:{feature}:{chat}:list:2'))
    assert '16 条数据，第 2 页/共 2 页' in display(b)['text']
    options=app.user_data[user]['admin_list_queries'][f'{chat}:{feature}']
    assert options=={'query':'','status':'all','page':1}


async def test_full_render_performance_all_1000_items_are_reachable_in_each_list(runtime):
    app,db,b,chat,user=runtime
    await create_items(db,chat,count=1000)
    timings={}
    for feature in ('autoreply','scheduled','ads'):
        seen=set()
        durations=[]
        for page in range(125):
            started=time.monotonic()
            await app.process_update(callback_update(app,user,1000+page,f'mlist:{feature}:{chat}:list:{page}'))
            durations.append(time.monotonic()-started)
            rendered=display(b)
            assert f'第 {page+1} 页/共 125 页' in rendered['text']
            assert len(rendered['text'].encode('utf-16-le'))//2<=4096
            prefixes={'autoreply':'auto_reply:detail:','scheduled':'sm:open:','ads':'ads:detail:'}
            keys=[button['callback_data'] for row in rendered['reply_markup']['inline_keyboard'] for button in row
                if button.get('callback_data','').startswith(prefixes[feature])]
            assert len(keys)==8 and not seen.intersection(keys)
            seen.update(keys)
        assert len(seen)==1000
        timings[feature]=sorted(durations)[118]
    assert all(duration<2 for duration in timings.values()),timings
    print('Full Application/DB/fake-HTTP render P95 seconds:',timings)


@pytest.mark.parametrize('status',['pending','processing','retryable_failed','succeeded','permanent_failed','uncertain','cancelled'])
async def test_all_delivery_summary_states_have_confirmed_link_only_for_supported_chat(status):
    from backend.features.admin.delivery_summary import format_delivery_summary, message_link, STATUS_LABELS
    now=dt.datetime.now(dt.UTC)
    success=SimpleNamespace(chat_id=-1001234567890,message_id=88,sent_at=now,status='succeeded',post_actions={})
    latest=SimpleNamespace(status=status,completed_at=now,send_started_at=now,created_at=now,scheduled_for=1,
        next_retry_at=now,error_code='telegram_network_unknown',post_actions={})
    text=format_delivery_summary(latest,success,chat_type='supergroup')
    assert STATUS_LABELS[status] in text and 'https://t.me/c/1234567890/88' in text
    assert message_link(-1001234567890,88,chat_type='group') is None
    assert message_link(-1001234567890,None,chat_type='supergroup') is None
    assert message_link(-1001234567890,88,chat_type='channel',username='public_channel')=='https://t.me/public_channel/88'


async def test_legacy_utc_sign_record_keeps_streak_and_does_not_award_same_business_day(runtime,monkeypatch):
    from backend.features.points.services import points_service_activity as activity
    _,db,_,chat,user=runtime
    legacy=dt.datetime(2026,10,14,16,1,tzinfo=dt.UTC)  # Shanghai15th, old UTC sign_date14th.
    async with db.session_factory() as s:
        s.add_all([SignInLog(chat_id=chat,user_id=user,sign_date=legacy.date(),created_at=legacy,points_awarded=5),
            UserDailyStats(chat_id=chat,user_id=user,stat_date=legacy.date(),consecutive_sign_days=3)])
        await s.commit()
    clock=[legacy+dt.timedelta(minutes=1)]
    class Clock(dt.datetime):
        @classmethod
        def now(cls,tz=None):
            return clock[0].astimezone(tz) if tz else clock[0].replace(tzinfo=None)
    monkeypatch.setattr(activity,'dt',SimpleNamespace(datetime=Clock,time=dt.time,timedelta=dt.timedelta,UTC=dt.UTC))
    async def sign():
        async with db.session_factory() as s:
            result=await activity.sign_in(s,chat,user,points=5,consecutive_days=4,consecutive_bonus=10)
            await s.commit()
            return result
    old=await sign()
    assert not old.success and old.consecutive_days==3 and old.balance==100
    clock[0]=dt.datetime(2026,10,15,16,1,tzinfo=dt.UTC)
    results=await asyncio.gather(sign(),sign(),sign())
    paid=[row for row in results if row.success]
    assert len(paid)==1 and paid[0].consecutive_days==4 and paid[0].bonus_points==10 and paid[0].balance==115
    async with db.session_factory() as s:
        logs=(await s.scalars(select(SignInLog).where(SignInLog.chat_id==chat).order_by(SignInLog.created_at))).all()
        assert len(logs)==2 and logs[0].sign_date==legacy.date() and logs[0].created_at==legacy
        assert await s.scalar(select(func.sum(PointsTransaction.amount)).where(PointsTransaction.chat_id==chat))==15


async def test_legacy_chat_reward_immutable_receipt_prevents_cutover_double_payment(runtime,monkeypatch):
    from backend.features.activity.services import engagement_chat as reward
    from backend.features.activity.services.engagement_core import get_or_create_chat_stat
    from backend.platform.db.schema.models.expansion_engagement import EngagementChatStat
    from backend.shared.services.base import ValidationError
    _,db,_,chat,user=runtime
    legacy=dt.datetime(2026,10,14,16,1,tzinfo=dt.UTC)
    async with db.session_factory() as s:
        await reward.update_chat_reward(s,chat,enabled=True,daily_message_target=1,reward_type='daily',reward_points_plan=[10]*7)
        s.add_all([PointsTransaction(chat_id=chat,user_id=user,amount=10,txn_type='reward',reason='水群激励奖励',created_at=legacy),
            EngagementChatStat(chat_id=chat,user_id=user,biz_date=legacy.date(),message_count=10,
                reward_claimed=True,rewarded_points=10,streak_days=3)])
        today=legacy.astimezone(dt.timezone(dt.timedelta(hours=8))).date()
        (await get_or_create_chat_stat(s,chat,user,biz_date=today)).message_count=10
        await s.commit()
    clock=[legacy+dt.timedelta(minutes=1)]
    monkeypatch.setattr(reward,'now_utc',lambda:clock[0])
    async with db.session_factory() as s:
        with pytest.raises(ValidationError,match='已经领取'):
            await reward.try_claim_chat_reward(s,chat,user)
    clock[0]=legacy+dt.timedelta(days=1)
    async with db.session_factory() as s:
        today=clock[0].astimezone(dt.timezone(dt.timedelta(hours=8))).date()
        (await get_or_create_chat_stat(s,chat,user,biz_date=today)).message_count=10
        await s.commit()
        result=await reward.try_claim_chat_reward(s,chat,user)
        await s.commit()
        assert result==(10,4)
        assert await s.scalar(select(func.count()).select_from(PointsTransaction).where(PointsTransaction.chat_id==chat))==2


async def test_old_ad_claim_cannot_start_or_finalize_new_attempt(runtime):
    from backend.features.automation.ad_delivery_repository import SqlAlchemyAdDeliveryStore, recover_expired_history
    from backend.platform.db.schema.models.automation import AdRotationHistory
    from backend.platform.delivery import DeliveryOutcome
    _,db,_,_,_=runtime
    plan=await ad_plan(runtime,policy='none')
    now=dt.datetime.now(dt.UTC)
    async with db.session_factory() as s:
        row=await s.get(AdRotationHistory,plan.history_id)
        row.attempt_count=1
        row.lease_until=now-dt.timedelta(seconds=1)
        recover_expired_history(row,now)
        await s.commit()
    store=SqlAlchemyAdDeliveryStore(db)
    claimed=await store.claim_due(now,now+dt.timedelta(minutes=2),limit=100)
    live=next(item for item in claimed if item.history_id==plan.history_id)
    assert live.attempt_count==2
    old=replace(plan,attempt_count=1)
    with pytest.raises(RuntimeError):
        await store.mark_send_started(old,now)
    with pytest.raises(RuntimeError):
        await store.finalize(old,DeliveryOutcome.success(message_id=999),now=now)
    async with db.session_factory() as s:
        row=await s.get(AdRotationHistory,plan.history_id)
        assert row.status=='processing' and row.attempt_count==2 and row.message_id is None


async def test_old_scheduled_claim_cannot_start_or_finalize_new_attempt(runtime):
    import uuid
    from backend.features.automation.scheduled_delivery_executor import ScheduledDeliveryPlan
    from backend.features.automation.scheduled_occurrence_repository import SqlAlchemyScheduledOccurrenceStore,recover_expired_occurrence
    from backend.platform.db.schema.models.scheduled_message import ScheduledMessageTask,ScheduledMessageLog
    from backend.platform.delivery import DeliveryOutcome
    _,db,_,chat,_=runtime
    now=dt.datetime.now(dt.UTC)
    snapshot={'text':'generic'}
    async with db.session_factory() as s:
        task=ScheduledMessageTask(task_id=uuid.uuid4(),short_id=uuid.uuid4().hex[:8],chat_id=chat,title='generic')
        s.add(task)
        await s.flush()
        row=ScheduledMessageLog(task_id=task.task_id,chat_id=chat,run_key=f'{chat}:stale',scheduled_for=1,
            content_snapshot=snapshot,status='processing',attempt_count=1,lease_until=now-dt.timedelta(seconds=1))
        s.add(row)
        await s.flush()
        recover_expired_occurrence(row,now)
        await s.commit()
    old=ScheduledDeliveryPlan(occurrence_id=row.id,task_id=str(task.task_id),chat_id=chat,snapshot=snapshot,attempt_count=1)
    store=SqlAlchemyScheduledOccurrenceStore(db)
    plans=await store.claim_due(now,now+dt.timedelta(minutes=2),limit=100)
    assert next(p for p in plans if p.occurrence_id==row.id).attempt_count==2
    with pytest.raises(RuntimeError):
        await store.mark_send_started(old,now)
    with pytest.raises(RuntimeError):
        await store.finalize(old,DeliveryOutcome.success(message_id=999),now=now)
    async with db.session_factory() as s:
        current=await s.get(ScheduledMessageLog,row.id)
        assert current.status=='processing' and current.attempt_count==2 and current.message_id is None


async def test_long_unicode_summary_preserves_whole_link_within_message_limit():
    from backend.features.admin.list_browser import _item_lines
    items=[SimpleNamespace(id=i,title='😀中文'*1000,enabled=True) for i in range(8)]
    link='最近成功消息：https://t.me/c/1234567890123/2147483647'
    summary='\n'.join(['😀中文'*200]*10+[link])
    rendered=_item_lines(items,'ads',summaries={i:summary for i in range(8)})
    assert rendered.count(link)==8 and len(rendered.encode('utf-16-le'))//2<4096
