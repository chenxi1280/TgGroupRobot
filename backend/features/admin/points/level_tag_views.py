"""Independent global/per-level display policy, ownership diagnostics and safe input."""

from backend.shared.ui.admin_keyboard import admin_keyboard
from sqlalchemy import func, select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from backend.features.admin.notice_views import authorized
from backend.features.points.services.level_tags import validate_tag
from backend.platform.db.schema.models.admin_effects import LevelTagState
from backend.platform.db.schema.models.chat import ChatSettings
from backend.platform.db.schema.models.points import PointsLevel
from backend.platform.state.state_service import clear_user_state, set_user_state
from backend.shared.callback_parser import CallbackParser
from backend.shared.handlers.base.message_helper import MessageHelper
from backend.shared.services.module_config_service import get_module_config, update_module_config

STATUS_LABELS = {'pending':'等待对账','processing':'设置中','applied':'已设置','cleared':'已清理',
    'conflict':'其他来源标签，已保留','not_applicable':'角色不适用','permanent_failed':'明确失败',
    'retryable_failed':'等待重试','uncertain':'结果待核实'}
ERROR_HINTS = {'foreign_tag_preserved':'已有其他来源标签，未覆盖。',
    'member_tag_requires_regular_member':'只支持普通成员，未修改管理员或离群用户。',
    'remote_tag_not_confirmed_no_automatic_repeat':'尚未读回原设置结果，暂不重复设置。'}


async def level_tag_callback(update, context):
    cb = CallbackParser.parse(update.callback_query.data or '')
    chat_id, target = cb.get_int_optional(1), cb.get_int_optional(2)
    if target is None or target < 0 or not await authorized(update, context, chat_id):
        await MessageHelper.safe_answer(update, '群组、等级或权限无效', show_alert=True)
        return
    async with context.application.bot_data['db'].session_factory() as session:
        settings = await session.get(ChatSettings, chat_id, with_for_update=True)
        level = await session.get(PointsLevel, target) if target else None
        if not _valid_level(settings, level, chat_id=chat_id, target=target):
            await MessageHelper.safe_answer(update, '等级或配置已不存在', show_alert=True)
            return
        if not await _configure(update, session, settings=settings, level=level, cb=cb):
            return
        await session.commit()
    await show_tags(update, context, chat_id=chat_id, target=target)


async def _configure(update, session, *, settings, level, cb):
    action = cb.get(3)
    if action == 'set' and cb.get(4) in {'0','1'}:
        return await _save_policy(update, session, settings=settings, level=level, enabled=cb.get(4) == '1')
    if action == 'input' and level is not None:
        await set_user_state(session, update.effective_user.id, update.effective_user.id,
            state_type='level_tag_input', state_data={'target_chat_id':settings.chat_id, 'level_id':level.id})
        await session.commit()
        await MessageHelper.safe_edit(update, '输入标签文案（1—16字、不含表情）。输入 默认 使用等级名称。', reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton('取消输入', callback_data=f'ltag:{settings.chat_id}:{level.id}:view')]]))
        return False
    if action == 'retry' and level is None:
        await _retry_failed(session, settings.chat_id)
        return True
    if action != 'view':
        await MessageHelper.safe_answer(update, '无效标签操作', show_alert=True)
        return False
    return True


async def _save_policy(update, session, *, settings, level, enabled):
    try:
        await _set_policy(session, settings, level=level, enabled=enabled)
        from backend.shared.services.ops_audit_service import record_ops_event
        await record_ops_event(session, domain='level_tags', event_type='display_policy', chat_id=settings.chat_id,
            user_id=update.effective_user.id, detail={'level_id':level.id if level is not None else None,'enabled':enabled})
        return True
    except ValueError as exc:
        await MessageHelper.safe_answer(update, str(exc), show_alert=True)
        return False


def _valid_level(settings, level, *, chat_id, target):
    return settings is not None and (not target or (level is not None and level.chat_id == chat_id))


async def _set_policy(session, settings, *, level, enabled):
    config = get_module_config(settings, 'level_tags')
    if level is None:
        config['enabled'] = enabled
    else:
        levels = dict(config.get('levels', {}))
        option = dict(levels.get(str(level.id), {}))
        if enabled:
            validate_tag(option.get('text') or level.level_name)
        option['enabled'] = enabled
        levels[str(level.id)] = option
        config['levels'] = levels
    await update_module_config(session, settings, module='level_tags', patch=config)


async def _retry_failed(session, chat_id):
    from sqlalchemy import update
    await session.execute(update(LevelTagState).where(LevelTagState.chat_id == chat_id,
        LevelTagState.status.in_(['permanent_failed','retryable_failed']),
        ~LevelTagState.error.startswith('telegram_rate_limited:')).values(status='pending', error=None, retry_at=None))


async def show_tags(update, context, *, chat_id, target):
    async with context.application.bot_data['db'].session_factory() as session:
        settings = await session.get(ChatSettings, chat_id)
        config = get_module_config(settings, 'level_tags')
        level = await session.get(PointsLevel, target) if target else None
        option = config if level is None else config.get('levels', {}).get(str(target), {})
        counts = (await session.execute(select(LevelTagState.status, func.count()).where(
            LevelTagState.chat_id == chat_id).group_by(LevelTagState.status))).all()
        failures = list((await session.scalars(select(LevelTagState).where(LevelTagState.chat_id == chat_id,
            LevelTagState.error.is_not(None)).order_by(LevelTagState.checked_at.desc()).limit(5))).all())
    text = _summary(level, chat_id=chat_id, config=config, option=option, counts=counts, failures=failures)
    prefix = f'ltag:{chat_id}:{target}'
    rows = [[InlineKeyboardButton('开启', callback_data=prefix+':set:1'), InlineKeyboardButton('关闭', callback_data=prefix+':set:0')]]
    if level:
        rows.append([InlineKeyboardButton('编辑标签', callback_data=prefix+':input')])
    else:
        rows.append([InlineKeyboardButton('重试明确失败', callback_data=prefix+':retry')])
    rows.append([InlineKeyboardButton('刷新状态', callback_data=prefix+':view')])
    back = f'adm:lvl:{chat_id}:detail:{target}' if target else f'adm:menu:points_level:{chat_id}'
    rows.append([InlineKeyboardButton('返回', callback_data=back)])
    await MessageHelper.safe_edit(update, text, reply_markup=admin_keyboard(rows))


def _summary(level, *, chat_id, config, option, counts, failures):
    text = f'等级标签：{level.level_name if level else "全局"}\n群：{chat_id}\n全局：{"开启" if config.get("enabled") else "关闭"}'
    text += f'\n当前项：{"开启" if option.get("enabled") else "关闭"}'
    if level:
        text += '\n文案：' + (option.get('text') or level.level_name)
    text += '\n保存只更新策略，后台按余额对账。仅管理普通成员标签；不授予身份/管理权。\n其他来源标签冲突会保留，关闭仅清理自己已确认设置的标签。'
    text += f'\n执行状态：{_status_counts(counts)}'
    for state in failures:
        text += f'\n用户{state.user_id}：{STATUS_LABELS.get(state.status,state.status)} {_error_hint(state.error)}'
    return text


async def level_tag_input(update, context, session, *, state, message_text):
    data = state.state_data or {}
    chat_id, level_id = data.get('target_chat_id'), data.get('level_id')
    if not await authorized(update, context, chat_id):
        await _exit_input(session, state, update.effective_user.id)
        await update.effective_message.reply_text('权限已失效，已退出。')
        return
    level = await session.get(PointsLevel, level_id)
    settings = await session.get(ChatSettings, chat_id, with_for_update=True)
    if level is None or level.chat_id != chat_id or settings is None:
        await _exit_input(session, state, update.effective_user.id)
        await update.effective_message.reply_text('等级已失效，已退出。')
        return
    try:
        value = None if message_text.strip() == '默认' else validate_tag(message_text)
        validate_tag(value or level.level_name)
    except ValueError as exc:
        await update.effective_message.reply_text(str(exc))
        return
    config = get_module_config(settings, 'level_tags')
    levels = dict(config.get('levels', {}))
    levels[str(level_id)] = {**levels.get(str(level_id), {}), 'text': value}
    await update_module_config(session, settings, module='level_tags', patch={'levels':levels})
    await _exit_input(session, state, update.effective_user.id)
    await show_tags(update, context, chat_id=chat_id, target=level_id)


async def _exit_input(session, state, user_id):
    await clear_user_state(session, state.chat_id, user_id)
    await session.commit()


def _status_counts(counts):
    return '、'.join(f'{STATUS_LABELS.get(status,status)} {count}' for status,count in counts) or '暂无对账记录'


def _error_hint(error):
    if error.startswith('telegram_rate_limited:'):
        return '接口限流，等待指定冷却时长。'
    return ERROR_HINTS.get(error, error[:100])
