"""Durable ancillary actions, independent of the primary message outcome."""
import datetime as dt
from sqlalchemy import select
from telegram.error import BadRequest
from backend.features.admin.services.effect_store import enqueue, identity
from backend.platform.db.schema.models.admin_effects import AdminEffect
from backend.platform.db.schema.models.automation import AdRotationHistory, AdRotationRule
from backend.platform.db.schema.models.scheduled_message import ScheduledMessageLog

MODELS = {'ads':AdRotationHistory, 'scheduled':ScheduledMessageLog}
METHODS = {'delete_previous':'delete_message','delete_delay':'delete_message',
           'unpin_previous':'unpin_chat_message','pin':'pin_chat_message'}
FACTS = {'succeeded':'succeeded','permanent_failed':'failed','retryable_failed':'waiting',
         'uncertain':'uncertain','processing':'processing','pending':'pending','cancelled':'cancelled'}


def source_identity(plan):
    if hasattr(plan,'history_id'):
        return 'ads',plan.history_id
    return 'scheduled',plan.occurrence_id


def merge_facts(existing, metadata):
    facts=metadata.get('post_actions',{})
    return {**(facts if isinstance(facts,dict) else {}),**(existing or {})}


async def queue_action(session, *, source, parent_id, chat_id, action, message_id, due):
    key=identity('delivery_action',source,parent_id,action,message_id)
    created=await enqueue(session,key=key,chat_id=chat_id,kind='delivery_action',due=due,
        payload={'source':source,'parent_id':parent_id,'action':action,'message_id':message_id})
    return created or await session.scalar(select(AdminEffect.id).where(AdminEffect.effect_key==key))


async def run_action(app, plan, *, action, message_id):
    if not message_id:
        return 'not_requested'
    db=getattr(app,'bot_data',{}).get('db')
    if db is None:
        await execute_action(app.bot,action=action,chat_id=plan.chat_id,message_id=message_id)
        return 'succeeded'
    source,parent_id=source_identity(plan)
    now=dt.datetime.now(dt.UTC)
    async with db.session_factory() as session:
        effect_id=await queue_action(session,source=source,parent_id=parent_id,chat_id=plan.chat_id,
            action=action,message_id=message_id,due=now)
        await session.commit()
    from backend.features.admin.services.effect_runtime import run_effect
    await run_effect(app,effect_id,chat_id=plan.chat_id,now=now)
    async with db.session_factory() as session:
        return FACTS[(await session.get(AdminEffect,effect_id)).status]


async def record_receipt(app, plan, *, message_id):
    db=getattr(app,'bot_data',{}).get('db')
    if db is None:
        return
    source,parent_id=source_identity(plan)
    now=dt.datetime.now(dt.UTC)
    async with db.session_factory() as session:
        parent=await session.get(MODELS[source],parent_id,with_for_update=True)
        if parent is None or parent.chat_id!=plan.chat_id or parent.status!='processing':
            raise RuntimeError('message receipt has lost its delivery claim')
        if plan.attempt_count is not None and parent.attempt_count!=plan.attempt_count:
            raise RuntimeError('message receipt belongs to a stale attempt')
        parent.message_id,parent.sent_at=message_id,now
        await _queue_receipt_actions(session,parent,source=source,message_id=message_id,now=now)
        await session.commit()


async def _queue_receipt_actions(session,parent,*,source,message_id,now):
    pin_requested = (parent.rule_snapshot.get('mode')=='send_pin' if source=='ads'
                     else bool(parent.content_snapshot.get('pin_message')))
    actions={'pin':now} if pin_requested else {}
    if source=='ads' and parent.rule_snapshot.get('delete_policy')=='delete_delay':
        delay=max(1,int(parent.rule_snapshot.get('delete_delay_seconds',60)))
        actions['delete_delay']=now+dt.timedelta(seconds=delay)
    for action,due in actions.items():
        await queue_action(session,source=source,parent_id=parent.id,chat_id=parent.chat_id,
            action=action,message_id=message_id,due=due)
        parent.post_actions={**(parent.post_actions or {}),action:'pending'}


async def eligible_action(session, row):
    payload=row.payload
    model=MODELS.get(payload.get('source'))
    if not _valid_payload(model,payload):
        return False
    parent=await session.get(model,payload['parent_id'])
    if parent is None or parent.chat_id!=row.chat_id:
        return False
    action=payload['action']
    if action in {'pin','delete_delay'}:
        return await _valid_sent_action(session,parent,payload=payload)
    return _previous_matches(parent,payload)


def _previous_matches(parent,payload):
    action,mid=payload['action'],payload['message_id']
    if parent.status not in {'processing','succeeded'}:
        return False
    snapshot=parent.rule_snapshot if payload['source']=='ads' else parent.content_snapshot
    if action=='unpin_previous':
        return bool(snapshot.get('unpin_previous')) and snapshot.get('last_pinned_message_id')==mid
    if payload['source']=='ads' and snapshot.get('delete_policy')=='delete_prev_cycle':
        snapshot=parent.content_snapshot
    return snapshot.get('last_sent_message_id')==mid


def _valid_payload(model,payload):
    return model is not None and payload.get('action') in METHODS


def _confirmed_target(parent,payload):
    if parent.message_id!=payload['message_id'] or parent.sent_at is None:
        return False
    if payload['source']=='scheduled':
        return payload['action']=='pin' and bool(parent.content_snapshot.get('pin_message'))
    if payload['action']=='pin':
        return parent.rule_snapshot.get('mode')=='send_pin'
    return parent.rule_snapshot.get('delete_policy')=='delete_delay'


async def _valid_sent_action(session,parent,*,payload):
    if not _confirmed_target(parent,payload):
        return False
    if payload['source']!='ads' or payload['action']!='pin':
        return True
    latest=await session.scalar(select(AdRotationHistory.id).where(AdRotationHistory.chat_id==parent.chat_id,
        AdRotationHistory.message_id.is_not(None),AdRotationHistory.sent_at.is_not(None))
        .order_by(AdRotationHistory.sent_at.desc(),AdRotationHistory.id.desc()).limit(1))
    return latest==parent.id


async def execute_action(bot, *, action, chat_id, message_id):
    try:
        result=await getattr(bot,METHODS[action])(chat_id=chat_id,message_id=message_id)
    except BadRequest as exc:
        if action.startswith('delete') and 'message to delete not found' in str(exc).lower():
            return {'already_absent':True,'message_id':message_id}
        raise
    if result is not True:
        raise BadRequest('ancillary action result not confirmed')
    return {'message_id':message_id,'action':action}


async def finalize_action(session, row):
    payload=row.payload
    parent=await session.get(MODELS[payload['source']],payload['parent_id'],with_for_update=True)
    if parent is None or parent.chat_id!=row.chat_id:
        return
    parent.post_actions={**(parent.post_actions or {}),payload['action']:FACTS[row.status]}
    if payload['source']!='ads' or row.status!='succeeded':
        return
    await _update_pin_fact(session,parent,row=row)


async def _update_pin_fact(session,parent,*,row):
    payload=row.payload
    rule=await session.get(AdRotationRule,row.chat_id,with_for_update=True)
    if payload['action']=='pin':
        parent.pinned_message_id=payload['message_id']
        if rule and rule.last_sent_message_id==payload['message_id']:
            rule.last_pinned_message_id=payload['message_id']
    if payload['action']=='unpin_previous' and rule and rule.last_pinned_message_id==payload['message_id']:
        rule.last_pinned_message_id=None
