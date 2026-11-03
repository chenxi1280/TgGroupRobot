"""HTTP, PostgreSQL and Telegram action boundaries of member verification."""
import asyncio
import datetime as dt
import os
import secrets
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from telegram import User
from telegram.error import NetworkError

from backend.app.web import create_web_app
from backend.features.verification import mini_app_actions
from backend.features.verification.verification_handler import _send_mini_app_prompt
from backend.features.verification.verification_service import create_or_replace_challenge, get_challenge
from backend.platform.config.core.settings import Settings
from backend.platform.db.runtime.session import create_database
from backend.platform.db.runtime.schema_gate import validate_database_schema
from backend.platform.db.schema.models.core import TgChat, TgUser, VerificationChallenge
from backend.shared.services.chat_service import get_chat_settings
from test_mini_app_auth import signed_data, TOKEN

URL = os.environ.get("TGR_REPAIR_TEST_DATABASE_URL")
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not URL, reason="Shanghai isolated test DB required")]


class Bot:
    username = "test_mini_app_bot"

    def __init__(self):
        self.restrict_chat_member = AsyncMock(return_value=True)
        self.get_chat_member = AsyncMock(return_value=SimpleNamespace(status="member"))
        self.send_message = AsyncMock(return_value=SimpleNamespace(message_id=42))


@pytest_asyncio.fixture
async def scope(monkeypatch):
    db = create_database(URL)
    identity = secrets.randbelow(1_000_000_000) + 2_000_000_000
    chat, user = -identity, identity
    bot = Bot()
    settings = Settings(_env_file=None, BOT_TOKEN=TOKEN, MINI_APP_ENABLED=True, ADMIN_WEB_ENABLED=False)
    telegram_app = SimpleNamespace(bot=bot, bot_data={"db": db, "settings": settings})
    welcome = AsyncMock()
    monkeypatch.setattr(mini_app_actions, "send_after_verify_welcome", welcome)
    async with db.session_factory() as session:
        session.add_all([TgChat(id=chat, type="supergroup", title="隔离验证群"), TgUser(id=user)])
        await session.flush()
        config = await get_chat_settings(session, chat)
        config.verification_enabled = True
        config.verification_mode = "button"
        config.verification_wrong_action = "none"
        config.join_self_review_enabled = False
        await session.commit()
    app = create_web_app(telegram_app, settings)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        value = SimpleNamespace(db=db, chat=chat, user=user, bot=bot, client=client,
                                telegram_app=telegram_app, welcome=welcome)
        yield value
    await db.engine.dispose()


def headers(user, token):
    return {"Authorization": "tma " + signed_data(user_id=user, issued_at=int(time.time())), "X-Verification-Token": token}


async def make_challenge(scope, mode="button", *, ttl=180):
    async with scope.db.session_factory() as session:
        challenge = await create_or_replace_challenge(
            session, scope.chat, scope.user, ttl_seconds=ttl, verification_type=mode,
        )
        challenge.mini_app_status = "pending"
        token, answer = challenge.token, challenge.answer
        await session.commit()
    return token, answer


async def submit(scope, token, *, action="agree", answer=""):
    return await scope.client.post("/miniapp/api/verification",
        headers=headers(scope.user, token), json={"action": action, "answer": answer})


async def test_schema_and_admin_disabled_member_app_are_independent(scope):
    await validate_database_schema(scope.db.engine)
    assert (await scope.client.get("/admin/")).status_code == 404
    token, _ = await make_challenge(scope)
    detail = await scope.client.get("/miniapp/api/verification", headers=headers(scope.user, token))
    assert detail.status_code == 200
    assert detail.json()["chat_title"] == "隔离验证群"
    async with scope.db.session_factory() as s:
        assert not (await get_challenge(s, scope.chat, scope.user)).solved


@pytest.mark.parametrize("mode", ["button", "math", "captcha"])
async def test_all_basic_modes_solve_without_exposing_answer_field(scope, mode):
    token, answer = await make_challenge(scope, mode)
    detail = await scope.client.get("/miniapp/api/verification", headers=headers(scope.user, token))
    assert "answer" not in detail.json()
    response = await submit(scope, token, action="agree" if mode == "button" else "answer", answer=answer or "")
    assert response.status_code == 200 and response.json()["status"] == "verified"
    assert scope.bot.restrict_chat_member.await_count == 1
    assert scope.welcome.await_count == 1
    assert scope.bot.restrict_chat_member.call_args.kwargs["chat_id"] == scope.chat
    again = await submit(scope, token, action="agree" if mode == "button" else "answer", answer=answer or "")
    assert again.json()["status"] == "verified" and scope.welcome.await_count == 1


async def test_wrong_user_and_replaced_token_do_not_change_challenge(scope):
    token, _ = await make_challenge(scope)
    response = await scope.client.post("/miniapp/api/verification", headers=headers(scope.user + 1, token), json={"action": "agree"})
    assert response.status_code == 403
    await make_challenge(scope)
    assert (await submit(scope, token)).status_code == 410
    assert scope.bot.restrict_chat_member.await_count == 0


async def test_wrong_answer_retry_expiry_and_timeout_claim_cannot_unmute(scope):
    token, _ = await make_challenge(scope, "math")
    assert (await submit(scope, token, action="answer", answer="incorrect")).status_code == 422
    async with scope.db.session_factory() as s:
        challenge = await get_challenge(s, scope.chat, scope.user)
        assert not challenge.solved
        challenge.expires_at = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1)
        await s.commit()
    assert (await submit(scope, token)).json()["status"] == "expired"
    token, _ = await make_challenge(scope)
    async with scope.db.session_factory() as s:
        challenge = await get_challenge(s, scope.chat, scope.user)
        challenge.timeout_status = "processing"
        await s.commit()
    assert (await submit(scope, token)).json()["status"] == "expired"
    assert scope.bot.restrict_chat_member.await_count == 0


async def test_concurrent_submissions_apply_one_action_and_one_welcome(scope):
    token, _ = await make_challenge(scope)
    responses = await asyncio.gather(*(submit(scope, token) for _ in range(3)))
    assert all(r.status_code == 200 for r in responses)
    assert {r.json()["status"] for r in responses} <= {"processing", "verified"}
    assert scope.bot.restrict_chat_member.await_count == 1
    assert scope.welcome.await_count == 1


@pytest.mark.parametrize("unknown", [False, True])
async def test_unmute_failure_never_reports_success_or_replays(scope, monkeypatch, unknown):
    token, _ = await make_challenge(scope)
    if unknown:
        monkeypatch.setattr(mini_app_actions, "unrestrict_and_notify", AsyncMock(side_effect=NetworkError("test network outcome")))
    else:
        scope.bot.get_chat_member.return_value = SimpleNamespace(status="restricted", is_member=True, can_send_messages=False)
    response = await submit(scope, token)
    assert response.json()["status"] == ("uncertain" if unknown else "failed")
    count = scope.bot.restrict_chat_member.await_count
    again = await submit(scope, token)
    assert again.json()["status"] == response.json()["status"]
    assert scope.bot.restrict_chat_member.await_count == count
    assert scope.welcome.await_count == 0


async def test_enabled_self_review_stays_in_original_group_flow(scope):
    async with scope.db.session_factory() as s:
        settings = await get_chat_settings(s, scope.chat)
        settings.join_self_review_enabled = True
        await s.commit()
    token, _ = await make_challenge(scope)
    response = await submit(scope, token)
    assert response.json()["status"] == "review"
    assert scope.bot.restrict_chat_member.await_count == 0
    assert scope.welcome.await_count == 0
    async with scope.db.session_factory() as s:
        challenge = await get_challenge(s, scope.chat, scope.user)
        assert challenge.question.startswith("[SELF_REVIEW]") and not challenge.solved
        assert challenge.mini_app_status is None
    assert (await submit(scope, token)).status_code == 410
    assert scope.bot.send_message.await_count == 1


async def test_decline_and_wrong_answer_apply_configured_policy_once(scope, monkeypatch):
    punish = AsyncMock()
    monkeypatch.setattr(mini_app_actions, "apply_verification_punishment", punish)
    token, _ = await make_challenge(scope)
    assert (await submit(scope, token, action="decline")).json()["status"] == "punished"
    await submit(scope, token, action="decline")
    assert punish.await_count == 1
    async with scope.db.session_factory() as s:
        settings = await get_chat_settings(s, scope.chat)
        settings.verification_wrong_action = "kick"
        await s.commit()
    token, _ = await make_challenge(scope, "captcha")
    assert (await submit(scope, token, action="answer", answer="wrong")).json()["status"] == "punished"
    assert punish.call_args.kwargs["action"] == "kick"


async def test_group_prompt_links_to_real_bot_and_exact_challenge(scope):
    token, _ = await make_challenge(scope)
    async with scope.db.session_factory() as s:
        challenge = await s.scalar(select(VerificationChallenge).where(VerificationChallenge.token == token))
        settings = await get_chat_settings(s, scope.chat)
        await _send_mini_app_prompt(SimpleNamespace(bot=scope.bot), SimpleNamespace(id=scope.chat),
            User(scope.user, "测试成员", False), settings=settings, challenge=challenge)
    markup = scope.bot.send_message.call_args.kwargs["reply_markup"]
    assert markup.inline_keyboard[0][0].url == f"https://t.me/test_mini_app_bot?startapp=verify_{token}"


async def test_upgrade_accepts_existing_bootstrap_column(scope, monkeypatch):
    from backend.platform.db.runtime.database_migrations import load_revision_modules
    from sqlalchemy import text
    revision = load_revision_modules()[-1]
    class Operations:
        def __init__(self, connection):
            self.connection = connection
        def execute(self, statement):
            self.connection.execute(text(statement))
    def upgrade(connection):
        monkeypatch.setattr(revision, 'op', Operations(connection))
        revision.upgrade()
        revision.upgrade()
    async with scope.db.engine.begin() as connection:
        await connection.run_sync(upgrade)
    await validate_database_schema(scope.db.engine)
