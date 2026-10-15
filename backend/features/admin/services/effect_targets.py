"""Explicit generic side-effect handlers; no target inferred from current selection."""
from __future__ import annotations

import datetime as dt
from sqlalchemy import select
from telegram import ChatPermissions
from telegram.error import BadRequest
from backend.features.admin.services.effect_store import enqueue, identity
from backend.features.admin.services.notice_config import send_notice
from backend.features.group_ops.services.lock_plans import valid_lock
from backend.platform.db.schema.models.admin_effects import AdminEffect
from backend.platform.db.schema.models.chat import ChatSettings
from backend.shared.services.module_config_service import get_module_config
from backend.shared.services.permission_service import PermissionPolicyService


async def eligible(app, row, *, now):
    if row.kind in {'alliance_punish','alliance_release'}:
        from backend.features.group_ops.services.alliance_effects import prepare
        return await prepare(app,row)
    async with app.bot_data['db'].session_factory() as session:
        if row.kind == 'delivery_action':
            from backend.features.automation.delivery_action_journal import eligible_action
            return await eligible_action(session,row)
        if row.kind == 'ad_expiry':
            from backend.features.automation.services.ad_expiry import valid_reminder
            return await valid_reminder(session, row, now=now)
        settings = await session.get(ChatSettings, row.chat_id)
        if row.kind == 'group_lock':
            return await _valid_group_lock(app, row, settings=settings, now=now)
        if row.kind == 'lock_notice':
            return await _valid_lock_notice(session, row, settings=settings)
        if row.kind == 'notice_delete':
            return await _valid_deletion(session, row)
    return False


async def _valid_group_lock(app, row, *, settings, now):
    valid = valid_lock(row, settings, now=now)
    actor = row.payload.get('actor_id')
    if valid and actor is not None:
        from types import SimpleNamespace
        valid = await PermissionPolicyService.can_manage(SimpleNamespace(bot=app.bot, application=app), row.chat_id, actor)
    return valid


async def _valid_deletion(session, row):
    parent = await session.get(AdminEffect, row.payload['parent_id'])
    return parent is not None and parent.kind == 'lock_notice' and parent.chat_id == row.chat_id and (
        parent.status == 'succeeded' and parent.result.get('message_id') == row.payload['message_id'])


async def _valid_lock_notice(session, row, *, settings):
    parent = await session.get(AdminEffect, row.payload['parent_id'])
    latest = await session.scalar(select(AdminEffect.id).where(AdminEffect.chat_id == row.chat_id,
        AdminEffect.kind == 'group_lock', AdminEffect.status == 'succeeded').order_by(AdminEffect.id.desc()).limit(1))
    mode = 'closed' if row.payload['closed'] else 'open'
    current = get_module_config(settings, 'group_lock').get('notices', {}).get(mode, {})
    return (parent is not None and parent.status == 'succeeded' and parent.id == latest
            and current.get('enabled', False) and current == row.payload['config'])


async def execute(app, row):
    if row.kind in {'alliance_punish','alliance_release'}:
        from backend.features.group_ops.services.alliance_effects import execute as execute_alliance
        return await execute_alliance(app,row)
    if row.kind == 'delivery_action':
        from backend.features.automation.delivery_action_journal import execute_action
        return await execute_action(app.bot,action=row.payload['action'],chat_id=row.chat_id,message_id=row.payload['message_id'])
    if row.kind == 'group_lock':
        kwargs = {'use_independent_chat_permissions': True} if row.payload['independent'] else {}
        result = await app.bot.set_chat_permissions(chat_id=row.chat_id,
            permissions=ChatPermissions(**row.payload['permissions']), **kwargs)
        if result is not True:
            raise BadRequest('permission result not confirmed')
        return {'permissions_applied': True, 'closed': row.payload['closed']}
    if row.kind == 'notice_delete':
        return await _delete_notice(app.bot, row)
    if row.kind == 'ad_expiry':
        return await _send_expiry(app, row)
    message = await send_notice(app.bot, row.chat_id, row.payload['config'], values={
        'chat_id': row.chat_id, 'state': '关群' if row.payload['closed'] else '开群'})
    return {'message_id': message.message_id}


async def _send_expiry(app, row):
    from backend.platform.db.schema.models.automation import AdCampaign
    from backend.shared.time_helper import format_timestamp
    async with app.bot_data['db'].session_factory() as session:
        ad = await session.get(AdCampaign, row.payload['ad_id'])
        values = {'title': ad.title, 'expiry': format_timestamp(ad.end_time.timestamp()),
                  'chat_id': row.chat_id, 'ad_id': ad.id}
    message = await send_notice(app.bot, row.payload['recipient'], row.payload['config'], values=values)
    return {'message_id': message.message_id, 'recipient': row.payload['recipient']}


async def followups(session, row, *, now):
    if row.kind == 'group_lock' and row.payload.get('notice', {}).get('enabled'):
        await enqueue(session, key=identity('lock_notice', row.id), chat_id=row.chat_id, kind='lock_notice',
            payload={'parent_id': row.id, 'closed': row.payload['closed'], 'config': row.payload['notice']},
            due=now, expires=row.expires_at)
    if row.kind == 'lock_notice':
        delay = row.payload['config'].get('delete_seconds', 0)
        if delay > 0:
            await enqueue(session, key=identity('notice_delete', row.id), chat_id=row.chat_id, kind='notice_delete',
                payload={'parent_id': row.id, 'message_id': row.result['message_id']},
                due=now+dt.timedelta(seconds=delay))


async def _delete_notice(bot, row):
    try:
        confirmed = await bot.delete_message(chat_id=row.chat_id, message_id=row.payload['message_id'])
    except BadRequest as exc:
        if 'message to delete not found' in str(exc).lower():
            return {'already_absent': True, 'message_id': row.payload['message_id']}
        raise
    if confirmed is not True:
        raise BadRequest('notice deletion result not confirmed')
    return {'deleted_message_id': row.payload['message_id']}
