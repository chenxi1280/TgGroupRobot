"""Actual PTB Application -> registered admin router -> real services/Postgres.
Only Telegram HTTP transport is substituted; no handler or resolver is mocked.
"""
import json
import os
from types import SimpleNamespace

import pytest
from telegram import Update
from telegram.ext import Application
from telegram.request import BaseRequest

from backend.features.admin.admin_router import AdminRouter
from backend.features.admin.ui.admin_main_keyboards import ADMIN_CATEGORIES
from backend.features.group_ops.services.chat_group_service import set_user_current_chat
from backend.platform.db.runtime.session import create_database
from test_mall_intent_postgres import seed

URL = os.environ.get("TGR_REPAIR_TEST_DATABASE_URL")
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not URL, reason="disposable Postgres URL required")]


class TelegramBoundary(BaseRequest):
    def __init__(self):
        self.calls = []
    @property
    def read_timeout(self):
        return 5
    async def initialize(self):
        pass
    async def shutdown(self):
        pass
    async def do_request(self, url, method, request_data=None, **kwargs):
        endpoint = url.rsplit("/", 1)[-1]
        parameters = request_data.parameters if request_data else {}
        self.calls.append((endpoint, parameters))
        if endpoint == "getMe":
            result = {"id": 999000, "is_bot": True, "first_name": "test", "username": "test_bot"}
        elif endpoint == "getChatMember":
            result = {"status": "creator", "is_anonymous": False,
                "user": {"id": int(parameters["user_id"]), "is_bot": False, "first_name": "tester"}}
        elif endpoint == "getChat":
            result = {"id": int(parameters["chat_id"]), "type": "supergroup", "title": "isolated repair group"}
        elif endpoint in {"sendMessage", "editMessageText", "sendPhoto", "editMessageCaption"}:
            result = {"message_id": len(self.calls), "date": 1780000000,
                "chat": {"id": int(parameters.get("chat_id", 1)), "type": "private"},
                "text": parameters.get("text", "")}
        elif endpoint == "getChatMemberCount":
            result = 3
        elif endpoint == "getChatAdministrators":
            result = []
        else:
            result = True
        return 200, json.dumps({"ok": True, "result": result}).encode()


def command_update(app, user, chat, update_id, text):
    return Update.de_json({"update_id": update_id, "message": {
        "message_id": update_id, "date": 1780000000, "text": text,
        "entities": [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}],
        "from": {"id": user, "is_bot": False, "first_name": "tester"},
        "chat": {"id": chat, "type": "private" if chat > 0 else "supergroup", "title": "test"}}}, app.bot)


def callback_update(app, user, update_id, data):
    return Update.de_json({"update_id": update_id, "callback_query": {
        "id": str(update_id), "chat_instance": "test", "data": data,
        "from": {"id": user, "is_bot": False, "first_name": "tester"},
        "message": {"message_id": update_id, "date": 1780000000,
            "chat": {"id": user, "type": "private"}, "text": "menu"}}}, app.bot)


async def test_admin_commands_and_every_feature_menu_through_registered_router():
    db = create_database(URL)
    transport = TelegramBoundary()
    app = Application.builder().token("999000:TEST_TOKEN").request(transport).build()
    app.bot_data["db"] = db
    failures = []
    async def capture(update, context):
        failures.append((update.callback_query.data if update.callback_query else "command", repr(context.error)))
    app.add_error_handler(capture)
    AdminRouter().register(app)
    await app.initialize()
    try:
        chat, user, _ = await seed(db)
        await set_user_current_chat(db, user, chat)
        await app.process_update(command_update(app, user, user, 1, "/admin"))
        await app.process_update(command_update(app, user, chat, 2, "/admin"))
        feature_ids = [feature for _, entries in ADMIN_CATEGORIES.values() for _, feature in entries]
        for i, feature in enumerate(feature_ids, 100):
            await app.process_update(callback_update(app, user, i, f"adm:menu:{feature}:{chat}"))
        assert not failures, failures
        assert any("start=manage_" in str(params) for endpoint, params in transport.calls if endpoint == "sendMessage")
        assert len([1 for endpoint, _ in transport.calls if endpoint == "answerCallbackQuery"]) >= len(feature_ids)
    finally:
        await app.shutdown()
        await db.engine.dispose()


async def test_real_paginated_orders_eggs_teachers_and_whitelist_are_all_reachable():
    from backend.platform.db.schema.models.core import PointsMallOrder, TgUser
    from backend.platform.db.schema.models.expansion_engagement import EngagementEggEvent
    from backend.platform.db.schema.models.garage_features import GarageCertifiedTeacher, GarageSpeechWhitelist
    db = create_database(URL)
    transport = TelegramBoundary()
    app = Application.builder().token("999000:TEST_TOKEN").request(transport).build()
    app.bot_data["db"] = db
    failures = []
    async def capture(update, context):
        failures.append(repr(context.error))
    app.add_error_handler(capture)
    AdminRouter().register(app)
    await app.initialize()
    try:
        chat, user, product = await seed(db)
        await set_user_current_chat(db, user, chat)
        async with db.session_factory() as s:
            orders = [PointsMallOrder(chat_id=chat, product_id=product, buyer_user_id=user,
                price_points=20, quantity=1, order_status="created") for _ in range(25)]
            eggs = [EngagementEggEvent(chat_id=chat, title=f"验收彩蛋 {i}") for i in range(17)]
            people = [TgUser(id=user+100+i, username=f"qa{i}") for i in range(21)]
            s.add_all(orders + eggs + people)
            await s.flush()
            s.add_all([GarageCertifiedTeacher(chat_id=chat, user_id=p.id) for p in people])
            s.add_all([GarageSpeechWhitelist(chat_id=chat, user_id=p.id) for p in people])
            await s.commit()
            expected = [{o.order_id for o in orders}, {e.id for e in eggs}, {p.id for p in people}, {p.id for p in people}]
        cases = [
            (f"adm:mall:{chat}:orders_status:a:0:", f"adm:mall:{chat}:order:detail:", 5, 4, 25),
            (f"act:egg:{chat}:list:all:", f"act:egg:{chat}:detail:", 4, 3, 17),
            (f"grg:teacher:list:{chat}:", f"grg:teacher:detail:{chat}:", 4, 3, 21),
            (f"grg:wl:list:{chat}:", f"grg:wl:detail:{chat}:", 4, 3, 21),
        ]
        update_id = 500
        for case, wanted in zip(cases, expected, strict=True):
            request_prefix, detail_prefix, id_index, pages, total = case
            reached = set()
            for page in range(pages):
                transport.calls.clear()
                await app.process_update(callback_update(app, user, update_id, request_prefix+str(page)))
                update_id += 1
                rendered = [params for endpoint, params in transport.calls if endpoint in {"sendMessage", "editMessageText"}]
                assert rendered and not failures, failures
                content = rendered[-1]
                assert str(total) in content["text"] and str(page+1) in content["text"]
                markup = content["reply_markup"]
                if isinstance(markup, str):
                    markup = json.loads(markup)
                callbacks = [b.get("callback_data", "") for row in markup["inline_keyboard"] for b in row]
                ids = [int(data.split(":")[id_index]) for data in callbacks if data.startswith(detail_prefix)]
                assert 0 < len(ids) <= 8
                reached.update(ids)
                # The last detail carries the original page in its return callback.
                detail = next(data for data in callbacks if data.startswith(detail_prefix))
                transport.calls.clear()
                await app.process_update(callback_update(app, user, update_id, detail))
                update_id += 1
                assert not failures, failures
                detail_messages = [params for endpoint, params in transport.calls if endpoint in {"sendMessage", "editMessageText"}]
                detail_markup = detail_messages[-1]["reply_markup"]
                if isinstance(detail_markup, str):
                    detail_markup = json.loads(detail_markup)
                back_callbacks = [button.get("callback_data", "") for row in detail_markup["inline_keyboard"] for button in row]
                assert request_prefix+str(page) in back_callbacks
            assert reached == wanted
    finally:
        await app.shutdown()
        await db.engine.dispose()


class MemberBoundary(TelegramBoundary):
    async def do_request(self, url, method, request_data=None, **kwargs):
        if url.endswith("/getChatMember"):
            parameters = request_data.parameters
            self.calls.append(("getChatMember", parameters))
            return 200, json.dumps({"ok": True, "result": {"status": "member", "user": {
                "id": int(parameters["user_id"]), "is_bot": False, "first_name": "member"}}}).encode()
        return await super().do_request(url, method, request_data, **kwargs)


async def test_assigned_member_can_fulfill_but_forwarded_order_and_admin_write_are_denied():
    from backend.features.points.points_router import PointsRouter
    from backend.platform.db.schema.models.core import PointsMallProduct, PointsMallOrder, TgUser
    from test_mall_intent_postgres import intent, confirm
    db = create_database(URL)
    transport = MemberBoundary()
    app = Application.builder().token("999000:TEST_TOKEN").request(transport).build()
    app.bot_data["db"] = db
    failures = []
    async def capture(update, context):
        failures.append(repr(context.error))
    app.add_error_handler(capture)
    AdminRouter().register(app)
    PointsRouter().register(app)
    await app.initialize()
    try:
        scope = await seed(db)
        chat, buyer, product = scope
        assigned, outsider = buyer + 100, buyer + 101
        async with db.session_factory() as s:
            s.add_all([TgUser(id=assigned), TgUser(id=outsider)])
            (await s.get(PointsMallProduct, product)).fulfiller_user_id = assigned
            await s.commit()
        token = await intent(db, scope)
        order_id = (await confirm(db, scope, token))[2]
        await app.process_update(callback_update(app, outsider, 700, f"morder:detail:{chat}:{order_id}"))
        assert any("无权" in params.get("text", "") for _, params in transport.calls)
        transport.calls.clear()
        await app.process_update(command_update(app, assigned, assigned, 701, f"/assign {order_id} {outsider}"))
        assert any("没有管理权限" in params.get("text", "") for _, params in transport.calls)
        transport.calls.clear()
        await app.process_update(command_update(app, assigned, assigned, 702, f"/deliver {order_id} 验收说明"))
        messages = [params for endpoint, params in transport.calls if endpoint == "sendMessage"]
        assert messages and "确认人工标记" in messages[-1]["text"], failures
        markup = messages[-1]["reply_markup"]
        if isinstance(markup, str):
            markup = json.loads(markup)
        callback = markup["inline_keyboard"][0][0]["callback_data"]
        await app.process_update(callback_update(app, outsider, 703, callback))
        async with db.session_factory() as s:
            assert (await s.get(PointsMallOrder, order_id)).order_status == "created"
        await app.process_update(callback_update(app, assigned, 704, callback))
        async with db.session_factory() as s:
            order = await s.get(PointsMallOrder, order_id)
            assert order.order_status == "fulfilled" and order.operator_user_id == assigned
        assert not failures, failures
    finally:
        await app.shutdown()
        await db.engine.dispose()


async def test_manual_publication_recovery_after_deadline_keeps_original_deadline():
    import datetime as dt
    import secrets
    from backend.features.activity.services.activity_publication_service import prepare_publication
    from backend.features.activity.services.guess_service_runtime import create_event, format_event_runtime
    from backend.platform.db.schema.models.activity_publications import ActivityPublication
    from backend.platform.db.schema.models.expansion import GuessEvent
    db = create_database(URL)
    transport = TelegramBoundary()
    app = Application.builder().token("999000:TEST_TOKEN").request(transport).build()
    app.bot_data["db"] = db
    failures = []
    async def capture(update, context):
        failures.append(repr(context.error))
    app.add_error_handler(capture)
    AdminRouter().register(app)
    await app.initialize()
    try:
        chat, user, _ = await seed(db)
        token = secrets.token_hex(12)
        expired = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1)
        async with db.session_factory() as s:
            async def create():
                return await create_event(s, chat, user, draft={"title": "recovery", "options": [{"key": "a", "label": "A"}],
                    "deadline_at": (dt.datetime.now(dt.UTC)+dt.timedelta(hours=1)).isoformat()})
            record = await prepare_publication(s, token=token, domain="guess", chat_id=chat,
                creator_user_id=user, create_entity=create, render=lambda event: {"text": format_event_runtime(event)})
            text = record.payload["text"]
            record.status = "uncertain"
            (await s.get(GuessEvent, record.entity_id)).deadline_at = expired
            await s.commit()
        raw = command_update(app, user, chat, 800, f"/verifypublication {token}").to_dict()
        raw["message"]["reply_to_message"] = {"message_id": 765, "date": 1780000000,
            "chat": {"id": chat, "type": "supergroup"}, "text": text,
            "from": {"id": app.bot.id, "is_bot": True, "first_name": "test"}}
        await app.process_update(Update.de_json(raw, app.bot))
        assert not failures, failures
        async with db.session_factory() as s:
            record = await s.get(ActivityPublication, token)
            event = await s.get(GuessEvent, record.entity_id)
            assert record.status == "succeeded" and record.message_id == 765
            assert event.status == "pending" and event.deadline_at == expired
        assert any("截止时间保持不变" in p.get("text", "") for _, p in transport.calls)
    finally:
        await app.shutdown()
        await db.engine.dispose()


async def test_shared_editor_text_enters_draft_through_real_private_message_dispatch():
    from sqlalchemy import select
    from telegram.ext import MessageHandler, filters
    from backend.app.update_pipeline import MessageDispatcher
    from backend.platform.db.schema.models.core import ChatSettings, EditDraft
    from backend.platform.state.conversation_state_service import ConversationStateService
    db = create_database(URL)
    transport = TelegramBoundary()
    app = Application.builder().token("999000:TEST_TOKEN").request(transport).build()
    app.bot_data["db"] = db
    app.add_handler(MessageHandler(filters.TEXT, MessageDispatcher().dispatch))
    failures = []
    async def capture(update, context):
        failures.append(repr(context.error))
    app.add_error_handler(capture)
    await app.initialize()
    try:
        chat, user, _ = await seed(db)
        async with db.session_factory() as session:
            from backend.features.admin.support import get_chat_settings
            settings = await get_chat_settings(session, chat)
            original = settings.invite_link_text_template
            await ConversationStateService.start(session, user, user,
                state_type="button_editor_text_input", state_data={
                    "target_chat_id": chat, "module_type": "invite", "entity_id": 0,
                    "row_index": 0, "col_index": 0, "message_field": "body"})
            await session.commit()
        update = Update.de_json({"update_id": 8001, "message": {
            "message_id": 8001, "date": 1780000000, "text": "草稿正文 {group}",
            "from": {"id": user, "is_bot": False, "first_name": "tester"},
            "chat": {"id": user, "type": "private"}}}, app.bot)
        await app.process_update(update)
        async with db.session_factory() as session:
            drafts = list((await session.execute(select(EditDraft).where(
                EditDraft.user_id == user, EditDraft.state_type == "button_layout_draft"))).scalars())
            assert len(drafts) == 1
            assert drafts[0].state_data["message"]["text"] == "草稿正文 {group}"
            assert (await session.get(ChatSettings, chat)).invite_link_text_template == original
            assert (await ConversationStateService.get(session, user, user)).state_type == "selected_chat"
        assert not failures
        assert not any("配置处理失败" in str(params) for _, params in transport.calls)
    finally:
        await app.shutdown()
        await db.engine.dispose()


async def test_group_pipeline_reaches_auction_and_accepts_captionless_photo():
    from telegram.ext import MessageHandler, filters
    from backend.app.update_pipeline import MessageDispatcher
    from backend.features.activity.services.auction_service import get_or_create_setting
    from backend.platform.state.conversation_state_service import ConversationStateService
    db = create_database(URL)
    transport = TelegramBoundary()
    app = Application.builder().token("999000:TEST_TOKEN").request(transport).build()
    app.bot_data["db"] = db
    app.add_handler(MessageHandler(filters.ALL, MessageDispatcher().dispatch))
    errors = []
    async def capture(update, context):
        errors.append(repr(context.error))
    app.add_error_handler(capture)
    await app.initialize()
    try:
        chat, user, _ = await seed(db)
        async with db.session_factory() as session:
            setting = await get_or_create_setting(session, chat)
            setting.enabled = True
            await session.commit()
        base = {"date": 1780000000,
            "from": {"id": user, "is_bot": False, "first_name": "tester"},
            "chat": {"id": chat, "type": "supergroup", "title": "isolated repair group"}}
        for update_id, content in [(9001, {"text": "拍卖"}), (9002, {"photo": [
            {"file_id": "photo-fixture", "file_unique_id": "unique", "width": 480, "height": 240}]})]:
            await app.process_update(Update.de_json({"update_id": update_id,
                "message": {**base, "message_id": update_id, **content}}, app.bot))
        async with db.session_factory() as session:
            state = await ConversationStateService.get(session, chat, user)
            assert state is not None
            assert state.state_type == "auction_wait_title"
            assert state.state_data["cover_file_id"] == "photo-fixture"
            assert state.state_data["source_message_id"] == 9002
        assert not errors
        assert any("拍卖标题" in str(params) for _, params in transport.calls)
        assert not any("操作失败" in str(params) for _, params in transport.calls)
    finally:
        await app.shutdown()
        await db.engine.dispose()


@pytest.mark.parametrize(('state_type', 'value', 'field', 'expected'), [
    ('game_wait_rake_ratio', '0.15', 'rake_ratio', 0.15),
    ('game_wait_auto_start_time', '09:30', 'auto_start_time', '09:30'),
    ('garage_badge_input', '验收', 'garage_auth_badge', '验收'),
])
async def test_game_and_garage_configuration_through_real_private_dispatch(state_type, value, field, expected):
    from telegram.ext import MessageHandler, filters
    from sqlalchemy import select
    from backend.app.update_pipeline import MessageDispatcher
    from backend.platform.state.conversation_state_service import ConversationStateService
    from backend.platform.db.schema.models.core import ChatSettings
    from backend.platform.db.schema.models.expansion_games import GameSetting
    db = create_database(URL)
    transport = TelegramBoundary()
    app = Application.builder().token('999000:TEST_TOKEN').request(transport).build()
    app.bot_data['db'] = db
    app.add_handler(MessageHandler(filters.ALL, MessageDispatcher().dispatch))
    errors = []
    async def capture(update, context):
        errors.append(repr(context.error))
    app.add_error_handler(capture)
    await app.initialize()
    try:
        chat, user, _ = await seed(db)
        await set_user_current_chat(db, user, chat)
        async with db.session_factory() as session:
            await ConversationStateService.start(session, user, user, state_type=state_type,
                state_data={'target_chat_id': chat})
            await session.commit()
        raw = command_update(app, user, user, 9201, value).to_dict()
        raw['message'].pop('entities', None)
        await app.process_update(Update.de_json(raw, app.bot))
        async with db.session_factory() as session:
            model = GameSetting if state_type.startswith('game_') else ChatSettings
            setting = (await session.execute(select(model).where(model.chat_id == chat))).scalar_one()
            actual = getattr(setting, field)
            assert float(actual) == expected if isinstance(expected, float) else actual == expected
            state = await ConversationStateService.get(session, user, user)
            assert state is None or state.state_type == 'selected_chat'
        assert not errors, errors
        assert not any('配置处理失败' in str(p) for _, p in transport.calls)
    finally:
        await app.shutdown()
        await db.engine.dispose()


async def test_all_categories_and_join_guards_through_application():
    from telegram.ext import MessageHandler, filters
    from backend.features.verification.verification_handler import new_members_handler
    from backend.features.admin.support import get_chat_settings
    db = create_database(URL)
    transport = TelegramBoundary()
    app = Application.builder().token('999000:TEST_TOKEN').request(transport).build()
    app.bot_data['db'] = db
    AdminRouter().register(app)
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_members_handler))
    errors = []
    async def capture(update, context):
        errors.append(repr(context.error))
    app.add_error_handler(capture)
    await app.initialize()
    try:
        chat, user, _ = await seed(db)
        await set_user_current_chat(db, user, chat)
        for i, category in enumerate(ADMIN_CATEGORIES, 9300):
            await app.process_update(callback_update(app, user, i, f'adm:menu:category_{category}:{chat}'))
            keyboard = transport.calls[-1][1].get('reply_markup')
            assert '返回管理首页' in str(keyboard)
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat)
            settings.verification_enabled = False
            settings.join_self_review_enabled = False
            settings.welcome_enabled = False
            await session.commit()
        raw = command_update(app, user, chat, 9400, 'join').to_dict()
        raw['message'].pop('text')
        raw['message'].pop('entities', None)
        raw['message']['new_chat_members'] = [{'id': user, 'is_bot': False, 'first_name': 'tester'}]
        await app.process_update(Update.de_json(raw, app.bot))
        assert not errors, errors
    finally:
        await app.shutdown()
        await db.engine.dispose()


async def test_shared_state_helper_persists_with_real_service():
    from backend.shared.handlers.base.state_helper import StateHelper
    db = create_database(URL)
    try:
        chat, user, _ = await seed(db)
        async with db.session_factory() as session:
            helper = StateHelper(session, chat, user)
            await helper.set_state('game_wait_rake_ratio', {'target_chat_id': chat})
            await session.commit()
        async with db.session_factory() as session:
            state = await StateHelper(session, chat, user).get_state()
            assert state.state_type == 'game_wait_rake_ratio'
            assert state.state_data['target_chat_id'] == chat
    finally:
        await db.engine.dispose()
