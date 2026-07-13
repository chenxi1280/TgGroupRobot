from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest
from telegram.error import NetworkError, RetryAfter

from backend.features.automation.ad_delivery_executor import AdDeliveryPlan, TelegramAdDeliveryExecutor
from backend.features.automation.ad_delivery_admin_service import (
    replay_uncertain_delivery,
    retry_delivery,
    toggle_pool_membership,
)
from backend.features.automation.ad_delivery_repository import (
    AdPlanningResult,
    finalize_history,
    recover_expired_history,
)
from backend.features.automation.ad_delivery_worker import (
    AdDeliveryBatchError,
    AdDeliveryWorker,
    AdWorkerDependencies,
)
from backend.platform.delivery import DeliveryOutcome, DeliveryStatus, RetryPolicy

NOW = dt.datetime(2026, 7, 13, tzinfo=dt.UTC)


def _plan() -> AdDeliveryPlan:
    return AdDeliveryPlan(
        history_id=4,
        chat_id=-1001,
        campaign_id=9,
        content_snapshot={
            "title": "广告",
            "content": "正文",
            "image_file_id": None,
            "buttons": [],
            "last_sent_message_id": None,
            "sort_order": 1,
        },
        rule_snapshot={
            "mode": "send",
            "delete_policy": "none",
            "delete_delay_seconds": 60,
            "unpin_previous": False,
            "last_sent_message_id": None,
            "last_pinned_message_id": None,
            "next_cursor": 2,
        },
    )


class _Bot:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    async def send_message(self, **kwargs):
        if self.error:
            raise self.error
        return SimpleNamespace(message_id=88)


@pytest.mark.asyncio
async def test_ad_executor_classifies_retry_and_unknown() -> None:
    retry = await TelegramAdDeliveryExecutor(SimpleNamespace(bot=_Bot(RetryAfter(2)))).execute(_plan())
    unknown = await TelegramAdDeliveryExecutor(SimpleNamespace(bot=_Bot(NetworkError("lost")))).execute(_plan())

    assert retry.status is DeliveryStatus.retryable_failed
    assert unknown.status is DeliveryStatus.uncertain


class _Store:
    def __init__(self, planning: AdPlanningResult | None = None) -> None:
        self.planning = planning or AdPlanningResult(1, 0)
        self.started = []
        self.finalized = []

    async def create_due_dispatches(self, now):
        return self.planning

    async def recover_expired_leases(self, now):
        return 0

    async def claim_due(self, now, lease_until, *, limit):
        return (_plan(),)

    async def mark_send_started(self, plan, now):
        self.started.append(plan.history_id)

    async def finalize(self, plan, outcome, *, now):
        self.finalized.append(outcome)

    async def mark_finalize_uncertain(self, plan, error, *, now):
        return None


class _Executor:
    def __init__(self, outcome: DeliveryOutcome) -> None:
        self.outcome = outcome

    async def execute(self, plan):
        return self.outcome


@pytest.mark.asyncio
async def test_ad_worker_surfaces_delivery_failure_to_scheduler() -> None:
    worker = AdDeliveryWorker(AdWorkerDependencies(
        store=_Store(),
        executor=_Executor(DeliveryOutcome.permanent_failure("forbidden", "denied")),
        clock=lambda: NOW,
    ))

    with pytest.raises(AdDeliveryBatchError) as error:
        await worker.run()

    assert error.value.summary.failed == 1


@pytest.mark.asyncio
async def test_ad_worker_surfaces_invalid_pool_after_processing_valid_work() -> None:
    store = _Store(AdPlanningResult(1, 1))
    worker = AdDeliveryWorker(AdWorkerDependencies(
        store=store,
        executor=_Executor(DeliveryOutcome.success(message_id=88)),
        clock=lambda: NOW,
    ))

    with pytest.raises(AdDeliveryBatchError) as error:
        await worker.run()

    assert error.value.summary.succeeded == 1
    assert store.started == [4]


def test_ad_success_alone_advances_cursor_and_counters() -> None:
    history = _history()
    rule = _rule()
    item = _item()
    policy = RetryPolicy(max_attempts=3)

    finalize_history(
        history,
        rule,
        item,
        outcome=DeliveryOutcome.retryable_failure("rate", "later"),
        now=NOW,
        retry_policy=policy,
    )
    assert rule.current_order_cursor == 1
    assert item.send_count == 0

    finalize_history(
        history,
        rule,
        item,
        outcome=DeliveryOutcome.success(message_id=88, metadata={"pinned_message_id": 88}),
        now=NOW,
        retry_policy=policy,
    )
    assert rule.current_order_cursor == 2
    assert item.send_count == 1
    assert history.message_id == 88


def test_ad_expired_lease_after_send_is_uncertain() -> None:
    history = _history()
    history.send_started_at = NOW

    recover_expired_history(history, NOW)

    assert history.status == DeliveryStatus.uncertain.value
    assert history.error_code == "lease_expired_after_send"


def _history():
    return SimpleNamespace(
        id=4,
        campaign_id=9,
        attempt_count=1,
        rule_snapshot={"next_cursor": 2},
        send_started_at=None,
        status="processing",
        next_retry_at=None,
        lease_until=NOW,
        error_code=None,
        error_message=None,
        completed_at=None,
        message_id=None,
        pinned_message_id=None,
        sent_at=None,
        cycle_no=0,
    )


def _rule():
    return SimpleNamespace(
        current_order_cursor=1,
        last_sent_at=None,
        last_sent_item_id=None,
        last_sent_message_id=None,
        last_pinned_message_id=None,
    )


def _item():
    return SimpleNamespace(
        last_sent_at=None,
        last_sent_message_id=None,
        last_sent_cycle_no=0,
        send_count=0,
    )


class _ScalarResult:
    def __init__(self, value) -> None:
        self.value = value

    def scalar_one_or_none(self):
        return self.value


@pytest.mark.asyncio
async def test_admin_retry_resets_only_explicit_failure() -> None:
    history = _history()
    history.status = DeliveryStatus.permanent_failed.value

    class _Session:
        async def execute(self, statement):
            return _ScalarResult(history)

    await retry_delivery(_Session(), 4, -1001)

    assert history.status == DeliveryStatus.pending.value
    assert history.attempt_count == 0


@pytest.mark.asyncio
async def test_uncertain_replay_records_admin_reason_and_lineage() -> None:
    history = _history()
    history.chat_id = -1001
    history.status = DeliveryStatus.uncertain.value
    history.content_snapshot = _plan().content_snapshot
    history.rule_snapshot = _plan().rule_snapshot
    history.sort_order_snapshot = 1
    history.title_snapshot = "广告"
    added = []

    class _Session:
        async def execute(self, statement):
            return _ScalarResult(history)

        def add(self, value):
            value.id = 5
            added.append(value)

        async def flush(self):
            return None

    replay_id = await replay_uncertain_delivery(
        _Session(),
        4,
        -1001,
        admin_id=7,
        reason="confirmed duplicate risk",
    )

    assert replay_id == 5
    assert added[0].replay_of_history_id == 4
    assert added[0].replay_admin_id == 7
    assert added[0].replay_reason == "confirmed duplicate risk"


@pytest.mark.asyncio
async def test_pool_toggle_rejects_cross_chat_campaign() -> None:
    rule = SimpleNamespace(top_campaign_ids=[], exclude_campaign_ids=[])
    campaign = SimpleNamespace(id=9, chat_id=-2002)

    class _Session:
        async def execute(self, statement):
            return _ScalarResult(rule)

        async def get(self, model, pk):
            return campaign

    with pytest.raises(Exception, match="不属于当前群"):
        await toggle_pool_membership(_Session(), -1001, 9, pool="top")
