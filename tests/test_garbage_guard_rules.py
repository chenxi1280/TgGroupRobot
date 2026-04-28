from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from backend.features.admin.ui.antispam import format_garbage_rule_text
from backend.features.moderation.services.garbage_guard_rules import (
    get_rule_config,
    is_global_whitelisted,
    set_global_whitelist_user_ids,
    set_rule_config,
)
from backend.features.moderation.services import garbage_guard_service
from backend.features.moderation.services.garbage_guard_service import apply_garbage_punishment, detect_garbage_violation
from backend.features.moderation.services.moderation_warning_service import WarningResult


def _settings():
    return SimpleNamespace(
        anti_spam_rules={},
        anti_flood_enabled=False,
        anti_flood_messages=5,
        anti_flood_seconds=5,
        anti_flood_mute_duration=3600,
        anti_flood_cleanup_messages=False,
    )


def _message(text: str = "hello", **kwargs):
    user = kwargs.pop(
        "from_user",
        SimpleNamespace(id=123, username="alice", first_name="小明", last_name=None),
    )
    return SimpleNamespace(
        message_id=42,
        text=text,
        caption=None,
        from_user=user,
        reply_markup=kwargs.pop("reply_markup", None),
        forward_origin=kwargs.pop("forward_origin", None),
        forward_from_chat=kwargs.pop("forward_from_chat", None),
        forward_from=kwargs.pop("forward_from", None),
        forward_date=kwargs.pop("forward_date", None),
        sender_chat=None,
    )


def test_rule_config_updates_preserve_global_whitelist() -> None:
    settings = _settings()

    set_global_whitelist_user_ids(settings, [2, 1, 2])
    set_rule_config(settings, "block_links", {"enabled": True})

    assert is_global_whitelisted(settings, 1) is True
    assert is_global_whitelisted(settings, 3) is False
    assert get_rule_config(settings, "block_links")["enabled"] is True
    assert settings.anti_spam_rules["exception_user_ids"] == [1, 2]


def test_detects_link_button_forward_and_spam_user_rules() -> None:
    settings = _settings()

    set_rule_config(settings, "block_links", {"enabled": True})
    violation = detect_garbage_violation(settings, _message("visit https://example.com"))
    assert violation is not None
    assert violation.rule_id == "block_links"

    set_rule_config(settings, "block_links", {"enabled": False})
    set_rule_config(settings, "block_buttons", {"enabled": True})
    violation = detect_garbage_violation(settings, _message(reply_markup=SimpleNamespace(inline_keyboard=[[object()]])))
    assert violation is not None
    assert violation.rule_id == "block_buttons"

    set_rule_config(settings, "block_buttons", {"enabled": False})
    set_rule_config(settings, "block_forwards", {"enabled": True})
    violation = detect_garbage_violation(settings, _message(forward_origin=SimpleNamespace()))
    assert violation is not None
    assert violation.rule_id == "block_forwards"

    set_rule_config(settings, "block_forwards", {"enabled": False})
    set_rule_config(settings, "spam_user", {"enabled": True, "check_no_username": True, "check_foreign_name": True})
    violation = detect_garbage_violation(
        settings,
        _message(from_user=SimpleNamespace(id=123, username=None, first_name="Alice", last_name=None)),
    )
    assert violation is not None
    assert violation.rule_id == "spam_user"


def test_long_message_and_long_name_are_independent_rules() -> None:
    settings = _settings()
    set_rule_config(settings, "long_message", {"enabled": True, "message_max_length": 20})
    set_rule_config(settings, "long_name", {"enabled": False, "name_max_length": 2})

    violation = detect_garbage_violation(settings, _message("1" * 21))
    assert violation is not None
    assert violation.rule_id == "long_message"
    assert violation.detail == "消息长度 21 字，超过 20 字限制"

    set_rule_config(settings, "long_message", {"enabled": False})
    violation = detect_garbage_violation(
        settings,
        _message("hi", from_user=SimpleNamespace(id=123, username="alice", first_name="很长很长的昵称", last_name=None)),
    )
    assert violation is None

    set_rule_config(settings, "long_name", {"enabled": True})
    violation = detect_garbage_violation(
        settings,
        _message("hi", from_user=SimpleNamespace(id=123, username="alice", first_name="很长很长的昵称", last_name=None)),
    )
    assert violation is not None
    assert violation.rule_id == "long_name"


def test_garbage_rule_text_shows_delete_only_effect_and_runtime_scope() -> None:
    settings = _settings()
    set_rule_config(settings, "banned_words", {"enabled": True, "delete_message": True, "notice_enabled": False})

    text = format_garbage_rule_text("锅巴 群", settings, "banned_words", banned_word_count=2)

    assert "实际触发条件: 包含/模糊匹配，命中词库后触发（当前 2 个词）" in text
    assert "当前效果: 只删除消息，不会警告/禁言/提示。" in text
    assert "警告成员: 关闭" in text
    assert "禁言成员: 关闭" in text
    assert "提示消息: 关闭" in text
    assert "生效对象: 普通成员；管理员和总白名单用户不会触发。" in text


def test_enabled_message_rules_default_to_delete_and_notice() -> None:
    settings = _settings()
    for rule_id in [
        "banned_words",
        "long_message",
        "long_name",
        "block_links",
        "block_buttons",
        "spam_user",
        "block_forwards",
        "flood",
    ]:
        set_rule_config(settings, rule_id, {"enabled": True})
        rule = get_rule_config(settings, rule_id)
        assert rule["delete_message"] is True, rule_id
        assert rule["notice_enabled"] is True, rule_id


def test_enabled_manual_warning_defaults_to_notice_but_not_delete_command() -> None:
    settings = _settings()
    set_rule_config(settings, "manual_warning", {"enabled": True})

    rule = get_rule_config(settings, "manual_warning")

    assert rule["warn_enabled"] is True
    assert rule["delete_message"] is False
    assert rule["notice_enabled"] is True


def test_enabled_leave_ban_does_not_default_to_notice() -> None:
    settings = _settings()
    set_rule_config(settings, "leave_ban", {"enabled": True})

    rule = get_rule_config(settings, "leave_ban")

    assert rule["delete_message"] is True
    assert rule["notice_enabled"] is False


def test_garbage_rule_text_shows_full_punishment_combo() -> None:
    settings = _settings()
    set_rule_config(
        settings,
        "banned_words",
        {
            "enabled": True,
            "delete_message": True,
            "warn_enabled": True,
            "warn_threshold": 1,
            "mute_enabled": True,
            "mute_seconds": 600,
            "notice_enabled": True,
            "notice_delete_seconds": 10,
        },
    )

    text = format_garbage_rule_text("锅巴 群", settings, "banned_words")

    assert "当前效果: 删除消息 + 警告成员 + 禁言成员 + 提示消息。" in text
    assert "警告成员: 启动，警告1次" in text
    assert "禁言成员: 启动，10分钟" in text
    assert "提示消息: 启动，10秒后删除" in text


def test_garbage_rule_text_shows_long_content_and_flood_conditions() -> None:
    settings = _settings()
    set_rule_config(settings, "long_message", {"enabled": True, "message_max_length": 100})
    set_rule_config(settings, "flood", {"enabled": True, "messages": 5, "seconds": 5})

    long_rule = get_rule_config(settings, "long_message")
    long_text = format_garbage_rule_text("锅巴 群", settings, "long_message")
    flood_text = format_garbage_rule_text("锅巴 群", settings, "flood")

    assert long_rule["delete_message"] is True
    assert long_rule["notice_enabled"] is True
    assert "实际触发条件: 超过 100 字触发" in long_text
    assert "当前效果: 删除消息 + 提示消息。" in long_text
    assert "实际触发条件: 5 秒内达到 5 条触发" in flood_text


def test_long_message_notice_can_still_be_disabled_explicitly() -> None:
    settings = _settings()
    set_rule_config(settings, "long_message", {"enabled": True, "message_max_length": 100})
    set_rule_config(settings, "long_message", {"notice_enabled": False})

    rule = get_rule_config(settings, "long_message")

    assert rule["enabled"] is True
    assert rule["delete_message"] is True
    assert rule["notice_enabled"] is False
    assert rule["notice_configured"] is True


def test_long_message_delete_can_still_be_disabled_explicitly() -> None:
    settings = _settings()
    set_rule_config(settings, "long_message", {"enabled": True, "message_max_length": 100})
    set_rule_config(settings, "long_message", {"delete_message": False, "mute_enabled": True})

    rule = get_rule_config(settings, "long_message")

    assert rule["enabled"] is True
    assert rule["delete_message"] is False
    assert rule["delete_configured"] is True
    assert rule["notice_enabled"] is True


@pytest.mark.asyncio
async def test_banned_word_full_punishment_deletes_warns_mutes_and_notices(monkeypatch) -> None:
    settings = _settings()
    set_rule_config(
        settings,
        "banned_words",
        {
            "enabled": True,
            "delete_message": True,
            "warn_enabled": True,
            "warn_threshold": 1,
            "mute_enabled": True,
            "mute_seconds": 600,
            "notice_enabled": True,
            "notice_delete_seconds": 10,
        },
    )
    calls: list[tuple[str, object]] = []

    async def fake_delete_many(context, *, chat_id: int, message_ids: list[int]):
        calls.append(("delete_many", (chat_id, message_ids)))
        return SimpleNamespace(applied=True)

    async def fake_add_warning(session, *, chat_id: int, user_id: int, rule: str, threshold: int):
        calls.append(("add_warning", (chat_id, user_id, rule, threshold)))
        return WarningResult(
            count=1,
            threshold=threshold,
            threshold_reached=True,
            expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(days=7),
        )

    async def fake_resolve_effective_action(context, chat_id: int, user_id: int, action: str, **kwargs):
        calls.append(("resolve_action", (chat_id, user_id, action)))
        return SimpleNamespace(action=action)

    async def fake_execute(context, **kwargs):
        calls.append(("execute", kwargs))
        return SimpleNamespace(applied=True)

    async def fake_record_violation(session, **kwargs):
        calls.append(("record_violation", kwargs))

    async def fake_send_temporary_notice(bot, *, chat_id: int, text: str, delete_after_seconds: int):
        calls.append(("notice", (chat_id, text, delete_after_seconds)))

    monkeypatch.setattr(garbage_guard_service.ActionExecutor, "delete_many", fake_delete_many)
    monkeypatch.setattr(garbage_guard_service.ActionExecutor, "execute", fake_execute)
    monkeypatch.setattr(garbage_guard_service, "add_warning", fake_add_warning)
    monkeypatch.setattr(garbage_guard_service, "resolve_effective_action", fake_resolve_effective_action)
    monkeypatch.setattr(garbage_guard_service, "record_violation", fake_record_violation)
    monkeypatch.setattr(garbage_guard_service, "send_temporary_notice", fake_send_temporary_notice)

    result = await apply_garbage_punishment(
        SimpleNamespace(bot=object()),
        object(),
        settings=settings,
        chat_id=-100123,
        target_user_id=42,
        target_label="Alice",
        rule_id="banned_words",
        detail="违禁词测试",
        message_ids=[99],
        actor_user_id=7,
        record_message_id=99,
    )

    assert result.applied is True
    assert result.action_label == "删除消息 + 警告成员 + 禁言成员"
    assert result.warning is not None
    assert result.warning.threshold_reached is True
    assert ("delete_many", (-100123, [99])) in calls
    assert ("add_warning", (-100123, 42, "banned_words", 1)) in calls
    assert ("resolve_action", (-100123, 42, "mute")) in calls
    execute_call = next(value for name, value in calls if name == "execute")
    assert execute_call["action"] == "mute"
    assert execute_call["mute_seconds"] == 600
    notice_call = next(value for name, value in calls if name == "notice")
    assert notice_call[0] == -100123
    assert notice_call[2] == 10


@pytest.mark.asyncio
async def test_garbage_punishment_tracks_failed_delete_separately_from_other_actions(monkeypatch) -> None:
    settings = _settings()
    set_rule_config(
        settings,
        "long_message",
        {
            "enabled": True,
            "delete_message": True,
            "mute_enabled": True,
            "mute_seconds": 600,
        },
    )

    async def fake_delete_many(context, *, chat_id: int, message_ids: list[int]):
        return SimpleNamespace(applied=False)

    async def fake_resolve_effective_action(context, chat_id: int, user_id: int, action: str, **kwargs):
        return SimpleNamespace(action=action)

    async def fake_execute(context, **kwargs):
        return SimpleNamespace(applied=True)

    async def fake_record_violation(session, **kwargs):
        return None

    monkeypatch.setattr(garbage_guard_service.ActionExecutor, "delete_many", fake_delete_many)
    monkeypatch.setattr(garbage_guard_service.ActionExecutor, "execute", fake_execute)
    monkeypatch.setattr(garbage_guard_service, "resolve_effective_action", fake_resolve_effective_action)
    monkeypatch.setattr(garbage_guard_service, "record_violation", fake_record_violation)

    result = await apply_garbage_punishment(
        SimpleNamespace(bot=object()),
        object(),
        settings=settings,
        chat_id=-100123,
        target_user_id=42,
        target_label="Alice",
        rule_id="long_message",
        detail="消息长度 101 字，超过 100 字限制",
        message_ids=[99],
        record_message_id=99,
    )

    assert result.applied is True
    assert result.delete_requested is True
    assert result.delete_applied is False
    assert result.action_label == "删除消息 + 禁言成员"


@pytest.mark.asyncio
async def test_garbage_punishment_records_and_returns_when_action_api_fails(monkeypatch) -> None:
    settings = _settings()
    set_rule_config(
        settings,
        "long_message",
        {
            "enabled": True,
            "delete_message": False,
            "mute_enabled": True,
            "mute_seconds": 600,
        },
    )
    recorded: list[dict[str, object]] = []

    async def fake_resolve_effective_action(context, chat_id: int, user_id: int, action: str, **kwargs):
        return SimpleNamespace(action=action)

    async def fake_execute(context, **kwargs):
        raise RuntimeError("missing mute permission")

    async def fake_record_violation(session, **kwargs):
        recorded.append(kwargs)

    monkeypatch.setattr(garbage_guard_service.ActionExecutor, "execute", fake_execute)
    monkeypatch.setattr(garbage_guard_service, "resolve_effective_action", fake_resolve_effective_action)
    monkeypatch.setattr(garbage_guard_service, "record_violation", fake_record_violation)

    result = await apply_garbage_punishment(
        SimpleNamespace(bot=object()),
        object(),
        settings=settings,
        chat_id=-100123,
        target_user_id=42,
        target_label="Alice",
        rule_id="long_message",
        detail="消息长度 101 字，超过 100 字限制",
        message_ids=[99],
        record_message_id=99,
    )

    assert result.applied is False
    assert result.action_label == "禁言成员"
    assert recorded[0]["rule"] == "long_message"
