from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from backend.shared.services.base import ValidationError
from backend.features.garage.services.alliance_service import AllianceService
from backend.features.garage.services.garage_forward_service import GarageForwardService


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalar_one(self):
        return self._value

    def all(self):
        return self._value


class _FakeSession:
    def __init__(self, *, execute_value=None) -> None:
        self._execute_value = execute_value
        self.deleted: list[object] = []
        self.flush_calls = 0

    async def execute(self, stmt):
        return _FakeResult(self._execute_value)

    async def get(self, model, key):
        return None

    async def delete(self, item):
        self.deleted.append(item)

    async def flush(self):
        self.flush_calls += 1

    async def rollback(self):
        return None


def test_alliance_invite_code_hash_is_stable_and_case_insensitive():
    assert AllianceService.hash_invite_code("abc123") == AllianceService.hash_invite_code("ABC123")


def test_alliance_name_validation_rejects_invalid_chars():
    with pytest.raises(ValidationError):
        AllianceService.validate_alliance_name("!!")


@pytest.mark.asyncio
async def test_rotate_invite_code_requires_owner(monkeypatch):
    async def fake_get_alliance_by_chat(session, chat_id):
        return SimpleNamespace(alliance_id=1, owner_chat_id=-10001)

    monkeypatch.setattr(AllianceService, "get_alliance_by_chat", fake_get_alliance_by_chat)

    with pytest.raises(ValidationError, match="只有创建群可以重置联盟邀请码"):
        await AllianceService.rotate_invite_code(
            object(),
            chat_id=-10002,
            operator_user_id=1,
        )


@pytest.mark.asyncio
async def test_leave_alliance_deletes_orphan_owner_alliance(monkeypatch):
    alliance = SimpleNamespace(alliance_id=9, owner_chat_id=-10001, updated_at=None)
    member = SimpleNamespace(alliance_id=9, chat_id=-10001, status="active")
    setting = SimpleNamespace(chat_id=-10001, alliance_id=9)
    session = _FakeSession()

    async def fake_get_member(inner_session, chat_id):
        return member

    async def fake_list_members(inner_session, alliance_id):
        return [(member, SimpleNamespace(id=-10001, title="Owner Chat"))]

    async def fake_get_setting(inner_session, chat_id):
        return setting

    async def fake_append_audit(*args, **kwargs):
        return None

    async def fake_session_get(model, key):
        return alliance

    session.get = fake_session_get  # type: ignore[method-assign]
    monkeypatch.setattr(AllianceService, "get_member", fake_get_member)
    monkeypatch.setattr(AllianceService, "list_members", fake_list_members)
    monkeypatch.setattr(AllianceService, "get_setting", fake_get_setting)
    monkeypatch.setattr(AllianceService, "append_audit", fake_append_audit)

    await AllianceService.leave_alliance(
        session,
        chat_id=-10001,
        operator_user_id=7,
    )

    assert member.status == "left"
    assert setting in session.deleted
    assert alliance in session.deleted
    assert session.flush_calls == 1


@pytest.mark.asyncio
async def test_join_alliance_merges_local_teachers_into_owner_pool(monkeypatch):
    alliance = SimpleNamespace(alliance_id=9, owner_chat_id=-10001, invite_code_expire_at=None)
    session = _FakeSession(execute_value=None)
    added: list[object] = []

    async def fake_get_member(inner_session, chat_id):
        return None

    async def fake_execute(stmt):
        text = str(stmt)
        if "FROM bot.group_alliances" in text:
            return _FakeResult(alliance)
        return _FakeResult(0)

    async def fake_ensure_setting(*args, **kwargs):
        return None

    async def fake_append_audit(*args, **kwargs):
        return None

    async def fake_merge(*args, **kwargs):
        added.append(kwargs)
        return 2

    session.execute = fake_execute  # type: ignore[method-assign]
    session.add = added.append  # type: ignore[attr-defined]
    monkeypatch.setattr(AllianceService, "get_member", fake_get_member)
    monkeypatch.setattr(AllianceService, "ensure_setting", fake_ensure_setting)
    monkeypatch.setattr(AllianceService, "append_audit", fake_append_audit)
    monkeypatch.setattr(
        "backend.features.garage.services.alliance_lifecycle.GarageAuthService.merge_local_certified_teachers_into_pool",
        fake_merge,
    )

    result = await AllianceService.join_alliance(
        session,
        chat_id=-10002,
        operator_user_id=7,
        invite_code="JOINCODE",
    )

    assert result is alliance
    assert added[0] == {
        "source_chat_id": -10002,
        "pool_chat_id": -10001,
        "operator_user_id": 7,
    }


@pytest.mark.asyncio
async def test_leave_alliance_syncs_shared_teachers_back_to_local_pool(monkeypatch):
    alliance = SimpleNamespace(alliance_id=9, owner_chat_id=-10001, updated_at=None)
    member = SimpleNamespace(alliance_id=9, chat_id=-10002, status="active")
    setting = SimpleNamespace(chat_id=-10002, alliance_id=9)
    session = _FakeSession()

    async def fake_get_member(inner_session, chat_id):
        return member

    async def fake_list_members(inner_session, alliance_id):
        return [
            (SimpleNamespace(chat_id=-10001, status="active"), SimpleNamespace(id=-10001, title="Owner Chat")),
            (member, SimpleNamespace(id=-10002, title="Member Chat")),
        ]

    async def fake_get_setting(inner_session, chat_id):
        return setting

    async def fake_append_audit(*args, **kwargs):
        return None

    async def fake_session_get(model, key):
        return alliance

    sync_calls: list[dict] = []

    async def fake_sync(*args, **kwargs):
        sync_calls.append(kwargs)
        return 3

    session.get = fake_session_get  # type: ignore[method-assign]
    monkeypatch.setattr(AllianceService, "get_member", fake_get_member)
    monkeypatch.setattr(AllianceService, "list_members", fake_list_members)
    monkeypatch.setattr(AllianceService, "get_setting", fake_get_setting)
    monkeypatch.setattr(AllianceService, "append_audit", fake_append_audit)
    monkeypatch.setattr(
        "backend.features.garage.services.alliance_lifecycle.GarageAuthService.sync_local_certified_teachers_from_effective_pool",
        fake_sync,
    )

    await AllianceService.leave_alliance(
        session,
        chat_id=-10002,
        operator_user_id=7,
    )

    assert sync_calls == [{"chat_id": -10002, "operator_user_id": 7}]
    assert member.status == "left"
    assert setting in session.deleted
    assert alliance.updated_at is not None


def test_garage_forward_should_forward_matches_mode_rules():
    assert GarageForwardService.should_forward("all", "", False) is True
    assert GarageForwardService.should_forward("text", "hello", False) is True
    assert GarageForwardService.should_forward("text", "hello", True) is False
    assert GarageForwardService.should_forward("media", "", True) is True
    assert GarageForwardService.should_forward("keyword", "keyword", False) is True
    assert GarageForwardService.should_forward("keyword", "", False) is False


def test_garage_forward_matches_keywords_uses_contains():
    assert GarageForwardService.matches_keywords("精品榜单已更新", ["榜单", "开奖"]) is True
    assert GarageForwardService.matches_keywords("普通消息", ["榜单", "开奖"]) is False
    assert GarageForwardService.matches_keywords("", ["榜单"]) is False


@pytest.mark.asyncio
async def test_garage_forward_add_source_reuses_existing():
    existing = SimpleNamespace(
        id=1,
        chat_id=-10001,
        source_channel_id=-10002,
        source_name="旧名称",
        enabled=False,
    )
    session = _FakeSession(execute_value=existing)

    item = await GarageForwardService.add_source(
        session,
        chat_id=-10001,
        source_channel_id=-10002,
        source_name="新名称",
    )

    assert item is existing
    assert existing.enabled is True
    assert existing.source_name == "新名称"
    assert session.flush_calls == 1


@pytest.mark.asyncio
async def test_garage_forward_claim_slot_returns_none_on_duplicate():
    from sqlalchemy.exc import IntegrityError

    class _SessionWithIntegrity(_FakeSession):
        def __init__(self) -> None:
            super().__init__()
            self.added: list[object] = []
            self.rolled_back = False

        def add(self, item):
            self.added.append(item)

        async def flush(self):
            raise IntegrityError("dup", None, None)

        async def rollback(self):
            self.rolled_back = True

    session = _SessionWithIntegrity()

    result = await GarageForwardService.claim_forward_slot(
        session,
        chat_id=-10001,
        source_channel_id=-10002,
        source_message_id=123,
    )

    assert result is None
    assert session.rolled_back is True


@pytest.mark.asyncio
async def test_garage_forward_claim_slot_reclaims_stale_placeholder():
    stale = SimpleNamespace(
        id=5,
        chat_id=-10001,
        source_channel_id=-10002,
        source_message_id=123,
        target_message_id=0,
        forwarded_at=dt.datetime.now(dt.UTC) - dt.timedelta(minutes=11),
    )

    class _SessionWithStale(_FakeSession):
        def __init__(self) -> None:
            super().__init__(execute_value=stale)
            self.added: list[object] = []

        def add(self, item):
            self.added.append(item)

    session = _SessionWithStale()

    result = await GarageForwardService.claim_forward_slot(
        session,
        chat_id=-10001,
        source_channel_id=-10002,
        source_message_id=123,
    )

    assert stale in session.deleted
    assert result is not None
    assert session.added
    assert session.flush_calls >= 2


@pytest.mark.asyncio
async def test_garage_forward_purge_expired_audits_filters_by_chat_and_result():
    class _PurgeSession(_FakeSession):
        def __init__(self) -> None:
            super().__init__()
            self.statements: list[str] = []

        async def execute(self, stmt):
            self.statements.append(str(stmt))
            if len(self.statements) == 1:
                return _FakeResult([(11,), (12,)])
            return _FakeResult(None)

    session = _PurgeSession()

    deleted = await GarageForwardService.purge_expired_audits(
        session,
        chat_id=-10001,
        result="failed",
        now=dt.datetime(2026, 5, 6, tzinfo=dt.UTC),
    )

    assert deleted == 2
    assert "garage_forward_audit_logs.chat_id = :chat_id_1" in session.statements[0]
    assert "garage_forward_audit_logs.result = :result_1" in session.statements[0]
    assert "DELETE FROM bot.garage_forward_audit_logs" in session.statements[1]
    assert session.flush_calls == 1


@pytest.mark.asyncio
async def test_remove_joint_ban_entry_deletes_item_and_records_audit(monkeypatch):
    entry = SimpleNamespace(
        id=8,
        alliance_id=9,
        target_user_id=12345,
        source_chat_id=-10002,
        reason="reply_team_command",
    )
    session = _FakeSession(execute_value=entry)
    audit_calls: list[dict] = []

    async def fake_get_member(inner_session, chat_id):
        return SimpleNamespace(alliance_id=9)

    async def fake_append_audit(*args, **kwargs):
        audit_calls.append(kwargs)
        return None

    monkeypatch.setattr(AllianceService, "get_member", fake_get_member)
    monkeypatch.setattr(AllianceService, "append_audit", fake_append_audit)

    removed = await AllianceService.remove_joint_ban_entry(
        session,
        chat_id=-10001,
        operator_user_id=7,
        entry_id=8,
    )

    assert removed is entry
    assert session.deleted == [entry]
    assert session.flush_calls == 1
    assert audit_calls == [
        {
            "chat_id": -10001,
            "alliance_id": 9,
            "action": "joint_ban_remove",
            "operator_user_id": 7,
            "payload": {
                "entry_id": 8,
                "target_user_id": 12345,
                "source_chat_id": -10002,
                "reason": "reply_team_command",
            },
        }
    ]
