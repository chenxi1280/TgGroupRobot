from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.points.points_message_actions import handle_message_points_action


class _Session:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class _SessionContext:
    def __init__(self, session: _Session) -> None:
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Db:
    def __init__(self, session: _Session) -> None:
        self.session = session

    def session_factory(self):
        return _SessionContext(self.session)


class _Message(SimpleNamespace):
    async def reply_text(self, text: str, **kwargs) -> None:
        self.replies.append(text)


def _settings(**overrides):
    data = dict(
        sign_enabled=True,
        sign_points=5,
        sign_consecutive_days=0,
        sign_consecutive_bonus=0,
        message_points_enabled=True,
        message_points=2,
        message_points_daily_limit=None,
        message_min_length=3,
        points_alias="积分",
        points_rank_alias="积分排行",
    )
    data.update(overrides)
    return SimpleNamespace(**data)


def _update(text: str, *, reply_target=None):
    replies: list[str] = []
    message = _Message(
        text=text,
        replies=replies,
        reply_to_message=SimpleNamespace(from_user=reply_target) if reply_target else None,
        sticker=None,
        audio=None,
        voice=None,
        video=None,
        photo=None,
        document=None,
        caption=None,
        entities=[],
        caption_entities=[],
    )
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=-1001, type="supergroup", title="群"),
        effective_user=SimpleNamespace(id=42, username="admin", first_name="Admin", last_name=None, language_code="zh-CN"),
        effective_message=message,
    ), replies


async def _call(update, session: _Session, settings, **overrides):
    async def ensure_chat(*args, **kwargs):
        return None

    async def ensure_user(*args, **kwargs):
        return None

    async def get_chat_settings(*args, **kwargs):
        return settings

    class ExtendedService:
        @staticmethod
        async def get_or_create_mall_setting(*args, **kwargs):
            return SimpleNamespace(enabled=False, entry_command="积分商城")

        @staticmethod
        async def get_or_create_level_setting(*args, **kwargs):
            return SimpleNamespace(enabled=False)

        @staticmethod
        async def list_custom_point_types(*args, **kwargs):
            return []

    async def add_message_points(*args, **kwargs):
        raise AssertionError("message points should not run")

    async def change_points(*args, **kwargs):
        return True, 0

    async def sign_in(*args, **kwargs):
        return SimpleNamespace(success=True, balance=0, consecutive_days=0, bonus_points=0)

    async def get_balance(*args, **kwargs):
        return 0

    async def get_user_rank(*args, **kwargs):
        return None

    async def get_leaderboard(*args, **kwargs):
        return []

    async def require_manage(*args, **kwargs):
        return True, None

    deps = dict(
        ensure_chat_func=ensure_chat,
        ensure_user_func=ensure_user,
        get_chat_settings_func=get_chat_settings,
        points_extended_service=ExtendedService,
        change_points_func=change_points,
        sign_in_func=sign_in,
        get_balance_func=get_balance,
        get_user_rank_func=get_user_rank,
        get_leaderboard_func=get_leaderboard,
        format_sign_in_success_message_func=lambda **kwargs: "签到成功",
        format_sign_in_already_message_func=lambda **kwargs: "今日已签到",
        format_balance_message_func=lambda balance, rank: f"余额 {balance} 排名 {rank}",
        format_leaderboard_message_func=lambda rows: f"排行 {len(rows)}",
        add_message_points_func=add_message_points,
        required_level_permission_func=lambda message: None,
        should_send_level_block_notice_func=lambda *args, **kwargs: False,
        show_mall_catalog_func=lambda *args, **kwargs: None,
        require_manage_func=require_manage,
    )
    deps.update(overrides)
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db(session)}))
    await handle_message_points_action(update, context, **deps)


@pytest.mark.asyncio
async def test_plain_sign_text_triggers_sign_in() -> None:
    session = _Session()
    update, replies = _update("签到")

    async def sign_in(*args, **kwargs):
        return SimpleNamespace(success=True, balance=5, consecutive_days=1, bonus_points=0)

    await _call(update, session, _settings(), sign_in_func=sign_in)

    assert replies == ["签到成功"]
    assert session.commits == 1


@pytest.mark.asyncio
async def test_plain_points_alias_queries_balance() -> None:
    session = _Session()
    update, replies = _update("积分")

    async def get_balance(*args, **kwargs):
        return 18

    async def get_rank(*args, **kwargs):
        return 3

    await _call(update, session, _settings(), get_balance_func=get_balance, get_user_rank_func=get_rank)

    assert replies == ["余额 18 排名 3"]
    assert session.commits == 1


@pytest.mark.asyncio
async def test_reply_admin_add_points_adjusts_target() -> None:
    session = _Session()
    target = SimpleNamespace(id=77, username="alice", first_name="Alice", last_name=None, language_code="zh-CN")
    update, replies = _update("加积分 12 活动奖励", reply_target=target)
    changes: list[tuple[int, int, str]] = []

    async def change_points(session, chat_id: int, user_id: int, amount: int, txn_type: str, reason: str):
        changes.append((user_id, amount, reason))
        return True, 40

    async def require_manage(*args, **kwargs):
        return True, None

    await _call(
        update,
        session,
        _settings(),
        change_points_func=change_points,
        require_manage_func=require_manage,
    )

    assert changes == [(77, 12, "活动奖励")]
    assert replies == ["✅ 已为 @alice 增加 12 积分，当前积分 40。\n备注：活动奖励"]
    assert session.commits == 1


@pytest.mark.asyncio
async def test_reply_admin_deduct_points_reports_insufficient_balance() -> None:
    session = _Session()
    target = SimpleNamespace(id=77, username=None, first_name="Alice", last_name=None, language_code="zh-CN")
    update, replies = _update("扣积分 99 违规", reply_target=target)

    async def change_points(*args, **kwargs):
        return False, 10

    await _call(update, session, _settings(), change_points_func=change_points)

    assert replies == ["目标用户积分不足，无法扣除。"]
    assert session.commits == 1
