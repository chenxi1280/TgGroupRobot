"""Generic notice configuration in private chat; preview and save have no group effects."""
from __future__ import annotations

from sqlalchemy import select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from backend.features.admin.services.notice_config import parse_value
from backend.features.automation.services.ad_expiry import DEFAULTS
from backend.platform.db.schema.models.admin_effects import NoticeConsent
from backend.platform.db.schema.models.automation import AdCampaign
from backend.platform.db.schema.models.chat import ChatSettings
from backend.platform.state.state_service import clear_user_state, set_user_state
from backend.shared.callback_parser import CallbackParser
from backend.shared.handlers.base.message_helper import MessageHelper
from backend.shared.services.base import ValidationError
from backend.shared.services.module_config_service import get_module_config, update_module_config
from backend.shared.services.permission_service import PermissionPolicyService

LOCK_DEFAULTS = {'enabled': False, 'text': '群 {chat_id} 已{state}。', 'delete_seconds': 0, 'buttons': []}
FIELDS = {'gnote': {'text', 'cover', 'buttons', 'delete_seconds'},
          'anote': {'text', 'advance_days', 'time', 'recipient'}}


async def authorized(update, context, chat_id):
    return (isinstance(chat_id, int) and chat_id < 0 and update.effective_chat.type == 'private'
            and await PermissionPolicyService.can_manage(context, chat_id, update.effective_user.id))


async def load_target(session, prefix: str, *, chat_id: int, target: str):
    if prefix == 'gnote' and target in {'open', 'closed'}:
        owner = await session.get(ChatSettings, chat_id, with_for_update=True)
        config = get_module_config(owner, 'group_lock').get('notices', {}).get(target, {})
        return owner, {**LOCK_DEFAULTS, **config}
    if prefix == 'anote' and target.isascii() and target.isdigit():
        owner = await session.scalar(select(AdCampaign).where(AdCampaign.id == int(target),
            AdCampaign.chat_id == chat_id).with_for_update())
        return owner, {**DEFAULTS, **(owner.expiry_notice or {})} if owner else {}
    return None, {}


async def save_target(session, owner, *, prefix: str, target: str, config: dict):
    if prefix == 'anote':
        owner.expiry_notice = config
        await session.flush()
        return
    notices = dict(get_module_config(owner, 'group_lock').get('notices', {}))
    notices[target] = config
    await update_module_config(session, owner, module='group_lock', patch={'notices': notices})


async def notice_callback(update, context):
    cb = CallbackParser.parse(update.callback_query.data or '')
    prefix, chat_id, target = cb.get(0), cb.get_int_optional(1), cb.get(2)
    if prefix not in FIELDS or not await authorized(update, context, chat_id):
        await MessageHelper.safe_answer(update, '群组、对象或权限无效', show_alert=True)
        return
    async with context.application.bot_data['db'].session_factory() as session:
        owner, config = await load_target(session, prefix, chat_id=chat_id, target=target)
        if owner is None:
            await MessageHelper.safe_answer(update, '配置已不存在', show_alert=True)
            return
        try:
            if not await configure(update, session, owner=owner, config=config, cb=cb):
                return
        except (ValueError, ValidationError) as exc:
            await MessageHelper.safe_answer(update, str(exc), show_alert=True)
            return
        await session.commit()
    if cb.get(3) == 'preview':
        await preview_notice(update, context, prefix=prefix, chat_id=chat_id, target=target, config=config)
    await show_notice(update, context, prefix=prefix, chat_id=chat_id, target=target, config=config)


async def configure(update, session, *, owner, config, cb):
    prefix, target, action, key = cb.get(0), cb.get(2), cb.get(3), cb.get(4)
    if action == 'input' and key in FIELDS[prefix]:
        await set_user_state(session, update.effective_user.id, update.effective_user.id,
            state_type='generic_notice_input', state_data={'prefix': prefix, 'target': target,
                'key': key, 'target_chat_id': owner.chat_id})
        await session.commit()
        await MessageHelper.safe_edit(update, input_prompt(prefix, key), reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton('取消输入', callback_data=f'{prefix}:{owner.chat_id}:{target}:view')]]))
        return False
    if action == 'set' and key == 'enabled' and cb.get(5) in {'0', '1'}:
        enabled = cb.get(5) == '1'
        await _check_enable(session, owner, prefix=prefix, config=config, enabled=enabled)
        config['enabled'] = enabled
        await save_target(session, owner, prefix=prefix, target=target, config=config)
    elif action not in {'view', 'preview'}:
        raise ValueError('无效通知操作。')
    return True


async def _check_enable(session, owner, *, prefix, config, enabled):
    if not enabled or prefix != 'anote':
        return
    consent = await session.get(NoticeConsent, (owner.chat_id, owner.id, config.get('recipient', 0)))
    if consent is None or not consent.enabled:
        raise ValueError('通知人尚未在私聊同意；请先复制授权链接给本人。')


def input_prompt(prefix, key):
    prompts = {'text': '输入纯文本；支持 {chat_id} {state}。', 'cover': '发送图片；输入 清空 移除封面。',
        'buttons': '每行输入 文本|链接；多个按钮用分号 ； 分隔；输入 清空 移除。',
        'delete_seconds': '输入保留秒数0—86400；0不删除。', 'advance_days': '输入提前提醒天数0—30。',
        'time': '输入每天提醒时刻，例如10:00（Asia/Shanghai）。', 'recipient': '输入通知人Telegram数字ID；本人还须在私聊显式同意。'}
    if prefix == 'anote' and key == 'text':
        return '输入纯文本；支持 {chat_id} {ad_id} {title} {expiry}。'
    return prompts[key]


async def show_notice(update, context, *, prefix, chat_id, target, config):
    rows = [[InlineKeyboardButton('开启' + (' ✅' if config['enabled'] else ''), callback_data=f'{prefix}:{chat_id}:{target}:set:enabled:1'),
             InlineKeyboardButton('关闭' + (' ✅' if not config['enabled'] else ''), callback_data=f'{prefix}:{chat_id}:{target}:set:enabled:0')]]
    labels = {'text':'通知文案','cover':'通知封面','buttons':'通知按钮','delete_seconds':'保留秒数',
              'advance_days':'提前天数','time':'每日时刻','recipient':'通知人'}
    for key in sorted(FIELDS[prefix]):
        rows.append([InlineKeyboardButton(labels[key], callback_data=f'{prefix}:{chat_id}:{target}:input:{key}')])
    kind = 'lock_notice' if prefix == 'gnote' else 'ad_expiry'
    back = f'adm:menu:night:{chat_id}' if prefix == 'gnote' else f'ads:detail:{chat_id}:{target}'
    rows.extend([[InlineKeyboardButton('预览配置', callback_data=f'{prefix}:{chat_id}:{target}:preview')],
        [InlineKeyboardButton('执行/恢复记录', callback_data=f'eff:{chat_id}:{kind}:list')],
        [InlineKeyboardButton('返回', callback_data=back)]])
    text = _summary(prefix, chat_id, target=target, config=config)
    if prefix == 'anote':
        text += await _consent_text(context, chat_id, target=target, config=config)
    else:
        text += f"\n通知保留：{config.get('delete_seconds', 0)}秒（0不删）；与触发口令清理独立。"
    await MessageHelper.safe_edit(update, text, reply_markup=InlineKeyboardMarkup(rows))


def _summary(prefix, chat_id, *, target, config):
    title = f"{'开群' if target == 'open' else '关群'}通知" if prefix == 'gnote' else f'广告#{target}到期提醒'
    text = f'{title}\n群：{chat_id}\n状态：' + ('开启' if config['enabled'] else '关闭')
    text += '\n保存/预览只改配置，不发送群消息。\n文案：' + config['text']
    text += f"\n封面：{'已配置' if config.get('cover') else '无'}；按钮：{len(config.get('buttons', []))}行"
    return text


async def _consent_text(context, chat_id, *, target, config):
    recipient = config.get('recipient')
    consent = None
    if recipient:
        async with context.application.bot_data['db'].session_factory() as session:
            consent = await session.get(NoticeConsent, (chat_id, int(target), recipient))
    text = f"\n时区：Asia/Shanghai；到期前{config['advance_days']}天起（含当天），每天{config['time']}；过期不提醒。\n通知人：{recipient or '未配置'}"
    if consent:
        text += '\n本人授权：' + ('已同意' if consent.enabled else '待同意/已撤销')
        text += f'\n本人授权/撤销链接：https://t.me/{context.bot.username}?start=ncons_{target}_{consent.version}'
    return text


async def notice_input(update, context, session, *, state, message_text):
    data = state.state_data or {}
    prefix, chat_id, target, key = (data.get(k) for k in ('prefix','target_chat_id','target','key'))
    if prefix not in FIELDS or key not in FIELDS[prefix] or not await authorized(update, context, chat_id):
        await clear_user_state(session, state.chat_id, update.effective_user.id)
        await session.commit()
        await update.effective_message.reply_text('权限或输入已失效，已退出。')
        return
    owner, config = await load_target(session, prefix, chat_id=chat_id, target=target)
    if owner is None:
        await clear_user_state(session, state.chat_id, update.effective_user.id)
        await session.commit()
        await update.effective_message.reply_text('配置已不存在，已退出。')
        return
    try:
        await _apply_input(update, session, owner=owner, config=config, data=data, text=message_text.strip())
    except (ValueError, ValidationError) as exc:
        await update.effective_message.reply_text(str(exc))
        return
    await save_target(session, owner, prefix=prefix, target=target, config=config)
    from backend.shared.services.ops_audit_service import record_ops_event
    await record_ops_event(session, domain='admin_notice', event_type='configure', chat_id=chat_id,
        user_id=update.effective_user.id, entity_id=f'{prefix}:{target}', detail={'field':key})
    await clear_user_state(session, state.chat_id, update.effective_user.id)
    await session.commit()
    await show_notice(update, context, prefix=prefix, chat_id=chat_id, target=target, config=config)


async def _apply_input(update, session, *, owner, config, data, text):
    key = data['key']
    if key == 'recipient':
        from backend.features.automation.notice_consent import set_recipient
        if not _valid_user_id(text):
            raise ValueError('请输入正整数用户ID。')
        await set_recipient(session, owner, user_id=int(text))
        config.update(recipient=int(text), enabled=False)
        return
    fields = {'chat_id', 'state'} if data['prefix'] == 'gnote' else {'chat_id','title','expiry','ad_id'}
    config[key] = parse_value(key, text, fields=fields, message=update.effective_message)


async def preview_notice(update, context, *, prefix, chat_id, target, config):
    from backend.features.admin.services.notice_config import send_notice
    values = {'chat_id':chat_id, 'state': '关群' if target == 'closed' else '开群'}
    if prefix == 'anote':
        from backend.shared.time_helper import format_timestamp
        async with context.application.bot_data['db'].session_factory() as session:
            ad = await session.get(AdCampaign, int(target))
            expiry = format_timestamp(ad.end_time.timestamp()) if ad.end_time else '未设置'
            values = {'chat_id':chat_id, 'ad_id':ad.id, 'title':ad.title, 'expiry':expiry}
    await MessageHelper.safe_answer(update)
    from telegram.error import TelegramError
    try:
        await send_notice(context.bot, update.effective_user.id, config, values=values)
    except (TelegramError, ValueError) as exc:
        await update.effective_message.reply_text(f'预览失败：{exc}')


MAX_USER_ID = 9223372036854775807


def _valid_user_id(text):
    return text.isascii() and text.isdigit() and 0 < int(text) <= MAX_USER_ID
