"""Private history and confirmed current-group release; never mass-unban."""
import datetime as dt
from sqlalchemy import func, select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from backend.features.admin.notice_views import authorized
from backend.features.admin.effect_views import LABELS
from backend.features.admin.services.effect_store import enqueue, identity
from backend.features.group_ops.services.alliance_effects import owned_parent
from backend.platform.db.schema.models.admin_effects import AdminEffect
from backend.shared.callback_parser import CallbackParser
from backend.shared.handlers.base.message_helper import MessageHelper

PAGE_SIZE=8


async def alliance_effect_callback(update,context):
    cb=CallbackParser.parse(update.callback_query.data or '')
    chat_id,action,value=cb.get_int_optional(1),cb.get(2),cb.get_int_optional(3)
    if not await authorized(update,context,chat_id):
        await MessageHelper.safe_answer(update,'无权管理该群处罚记录',show_alert=True)
        return
    if action=='list':
        await _show_history(update,context,chat_id=chat_id,page=value or 0)
        return
    if action not in {'ask','confirm'} or value is None:
        await MessageHelper.safe_answer(update,'无效处罚操作',show_alert=True)
        return
    async with context.application.bot_data['db'].session_factory() as session:
        parent=await session.get(AdminEffect,value,with_for_update=True)
        if not owned_parent(parent,chat_id):
            await MessageHelper.safe_answer(update,'记录不属于本群、未确认处罚或不是系统施加，不能解除',show_alert=True)
            return
        if action=='confirm':
            await _queue_release(session,parent=parent,actor_id=update.effective_user.id)
            await session.commit()
    if action=='ask':
        await _show_confirmation(update,chat_id=chat_id,parent=parent)
        return
    await MessageHelper.safe_answer(update,'已提交本群解除，请查看执行结果；入队不代表已解除。')
    await _show_history(update,context,chat_id=chat_id,page=0)


async def _queue_release(session,*,parent,actor_id):
    await enqueue(session,key=identity('alliance_release',parent.id),chat_id=parent.chat_id,kind='alliance_release',
        due=dt.datetime.now(dt.UTC),payload={'parent_id':parent.id,'user_id':parent.payload['user_id'],'actor_id':actor_id})
    from backend.shared.services.ops_audit_service import record_ops_event
    await record_ops_event(session,domain='alliance',event_type='request_local_release',chat_id=parent.chat_id,
        user_id=actor_id,entity_id=str(parent.id),detail={'user_id':parent.payload['user_id'],'scope':'current_chat'})


async def _show_confirmation(update,*,chat_id,parent):
    text=f"确认解除本群对用户{parent.payload['user_id']}的系统处罚？\n仅处理本群，远端状态不符则停止。"
    text+='\n不移除联盟池，不解封其他群。该池版本在本群停止重复执行；池升级/重建后重新判断。'
    rows=[[InlineKeyboardButton('确认本群解除',callback_data=f'asan:{chat_id}:confirm:{parent.id}')],
          [InlineKeyboardButton('返回记录',callback_data=f'asan:{chat_id}:list:0')]]
    await MessageHelper.safe_edit(update,text,reply_markup=InlineKeyboardMarkup(rows))


async def _show_history(update,context,*,chat_id,page):
    async with context.application.bot_data['db'].session_factory() as session:
        query=select(AdminEffect).where(AdminEffect.chat_id==chat_id,AdminEffect.kind=='alliance_punish')
        total=await session.scalar(select(func.count()).select_from(query.subquery()))
        page=min(max(0,page),max(0,(total-1)//PAGE_SIZE))
        rows=list((await session.scalars(query.order_by(AdminEffect.id.desc()).offset(page*PAGE_SIZE).limit(PAGE_SIZE))).all())
        releases=list((await session.scalars(select(AdminEffect).where(AdminEffect.chat_id==chat_id,
            AdminEffect.kind=='alliance_release',AdminEffect.payload['parent_id'].astext.in_([str(row.id) for row in rows])))).all())
    release_by_parent={row.payload['parent_id']:row for row in releases}
    lines,buttons=_history_rows(rows,release_by_parent,chat_id=chat_id)
    nav=[]
    if page:
        nav.append(InlineKeyboardButton('上一页',callback_data=f'asan:{chat_id}:list:{page-1}'))
    if (page+1)*PAGE_SIZE<total:
        nav.append(InlineKeyboardButton('下一页',callback_data=f'asan:{chat_id}:list:{page+1}'))
    buttons.extend([nav] if nav else [])
    buttons.extend([[InlineKeyboardButton('处罚异常恢复',callback_data=f'eff:{chat_id}:alliance_punish:list'),
                    InlineKeyboardButton('解除异常恢复',callback_data=f'eff:{chat_id}:alliance_release:list')],
                   [InlineKeyboardButton('返回联盟',callback_data=f'ali:home:{chat_id}')]])
    await MessageHelper.safe_edit(update,f'本群联盟处罚记录 共{total}条，第{page+1}页\n'+'\n\n'.join(lines or ['暂无记录']),
        reply_markup=InlineKeyboardMarkup(buttons))


def _history_rows(rows,releases,*,chat_id):
    lines,buttons=[],[]
    for row in rows:
        release=releases.get(row.id)
        text=f"#{row.id} 用户{row.payload['user_id']} {'禁言' if row.payload['action']=='mute' else '封禁'}：{LABELS[row.status]}"
        text+=f"\n来源池#{row.payload['entry_id']}；"+('系统已施加' if row.result.get('applied') else '未取得已施加所有权')
        if release:
            text+='；本群解除：'+LABELS[release.status]
        elif owned_parent(row,chat_id):
            buttons.append([InlineKeyboardButton(f'本群解除 #{row.id}',callback_data=f'asan:{chat_id}:ask:{row.id}')])
        lines.append(text)
    return lines,buttons
