from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.web_admin.announcement_service import (
    DEFAULT_ANNOUNCEMENT_TEXT,
    format_announcement_line,
)
from backend.features.web_admin.auth_service import (
    ensure_bootstrap_admin,
    hash_password,
    hash_token,
    revoke_admin_sessions,
    verify_password,
)
from backend.features.web_admin.card_service import (
    COPY_CARD_LIMIT,
    KEY_SPECS,
    is_card_voided,
    serialize_batch,
    serialize_card,
)


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _FakeSession:
    def __init__(self, existing):
        self.existing = existing
        self.added = []

    async def execute(self, statement):
        return _ScalarResult(self.existing)

    def add(self, entity):
        self.added.append(entity)

    async def flush(self):
        return None


class _RowCountResult:
    rowcount = 2


class _FakeRevokeSession:
    def __init__(self):
        self.statements = []
        self.flushed = False

    async def execute(self, statement):
        self.statements.append(statement)
        return _RowCountResult()

    async def flush(self):
        self.flushed = True


def test_admin_password_hash_verifies_and_rejects_wrong_password() -> None:
    stored = hash_password("secret-pass")

    assert verify_password("secret-pass", stored)
    assert not verify_password("wrong-pass", stored)


@pytest.mark.asyncio
async def test_revoke_admin_sessions_targets_active_sessions_and_can_keep_current_token() -> None:
    session = _FakeRevokeSession()

    count = await revoke_admin_sessions(session, admin_account_id=7, except_token="current-token")

    sql = str(session.statements[0].compile(compile_kwargs={"literal_binds": True}))
    assert count == 2
    assert session.flushed is True
    assert "admin_sessions" in sql
    assert "admin_account_id = 7" in sql
    assert "revoked_at IS NULL" in sql
    assert hash_token("current-token") in sql


def test_key_specs_match_first_version_contract() -> None:
    assert [item["days"] for item in KEY_SPECS] == [30, 60, 90, 365]
    assert COPY_CARD_LIMIT == 40


def test_voided_card_serializes_as_unusable() -> None:
    card = SimpleNamespace(
        id=7,
        batch_id=2,
        card_code_plain="TGR-ABCD",
        spec_days=30,
        duration_seconds=30 * 86400,
        used=False,
        used_by_chat_id=None,
        used_by_user_id=None,
        used_at=None,
        copy_status="voided",
        export_status="voided",
        created_at=None,
    )

    payload = serialize_card(card)

    assert is_card_voided(card)
    assert payload["status"] == "voided"
    assert payload["voided"] is True


def test_batch_available_count_excludes_voided_cards() -> None:
    batch = SimpleNamespace(
        id=2,
        batch_no="RK202605120001",
        spec_days=30,
        quantity=10,
        copy_count=0,
        export_count=0,
        created_at=None,
    )

    payload = serialize_batch(batch, used_count=3, voided_count=2)

    assert payload["used_count"] == 3
    assert payload["voided_count"] == 2
    assert payload["available_count"] == 5


@pytest.mark.asyncio
async def test_bootstrap_admin_does_not_recreate_when_disabled_account_exists() -> None:
    existing = SimpleNamespace(id=1, username="admin", status="disabled")
    session = _FakeSession(existing)
    settings = SimpleNamespace(
        admin_bootstrap_username="admin",
        admin_bootstrap_password="secret-pass",
        admin_bootstrap_display_name="超级管理员",
    )

    result = await ensure_bootstrap_admin(session, settings)

    assert result is existing
    assert session.added == []


@pytest.mark.parametrize(
    ("settings", "expected"),
    [
        ({"enabled": True, "entry_text": "", "target_url": "", "message_text": ""}, DEFAULT_ANNOUNCEMENT_TEXT),
        (
            {
                "enabled": True,
                "entry_text": "更新日志",
                "target_url": "https://example.com/changelog",
                "message_text": "新版后台已上线",
            },
            "更新日志\nhttps://example.com/changelog\n新版后台已上线",
        ),
        ({"enabled": False, "entry_text": "更新日志", "target_url": "", "message_text": ""}, ""),
    ],
)
def test_format_announcement_line(settings: dict, expected: str) -> None:
    assert format_announcement_line(settings) == expected
