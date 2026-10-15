"""Reconcile only owned member tags. Never grant roles or replace foreign labels."""
from __future__ import annotations

import datetime as dt
import unicodedata
from sqlalchemy import exists, func, or_, select, union
from sqlalchemy.dialects.postgresql import insert
from telegram.error import BadRequest, EndPointNotFound, Forbidden, NetworkError, RetryAfter, TelegramError
from backend.features.admin.services.effect_runtime import group_execution_lock
from backend.features.points.services.points_extended_levels import PointsExtendedLevelsMixin as Levels
from backend.platform.db.schema.models.admin_effects import LevelTagState
from backend.platform.db.schema.models.chat import ChatMember, ChatSettings
from backend.platform.db.schema.models.points import PointsAccount
from backend.shared.services.module_config_service import get_module_config

TAG_LIMIT = 16
TAG_BATCH = 100
SYMBOL_START = 0x2100
SYMBOL_END = 0x2BFF
TEXT_PUNCTUATION = set("，。！？、；：‘’“”（）《》【】—…·「」『』")


def validate_tag(text: str):
    text = text.strip()
    if not text or len(text) > TAG_LIMIT:
        raise ValueError('标签需要1—16字。')
    # Conservative text-only policy excludes symbols, controls and emoji sequences.
    if not all(_text_character(char) for char in text):
        raise ValueError('标签不支持表情、控制符和特殊符号，请使用文字或数字。')
    return text


async def desired_tag(session, settings, user_id):
    config = get_module_config(settings, 'level_tags')
    if not config.get('enabled'):
        return ''
    level = await Levels.resolve_user_level(session, settings.chat_id, user_id)
    if level is None:
        return ''
    option = config.get('levels', {}).get(str(level.id), {})
    if not option.get('enabled'):
        return ''
    return validate_tag(option.get('text') or level.level_name)


def tag_value(member):
    return getattr(member, 'tag', None) or (getattr(member, 'api_kwargs', {}) or {}).get('tag') or ''


async def _set_tag(bot, *, chat_id, user_id, tag):
    result = await bot.do_api_request('setChatMemberTag', api_kwargs={
        'chat_id': chat_id, 'user_id': user_id, 'tag': tag})
    if result is not True:
        raise BadRequest('member tag was not confirmed')


async def reconcile_tags(app, *, now=None):
    now = now or dt.datetime.now(dt.UTC)
    db = app.bot_data['db']
    async with db.session_factory() as session:
        cooldown = await session.scalar(select(func.max(LevelTagState.retry_at)).where(
            LevelTagState.error.startswith('telegram_rate_limited:')))
        if cooldown is not None and cooldown > now:
            return
        configured = ChatSettings.module_config.has_key('level_tags')
        owned = select(LevelTagState.chat_id)
        chats = list((await session.scalars(select(ChatSettings.chat_id).where(
            configured | ChatSettings.chat_id.in_(owned)))).all())
    errors = []
    for chat_id in chats:
        async with group_execution_lock(db, chat_id) as acquired:
            if acquired:
                await _seed_states(db, chat_id)
                errors.extend(await _reconcile_chat(app, chat_id, now=now))
        if 'rate_limited' in errors:
            break
    if errors:
        raise RuntimeError('level tag reconciliation failed; inspect tag ownership history')


async def _seed_states(db, chat_id):
    async with db.session_factory() as session:
        settings = await session.get(ChatSettings, chat_id)
        if not get_module_config(settings, 'level_tags').get('enabled'):
            return
        users = union(select(PointsAccount.user_id).where(PointsAccount.chat_id == chat_id),
                      select(ChatMember.user_id).where(ChatMember.chat_id == chat_id)).subquery()
        missing = select(users.c.user_id).where(~exists(select(LevelTagState.user_id).where(
            LevelTagState.chat_id == chat_id, LevelTagState.user_id == users.c.user_id))).limit(TAG_BATCH)
        for user_id in (await session.scalars(missing)).all():
            await session.execute(insert(LevelTagState).values(chat_id=chat_id, user_id=user_id,
                desired_tag='', status='pending').on_conflict_do_nothing())
        await session.commit()


async def _reconcile_chat(app, chat_id, *, now):
    db, errors = app.bot_data['db'], []
    async with db.session_factory() as session:
        users = list((await session.scalars(select(LevelTagState.user_id).where(LevelTagState.chat_id == chat_id,
            or_(LevelTagState.retry_at.is_(None), LevelTagState.retry_at <= now))
            .order_by(LevelTagState.checked_at, LevelTagState.user_id).limit(TAG_BATCH))).all())
    for user_id in users:
        outcome = await reconcile_member(app, chat_id=chat_id, user_id=user_id, now=now)
        if outcome:
            errors.append(outcome)
        if outcome == 'rate_limited':
            break
    return errors


async def reconcile_member(app, *, chat_id, user_id, now):
    db = app.bot_data['db']
    async with db.session_factory() as session:
        state = await session.get(LevelTagState, (chat_id, user_id), with_for_update=True)
        settings = await session.get(ChatSettings, chat_id)
        state.checked_at, state.retry_at = now, None
        try:
            wanted = await desired_tag(session, settings, user_id)
            member = await app.bot.get_chat_member(chat_id=chat_id, user_id=user_id)
            result = await _reconcile_read(session, state, member=member, wanted=wanted)
            state.checked_at = now
            await session.commit()
            if result != 'write':
                return False
            await _verify_bot_right(app.bot, chat_id)
            state.status, state.desired_tag = 'processing', wanted
            await session.commit()
            await _set_tag(app.bot, chat_id=chat_id, user_id=user_id, tag=wanted)
            state.applied_tag = wanted or None
            state.status, state.error = ('applied' if wanted else 'cleared'), None
        except (BadRequest, EndPointNotFound, Forbidden, ValueError) as exc:
            state.status, state.error = 'permanent_failed', str(exc)
        except RetryAfter as exc:
            delay = exc.retry_after.total_seconds() if isinstance(exc.retry_after, dt.timedelta) else exc.retry_after
            state.status, state.error = 'retryable_failed', f'telegram_rate_limited: {delay}'
            state.retry_at = now + dt.timedelta(seconds=delay)
        except (NetworkError, TelegramError) as exc:
            state.status = 'uncertain' if state.status in {'processing','uncertain'} else 'retryable_failed'
            state.error = str(exc)
            state.retry_at = now + dt.timedelta(minutes=1)
        await session.commit()
        return _failure_state(state)


async def _reconcile_read(session, state, *, member, wanted):
    current = tag_value(member)
    if member.status not in {'member','restricted'}:
        state.status, state.error = 'not_applicable', 'member_tag_requires_regular_member'
        return 'done'
    if not _recover_unknown(state, current):
        return 'done'
    if current and current != state.applied_tag:
        state.status, state.error = 'conflict', 'foreign_tag_preserved'
        return 'done'
    if state.status == 'permanent_failed' and state.desired_tag == wanted:
        return 'done'
    if current == wanted:
        state.status, state.error = ('applied' if wanted else 'cleared'), None
        return 'done'
    state.desired_tag = wanted
    return 'write'


async def _verify_bot_right(bot, chat_id):
    member = await bot.get_chat_member(chat_id=chat_id, user_id=bot.id)
    rights = getattr(member, 'can_manage_tags', False) or (getattr(member, 'api_kwargs', {}) or {}).get('can_manage_tags')
    if member.status != 'creator' and not (member.status == 'administrator' and rights):
        raise Forbidden('机器人缺少 can_manage_tags 权限；未修改标签')


def _recover_unknown(state, current):
    if state.status not in {'processing','uncertain'}:
        return True
    if current != state.desired_tag:
        state.status, state.error = 'uncertain', 'remote_tag_not_confirmed_no_automatic_repeat'
        return False
    state.applied_tag = current or None
    state.status, state.error = ('applied' if current else 'cleared'), None
    return True


def _failure_state(state):
    if (state.error or '').startswith('telegram_rate_limited:'):
        return 'rate_limited'
    return state.status in {'permanent_failed','uncertain','retryable_failed'}


def _text_character(char):
    category = unicodedata.category(char)
    if SYMBOL_START <= ord(char) <= SYMBOL_END:
        return False
    if category[0] in {'L','N'} or char == ' ':
        return True
    return char in TEXT_PUNCTUATION or (char.isascii() and category[0] == 'P' and char not in '#*')
