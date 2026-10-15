"""Deleting a pinned message must not manufacture an unpin failure."""
from types import SimpleNamespace

import pytest
from telegram.error import BadRequest, Forbidden

from backend.features.automation.ad_delivery_executor import AdDeliveryPlan, TelegramAdDeliveryExecutor
from backend.features.automation.delivery_action_journal import execute_action
from backend.platform.delivery import DeliveryStatus


class StatefulBot:
    def __init__(self):
        self.live = {12}
        self.pinned = {12}
        self.calls = []

    async def unpin_chat_message(self, **kwargs):
        mid = kwargs['message_id']
        self.calls.append(('unpin', mid))
        if mid not in self.live:
            raise BadRequest('Message to unpin not found')
        self.pinned.discard(mid)
        return True

    async def delete_message(self, **kwargs):
        mid = kwargs['message_id']
        self.calls.append(('delete', mid))
        self.live.remove(mid)
        self.pinned.discard(mid)
        return True

    async def send_message(self, **kwargs):
        self.calls.append(('send', 88))
        self.live.add(88)
        return SimpleNamespace(message_id=88)

    async def pin_chat_message(self, **kwargs):
        mid = kwargs['message_id']
        self.calls.append(('pin', mid))
        self.pinned.add(mid)
        return True


@pytest.mark.asyncio
@pytest.mark.parametrize('policy', ['delete_prev', 'delete_prev_cycle'])
async def test_unpin_precedes_deletion_of_the_same_previous_message(policy):
    bot = StatefulBot()
    plan = AdDeliveryPlan(history_id=4, chat_id=-1001, campaign_id=9,
        content_snapshot={'content': 'notice', 'last_sent_message_id': 12},
        rule_snapshot={'mode': 'send_pin', 'delete_policy': policy, 'unpin_previous': True,
                       'last_sent_message_id': 12, 'last_pinned_message_id': 12})
    result = await TelegramAdDeliveryExecutor(SimpleNamespace(bot=bot)).execute(plan)
    assert result.status is DeliveryStatus.succeeded
    assert bot.calls == [('unpin', 12), ('delete', 12), ('send', 88), ('pin', 88)]
    assert bot.live == bot.pinned == {88}
    assert dict(result.metadata)['post_actions'] == dict.fromkeys(['delete_previous', 'unpin_previous', 'pin'], 'succeeded')


class AbsentBot:
    def __init__(self, error):
        self.error = error

    async def unpin_chat_message(self, **kwargs):
        raise self.error

    delete_message = unpin_chat_message
    pin_chat_message = unpin_chat_message


@pytest.mark.asyncio
@pytest.mark.parametrize(('action', 'error'), [
    ('unpin_previous', 'Message to unpin not found'),
    ('delete_previous', 'Message to delete not found'),
    ('delete_delay', 'Message to delete not found'),
])
async def test_exact_absence_is_idempotent(action, error):
    result = await execute_action(AbsentBot(BadRequest(error)), action=action, chat_id=-1001, message_id=12)
    assert result == {'already_absent': True, 'message_id': 12}


@pytest.mark.asyncio
@pytest.mark.parametrize(('action', 'error'), [
    ('pin', BadRequest('Message to unpin not found')),
    ('unpin_previous', BadRequest('Not enough rights')),
    ('unpin_previous', BadRequest('Message to delete not found')),
    ('unpin_previous', Forbidden('bot was kicked')),
])
async def test_other_errors_remain_failures(action, error):
    with pytest.raises(type(error)):
        await execute_action(AbsentBot(error), action=action, chat_id=-1001, message_id=12)
