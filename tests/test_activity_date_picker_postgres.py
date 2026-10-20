"""Real draft transactions and registered calendars; Telegram is a fake boundary."""
import copy

import pytest
import pytest_asyncio
from sqlalchemy import select
from telegram import Update

import test_component_input_postgres as component
import test_remaining_generic_postgres as remaining
from test_component_input_postgres import buttons, rendered
from test_admin_routes_postgres import callback_update, command_update
from backend.platform.db.schema.models.chat import ConversationState
from backend.platform.state.state_service import set_user_state
from backend.features.activity.date_picker import attach
from backend.shared.ui.datetime_picker import KEY

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not remaining.URL, reason="Shanghai isolated DB required")]


@pytest_asyncio.fixture
async def runtime():
    async for value in component.runtime.__wrapped__():
        from backend.features.activity.lottery_router import LotteryRouter
        from backend.features.activity.solitaire_router import SolitaireRouter
        from telegram.ext import MessageHandler
        dispatchers = [h for h in value[0].handlers[0] if isinstance(h, MessageHandler) and h.callback.__name__ == "dispatch"]
        for handler in dispatchers:
            value[0].remove_handler(handler)
        LotteryRouter().register(value[0])
        from telegram.warnings import PTBUserWarning
        with pytest.warns(PTBUserWarning, match="per_message=False"):
            SolitaireRouter().register(value[0])
        for handler in dispatchers:
            value[0].add_handler(handler)
        yield value
        from sqlalchemy import func
        from backend.platform.db.schema.models.activity import Lottery, Solitaire
        from backend.platform.db.schema.models.expansion import AuctionItem, GuessEvent
        async with value[1].session_factory() as session:
            for model in (Lottery, Solitaire, AuctionItem, GuessEvent):
                assert await session.scalar(select(func.count()).select_from(model).where(model.chat_id == value[3])) == 0


def cb(app, user, data, *, chat=None):
    update = callback_update(app, user, 8800, data)
    if chat is None:
        return update
    raw = update.to_dict()
    raw["callback_query"]["message"]["chat"] = {"id": chat, "type": "supergroup", "title": "test"}
    return Update.de_json(raw, app.bot)


async def state_of(db, user, *, chat=None):
    async with db.session_factory() as s:
        return await s.scalar(select(ConversationState).where(
            ConversationState.user_id == user, ConversationState.chat_id == (chat or user)))


async def press(runtime, action, *, value=None, chat=None):
    app, _, boundary, _, user = runtime
    callback = next(b["callback_data"] for b in buttons(boundary)
                    if b.get("callback_data", "").startswith("acal:")
                    and b["callback_data"].split(":")[3] == action
                    and (value is None or b["callback_data"].split(":")[4] == value))
    await app.process_update(cb(app, user, callback, chat=chat))
    return callback


async def choose(runtime, *, chat=None):
    for action, value in [("open", None), ("month", "12"), ("day", None), ("hour", "23"),
                          ("minutes", "2"), ("minute", "59")]:
        await press(runtime, action, value=value, chat=chat)


def no_group_publish(boundary):
    assert not any(int(p["chat_id"]) < 0 for method, p in boundary.calls
                   if method in {"sendMessage", "sendPhoto"})


async def test_guess_calendar_only_changes_draft_and_rejects_replay(runtime):
    app, db, b, chat, user = runtime
    await app.process_update(callback_update(app, user, 8100, f"guess:create:{chat}:deadline"))
    initial = await state_of(db, user)
    assert KEY in initial.state_data
    await choose(runtime)
    assert "deadline_at" not in (await state_of(db, user)).state_data
    await app.process_update(command_update(app, user, user, 8101, "2099-12-31 12:00"))
    assert "本条消息未保存" in rendered(b)["text"]
    # Restore current calendar by reading its durable confirm revision.
    st = await state_of(db, user)
    p = st.state_data[KEY]
    confirm = f"acal:{p['token']}:{p['revision']}:apply:"
    await app.process_update(cb(app, user, confirm))
    saved = await state_of(db, user)
    assert saved.state_type == "guess_draft" and saved.state_data["deadline_at"]
    assert KEY not in saved.state_data
    await app.process_update(cb(app, user, confirm))
    assert (await state_of(db, user)).state_data == saved.state_data
    no_group_publish(b)


async def test_solitaire_date_is_staged_cancel_keeps_it_and_manual_returns_config(runtime):
    app, db, b, chat, user = runtime
    await app.process_update(callback_update(app, user, 8200, f"sol:create:{chat}"))
    await choose(runtime)
    assert "calendar_deadline" not in (await state_of(db, user)).state_data
    await press(runtime, "apply")
    saved = (await state_of(db, user)).state_data["calendar_deadline"]
    assert "配置省略截止时间行" in rendered(b)["text"]
    await press(runtime, "open")
    await press(runtime, "cancel")
    assert (await state_of(db, user)).state_data["calendar_deadline"] == saved
    await press(runtime, "open")
    await press(runtime, "manual")
    assert "一次性发送配置" in rendered(b)["text"]
    no_group_publish(b)


async def test_lottery_calendar_advances_to_original_confirmation(runtime):
    app, db, b, chat, user = runtime
    data = {"target_chat_id": chat, "step": "prize_action", "title": "calendar lottery",
            "prizes": [{"name": "奖品", "quantity": 1, "points_reward": 0}],
            "lottery_type": "common", "selection_mode": "threshold_random", "draw_trigger": "time_deadline"}
    async with db.session_factory() as s:
        await set_user_state(s, user, user, state_type="lottery_create", state_data=data)
        await s.commit()
    await app.process_update(callback_update(app, user, 8300, f"lot:wiz:{chat}:prize:done"))
    await choose(runtime)
    await press(runtime, "apply")
    state = await state_of(db, user)
    assert state.state_type == "lottery_create" and state.state_data["step"] == "preset_confirm"
    assert state.state_data["draw_time"] and state.state_data["prizes"] == data["prizes"]
    assert KEY not in state.state_data
    no_group_publish(b)


@pytest.mark.parametrize("fault", ["foreign_user", "changed", "revoked", "expired", "wrong_step"])
async def test_activity_picker_rejects_invalid_ownership_state_and_permission(runtime, fault):
    app, db, b, chat, user = runtime
    data = attach({"target_chat_id": chat, "title": "keep", "step": "draw_param", "draw_trigger": "time_deadline"}, back="lot:menu")
    p = data[KEY]
    old = copy.deepcopy(data)
    if fault == "changed":
        data["title"] = "new title"
    if fault == "expired":
        p["expires"] = 0
    if fault == "wrong_step":
        data["step"] = "prize_name"
    async with db.session_factory() as s:
        await set_user_state(s, user, user, state_type="lottery_create", state_data=data)
        await s.commit()
    if fault == "revoked":
        b.member(user)
    await app.process_update(cb(app, user + 777 if fault == "foreign_user" else user,
                                f"acal:{p['token']}:{p['revision']}:open:"))
    state = await state_of(db, user)
    assert state.state_data[KEY]["revision"] == old[KEY]["revision"]
    assert "draw_time" not in state.state_data
    assert any(params.get("show_alert") for method, params in b.calls if method == "answerCallbackQuery")
    no_group_publish(b)


async def test_auction_group_calendar_reaches_preview_without_publication(runtime):
    from types import SimpleNamespace
    from backend.features.activity.auction_handler import _AuctionFlow, _handle_auction_start_price
    from backend.features.activity.services.auction_service import get_or_create_setting
    app, db, b, chat, user = runtime
    update = command_update(app, user, chat, 8500, "100")
    context = SimpleNamespace(bot=app.bot, application=app)
    async with db.session_factory() as s:
        setting = await get_or_create_setting(s, chat)
        setting.enabled = True
        flow = _AuctionFlow(update, context, s, setting, update.effective_chat,
                            update.effective_user, update.effective_message, "100")
        await _handle_auction_start_price(flow, {"title": "拍卖草稿", "source_message_id": 42})
    await choose(runtime, chat=chat)
    before = await state_of(db, user, chat=chat)
    assert "end_at" not in before.state_data
    await press(runtime, "apply", chat=chat)
    after = await state_of(db, user, chat=chat)
    assert after.state_type == "auction_wait_confirm"
    assert after.state_data["end_at"] and after.state_data["source_message_id"] == 42
    assert KEY not in after.state_data
    assert "确认 或 取消" in rendered(b)["text"]
    # Only the original input/confirmation prompts may go to the group.
    assert not any("起拍价" in p.get("text", "") and "截止时间" in p.get("text", "")
                   and "请确认拍卖信息" not in p.get("text", "")
                   for method, p in b.calls if method == "sendMessage" and int(p["chat_id"]) == chat)
    assert any(int(p["chat_id"]) == user for method, p in b.calls if method == "sendMessage")


async def test_restored_activity_draft_drops_transient_calendar_lock(runtime):
    from backend.platform.state.edit_drafts import suspend_inputs
    app, db, b, chat, user = runtime
    await app.process_update(callback_update(app, user, 8700, f"guess:create:{chat}:deadline"))
    await press(runtime, "open")
    async with db.session_factory() as s:
        drafts = await suspend_inputs(s, user)
        token = drafts[0].token
        await s.commit()
    await app.process_update(callback_update(app, user, 8701, f"draft:resume:{chat}:{token}"))
    state = await state_of(db, user)
    assert state.state_type == "guess_wait_deadline" and KEY not in state.state_data
    await app.process_update(command_update(app, user, user, 8702, "2099-12-31 12:00"))
    state = await state_of(db, user)
    assert state.state_type == "guess_draft" and state.state_data["deadline_at"]
    no_group_publish(b)


@pytest.mark.parametrize("kind", ["lottery_create", "solitaire_create", "guess_wait_deadline", "auction_wait_end_at"])
async def test_past_activity_date_cannot_be_applied(runtime, kind):
    app, db, b, chat, user = runtime
    from backend.features.activity.services.auction_service import get_or_create_setting
    scope = chat if kind.startswith("auction") else user
    data = attach({"target_chat_id": chat, "step": "draw_param", "draw_trigger": "time_deadline"},
                  back="back", initial="2000-01-01 00:00")
    data[KEY]["step"] = "confirm"
    p = data[KEY]
    async with db.session_factory() as s:
        if scope == chat:
            setting = await get_or_create_setting(s, chat)
            setting.enabled = True
        await set_user_state(s, scope, user, state_type=kind, state_data=data)
        await s.commit()
    await app.process_update(cb(app, user, f"acal:{p['token']}:{p['revision']}:apply:", chat=chat if scope == chat else None))
    state = await state_of(db, user, chat=scope)
    assert state.state_type == kind and state.state_data == data


async def test_leaving_solitaire_does_not_swallow_other_editor_input(runtime):
    app, db, b, chat, user = runtime
    await app.process_update(callback_update(app, user, 8900, f"sol:create:{chat}"))
    await app.process_update(callback_update(app, user, 8901, f"guess:create:{chat}:deadline"))
    await app.process_update(command_update(app, user, user, 8902, "2099-12-31 12:00"))
    state = await state_of(db, user)
    assert state.state_type == "guess_draft" and state.state_data["deadline_at"]
    no_group_publish(b)


async def test_switching_guess_field_drops_calendar_input_lock(runtime):
    app, db, b, chat, user = runtime
    await app.process_update(callback_update(app, user, 8950, f"guess:create:{chat}:deadline"))
    old = await press(runtime, "open")
    await app.process_update(callback_update(app, user, 8951, f"guess:create:{chat}:title"))
    state = await state_of(db, user)
    assert state.state_type == "guess_wait_title" and KEY not in state.state_data
    await app.process_update(cb(app, user, old))
    await app.process_update(command_update(app, user, user, 8952, "新竞猜标题"))
    state = await state_of(db, user)
    assert state.state_type == "guess_draft" and state.state_data["title"] == "新竞猜标题"
    no_group_publish(b)
