"""Navigation and control regressions through PTB routing and disposable Postgres."""
import os
from collections import Counter

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, MessageHandler, filters

from backend.app.update_pipeline import MessageDispatcher
from backend.features.admin.admin_router import AdminRouter
from backend.features.admin.feature_registry import FEATURE_REGISTRATIONS
from backend.features.moderation.garbage_guard_config_handler import garbage_guard_config_callback
from backend.features.moderation.services.garbage_guard_rules import RULE_ORDER, get_rule_config
from backend.features.admin.ui.antispam import garbage_guard_rule_keyboard
from backend.features.points.points_router import PointsRouter
from backend.platform.db.runtime.session import create_database
from backend.platform.db.schema.models.core import ChatSettings, VerificationChallenge
from backend.platform.runtime.chat_shard import install_chat_sharded_processing
from test_admin_routes_postgres import TelegramBoundary, callback_update, command_update
from test_mall_intent_postgres import seed

URL = os.environ.get("TGR_REPAIR_TEST_DATABASE_URL")
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not URL, reason="disposable Postgres URL required")]


@pytest_asyncio.fixture
async def runtime():
    db = create_database(URL)
    transport = TelegramBoundary()
    app = Application.builder().token("999000:TEST_TOKEN").request(transport).build()
    app.bot_data["db"] = db
    AdminRouter().register(app)
    PointsRouter().register(app)
    app.add_handler(CallbackQueryHandler(garbage_guard_config_callback, pattern=r"^gg:"))
    app.add_handler(MessageHandler(filters.ALL, MessageDispatcher().dispatch))
    errors = []

    async def capture(update, context):
        errors.append(repr(context.error))

    app.add_error_handler(capture)
    install_chat_sharded_processing(app)
    await app.initialize()
    try:
        chat, user, _ = await seed(db)
        yield app, db, transport, errors, chat, user
        assert not errors, errors
    finally:
        await app.shutdown()
        await db.engine.dispose()


def displayed_buttons(transport):
    displays = [params for endpoint, params in transport.calls if endpoint in {"sendMessage", "editMessageText"}]
    assert displays, transport.calls
    return [button for row in displays[-1]["reply_markup"]["inline_keyboard"] for button in row]


async def test_every_feature_returns_to_its_category_and_has_unique_actions(runtime):
    app, db, transport, _, chat, user = runtime
    for i, feature in enumerate(FEATURE_REGISTRATIONS.values(), 100):
        transport.calls.clear()
        await app.process_update(callback_update(app, user, i, f"adm:menu:{feature.feature_id}:{chat}"))
        buttons = displayed_buttons(transport)
        assert any(button["callback_data"] == f"adm:menu:category_{feature.category}:{chat}"
                   for button in buttons if "返回" in button["text"]), feature.feature_id
        # Repeated labels may refresh the same page, but editing or writing actions must be unique.
        callbacks = [b["callback_data"] for b in buttons if b.get("callback_data")]
        duplicates = {cb for cb, count in Counter(callbacks).items() if count > 1}
        assert all(":home:" in cb or ":noop" in cb or cb.startswith("adm:menu:") for cb in duplicates), feature.feature_id
        assert all(len(cb.encode()) <= 64 for cb in callbacks), feature.feature_id
        if feature.feature_id == "newmem":
            assert all(len(row) <= 3 for row in [params for endpoint, params in transport.calls if endpoint in {"sendMessage", "editMessageText"}][-1]["reply_markup"]["inline_keyboard"])
        async with db.session_factory() as session:
            settings = await session.get(ChatSettings, chat)
            for rule in RULE_ORDER:
                rows = garbage_guard_rule_keyboard(settings, chat, rule).inline_keyboard
                actions = [b.callback_data for row in rows for b in row if b.callback_data and not b.callback_data.startswith("gg:rule:")]
                assert len(actions) == len(set(actions)), rule
                assert not any(":toggle:" in cb or ":noop:" in cb for cb in actions)
                assert all(len(cb.encode()) <= 64 for cb in actions)


@pytest.mark.parametrize(("prefix", "field"), [("nml", "new_member_limit_enabled"),
    ("night", "night_mode_enabled"), ("fs", "force_subscribe_enabled"), ("gg", "enabled")])
async def test_explicit_targets_labels_and_legacy_toggles_do_not_reverse_state(runtime, prefix, field):
    app, db, _, _, chat, user = runtime
    def callback(op, value=""):
        if prefix == "gg":
            return f"gg:{op}:block_links:enabled:{chat}" + (f":{value}" if value else "")
        return f"adm:{prefix}:{chat}:{op}:enabled" + (f":{value}" if value else "")
    async def value():
        async with db.session_factory() as session:
            settings = await session.get(ChatSettings, chat)
            return get_rule_config(settings, "block_links")["enabled"] if prefix == "gg" else getattr(settings, field)
    for i, target in enumerate(["1", "1", "0", "0"], 200):
        await app.process_update(callback_update(app, user, i, callback("set", target)))
        assert await value() is (target == "1")
    await app.process_update(callback_update(app, user, 210, callback("toggle")))
    assert await value() is False
    label = f"gg:rule:block_links:{chat}" if prefix == "gg" else f"adm:menu:{dict(nml='newmem',night='night',fs='forcesub')[prefix]}:{chat}"
    await app.process_update(callback_update(app, user, 211, label))
    assert await value() is False
    await app.process_update(callback_update(app, user, 212, callback("set", "invalid")))
    assert await value() is False


@pytest.mark.parametrize(("entry", "exit_to", "field"), [
    ("gg:input:whitelist:{chat}", "gg:whitelist:{chat}", "anti_spam_rules"),
    ("gg:input:quick_reply_actions:mute_keyword:{chat}", "gg:rule:quick_reply_actions:{chat}", "anti_spam_rules"),
    ("pts:edit:points_alias:{chat}", "pts:rule:checkin:{chat}", "points_alias"),
    ("pts:edit:points_alias:{chat}", "pts:view:display_rules:{chat}", "points_alias"),
    ("pts:edit:points_alias:{chat}", "pts:home:{chat}", "points_alias"),
])
async def test_return_from_input_stops_plain_messages_from_changing_configuration(runtime, entry, exit_to, field):
    app, db, transport, _, chat, user = runtime
    await app.process_update(callback_update(app, user, 300, f"adm:menu:points:{chat}"))
    async with db.session_factory() as session:
        before = getattr(await session.get(ChatSettings, chat), field)
    await app.process_update(callback_update(app, user, 301, entry.format(chat=chat)))
    assert any("返回" in b["text"] for b in displayed_buttons(transport))
    if entry.startswith("pts:"):
        assert app.user_data[user]["points_edit_field"] == field
    if exit_to == "pts:home:{chat}":
        assert [b["callback_data"] for b in displayed_buttons(transport) if "返回" in b["text"]] == [exit_to.format(chat=chat)]
    transport.calls.clear()
    await app.process_update(callback_update(app, user, 302, exit_to.format(chat=chat)))
    assert displayed_buttons(transport)
    if exit_to == "pts:home:{chat}":
        assert any(b["callback_data"] == f"pts:edit:points_alias:{chat}" for b in displayed_buttons(transport))
    if entry.startswith("pts:"):
        assert "points_edit_field" not in app.user_data[user]
    raw = command_update(app, user, user, 303, "退出后普通文本").to_dict()
    raw["message"].pop("entities", None)
    await app.process_update(Update.de_json(raw, app.bot))
    async with db.session_factory() as session:
        assert getattr(await session.get(ChatSettings, chat), field) == before


async def test_old_group_menu_and_toggle_open_current_navigation(runtime):
    app, _, transport, _, chat, user = runtime
    for i, data in enumerate(["adm:menu:main", "adm:menu:settings", "adm:toggle:sign_enabled"], 400):
        raw = callback_update(app, user, i, data).to_dict()
        raw["callback_query"]["message"]["chat"] = {"id": chat, "type": "supergroup", "title": "test"}
        transport.calls.clear()
        await app.process_update(Update.de_json(raw, app.bot))
        buttons = displayed_buttons(transport)
        assert not any(b.get("callback_data", "").startswith("adm:toggle:") for b in buttons)
        assert all(str(chat) in b.get("callback_data", "") for b in buttons if b.get("callback_data", "").startswith("adm:menu:"))
        if data == "adm:menu:main":
            assert len([b for b in buttons if b.get("callback_data", "").startswith("adm:menu:category_")]) == 6
        if data == "adm:toggle:sign_enabled":
            assert any(b.get("callback_data", "").startswith("pts:toggle:") for b in buttons)


async def test_own_bot_join_records_membership_without_verifying_or_restricting_itself(runtime):
    from types import SimpleNamespace
    from backend.features.verification.verification_handler import new_members_handler
    app, db, transport, _, chat, user = runtime
    raw = command_update(app, user, chat, 900, "/admin").to_dict()
    raw["message"].pop("text")
    raw["message"].pop("entities")
    raw["message"]["new_chat_members"] = [dict(app.bot.to_dict(), is_bot=True)]
    transport.calls.clear()
    await new_members_handler(Update.de_json(raw, app.bot), SimpleNamespace(application=app, bot=app.bot, user_data={}))
    async with db.session_factory() as session:
        assert (await session.execute(select(func.count()).select_from(VerificationChallenge).where(
            VerificationChallenge.chat_id == chat))).scalar() == 0
    assert not any(endpoint in {"restrictChatMember", "banChatMember", "sendMessage"} for endpoint, _ in transport.calls)


async def test_short_points_home_returns_without_an_active_conversation(runtime):
    app, _, transport, _, chat, user = runtime
    await app.process_update(callback_update(app, user, 950, f"pts:rule:checkin:{chat}"))
    transport.calls.clear()
    await app.process_update(callback_update(app, user, 951, f"pts:home:{chat}"))
    assert any(b["callback_data"] == f"pts:edit:points_alias:{chat}" for b in displayed_buttons(transport))
