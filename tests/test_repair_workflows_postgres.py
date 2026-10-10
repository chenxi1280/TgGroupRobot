"""Real database boundaries for PRD drafts, publications, and order fulfillment."""
import datetime as dt
import os
import secrets
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from telegram.error import TimedOut

from backend.platform.db.runtime.session import create_database
from backend.platform.db.schema.models.core import (
    ConversationState, EditDraft, PointsMallOrder, PointsMallProduct, MallNotification,
)
from backend.platform.db.schema.models.expansion import GuessEvent
from backend.features.activity.services.guess_service_runtime import create_event, format_event_runtime
from backend.features.activity.services.activity_publication_service import prepare_publication, send_publication
from backend.platform.state.edit_drafts import suspend_inputs
from backend.platform.state.conversation_state_service import ConversationStateService
from backend.features.group_ops.services.chat_group_service import set_user_current_chat
from backend.features.points.services.points_extended_service import PointsExtendedService as Mall
from backend.features.points.services.mall_notifications import deliver_notification
from backend.shared.button_layout_service import ButtonEditorContext, ButtonLayoutEditorService
from backend.shared.button_layout_persistence import _ensure_draft, _persist_draft, save_button_draft
from backend.shared.services.chat_service import get_chat_settings
from backend.shared.services.base import ValidationError
from test_mall_intent_postgres import seed, intent, confirm

URL = os.environ.get("TGR_REPAIR_TEST_DATABASE_URL")
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not URL, reason="disposable Postgres URL required")]


async def test_switching_groups_preserves_draft_without_active_input_after_restart():
    db = create_database(URL)
    try:
        chat, user, _ = await seed(db)
        other, _, _ = await seed(db)
        async with db.session_factory() as s:
            await ConversationStateService.start(s, chat, user, state_type="command_config_alias_input",
                state_data={"target_chat_id": chat, "command_key": "sign", "unsaved": "keep me"})
            await s.commit()
        await set_user_current_chat(db, user, other)
        await db.engine.dispose()
        async with db.session_factory() as s:
            active = list((await s.execute(select(ConversationState).where(ConversationState.user_id == user,
                ConversationState.state_type != "selected_chat"))).scalars())
            drafts = list((await s.execute(select(EditDraft).where(EditDraft.user_id == user))).scalars())
            assert not active
            assert len(drafts) == 1 and drafts[0].state_data["unsaved"] == "keep me"
            await ConversationStateService.clear(s, user, user)
            await s.commit()
        async with db.session_factory() as s:
            assert await s.scalar(select(func.count()).select_from(EditDraft).where(EditDraft.user_id == user)) == 1
    finally:
        await db.engine.dispose()


async def test_buttons_draft_restart_explicit_save_and_conflict():
    db = create_database(URL)
    try:
        chat, user, _ = await seed(db)
        ctx = SimpleNamespace(user_data={"button_editor_user_id": user})
        editor = ButtonEditorContext("invite", chat, 0)
        grid = ButtonLayoutEditorService.to_grid([[{"text": "new", "url": "https://example.com"}]])
        async with db.session_factory() as s:
            await _persist_draft(s, ctx, editor, grid=grid)
            settings = await get_chat_settings(s, chat)
            assert not settings.invite_link_buttons
            await s.commit()
        await db.engine.dispose()
        ctx = SimpleNamespace(user_data={"button_editor_user_id": user})
        async with db.session_factory() as s:
            assert await _ensure_draft(s, ctx, editor) == grid
            settings = await get_chat_settings(s, chat)
            settings.invite_link_buttons = [[{"text": "someone else", "url": "https://example.org"}]]
            await s.commit()
        async with db.session_factory() as s:
            with pytest.raises(ValidationError, match="其他人"):
                await save_button_draft(s, ctx, editor)
        async with db.session_factory() as s:
            settings = await get_chat_settings(s, chat)
            settings.invite_link_buttons = []
            await s.commit()
        async with db.session_factory() as s:
            await save_button_draft(s, ctx, editor)
            await s.commit()
        async with db.session_factory() as s:
            assert (await get_chat_settings(s, chat)).invite_link_buttons == [[{"text": "new", "url": "https://example.com"}]]
    finally:
        await db.engine.dispose()


@pytest.mark.parametrize("unknown", [False, True])
async def test_publication_success_or_unknown_never_recreates_or_resends(unknown):
    db = create_database(URL)
    try:
        chat, user, _ = await seed(db)
        token = secrets.token_hex(12)
        calls = []
        async def send_message(**kwargs):
            calls.append(kwargs)
            if unknown:
                raise TimedOut("response lost")
            return SimpleNamespace(message_id=123)
        context = SimpleNamespace(bot=SimpleNamespace(send_message=send_message))
        for _ in range(2):
            async with db.session_factory() as s:
                async def create():
                    return await create_event(s, chat, user, draft={"title": "test", "options": [{"key": "a", "label": "A"}],
                        "deadline_at": (dt.datetime.now(dt.UTC)+dt.timedelta(hours=1)).isoformat()})
                record = await prepare_publication(s, token=token, domain="guess", chat_id=chat,
                    creator_user_id=user, create_entity=create, render=lambda event: {"text": format_event_runtime(event)})
                record = await send_publication(s, context, record)
                assert record.status == ("uncertain" if unknown else "succeeded")
            await db.engine.dispose()
        assert len(calls) == 1
        async with db.session_factory() as s:
            events = list((await s.execute(select(GuessEvent).where(GuessEvent.chat_id == chat))).scalars())
            assert len(events) == 1
            assert events[0].status == ("publishing" if unknown else "running")
    finally:
        await db.engine.dispose()


async def test_notification_unknown_keeps_order_and_does_not_resend():
    db = create_database(URL)
    try:
        scope = await seed(db)
        token = await intent(db, scope)
        _, _, order_id = await confirm(db, scope, token)
        async with db.session_factory() as s:
            notification_id = await s.scalar(select(MallNotification.id).where(MallNotification.order_id == order_id, MallNotification.role == "buyer"))
        calls = []
        async def send_message(**kwargs):
            calls.append(kwargs)
            raise TimedOut("response lost")
        context = SimpleNamespace(bot=SimpleNamespace(send_message=send_message))
        await deliver_notification(db, context, notification_id)
        await deliver_notification(db, context, notification_id)
        assert len(calls) == 1
        async with db.session_factory() as s:
            assert (await s.get(MallNotification, notification_id)).status == "uncertain"
            assert (await s.get(PointsMallOrder, order_id)).order_status == "created"
    finally:
        await db.engine.dispose()


async def test_fulfillment_reassignment_and_refund_compete_safely():
    db = create_database(URL)
    try:
        scope = await seed(db)
        _, _, order_id = await confirm(db, scope, await intent(db, scope))
        async with db.session_factory() as s:
            ok, _, _ = await Mall.fulfill_order(s, chat_id=scope[0], order_id=order_id,
                operator_user_id=scope[1], note="sent", assigned_only=True)
            assert not ok
            ok, _, _ = await Mall.cancel_order(s, chat_id=scope[0], order_id=order_id, operator_user_id=scope[1])
            assert ok
            await s.commit()
        async with db.session_factory() as s:
            ok, _, _ = await Mall.fulfill_order(s, chat_id=scope[0], order_id=order_id,
                operator_user_id=scope[1], note="sent")
            assert not ok
            ok, _, _ = await Mall.refund_order(s, chat_id=scope[0], order_id=order_id, operator_user_id=scope[1])
            assert not ok
            product = await s.get(PointsMallProduct, scope[2])
            assert product.stock_left == product.stock_total
    finally:
        await db.engine.dispose()


async def test_expired_input_is_archived_once_and_recovery_has_no_expired_ttl():
    db = create_database(URL)
    try:
        chat, user, _ = await seed(db)
        async with db.session_factory() as s:
            await ConversationStateService.start(s, user, user, state_type="command_config_alias_input",
                state_data={"target_chat_id": chat, "command_key": "sign", "base_alias": None},
                expire_at=dt.datetime.now(dt.UTC)-dt.timedelta(seconds=1))
            await s.commit()
        for _ in range(2):
            async with db.session_factory() as s:
                state = await ConversationStateService.get(s, user, user)
                assert state is None or state.state_type == "selected_chat"
                await s.commit()
        async with db.session_factory() as s:
            drafts = list((await s.execute(select(EditDraft).where(EditDraft.user_id == user))).scalars())
            assert len(drafts) == 1
            assert "__expire_at__" not in drafts[0].state_data
    finally:
        await db.engine.dispose()


async def test_failed_ui_feedback_survives_restart_then_is_shown():
    from backend.platform.runtime.request_scope import bind_request_scope
    from backend.platform.telegram.ui_feedback import retain_feedback, show_pending_feedback
    from backend.platform.db.schema.models.ui_feedback import UiFeedback
    db = create_database(URL)
    try:
        _, user, _ = await seed(db)
        async with bind_request_scope(update_id=42, chat_id=user, user_id=user) as scope:
            scope.cache["feedback_db"] = db
            await retain_feedback(None, "订单已创建 #123")
            await retain_feedback(None, "订单已创建 #123")
        await db.engine.dispose()
        seen = []
        async def reply(text):
            seen.append(text)
        update = SimpleNamespace(effective_chat=SimpleNamespace(type="private"),
            effective_user=SimpleNamespace(id=user), effective_message=SimpleNamespace(reply_text=reply))
        context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": db}))
        await show_pending_feedback(update, context)
        await show_pending_feedback(update, context)
        assert len(seen) == 1 and "订单已创建 #123" in seen[0]
        async with db.session_factory() as s:
            assert await s.scalar(select(func.count()).select_from(UiFeedback).where(UiFeedback.user_id == user)) == 1
    finally:
        await db.engine.dispose()


async def test_cancel_and_fulfill_concurrent_has_one_terminal_effect():
    import asyncio
    from backend.platform.db.schema.models.core import PointsAccount
    db = create_database(URL)
    try:
        scope = await seed(db)
        _, _, order_id = await confirm(db, scope, await intent(db, scope))
        async def operate(action):
            async with db.session_factory() as s:
                args = dict(chat_id=scope[0], order_id=order_id, operator_user_id=scope[1])
                if action == "fulfill":
                    result = await Mall.fulfill_order(s, **args, note="test-only delivery")
                else:
                    result = await Mall.cancel_order(s, **args)
                await s.commit()
                return result[0]
        results = await asyncio.gather(operate("fulfill"), operate("cancel"))
        assert sum(results) == 1
        async with db.session_factory() as s:
            order = await s.get(PointsMallOrder, order_id)
            balance = await s.scalar(select(PointsAccount.balance).where(PointsAccount.chat_id == scope[0], PointsAccount.user_id == scope[1]))
            product = await s.get(PointsMallProduct, scope[2])
            assert (balance, product.stock_left) == ((100, 2) if order.order_status == "canceled" else (80, 1))
    finally:
        await db.engine.dispose()


async def test_legacy_conflicts_require_selection_and_migration_is_idempotent():
    from backend.platform.state.edit_drafts import suspend_conflicting_legacy_inputs
    db = create_database(URL)
    try:
        chat, user, _ = await seed(db)
        from backend.shared.services.module_settings_service import ModuleSettingsService
        async with db.session_factory() as s:
            await ModuleSettingsService.ensure(s, user)
            s.add_all([ConversationState(chat_id=user, user_id=user, state_type="command_config_alias_input", state_data={"target_chat_id": chat}),
                       ConversationState(chat_id=chat, user_id=user, state_type="guess_wait_title", state_data={"target_chat_id": chat})])
            await s.commit()
        async with db.session_factory() as s:
            assert len(await suspend_conflicting_legacy_inputs(s, user)) == 2
            await s.commit()
        async with db.session_factory() as s:
            assert await suspend_conflicting_legacy_inputs(s, user) == []
            assert await s.scalar(select(func.count()).select_from(EditDraft).where(EditDraft.user_id == user)) == 2
    finally:
        await db.engine.dispose()


async def test_shared_message_body_cover_draft_restart_atomic_save_conflict():
    from backend.shared.button_layout_persistence import ensure_message_draft, discard_button_draft
    db = create_database(URL)
    try:
        chat, user, _ = await seed(db)
        ctx = SimpleNamespace(user_data={"button_editor_user_id": user})
        editor = ButtonEditorContext("invite", chat, 0)
        async with db.session_factory() as s:
            record = await ensure_message_draft(s, ctx, editor)
            original = dict(record.state_data["base_message"])
            record.state_data = {**record.state_data, "message": {"text": "新正文 {group}", "media": "test-photo", "media_type": "photo"}}
            await s.commit()
        await db.engine.dispose()
        async with db.session_factory() as s:
            settings = await get_chat_settings(s, chat)
            assert settings.invite_link_text_template == original["text"]
            assert not settings.invite_link_cover_file_id
            await save_button_draft(s, ctx, editor)
            await s.commit()
        async with db.session_factory() as s:
            settings = await get_chat_settings(s, chat)
            assert settings.invite_link_text_template == "新正文 {group}"
            assert settings.invite_link_cover_file_id == "test-photo"
            settings.invite_link_text_template = "另一管理员修改"
            await s.commit()
        async with db.session_factory() as s:
            with pytest.raises(ValidationError, match="正文或封面"):
                await save_button_draft(s, ctx, editor)
        async with db.session_factory() as s:
            await discard_button_draft(s, ctx, editor)
            await s.commit()
            assert (await get_chat_settings(s, chat)).invite_link_text_template == "另一管理员修改"
    finally:
        await db.engine.dispose()


async def test_archived_configuration_draft_detects_later_changes():
    from backend.platform.state.draft_versions import resumed_version_matches
    db = create_database(URL)
    try:
        chat, user, _ = await seed(db)
        async with db.session_factory() as s:
            settings = await get_chat_settings(s, chat)
            settings.sign_points = 5
            await ConversationStateService.start(s, user, user, state_type="command_config_alias_input",
                state_data={"target_chat_id": chat, "command_key": "sign"})
            drafts = await suspend_inputs(s, user)
            token = drafts[0].token
            await s.commit()
        async with db.session_factory() as s:
            assert await resumed_version_matches(s, await s.get(EditDraft, token))
            (await get_chat_settings(s, chat)).sign_points = 9
            await s.commit()
        async with db.session_factory() as s:
            assert not await resumed_version_matches(s, await s.get(EditDraft, token), lock=True)
            assert (await get_chat_settings(s, chat)).sign_points == 9
    finally:
        await db.engine.dispose()


async def test_two_notification_workers_claim_pending_once_after_restart():
    import asyncio
    db = create_database(URL)
    try:
        scope = await seed(db)
        _, _, order_id = await confirm(db, scope, await intent(db, scope))
        async with db.session_factory() as s:
            notification_id = await s.scalar(select(MallNotification.id).where(MallNotification.order_id == order_id, MallNotification.role == "buyer"))
        await db.engine.dispose()
        calls = []
        async def send_message(**kwargs):
            calls.append(kwargs)
            await asyncio.sleep(0.02)
            return SimpleNamespace(message_id=456)
        context = SimpleNamespace(bot=SimpleNamespace(send_message=send_message))
        await asyncio.gather(*(deliver_notification(db, context, notification_id) for _ in range(3)))
        assert len(calls) == 1
        async with db.session_factory() as s:
            assert (await s.get(MallNotification, notification_id)).status == "succeeded"
            assert (await s.get(PointsMallOrder, order_id)).order_status == "created"
    finally:
        await db.engine.dispose()


async def test_send_success_followed_by_commit_loss_retains_processing_and_never_replays(monkeypatch):
    db = create_database(URL)
    try:
        chat, user, _ = await seed(db)
        token = secrets.token_hex(12)
        calls = []
        async with db.session_factory() as s:
            async def create():
                return await create_event(s, chat, user, draft={"title": "commit loss", "options": [{"key": "a", "label": "A"}],
                    "deadline_at": (dt.datetime.now(dt.UTC)+dt.timedelta(hours=1)).isoformat()})
            record = await prepare_publication(s, token=token, domain="guess", chat_id=chat,
                creator_user_id=user, create_entity=create, render=lambda event: {"text": format_event_runtime(event)})
            original_commit = s.commit
            async def fail_commit():
                raise RuntimeError("simulated commit connection loss")
            async def send_message(**kwargs):
                calls.append(kwargs)
                monkeypatch.setattr(s, "commit", fail_commit)
                return SimpleNamespace(message_id=555)
            with pytest.raises(RuntimeError, match="commit connection"):
                await send_publication(s, SimpleNamespace(bot=SimpleNamespace(send_message=send_message)), record)
            monkeypatch.setattr(s, "commit", original_commit)
        await db.engine.dispose()
        from backend.platform.db.schema.models.activity_publications import ActivityPublication
        async with db.session_factory() as s:
            record = await s.get(ActivityPublication, token)
            assert record.status == "processing"
            await send_publication(s, SimpleNamespace(bot=SimpleNamespace(send_message=send_message)), record)
            assert (await s.get(GuessEvent, record.entity_id)).status == "publishing"
        assert len(calls) == 1
    finally:
        await db.engine.dispose()
