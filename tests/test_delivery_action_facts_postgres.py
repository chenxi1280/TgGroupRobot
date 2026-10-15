"""One send remains successful when ancillary Telegram actions fail; facts survive reload."""
import datetime as dt
from types import SimpleNamespace

import pytest
import pytest_asyncio
import test_competitor_admin_lists_postgres as list_tests
from sqlalchemy import select
from telegram.error import Forbidden

from backend.features.automation.ad_delivery_executor import AdDeliveryPlan, TelegramAdDeliveryExecutor
from backend.features.automation.ad_delivery_repository import SqlAlchemyAdDeliveryStore
from backend.features.automation.scheduled_delivery_executor import ScheduledDeliveryPlan, TelegramScheduledDeliveryExecutor
from backend.features.automation.scheduled_occurrence_repository import SqlAlchemyScheduledOccurrenceStore
from backend.features.admin.delivery_summary import format_delivery_summary
from backend.platform.db.schema.models.automation import AdCampaign, AdRotationHistory, AdRotationRule
from backend.platform.db.schema.models.scheduled_message import ScheduledMessageLog, ScheduledMessageTask
from backend.platform.delivery import DeliveryStatus
from test_competitor_admin_lists_postgres import URL, create_items

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
