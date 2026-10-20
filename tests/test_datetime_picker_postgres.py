import pytest
from sqlalchemy import select

import pytest_asyncio
import test_component_input_postgres as component
from test_component_input_postgres import tasks, buttons, rendered
from test_admin_routes_postgres import callback_update, command_update
import test_remaining_generic_postgres as remaining
from backend.features.automation.services.scheduled_message_service import ScheduledMessageService as SM
from backend.platform.db.schema.models.chat import ConversationState

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not remaining.URL, reason="Shanghai isolated DB required")]


@pytest_asyncio.fixture
async def runtime():
    async for value in component.runtime.__wrapped__():
        yield value


async def press(app, boundary, user, action, *, value=None, update_id=2100):
    callback = next(b["callback_data"] for b in buttons(boundary)
                    if b.get("callback_data", "").startswith("dtp:")
                    and b["callback_data"].split(":")[3] == action
                    and (value is None or b["callback_data"].split(":")[4] == value))
    await app.process_update(callback_update(app, user, update_id, callback))
    return callback


async def select_time(app, boundary, user, *, future=False):
    await press(app, boundary, user, "open")
    if future:
        await press(app, boundary, user, "month", value="12")
    await press(app, boundary, user, "day")
    await press(app, boundary, user, "hour", value="23")
    await press(app, boundary, user, "minutes", value="2")
    await press(app, boundary, user, "minute", value="59")


async def test_calendar_requires_confirmation_and_old_callbacks_cannot_write(runtime):
    app, db, b, chat, user = runtime
    task, _ = await tasks(db, chat, user)
    await app.process_update(callback_update(app, user, 2000, f"sm:edit:{chat}:{task}:start_at"))
    await select_time(app, b, user)
    async with db.session_factory() as session:
        assert (await SM.get_task_in_chat_or_404(session, chat, task)).start_at is None
    apply_callback = next(x["callback_data"] for x in buttons(b) if ":apply:" in x.get("callback_data", ""))
    await app.process_update(command_update(app, user, user, 2001, "2099-12-31 12:00"))
    assert "本条消息未保存" in rendered(b)["text"]
    await app.process_update(callback_update(app, user, 2003, apply_callback))
    async with db.session_factory() as session:
        saved = (await SM.get_task_in_chat_or_404(session, chat, task)).start_at
        assert saved is not None
    await app.process_update(callback_update(app, user, 2002, apply_callback))
    assert any("已过期" in p.get("text", "") for method, p in b.calls if method == "answerCallbackQuery")
    async with db.session_factory() as session:
        assert (await SM.get_task_in_chat_or_404(session, chat, task)).start_at == saved
    assert not any(int(p["chat_id"]) < 0 for method, p in b.calls if method in {"sendMessage", "sendPhoto"})


async def test_calendar_cancel_and_stale_other_editor_keep_original_value(runtime):
    app, db, b, chat, user = runtime
    first, second = await tasks(db, chat, user)
    await app.process_update(callback_update(app, user, 2200, f"sm:edit:{chat}:{first}:start_at"))
    old = await press(app, b, user, "open")
    await press(app, b, user, "cancel")
    await app.process_update(command_update(app, user, user, 2201, "2099-12-31 12:00"))
    await app.process_update(callback_update(app, user, 2202, f"sm:edit:{chat}:{second}:start_at"))
    await app.process_update(callback_update(app, user, 2203, old))
    async with db.session_factory() as session:
        assert (await SM.get_task_in_chat_or_404(session, chat, first)).start_at is None
        assert (await SM.get_task_in_chat_or_404(session, chat, second)).start_at is None
        state = await session.scalar(select(ConversationState).where(ConversationState.user_id == user, ConversationState.chat_id == user))
        assert state.state_data["task_id"] == second


async def test_calendar_conflict_and_revocation_cannot_overwrite(runtime):
    app, db, b, chat, user = runtime
    task, _ = await tasks(db, chat, user)
    await app.process_update(callback_update(app, user, 2300, f"sm:edit:{chat}:{task}:start_at"))
    await select_time(app, b, user)
    async with db.session_factory() as session:
        await SM.update_task_start_at(session, task, "2099-12-31 12:00")
        await session.commit()
    callback = await press(app, b, user, "apply")
    assert any("已被修改" in p.get("text", "") for method, p in b.calls if method == "answerCallbackQuery")
    b.member(user)
    await app.process_update(callback_update(app, user, 2301, callback))
    async with db.session_factory() as session:
        state = await session.scalar(select(ConversationState).where(ConversationState.user_id == user, ConversationState.chat_id == user))
        assert state.state_type == "selected_chat"
        assert (await SM.get_task_in_chat_or_404(session, chat, task)).start_at is not None


async def test_calendar_foreign_user_deleted_object_and_manual_input(runtime):
    from sqlalchemy import delete
    from backend.platform.db.schema.models.scheduled_message import ScheduledMessageTask
    app, db, b, chat, user = runtime
    task, other = await tasks(db, chat, user)
    await app.process_update(callback_update(app, user, 2400, f"sm:edit:{chat}:{task}:start_at"))
    foreign = next(x['callback_data'] for x in buttons(b) if x.get('callback_data', '').startswith('dtp:'))
    await app.process_update(callback_update(app, user + 1, 2401, foreign))
    assert any('已过期' in p.get('text', '') for m, p in b.calls if m == 'answerCallbackQuery')
    await press(app, b, user, 'open')
    await press(app, b, user, 'manual')
    await app.process_update(command_update(app, user, user, 2402, '2099-12-30 12:37'))
    async with db.session_factory() as s:
        assert (await SM.get_task_in_chat_or_404(s, chat, task)).start_at is not None
    await app.process_update(callback_update(app, user, 2403, f"sm:edit:{chat}:{other}:start_at"))
    await select_time(app, b, user)
    async with db.session_factory() as s:
        await s.execute(delete(ScheduledMessageTask).where(ScheduledMessageTask.chat_id == chat, ScheduledMessageTask.short_id == other))
        await s.commit()
    await press(app, b, user, 'apply')
    assert any('对象已删除' in p.get('text', '') for m, p in b.calls if m == 'answerCallbackQuery')


@pytest.mark.parametrize('field', ['start', 'end', 'rule'])
async def test_ads_calendar_applies_to_original_field_without_enabling_or_sending(runtime, field):
    from backend.features.automation.services.ad_rotation_service import create_rotation_item
    from backend.platform.db.schema.models.automation import AdCampaign, AdRotationRule
    app, db, b, chat, user = runtime
    async with db.session_factory() as s:
        item = await create_rotation_item(s, chat_id=chat, created_by_user_id=user)
        item.enabled = False
        ident = item.id
        await s.commit()
    entry = f'ads:rules:input:{chat}:start' if field == 'rule' else f'ads:item:input:{chat}:{ident}:{field}'
    await app.process_update(callback_update(app, user, 2500, entry))
    await select_time(app, b, user, future=True)
    copied = next(x['copy_text']['text'] for x in buttons(b) if 'copy_text' in x)
    assert copied.endswith('23:59')
    await press(app, b, user, 'apply')
    async with db.session_factory() as s:
        item = await s.get(AdCampaign, ident)
        assert item.enabled is False
        if field == 'rule':
            assert (await s.get(AdRotationRule, chat)).start_at is not None
        else:
            assert getattr(item, 'start_time' if field == 'start' else 'end_time') is not None
    assert not any(int(p['chat_id']) < 0 for m, p in b.calls if m in {'sendMessage','sendPhoto'})


@pytest.mark.parametrize('field', ['sm_start', 'sm_end', 'ads_start', 'ads_end', 'ads_rule'])
@pytest.mark.parametrize('picker_step', ['day', 'hour', 'minute', 'confirm'])
async def test_restore_expired_calendar_draft_accepts_text_and_keeps_target(runtime, field, picker_step):
    from backend.platform.db.schema.models.chat import EditDraft
    from backend.platform.db.schema.models.automation import AdCampaign, AdRotationRule
    from backend.features.automation.services.ad_rotation_service import create_rotation_item
    from backend.shared.ui.datetime_picker import KEY
    app, db, b, chat, user = runtime
    if field.startswith('sm_'):
        ident, _ = await tasks(db, chat, user)
        entry = f"sm:edit:{chat}:{ident}:{'start_at' if field == 'sm_start' else 'end_at'}"
    else:
        async with db.session_factory() as s:
            item = await create_rotation_item(s, chat_id=chat, created_by_user_id=user)
            item.enabled = False
            ident = item.id
            await s.commit()
        entry = f'ads:rules:input:{chat}:start' if field == 'ads_rule' else f"ads:item:input:{chat}:{ident}:{'start' if field == 'ads_start' else 'end'}"
    await app.process_update(callback_update(app, user, 2600, entry))
    await press(app, b, user, 'open')
    if picker_step != 'day':
        await press(app, b, user, 'day')
    if picker_step in {'minute', 'confirm'}:
        await press(app, b, user, 'hour', value='23')
    if picker_step == 'confirm':
        await press(app, b, user, 'minute')
    async with db.session_factory() as s:
        state = await s.scalar(select(ConversationState).where(ConversationState.user_id == user, ConversationState.chat_id == user))
        assert state.state_data[KEY]['step'] == picker_step
        p = {**state.state_data[KEY], 'expires': 0}
        state.state_data = {**state.state_data, KEY: p}
        kind = state.state_type
        old = f"dtp:{p['token']}:{p['revision']}:apply:"
        await s.commit()
    await app.process_update(callback_update(app, user, 2601, f'adm:menu:main:{chat}'))
    async with db.session_factory() as s:
        draft = await s.scalar(select(EditDraft).where(EditDraft.user_id == user, EditDraft.chat_id == chat,
                                                       EditDraft.state_type == kind).order_by(EditDraft.created_at.desc()))
        assert draft is not None and KEY in draft.state_data
        token = draft.token
        expected = {key: value for key, value in draft.state_data.items() if key != KEY}
    await app.process_update(callback_update(app, user, 2602, f'draft:resume:{chat}:{token}'))
    async with db.session_factory() as s:
        state = await s.scalar(select(ConversationState).where(ConversationState.user_id == user, ConversationState.chat_id == user))
        assert state.state_type == kind and state.state_data == expected
    await app.process_update(callback_update(app, user, 2603, old))
    assert any('已过期' in p.get('text', '') for m, p in b.calls if m == 'answerCallbackQuery')
    import asyncio
    await asyncio.wait_for(app.process_update(command_update(app, user, user, 2604, '2099-12-31 12:37')), timeout=10)
    async with db.session_factory() as s:
        if field.startswith('sm_'):
            task = await SM.get_task_in_chat_or_404(s, chat, ident)
            saved = getattr(task, 'start_at' if field == 'sm_start' else 'end_at')
            assert task.enabled is False
        elif field == 'ads_rule':
            saved = (await s.get(AdRotationRule, chat)).start_at
        else:
            item = await s.get(AdCampaign, ident)
            saved = getattr(item, 'start_time' if field == 'ads_start' else 'end_time')
            assert item.enabled is False
        from backend.shared.time_helper import LOCAL_TIMEZONE
        if field.startswith("sm_"):
            from datetime import datetime
            saved = datetime.fromtimestamp(saved, LOCAL_TIMEZONE)
        assert saved.astimezone(LOCAL_TIMEZONE).strftime('%Y-%m-%d %H:%M') == '2099-12-31 12:37'
    assert not any(int(p['chat_id']) < 0 for m, p in b.calls if m in {'sendMessage', 'sendPhoto'})
