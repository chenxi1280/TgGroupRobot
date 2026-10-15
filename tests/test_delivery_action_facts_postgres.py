"""One send remains successful when ancillary Telegram actions fail; facts survive reload."""
import datetime as dt
import json
from types import SimpleNamespace

import pytest
import pytest_asyncio
import test_competitor_admin_lists_postgres as list_tests
from sqlalchemy import select
from telegram.error import Forbidden
from telegram import Bot

from backend.features.automation.ad_delivery_executor import AdDeliveryPlan, TelegramAdDeliveryExecutor
from backend.features.automation.ad_delivery_repository import SqlAlchemyAdDeliveryStore
from backend.features.automation.scheduled_delivery_executor import ScheduledDeliveryPlan, TelegramScheduledDeliveryExecutor
from backend.features.automation.scheduled_occurrence_repository import SqlAlchemyScheduledOccurrenceStore
from backend.features.admin.delivery_summary import format_delivery_summary
from backend.platform.db.schema.models.automation import AdCampaign, AdRotationHistory, AdRotationRule
from backend.platform.db.schema.models.scheduled_message import ScheduledMessageLog, ScheduledMessageTask
from backend.platform.delivery import DeliveryStatus
from test_competitor_admin_lists_postgres import URL, create_items
from test_admin_routes_postgres import TelegramBoundary, callback_update

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not URL, reason="disposable Postgres URL required")]


@pytest_asyncio.fixture
async def runtime():
    async for state in list_tests.runtime.__wrapped__():
        yield state


class AncillaryFailureBot:
    def __init__(self):
        self.sends = 0

    async def send_message(self, **kwargs):
        self.sends += 1
        return SimpleNamespace(message_id=6789)

    async def pin_chat_message(self, **kwargs):
        raise Forbidden("pin denied")

    async def unpin_chat_message(self, **kwargs):
        raise Forbidden("unpin denied")

    async def delete_message(self, **kwargs):
        raise Forbidden("delete denied")


async def test_scheduled_send_and_failed_pin_are_independent_persisted_facts(runtime):
    _, db, _, _, chat, _ = runtime
    tasks, _ = await create_items(db, chat, count=1)
    snapshot = {"text": "generic notice", "parse_mode": "none", "delete_previous": True,
                "last_sent_message_id": 12, "pin_message": True}
    async with db.session_factory() as s:
        row = ScheduledMessageLog(task_id=tasks[0].task_id, chat_id=chat, run_key=f"{chat}:facts",
            scheduled_for=1, content_snapshot=snapshot, status="processing", attempt_count=1)
        s.add(row)
        await s.commit()
    plan = ScheduledDeliveryPlan(occurrence_id=row.id, task_id=str(tasks[0].task_id), chat_id=chat, snapshot=snapshot)
    bot = AncillaryFailureBot()
    outcome = await TelegramScheduledDeliveryExecutor(SimpleNamespace(bot=bot)).execute(plan)
    assert outcome.status is DeliveryStatus.succeeded and bot.sends == 1
    await SqlAlchemyScheduledOccurrenceStore(db).finalize(plan, outcome, now=dt.datetime.now(dt.UTC))
    async with db.session_factory() as s:
        row = await s.get(ScheduledMessageLog, row.id)
        task = await s.get(ScheduledMessageTask, tasks[0].task_id)
        assert row.status == "succeeded" and row.message_id == task.last_sent_message_id == 6789
        assert row.post_actions == {"delete_previous": "failed", "pin": "failed"}
        assert "附加操作失败：置顶、删除旧消息" in format_delivery_summary(row, row)
        assert row.next_retry_at is None


async def test_ad_pin_failure_keeps_old_pin_fact_without_repeating_send(runtime):
    _, db, _, _, chat, _ = runtime
    _, ads = await create_items(db, chat, count=1)
    content = {"content": "generic notice", "title": "notice"}
    rule_snapshot = {"mode": "send_pin", "delete_policy": "delete_prev", "unpin_previous": True,
                     "last_sent_message_id": 12, "last_pinned_message_id": 12, "next_cursor": 1}
    async with db.session_factory() as s:
        rule = AdRotationRule(chat_id=chat, last_pinned_message_id=12)
        row = AdRotationHistory(chat_id=chat, campaign_id=ads[0].id, dispatch_key=f"{chat}:facts",
            scheduled_for=dt.datetime.now(dt.UTC), content_snapshot=content, rule_snapshot=rule_snapshot,
            status="processing", attempt_count=1)
        s.add_all([rule, row])
        await s.commit()
    plan = AdDeliveryPlan(history_id=row.id, chat_id=chat, campaign_id=ads[0].id,
                          content_snapshot=content, rule_snapshot=rule_snapshot)
    bot = AncillaryFailureBot()
    outcome = await TelegramAdDeliveryExecutor(SimpleNamespace(bot=bot)).execute(plan)
    await SqlAlchemyAdDeliveryStore(db).finalize(plan, outcome, now=dt.datetime.now(dt.UTC))
    async with db.session_factory() as s:
        row = await s.get(AdRotationHistory, row.id)
        rule = await s.scalar(select(AdRotationRule).where(AdRotationRule.chat_id == chat))
        item = await s.get(AdCampaign, ads[0].id)
        assert row.status == "succeeded" and row.message_id == 6789 and bot.sends == 1
        assert row.post_actions == {"delete_previous": "failed", "pin": "failed", "unpin_previous": "failed"}
        assert row.pinned_message_id is None and rule.last_pinned_message_id == 12
        assert item.send_count == 1 and row.next_retry_at is None


class MissingUnpinBoundary(TelegramBoundary):
    async def do_request(self, url, method, request_data=None, **kwargs):
        if url.endswith('/unpinChatMessage'):
            self.calls.append(('unpinChatMessage', request_data.parameters))
            return 400, json.dumps({'ok': False, 'error_code': 400,
                                    'description': 'Bad Request: Message to unpin not found'}).encode()
        return await super().do_request(url, method, request_data=request_data, **kwargs)


async def test_registered_recovery_of_absent_unpin_updates_parent_without_resending(runtime):
    from backend.features.admin.effect_views import _result_text
    from backend.features.admin.services.effect_runtime import run_effect
    from backend.features.automation.delivery_action_journal import queue_action
    from backend.platform.db.schema.models.admin_effects import AdminEffect
    app, db, _, _, chat, user = runtime
    _, ads = await create_items(db, chat, count=1)
    now = dt.datetime.now(dt.UTC)
    async with db.session_factory() as s:
        parent = AdRotationHistory(chat_id=chat, campaign_id=ads[0].id, dispatch_key=f'{chat}:absent-unpin',
            scheduled_for=now, content_snapshot={'content': 'already sent'},
            rule_snapshot={'unpin_previous': True, 'last_pinned_message_id': 12},
            status='succeeded', attempt_count=1, message_id=88, sent_at=now,
            post_actions={'unpin_previous': 'failed', 'pin': 'succeeded'})
        s.add(parent)
        await s.flush()
        eid = await queue_action(s, source='ads', parent_id=parent.id, chat_id=chat,
                                 action='unpin_previous', message_id=12, due=now)
        row = await s.get(AdminEffect, eid)
        row.status, row.attempts, row.error = 'permanent_failed', 1, 'Message to unpin not found'
        await s.commit()
    await app.process_update(callback_update(app, user, 99001, f'eff:{chat}:delivery_action:retry:{eid}'))
    boundary = MissingUnpinBoundary()
    async with Bot('999000:TEST_TOKEN', request=boundary) as bot:
        worker = SimpleNamespace(bot=bot, bot_data={'db': db})
        now = dt.datetime.now(dt.UTC)
        assert await run_effect(worker, eid, chat_id=chat, now=now) == 'succeeded'
        assert await run_effect(worker, eid, chat_id=chat, now=now) == 'not_claimed'
    async with db.session_factory() as s:
        row = await s.get(AdminEffect, eid)
        parent = await s.get(AdRotationHistory, parent.id)
        item = await s.get(AdCampaign, ads[0].id)
        assert row.result == {'already_absent': True, 'message_id': 12} and row.attempts == 1
        assert _result_text(row.result) == '消息已不存在'
        assert parent.message_id == 88 and parent.attempt_count == 1 and item.send_count == 0
        assert parent.post_actions == {'unpin_previous': 'succeeded', 'pin': 'succeeded'}
    assert [name for name, _ in boundary.calls] == ['getMe', 'unpinChatMessage']
