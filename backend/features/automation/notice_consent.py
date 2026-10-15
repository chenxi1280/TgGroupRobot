"""Private, recipient-owned authorization. Admin configuration never grants consent."""
import datetime as dt
import secrets
from sqlalchemy import select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from backend.platform.db.schema.models.admin_effects import NoticeConsent
from backend.platform.db.schema.models.automation import AdCampaign
from backend.shared.callback_parser import CallbackParser
from backend.shared.handlers.base.message_helper import MessageHelper


CONSENT_PARTS = 3


async def set_recipient(session, ad, *, user_id: int):
    rows = list((await session.scalars(select(NoticeConsent).where(NoticeConsent.ad_id == ad.id,
        NoticeConsent.chat_id == ad.chat_id).with_for_update())).all())
    for old in rows:
        old.enabled = False
    consent = next((item for item in rows if item.user_id == user_id), None)
    if consent is None:
        consent = NoticeConsent(chat_id=ad.chat_id, ad_id=ad.id, user_id=user_id)
        session.add(consent)
    consent.enabled, consent.version = False, secrets.token_hex(8)
    consent.updated_at = dt.datetime.now(dt.UTC)
    await session.flush()


async def handle_consent_start(update, context, payload: str):
    if not payload.startswith('ncons_'):
        return False
    if update.effective_chat.type != 'private':
        return True
    parts = payload.split('_')
    if len(parts) != CONSENT_PARTS or not parts[1].isdigit():
        await update.effective_message.reply_text('授权链接无效。')
        return True
    row = await _find_consent(context, ad_id=int(parts[1]), user_id=update.effective_user.id, version=parts[2])
    if row is None:
        await update.effective_message.reply_text('授权已失效，或链接不属于当前账号。')
        return True
    prefix = f'ncons:{row.chat_id}:{row.ad_id}:{row.version}'
    await update.effective_message.reply_text(f'是否接收广告#{row.ad_id}的到期提醒？\n授权群：{row.chat_id}\n可随时用此链接撤销。',
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton('同意提醒', callback_data=prefix+':1'),
            InlineKeyboardButton('撤销提醒', callback_data=prefix+':0')]]))
    return True


async def _find_consent(context, *, ad_id: int, user_id: int, version: str):
    async with context.application.bot_data['db'].session_factory() as session:
        row = await session.scalar(select(NoticeConsent).where(NoticeConsent.ad_id == ad_id,
            NoticeConsent.user_id == user_id, NoticeConsent.version == version))
        ad = await session.get(AdCampaign, ad_id)
        if row is None or ad is None or (ad.expiry_notice or {}).get('recipient') != user_id:
            return None
        return row


async def consent_callback(update, context):
    cb = CallbackParser.parse(update.callback_query.data or '')
    chat_id, ad_id, version, value = cb.get_int_optional(1), cb.get_int_optional(2), cb.get(3), cb.get(4)
    if not _valid_parameters(update, chat_id, ad_id=ad_id, value=value):
        await MessageHelper.safe_answer(update, '授权参数无效', show_alert=True)
        return
    db = context.application.bot_data['db']
    async with db.session_factory() as session:
        ad = await session.get(AdCampaign, ad_id)
        row = await session.get(NoticeConsent, (chat_id, ad_id, update.effective_user.id), with_for_update=True)
        if not _valid_consent(row, ad, chat_id=chat_id, version=version, user_id=update.effective_user.id):
            await MessageHelper.safe_answer(update, '授权已失效或不属于当前账号', show_alert=True)
            return
        row.enabled = value == '1'
        row.updated_at = dt.datetime.now(dt.UTC)
        from backend.shared.services.ops_audit_service import record_ops_event
        await record_ops_event(session, domain='ad_expiry', event_type='recipient_consent', chat_id=chat_id,
            user_id=update.effective_user.id, entity_id=str(ad_id), detail={'enabled':row.enabled,'version':row.version})
        await session.commit()
    await MessageHelper.safe_edit(update, '已同意到期提醒。' if value == '1' else '已撤销到期提醒；未发送的计划将取消。')


def _valid_consent(row, ad, *, chat_id, version, user_id):
    return (row is not None and row.version == version and ad is not None and ad.chat_id == chat_id
            and (ad.expiry_notice or {}).get('recipient') == user_id)


def _valid_parameters(update, chat_id, *, ad_id, value):
    return (update.effective_chat.type == 'private' and isinstance(chat_id, int) and chat_id < 0
            and isinstance(ad_id, int) and ad_id > 0 and value in {'0','1'})
