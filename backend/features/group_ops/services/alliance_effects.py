"""One durable sanction per pool version/group/type; explicit owned releases."""
import datetime as dt
from types import SimpleNamespace
from sqlalchemy import select
from telegram import ChatPermissions
from telegram.error import BadRequest, Forbidden
from backend.features.admin.services.effect_store import enqueue, identity
from backend.platform.db.schema.models.admin_effects import AdminEffect
from backend.platform.db.schema.models.alliance import GroupAllianceBanPool, GroupAllianceMember, GroupAllianceSetting
from backend.shared.services.permission_service import PermissionPolicyService

SEND_FIELDS=('can_send_messages','can_send_audios','can_send_documents','can_send_photos','can_send_videos',
             'can_send_video_notes','can_send_voice_notes','can_send_polls','can_send_other_messages','can_add_web_page_previews')


async def plan_punishment(session, *, entry, chat_id, actor_id=None):
    key=identity('alliance_punish',entry.id,chat_id,entry.punishment_type)
    created=await enqueue(session,key=key,chat_id=chat_id,kind='alliance_punish',due=dt.datetime.now(dt.UTC),
        payload={'entry_id':entry.id,'alliance_id':entry.alliance_id,'user_id':entry.target_user_id,
                 'action':entry.punishment_type,'actor_id':actor_id})
    effect_id=created or await session.scalar(select(AdminEffect.id).where(AdminEffect.effect_key==key))
    released=await session.scalar(select(AdminEffect.id).where(
        AdminEffect.effect_key==identity('alliance_release',effect_id),AdminEffect.status=='succeeded'))
    return None if released else effect_id


async def prepare(app, row):
    context=SimpleNamespace(bot=app.bot,application=app)
    actor=row.payload.get('actor_id')
    if actor is not None and not await PermissionPolicyService.can_manage(context,row.chat_id,actor,capability='moderation'):
        return False
    if row.kind=='alliance_release':
        return await _prepare_release(app,row)
    async with app.bot_data['db'].session_factory() as session:
        if not await _pool_valid(session,row):
            return False
    target=await app.bot.get_chat_member(chat_id=row.chat_id,user_id=row.payload['user_id'])
    if target.status in {'administrator','creator'}:
        raise BadRequest('目标是管理员或群主，未执行联盟处罚')
    await _check_bot_right(app.bot,row.chat_id)
    await _save_prepared(app,row,{'before':member_snapshot(target),'preexisting':_already_restricted(target,row.payload['action'])})
    return True


async def _pool_valid(session,row):
    data=row.payload
    entry=await session.get(GroupAllianceBanPool,data['entry_id'])
    member=await session.scalar(select(GroupAllianceMember).where(GroupAllianceMember.chat_id==row.chat_id,
        GroupAllianceMember.alliance_id==data['alliance_id'],GroupAllianceMember.status=='active'))
    if member is None or entry is None:
        return False
    matches=entry.alliance_id==data['alliance_id'] and entry.target_user_id==data['user_id'] and entry.punishment_type==data['action']
    if data.get('actor_id') is not None:
        return matches
    setting=await session.get(GroupAllianceSetting,row.chat_id)
    return matches and setting is not None and setting.joint_ban_enabled and setting.alliance_id==data['alliance_id']


async def _check_bot_right(bot,chat_id):
    member=await bot.get_chat_member(chat_id=chat_id,user_id=bot.id)
    if member.status!='creator' and not getattr(member,'can_restrict_members',False):
        raise Forbidden('机器人缺少限制成员权限，未执行处罚或解除')


def member_snapshot(member):
    until=getattr(member,'until_date',None)
    return {'status':member.status,'until':int(until.timestamp()) if until else 0,
            'permissions':{key:bool(getattr(member,key,False)) for key in SEND_FIELDS}}


def _already_restricted(member,action):
    if member.status=='kicked':
        return True
    if action=='ban' or member.status!='restricted':
        return False
    return not any(member_snapshot(member)['permissions'].values())


async def _save_prepared(app,row,changes):
    async with app.bot_data['db'].session_factory() as session:
        live=await session.get(AdminEffect,row.id,with_for_update=True)
        if live.status!='processing' or live.attempts!=row.attempts:
            raise RuntimeError('alliance preparation claim lost')
        row.payload={**row.payload,**changes}
        live.payload=row.payload
        await session.commit()


async def _prepare_release(app,row):
    async with app.bot_data['db'].session_factory() as session:
        parent=await session.get(AdminEffect,row.payload['parent_id'])
        latest=await session.scalar(select(AdminEffect.id).where(AdminEffect.chat_id==row.chat_id,
            AdminEffect.kind=='alliance_punish',AdminEffect.status=='succeeded',
            AdminEffect.payload['user_id'].astext==str(row.payload['user_id']),
            AdminEffect.result['applied'].astext=='true').order_by(AdminEffect.id.desc()).limit(1))
        if not owned_parent(parent,row.chat_id) or parent.id!=latest:
            return False
    current=await app.bot.get_chat_member(chat_id=row.chat_id,user_id=row.payload['user_id'])
    if not _matches_owned(current,parent):
        raise BadRequest('当前处罚与系统记录不一致，保留现状；请先人工核实')
    await _check_bot_right(app.bot,row.chat_id)
    restore={}
    if parent.payload['action']=='mute':
        chat=await app.bot.get_chat(row.chat_id)
        if chat.permissions is None:
            raise BadRequest('无法读回群权限，未解除')
        restore=_restore_permissions(parent.payload['before'],chat.permissions)
    before=parent.payload['before']
    until=before['until'] if before['until']>dt.datetime.now(dt.UTC).timestamp() else 0
    await _save_prepared(app,row,{'action':parent.payload['action'],'restore':restore,'restore_until':until})
    return True


def owned_parent(parent,chat_id):
    return parent is not None and parent.chat_id==chat_id and parent.kind=='alliance_punish' and parent.status=='succeeded' and parent.result.get('applied') is True


def _matches_owned(member,parent):
    if parent.payload['action']=='ban':
        return member.status=='kicked'
    snapshot=member_snapshot(member)
    return snapshot['status']=='restricted' and snapshot['until']==0 and not any(snapshot['permissions'].values())


def _restore_permissions(before,current):
    permissions={key:bool(getattr(current,key,False)) for key in SEND_FIELDS}
    active=before['until']==0 or before['until']>dt.datetime.now(dt.UTC).timestamp()
    if before['status']=='restricted' and active:
        permissions={key:allowed and before['permissions'].get(key,False) for key,allowed in permissions.items()}
    return permissions


async def execute(app,row):
    data=row.payload
    if row.kind=='alliance_punish' and data.get('preexisting'):
        return {'preexisting':True,'user_id':data['user_id']}
    kwargs={'chat_id':row.chat_id,'user_id':data['user_id']}
    if data['action']=='ban':
        method=app.bot.unban_chat_member if row.kind=='alliance_release' else app.bot.ban_chat_member
        extra={'only_if_banned':True} if row.kind=='alliance_release' else {}
        confirmed=await method(**kwargs,**extra)
    else:
        values=data['restore'] if row.kind=='alliance_release' else {key:False for key in SEND_FIELDS}
        confirmed=await app.bot.restrict_chat_member(**kwargs,permissions=ChatPermissions(**values),
            until_date=data.get('restore_until',0),use_independent_chat_permissions=True)
    if confirmed is not True:
        raise BadRequest('Telegram未确认处罚结果')
    return {'released' if row.kind=='alliance_release' else 'applied':True,'user_id':data['user_id'],'action':data['action']}
