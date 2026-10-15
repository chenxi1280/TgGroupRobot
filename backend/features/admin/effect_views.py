"""Scoped effect history and safe recovery of explicit failures only."""

from backend.shared.ui.admin_keyboard import admin_keyboard
import datetime as dt
from sqlalchemy import func, select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from backend.features.admin.notice_views import authorized
from backend.platform.db.schema.models.admin_effects import AdminEffect
from backend.shared.callback_parser import CallbackParser
from backend.shared.handlers.base.message_helper import MessageHelper
from backend.shared.time_helper import format_timestamp

PAGE_SIZE = 8
KINDS = {'group_lock','lock_notice','notice_delete','ad_expiry','delivery_action','alliance_punish','alliance_release'}
KIND_LABELS = {'group_lock':'群权限切换','lock_notice':'开/关群通知','notice_delete':'通知清理','ad_expiry':'到期提醒',
    'delivery_action':'消息附加动作','alliance_punish':'联盟处罚','alliance_release':'本群解除'}
ERROR_HINTS = {'expired_or_configuration_changed':'已过期或配置已变更','cancelled_by_admin':'管理员已取消',
    'superseded_schedule':'已被新计划替代','superseded_by_phrase':'已被后续口令替代',
    'lease_expired_after_remote_start':'调用后中断，结果待核实','telegram_rate_limited':'等待Telegram限流冷却'}
LABELS = {'pending':'等待执行','processing':'执行中','retryable_failed':'等待重试','permanent_failed':'明确失败',
          'uncertain':'结果未知，不自动重试','succeeded':'已确认成功','cancelled':'已取消'}


async def effect_callback(update, context):
    cb = CallbackParser.parse(update.callback_query.data or '')
    chat_id, kind, action = cb.get_int_optional(1), cb.get(2), cb.get(3)
    if kind not in KINDS or not await authorized(update, context, chat_id):
        await MessageHelper.safe_answer(update, '无权查看该执行记录', show_alert=True)
        return
    async with context.application.bot_data['db'].session_factory() as session:
        if action in {'retry','cancel'}:
            row = await session.get(AdminEffect, cb.get_int_optional(4), with_for_update=True)
            previous = getattr(row, "status", None)
            if not _change(row, chat_id=chat_id, kind=kind, action=action):
                await MessageHelper.safe_answer(update, _recovery_hint(row, chat_id=chat_id), show_alert=True)
                return
            from backend.shared.services.ops_audit_service import record_ops_event
            await record_ops_event(session, domain='admin_effect', event_type=action, chat_id=chat_id,
                user_id=update.effective_user.id, entity_id=str(row.id), detail={'before':previous,'after':row.status})
        elif action != 'list':
            await MessageHelper.safe_answer(update, '无效记录操作', show_alert=True)
            return
        rows, total, page = await _history_page(session, chat_id=chat_id, kind=kind, page=_requested_page(cb, action))
        await session.commit()
    lines, buttons = _render_rows(rows, chat_id=chat_id)
    nav = _page_buttons(chat_id, kind=kind, page=page, total=total)
    buttons.extend([nav] if nav else [])
    buttons.extend([[InlineKeyboardButton('刷新', callback_data=f'eff:{chat_id}:{kind}:list')],
        [InlineKeyboardButton('返回', callback_data=_back_callback(chat_id, kind=kind))]])
    await MessageHelper.safe_edit(update, f'执行与异常恢复（共{total}条，第{page+1}页）\n'+'\n\n'.join(lines or ['暂无记录'])+
        '\n结果未知须核实远端，系统不会自动重发。', reply_markup=admin_keyboard(buttons))


def _render_rows(rows, *, chat_id):
    lines, buttons = [], []
    for row in rows:
        lines.append(f'#{row.id} {KIND_LABELS.get(row.kind,row.kind)} {LABELS.get(row.status,row.status)}\n计划：{format_timestamp(row.next_run_at.timestamp())}\n结果：{_result_text(row.result)}\n原因：{ERROR_HINTS.get(row.error,(row.error or "无")[:160])}')
        if row.status in {'permanent_failed','retryable_failed'}:
            buttons.append([InlineKeyboardButton(f'重试明确失败 #{row.id}', callback_data=f'eff:{chat_id}:{row.kind}:retry:{row.id}')])
        if row.status in {'pending','retryable_failed'}:
            buttons.append([InlineKeyboardButton(f'取消 #{row.id}', callback_data=f'eff:{chat_id}:{row.kind}:cancel:{row.id}')])
    return lines, buttons


def _change(row, *, chat_id, kind, action):
    if row is None or row.chat_id != chat_id or row.kind != kind:
        return False
    if action == 'retry' and row.status in {'permanent_failed','retryable_failed'}:
        if row.error == 'telegram_rate_limited' and row.next_run_at > dt.datetime.now(dt.UTC):
            return False
        row.status, row.started_at, row.attempts = 'pending', None, 0
        row.completed_at, row.error, row.lease_until = None, None, None
        row.next_run_at = dt.datetime.now(dt.UTC)
        return True
    if action == 'cancel' and row.status in {'pending','retryable_failed'}:
        row.status, row.error = 'cancelled', 'cancelled_by_admin'
        row.completed_at = dt.datetime.now(dt.UTC)
        return True
    return False


def _recovery_hint(row, *, chat_id):
    if row is not None and row.chat_id == chat_id and row.error == 'telegram_rate_limited':
        return 'Telegram限流等待中，请在计划时间后重试。'
    return '状态已变更；未知结果禁止直接重发'


async def _history_page(session, *, chat_id, kind, page):
    kinds = {'group_lock','lock_notice','notice_delete'} if kind == 'group_lock' else {kind}
    query = select(AdminEffect).where(AdminEffect.chat_id == chat_id, AdminEffect.kind.in_(kinds))
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    page = min(max(page or 0, 0), max(0, (total-1)//PAGE_SIZE))
    rows = list((await session.scalars(query.order_by(AdminEffect.id.desc()).offset(page*PAGE_SIZE).limit(PAGE_SIZE))).all())
    return rows, total, page


def _page_buttons(chat_id, *, kind, page, total):
    rows = []
    if page > 0:
        rows.append(InlineKeyboardButton('上一页', callback_data=f'eff:{chat_id}:{kind}:list:{page-1}'))
    if (page+1)*PAGE_SIZE < total:
        rows.append(InlineKeyboardButton('下一页', callback_data=f'eff:{chat_id}:{kind}:list:{page+1}'))
    return rows


def _requested_page(cb, action):
    return cb.get_int_optional(4) if action == 'list' else 0


def _back_callback(chat_id, *, kind):
    if kind=='delivery_action':
        return f'adm:menu:category_messages:{chat_id}'
    if kind.startswith('alliance_'):
        return f'asan:{chat_id}:list:0'
    return f'adm:menu:ads:{chat_id}' if kind == 'ad_expiry' else f'adm:menu:night:{chat_id}'


def _result_text(result):
    if result.get('applied'):
        return '已确认执行本群处罚'
    if result.get('released'):
        return '已确认解除本群处罚'
    if result.get('preexisting'):
        return '已有其他来源处罚，未重复执行，未取得解除所有权'
    if result.get('permissions_applied'):
        return '权限已确认生效'
    if 'message_id' in result:
        return f"消息ID：{result['message_id']}"
    if 'deleted_message_id' in result:
        return f"已删除消息：{result['deleted_message_id']}"
    if result.get('already_absent'):
        return '消息已不存在'
    return '尚无已确认结果'
