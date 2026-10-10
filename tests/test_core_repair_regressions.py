from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.error import BadRequest


@pytest.mark.asyncio
async def test_ad_history_identical_refresh_does_not_report_error():
    from backend.features.automation.ads_operations import _edit
    from telegram import InlineKeyboardMarkup
    query = SimpleNamespace(id='history-repeat', answer=AsyncMock(),
        edit_message_text=AsyncMock(side_effect=BadRequest('Message is not modified')))
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(callback_query=query, effective_message=message)
    await _edit(update, 'history', InlineKeyboardMarkup([]))
    query.answer.assert_awaited_once()
    query.edit_message_text.assert_awaited_once()
    message.reply_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_prompt_fail_open_reaches_real_unrestrict_and_notify(monkeypatch):
    from backend.features.verification import verification_handler as handler
    from backend.features.verification import verification_runtime as runtime
    audit = AsyncMock()
    monkeypatch.setattr(handler, '_audit_prompt_failure', audit)
    monkeypatch.setattr(handler, '_notify_prompt_failure', AsyncMock())
    restrict = AsyncMock()
    monkeypatch.setattr(runtime, 'restrict_user_safely', restrict)
    session = SimpleNamespace(commit=AsyncMock())
    context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()), job_queue=None)
    challenge = SimpleNamespace(solved=False, timeout_handled=False)
    member = SimpleNamespace(id=42, mention_html=lambda: 'tester')
    await handler._release_after_prompt_failure(context, session, SimpleNamespace(id=-1001),
        member=member, settings=SimpleNamespace(language='zh-CN'), challenge=challenge)
    assert challenge.solved and challenge.timeout_handled
    session.commit.assert_awaited_once()
    restrict.assert_awaited_once()
    assert restrict.await_args.kwargs['user_id'] == 42
    assert restrict.await_args.kwargs['permissions'].can_send_messages is True
