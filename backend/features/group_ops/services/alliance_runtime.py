"""Command admission, shared-pool intent, and actual local execution stay distinct."""
import datetime as dt
from backend.features.garage.services.alliance_service import AllianceService
from backend.features.admin.services.effect_runtime import run_effect
from backend.features.group_ops.services.alliance_effects import plan_punishment
from backend.platform.db.schema.models.admin_effects import AdminEffect
from backend.shared.services.base import ValidationError
from backend.shared.services.permission_service import PermissionPolicyService


async def process_command(context,db,*,chat,user,message,action):
    if not await PermissionPolicyService.can_manage(context,chat.id,user.id,capability='moderation'):
        await message.reply_text('无权修改该群的联盟处罚。')
        return True
    target=getattr(getattr(message,'reply_to_message',None),'from_user',None)
    if target is None:
        await message.reply_text('请回复目标成员发送 team 或 team_mute。')
        return True
    async with db.session_factory() as session:
        try:
            entry=await AllianceService.add_joint_ban_entry(session,chat_id=chat.id,
                operator_user_id=user.id,target_user_id=target.id,punishment_type=action,
                reason='reply_team_mute' if action=='mute' else 'reply_team_command')
        except ValidationError as exc:
            await message.reply_text(str(exc))
            return True
        effect_id=await plan_punishment(session,entry=entry,chat_id=chat.id,actor_id=user.id)
        await session.commit()
    if effect_id is None:
        await message.reply_text('该池版本已在本群解除，未重复处罚；如需新处罚请先移除旧池记录。')
        return True
    await run_effect(context.application,effect_id,chat_id=chat.id,now=dt.datetime.now(dt.UTC))
    async with db.session_factory() as session:
        row=await session.get(AdminEffect,effect_id)
        text=_result_text(row)
    await message.reply_text(text)
    return True


def _result_text(row):
    if row.status=='succeeded' and row.result.get('applied'):
        return '联盟池已记录；本群处罚已确认执行。重复事件沿用原结果；移除池不会自动解封。'
    if row.status=='succeeded' and row.result.get('preexisting'):
        return '联盟池已记录；目标已有处罚，未重复执行，系统不会解除其他来源处罚。'
    from backend.features.admin.effect_views import LABELS
    return f'联盟池已记录；本群处罚未确认成功（{LABELS.get(row.status,"状态待核实")}）。请查看联盟执行/恢复记录，未知结果不重放。'


async def process_hit(context,db,*,chat,user):
    async with db.session_factory() as session:
        hit=await AllianceService.get_joint_ban_hit(session,chat_id=chat.id,target_user_id=user.id)
        if hit is None:
            return False
        effect_id=await plan_punishment(session,entry=hit[1],chat_id=chat.id)
        await session.commit()
    if effect_id is None:
        return False
    await run_effect(context.application,effect_id,chat_id=chat.id,now=dt.datetime.now(dt.UTC))
    return True
