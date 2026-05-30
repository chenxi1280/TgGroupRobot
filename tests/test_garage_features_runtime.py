from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

import backend.features.group_ops.group_message_handler as group_message_handler
import backend.features.group_ops.group_hooks.car_review as car_review_hook
from backend.features.group_ops.group_hooks.teacher_search import _format_teacher_keyword_search
from backend.features.group_ops.group_hooks.teacher_search_format import build_teacher_keyword_search_markup
from backend.features.admin.garage import review_submit
from backend.features.group_ops.group_message_handler import _process_garage_features
from backend.platform.db.schema.models.core import TgUser
from backend.platform.db.schema.models.garage_features import (
    CarReviewAuditLog,
    CarReviewReport,
    TeacherProfile,
    TeacherSearchSetting,
    TeacherSourcePost,
)
from backend.shared.services.user_service import ensure_user
from backend.features.garage.services.garage_features_service import CarReviewService, GarageAuthService, TeacherSearchService
from backend.features.garage.services.teacher_search_settings import TeacherSearchSettingsMixin
from backend.shared.services.base import ValidationError


class _ExecuteResult:
    def __init__(self, scalar=None, rows=None, rowcount=0):
        self._scalar = scalar
        self._rows = rows or []
        self.rowcount = rowcount

    def scalar_one_or_none(self):
        return self._scalar

    def all(self):
        return list(self._rows)

    def scalars(self):
        return SimpleNamespace(all=lambda: [row[0] if isinstance(row, tuple) else row for row in self._rows])


class _FakeSession:
    def __init__(self, execute_results=None, get_map=None):
        self.execute_results = list(execute_results or [])
        self.get_map = dict(get_map or {})
        self.added = []
        self.flushes = 0
        self.commits = 0
        self.next_id = 1

    def add(self, obj):
        if hasattr(obj, "report_id") and getattr(obj, "report_id", None) is None:
            obj.report_id = self.next_id
            self.next_id += 1
        if hasattr(obj, "id") and getattr(obj, "id", None) is None:
            obj.id = self.next_id
            self.next_id += 1
        self.added.append(obj)
        if hasattr(obj, "report_id"):
            self.get_map[(obj.__class__, obj.report_id)] = obj

    async def execute(self, stmt):
        if self.execute_results:
            return self.execute_results.pop(0)
        return _ExecuteResult()

    async def get(self, model, key):
        return self.get_map.get((model, key))

    async def flush(self):
        self.flushes += 1

    async def commit(self):
        self.commits += 1


class _SessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeDb:
    def __init__(self, session):
        self._session = session

    def session_factory(self):
        return _SessionContext(self._session)


@pytest.mark.asyncio
async def test_mark_attendance_sets_open_course_without_default_location():
    session = _FakeSession(
        execute_results=[
            _ExecuteResult(scalar=None),
            _ExecuteResult(scalar=None),
        ]
    )

    item = await TeacherSearchService.mark_attendance(
        session,
        chat_id=-1001,
        user_id=7,
        source_message_id=55,
    )

    profiles = [obj for obj in session.added if isinstance(obj, TeacherProfile)]
    assert item.source_message_id == 55
    assert profiles
    assert profiles[0].open_course_today is True
    assert profiles[0].latitude is None
    assert profiles[0].longitude is None


@pytest.mark.asyncio
async def test_mark_attendance_rest_clears_open_course_flag():
    session = _FakeSession(
        execute_results=[
            _ExecuteResult(scalar=None),
            _ExecuteResult(scalar=None),
        ]
    )

    item = await TeacherSearchService.mark_attendance(
        session,
        chat_id=-1001,
        user_id=7,
        source_message_id=55,
        status="rest",
    )

    profiles = [obj for obj in session.added if isinstance(obj, TeacherProfile)]
    assert item.status == "rest"
    assert profiles
    assert profiles[0].open_course_today is False
    assert profiles[0].open_course_status == "rest"


@pytest.mark.asyncio
async def test_update_teacher_labels_rejects_more_than_ten_items():
    session = _FakeSession(execute_results=[_ExecuteResult(scalar=None)])

    with pytest.raises(ValidationError, match="服务标签最多可设置 10 个"):
        await TeacherSearchService.update_teacher_labels(
            session,
            chat_id=-1001,
            user_id=7,
            labels="1 2 3 4 5 6 7 8 9 10 11",
        )


@pytest.mark.asyncio
async def test_has_recorded_teacher_location_only_reads_teacher_profile():
    session = _FakeSession(execute_results=[_ExecuteResult(scalar=SimpleNamespace(latitude=31.2, longitude=121.4))])

    recorded = await TeacherSearchService.has_recorded_teacher_location(session, -1001, 7)

    assert recorded is True

    session = _FakeSession(execute_results=[_ExecuteResult(scalar=SimpleNamespace(latitude=None, longitude=121.4))])

    recorded = await TeacherSearchService.has_recorded_teacher_location(session, -1001, 7)

    assert recorded is False


@pytest.mark.asyncio
async def test_reset_stale_open_course_flags_returns_updated_count():
    session = _FakeSession(execute_results=[_ExecuteResult(rowcount=3)])

    count = await TeacherSearchService.reset_stale_open_course_flags(session)

    assert count == 3
    assert session.flushes == 1


@pytest.mark.asyncio
async def test_list_nearby_teachers_orders_by_distance_and_formats_fuzzy_text(monkeypatch):
    rows = [
        (
            SimpleNamespace(user_id=1, latitude=31.2305, longitude=121.4739, region_text="A区", price_text="100", labels=["新人"], updated_at=dt.datetime.now(dt.UTC)),
            SimpleNamespace(id=1, username="nearer", first_name="Near", last_name=None),
        ),
        (
            SimpleNamespace(user_id=2, latitude=31.2405, longitude=121.4839, region_text="B区", price_text="200", labels=["热门"], updated_at=dt.datetime.now(dt.UTC)),
            SimpleNamespace(id=2, username="farther", first_name="Far", last_name=None),
        ),
    ]

    async def fake_list_open_course_teachers(session, chat_id):
        return rows

    monkeypatch.setattr(TeacherSearchService, "list_open_course_teachers", fake_list_open_course_teachers)

    items = await TeacherSearchService.list_nearby_teachers(
        _FakeSession(),
        -1001,
        31.2304,
        121.4738,
        only_open_course=True,
        limit=10,
    )

    assert [item["user"].username for item in items] == ["nearer", "farther"]
    assert all(item["distance_text"] for item in items)


@pytest.mark.asyncio
async def test_list_nearby_teachers_filters_condition_then_orders_by_distance(monkeypatch):
    rows = [
        (
            SimpleNamespace(user_id=1, created_at=dt.datetime.now(dt.UTC), id=1),
            SimpleNamespace(
                user_id=1,
                latitude=31.2305,
                longitude=121.4739,
                region_text="A区",
                price_text="400",
                labels=[],
                updated_at=dt.datetime.now(dt.UTC),
            ),
            SimpleNamespace(id=1, username="near_400", first_name="Near", last_name=None),
            None,
        ),
        (
            SimpleNamespace(user_id=2, created_at=dt.datetime.now(dt.UTC), id=2),
            SimpleNamespace(
                user_id=2,
                latitude=31.2605,
                longitude=121.5039,
                region_text="B区",
                price_text="600",
                labels=[],
                updated_at=dt.datetime.now(dt.UTC),
            ),
            SimpleNamespace(id=2, username="far_600", first_name="Far", last_name=None),
            None,
        ),
        (
            SimpleNamespace(user_id=3, created_at=dt.datetime.now(dt.UTC), id=3),
            SimpleNamespace(
                user_id=3,
                latitude=31.2310,
                longitude=121.4744,
                region_text="C区",
                price_text="700",
                labels=[],
                updated_at=dt.datetime.now(dt.UTC),
            ),
            SimpleNamespace(id=3, username="near_700", first_name="Near", last_name=None),
            None,
        ),
    ]
    session = _FakeSession(execute_results=[_ExecuteResult(rows=rows)])

    async def fake_resolve_pool(session, chat_id: int):
        return chat_id

    monkeypatch.setattr(GarageAuthService, "resolve_teacher_pool_chat_id", fake_resolve_pool)

    items = await TeacherSearchService.list_nearby_teachers(
        session,
        -1001,
        31.2304,
        121.4738,
        only_open_course=False,
        keyword="500左右",
        limit=10,
    )

    assert [item["user"].username for item in items] == ["near_400", "far_600"]


@pytest.mark.asyncio
async def test_search_teachers_by_keyword_matches_full_name(monkeypatch):
    rows = [
        (
            SimpleNamespace(
                user_id=1,
                region_text="A区",
                price_text="100",
                labels=[],
                updated_at=dt.datetime.now(dt.UTC),
            ),
            SimpleNamespace(id=1, username="teacher_a", first_name="小", last_name="雪"),
        )
    ]

    async def fake_list_open_course_teachers(session, chat_id):
        return rows

    monkeypatch.setattr(TeacherSearchService, "list_open_course_teachers", fake_list_open_course_teachers)

    matches = await TeacherSearchService.search_teachers_by_keyword(
        _FakeSession(),
        -1001,
        "小雪",
        only_open_course=True,
    )

    assert matches == rows


@pytest.mark.asyncio
async def test_search_teachers_by_keyword_filters_by_review_score(monkeypatch):
    rows = [
        (
            SimpleNamespace(
                user_id=1,
                region_text="A区",
                price_text="100",
                labels=["新人"],
                avg_score=92.5,
                review_count=3,
                updated_at=dt.datetime.now(dt.UTC),
            ),
            SimpleNamespace(id=1, username="teacher_a", first_name="小", last_name="雪"),
        ),
        (
            SimpleNamespace(
                user_id=2,
                region_text="B区",
                price_text="90",
                labels=["新人"],
                avg_score=80,
                review_count=4,
                updated_at=dt.datetime.now(dt.UTC),
            ),
            SimpleNamespace(id=2, username="teacher_b", first_name="小", last_name="夏"),
        ),
    ]

    async def fake_list_searchable_teachers(session, chat_id, *, only_open_course=False):
        return rows

    monkeypatch.setattr(
        "backend.features.garage.services.teacher_search_queries.TeacherSearchQueryMixin.list_searchable_teachers",
        fake_list_searchable_teachers,
    )

    matches = await TeacherSearchService.search_teachers_by_keyword(
        _FakeSession(),
        -1001,
        "90分以上",
        only_open_course=False,
    )

    assert matches == [rows[0]]


@pytest.mark.asyncio
async def test_search_teachers_by_keyword_matches_fuzzy_price_text(monkeypatch):
    rows = [
        (
            SimpleNamespace(user_id=1, created_at=dt.datetime.now(dt.UTC), id=1),
            SimpleNamespace(
                user_id=1,
                region_text="A区",
                price_text="400",
                labels=[],
                updated_at=dt.datetime.now(dt.UTC),
                latitude=None,
                longitude=None,
            ),
            SimpleNamespace(id=1, username="teacher_a", first_name="A", last_name=None),
            None,
        ),
        (
            SimpleNamespace(user_id=2, created_at=dt.datetime.now(dt.UTC), id=2),
            SimpleNamespace(
                user_id=2,
                region_text="B区",
                price_text="600",
                labels=[],
                updated_at=dt.datetime.now(dt.UTC),
                latitude=None,
                longitude=None,
            ),
            SimpleNamespace(id=2, username="teacher_b", first_name="B", last_name=None),
            None,
        ),
        (
            SimpleNamespace(user_id=3, created_at=dt.datetime.now(dt.UTC), id=3),
            SimpleNamespace(
                user_id=3,
                region_text="C区",
                price_text="650",
                labels=[],
                updated_at=dt.datetime.now(dt.UTC),
                latitude=None,
                longitude=None,
            ),
            SimpleNamespace(id=3, username="teacher_c", first_name="C", last_name=None),
            None,
        )
    ]
    session = _FakeSession(execute_results=[_ExecuteResult(rows=rows)])

    async def fake_resolve_pool(session, chat_id: int):
        return chat_id

    monkeypatch.setattr(GarageAuthService, "resolve_teacher_pool_chat_id", fake_resolve_pool)

    matches = await TeacherSearchService.search_teachers_by_keyword(
        session,
        -1001,
        "500左右",
        only_open_course=False,
    )

    assert [(profile.price_text, user.username) for profile, user in matches] == [
        ("400", "teacher_a"),
        ("600", "teacher_b"),
    ]


@pytest.mark.asyncio
async def test_search_teachers_by_keyword_includes_certified_teacher_without_profile(monkeypatch):
    rows = [
        (
            SimpleNamespace(user_id=7, created_at=dt.datetime.now(dt.UTC), id=1),
            None,
            SimpleNamespace(id=7, username="teacher_empty", first_name="空", last_name="资料"),
            None,
        )
    ]
    session = _FakeSession(execute_results=[_ExecuteResult(rows=rows)])

    async def fake_resolve_pool(session, chat_id: int):
        return chat_id

    monkeypatch.setattr(GarageAuthService, "resolve_teacher_pool_chat_id", fake_resolve_pool)

    matches = await TeacherSearchService.search_teachers_by_keyword(
        session,
        -1001,
        "teacher_empty",
        only_open_course=False,
    )

    assert len(matches) == 1
    profile, user = matches[0]
    assert profile.user_id == 7
    assert profile.open_course_status is None
    assert user.username == "teacher_empty"


@pytest.mark.asyncio
async def test_search_teachers_by_keyword_matches_certified_teacher_id_without_profile(monkeypatch):
    rows = [
        (
            SimpleNamespace(user_id=7, created_at=dt.datetime.now(dt.UTC), id=1),
            None,
            None,
            None,
        )
    ]
    session = _FakeSession(execute_results=[_ExecuteResult(rows=rows)])

    async def fake_resolve_pool(session, chat_id: int):
        return chat_id

    monkeypatch.setattr(GarageAuthService, "resolve_teacher_pool_chat_id", fake_resolve_pool)

    matches = await TeacherSearchService.search_teachers_by_keyword(
        session,
        -1001,
        "7",
        only_open_course=False,
    )

    assert len(matches) == 1
    profile, user = matches[0]
    assert profile.user_id == 7
    assert user is None


@pytest.mark.asyncio
async def test_index_channel_post_certifies_contact_and_profiles_tags(monkeypatch):
    teacher = SimpleNamespace(id=77, username="tj373", first_name="T", last_name=None)
    session = _FakeSession(
        execute_results=[
            _ExecuteResult(scalar=teacher),
            _ExecuteResult(scalar=None),
        ],
        get_map={(TgUser, 77): teacher},
    )
    certified: list[dict[str, object]] = []

    async def fake_add_teacher_by_user_id(session, chat_id: int, user_id: int, operator_user_id):
        certified.append(
            {
                "chat_id": chat_id,
                "user_id": user_id,
                "operator_user_id": operator_user_id,
            }
        )
        return SimpleNamespace(chat_id=chat_id, user_id=user_id, enabled=True)

    monkeypatch.setattr(GarageAuthService, "add_teacher_by_user_id", fake_add_teacher_by_user_id)

    result = await TeacherSearchService.index_channel_post_teacher_profile(
        session,
        chat_id=-1001,
        channel_id=-2001,
        message_id=33,
        text=(
            "【所在位置】：#天津\n"
            "【上课费用】：800/50分钟 1500/90分钟\n"
            "【详细标签】：#变形 #妹妹体 #态度好\n"
            "【联系方式】：@tj373"
        ),
    )

    profiles = [obj for obj in session.added if isinstance(obj, TeacherProfile)]
    assert result.indexed is True
    assert result.user_id == 77
    assert certified == [{"chat_id": -1001, "user_id": 77, "operator_user_id": None}]
    assert profiles
    assert profiles[0].region_text == "天津"
    assert profiles[0].price_text == "800/50分钟 1500/90分钟"
    assert "变形" in profiles[0].labels


@pytest.mark.asyncio
async def test_index_channel_post_creates_pending_source_profile_when_contact_user_missing():
    session = _FakeSession(execute_results=[_ExecuteResult(scalar=None)])

    result = await TeacherSearchService.index_channel_post_teacher_profile(
        session,
        chat_id=-1001,
        channel_id=-2001,
        message_id=33,
        channel_username="tianjin_garage",
        channel_title="天津音乐学院车库",
        text=(
            "【所在位置】：#河西区\n"
            "【上课费用】：800/50分钟\n"
            "【详细标签】：#颜值车 #深喉\n"
            "【联系方式】：@jt37373"
        ),
    )

    source_posts = [obj for obj in session.added if obj.__class__.__name__ == "TeacherSourcePost"]
    assert result.indexed is True
    assert result.reason == "pending_bind"
    assert result.username == "jt37373"
    assert result.user_id is None
    assert source_posts
    assert source_posts[0].chat_id == -1001
    assert source_posts[0].source_channel_id == -2001
    assert source_posts[0].source_channel_username == "tianjin_garage"
    assert source_posts[0].source_channel_title == "天津音乐学院车库"
    assert source_posts[0].source_message_id == 33
    assert source_posts[0].source_url == "https://t.me/tianjin_garage/33"
    assert source_posts[0].username == "jt37373"
    assert source_posts[0].teacher_user_id is None
    assert source_posts[0].bind_status == "pending_bind"
    assert source_posts[0].region_text == "河西区"
    assert source_posts[0].price_text == "800/50分钟"
    assert source_posts[0].labels == ["河西区", "颜值车", "深喉"]


@pytest.mark.asyncio
async def test_index_channel_post_uses_private_channel_source_url_without_username():
    session = _FakeSession(execute_results=[_ExecuteResult(scalar=None)])

    result = await TeacherSearchService.index_channel_post_teacher_profile(
        session,
        chat_id=-1001,
        channel_id=-1002001,
        message_id=33,
        text="【详细标签】：#颜值车\n【联系方式】：@jt37373",
    )

    source_posts = [obj for obj in session.added if obj.__class__.__name__ == "TeacherSourcePost"]
    assert result.source_url == "https://t.me/c/2001/33"
    assert source_posts[0].source_url == "https://t.me/c/2001/33"


@pytest.mark.asyncio
async def test_search_teachers_by_keyword_matches_pending_source_profile(monkeypatch):
    source_post = SimpleNamespace(
        id=9,
        chat_id=-1001,
        source_channel_title="天津音乐学院车库",
        source_url="https://t.me/tianjin_garage/33",
        username="jt37373",
        teacher_user_id=None,
        bind_status="pending_bind",
        labels=["颜值车", "深喉"],
        region_text="河西区",
        price_text="800/50分钟",
        raw_text="【详细标签】：#颜值车 #深喉\n【联系方式】：@jt37373",
        updated_at=dt.datetime.now(dt.UTC),
    )
    session = _FakeSession(
        execute_results=[
            _ExecuteResult(rows=[]),
            _ExecuteResult(rows=[(source_post, None)]),
        ]
    )

    async def fake_resolve_pool(session, chat_id: int):
        return chat_id

    monkeypatch.setattr(GarageAuthService, "resolve_teacher_pool_chat_id", fake_resolve_pool)

    matches = await TeacherSearchService.search_teachers_by_keyword(
        session,
        -1001,
        "颜值车",
        only_open_course=False,
    )

    assert len(matches) == 1
    profile, user = matches[0]
    assert user is None
    assert profile.source_profile_id == 9
    assert profile.source_status == "pending_bind"
    assert profile.source_username == "jt37373"
    assert profile.source_channel_title == "天津音乐学院车库"
    assert profile.source_url == "https://t.me/tianjin_garage/33"


@pytest.mark.asyncio
async def test_ensure_user_binds_pending_source_profiles_for_matching_username(monkeypatch):
    source_post = TeacherSourcePost(
        chat_id=-1001,
        source_channel_id=-2001,
        source_message_id=33,
        source_channel_title="天津音乐学院车库",
        source_url="https://t.me/tianjin_garage/33",
        username="jt37373",
        bind_status="pending_bind",
        labels=["颜值车"],
        region_text="河西区",
        price_text="800/50分钟",
        raw_text="【详细标签】：#颜值车\n【所在位置】：#河西区\n【上课费用】：800/50分钟\n【联系方式】：@jt37373",
    )
    session = _FakeSession(
        execute_results=[
            _ExecuteResult(scalar=None),
            _ExecuteResult(rows=[source_post]),
        ]
    )
    certified: list[tuple[int, int]] = []
    profiles: list[TeacherProfile] = []

    async def fake_add_teacher_by_user_id(session, chat_id: int, user_id: int, operator_user_id):
        certified.append((chat_id, user_id))
        return SimpleNamespace(chat_id=chat_id, user_id=user_id, enabled=True)

    async def fake_ensure_teacher_profile(session, chat_id: int, user_id: int):
        profile = TeacherProfile(chat_id=chat_id, user_id=user_id)
        profiles.append(profile)
        return profile

    monkeypatch.setattr(GarageAuthService, "add_teacher_by_user_id", fake_add_teacher_by_user_id)
    monkeypatch.setattr(TeacherSearchSettingsMixin, "ensure_teacher_profile", fake_ensure_teacher_profile)

    user = await ensure_user(
        session,
        user_id=77,
        username="JT37373",
        first_name="T",
        last_name=None,
        language_code="zh",
    )

    assert user.id == 77
    assert source_post.teacher_user_id == 77
    assert source_post.bind_status == "bound"
    assert source_post.failure_reason is None
    assert certified == [(-1001, 77)]
    assert profiles[0].region_text == "河西区"
    assert profiles[0].price_text == "800/50分钟"
    assert "颜值车" in profiles[0].labels


def test_format_teacher_keyword_search_shows_pending_channel_source_profile():
    text = _format_teacher_keyword_search(
        "颜值车",
        [
            (
                SimpleNamespace(
                    user_id=0,
                    source_profile_id=9,
                    source_status="pending_bind",
                    source_username="jt37373",
                    source_channel_title="天津音乐学院车库",
                    source_url="https://t.me/tianjin_garage/33",
                    labels=["颜值车", "深喉"],
                    region_text="河西区",
                    price_text="800/50分钟",
                    latitude=None,
                    longitude=None,
                    open_course_today=False,
                    open_course_status=None,
                    review_count=0,
                    avg_score=0,
                ),
                None,
            )
        ],
        badge="🤝",
    )

    assert "待绑定 @jt37373 · 频道资料 · 河西区" in text
    assert "标签：颜值车 / 深喉" in text
    assert "价格：800/50分钟" in text
    assert "来源：天津音乐学院车库" in text
    assert "原帖：https://t.me/tianjin_garage/33" in text


def test_build_teacher_keyword_search_markup_adds_source_post_url_button():
    markup = build_teacher_keyword_search_markup(
        [
            (
                SimpleNamespace(source_url="https://t.me/tianjin_garage/33"),
                None,
            )
        ]
    )

    assert markup is not None
    button = markup.inline_keyboard[0][0]
    assert button.text == "1. 查看原帖"
    assert button.url == "https://t.me/tianjin_garage/33"


def test_format_teacher_keyword_search_keeps_bound_channel_source_link():
    text = _format_teacher_keyword_search(
        "颜值车",
        [
            (
                SimpleNamespace(
                    user_id=77,
                    labels=["颜值车"],
                    region_text="河西区",
                    price_text="800/50分钟",
                    latitude=None,
                    longitude=None,
                    open_course_today=False,
                    open_course_status=None,
                    review_count=0,
                    avg_score=0,
                    source_status="bound",
                    source_channel_title="天津音乐学院车库",
                    source_url="https://t.me/tianjin_garage/33",
                ),
                SimpleNamespace(id=77, username="jt37373", first_name=None, last_name=None),
            )
        ],
        badge="🤝",
    )

    assert "1. 🤝 @jt37373" in text
    assert "来源：天津音乐学院车库" in text
    assert "原帖：https://t.me/tianjin_garage/33" in text


@pytest.mark.asyncio
async def test_list_open_course_teachers_reads_certified_rows_and_filters_status(monkeypatch):
    rows = [
        (
            SimpleNamespace(user_id=1, created_at=dt.datetime.now(dt.UTC), id=1),
            SimpleNamespace(
                user_id=1,
                region_text="A区",
                price_text="100",
                labels=["新人"],
                updated_at=dt.datetime.now(dt.UTC),
                latitude=None,
                longitude=None,
            ),
            SimpleNamespace(id=1, username="teacher_a", first_name="A", last_name=None),
            SimpleNamespace(status="rest", created_at=dt.datetime.now(dt.UTC)),
        ),
        (
            SimpleNamespace(user_id=2, created_at=dt.datetime.now(dt.UTC), id=2),
            SimpleNamespace(
                user_id=2,
                region_text="B区",
                price_text="200",
                labels=["热门"],
                updated_at=dt.datetime.now(dt.UTC),
                latitude=None,
                longitude=None,
            ),
            SimpleNamespace(id=2, username="teacher_b", first_name="B", last_name=None),
            SimpleNamespace(status="full", created_at=dt.datetime.now(dt.UTC)),
        ),
        (
            SimpleNamespace(user_id=3, created_at=dt.datetime.now(dt.UTC), id=3),
            None,
            SimpleNamespace(id=3, username="teacher_c", first_name="C", last_name=None),
            SimpleNamespace(status="open", created_at=dt.datetime.now(dt.UTC)),
        ),
    ]
    session = _FakeSession(execute_results=[_ExecuteResult(rows=rows)])

    async def fake_resolve_pool(session, chat_id: int):
        return chat_id

    monkeypatch.setattr(GarageAuthService, "resolve_teacher_pool_chat_id", fake_resolve_pool)

    filtered = await TeacherSearchService.list_open_course_teachers(session, -1001)

    assert [profile.user_id for profile, _ in filtered] == [2, 3]
    assert [profile.open_course_status for profile, _ in filtered] == ["full", "open"]


@pytest.mark.asyncio
async def test_attendance_source_chat_uses_linked_external_group():
    session = _FakeSession(
        get_map={
            (TeacherSearchSetting, -1001): SimpleNamespace(
                attendance_mode="external",
                attendance_source_chat_id=-2002,
            )
        }
    )

    source_chat_id = await TeacherSearchService.get_attendance_source_chat_id(session, -1001)

    assert source_chat_id == -2002


@pytest.mark.asyncio
async def test_attendance_source_accepts_teacher_certified_in_linked_target(monkeypatch):
    session = _FakeSession(execute_results=[_ExecuteResult(rows=[(-1001,)])])
    checked: list[tuple[int, int]] = []

    async def fake_is_effective_teacher(session, chat_id: int, user_id: int):
        checked.append((chat_id, user_id))
        return chat_id == -1001 and user_id == 42

    monkeypatch.setattr(GarageAuthService, "is_effective_certified_teacher", fake_is_effective_teacher)

    assert await TeacherSearchService.is_certified_teacher_for_attendance_source(session, -2002, 42) is True
    assert checked == [(-1001, 42)]


@pytest.mark.asyncio
async def test_build_teacher_summary_groups_by_region(monkeypatch):
    rows = [
        (
            SimpleNamespace(chat_id=-1001, user_id=1, enabled=True, created_at=dt.datetime.now(dt.UTC)),
            SimpleNamespace(region_text="A区", price_text="100", labels=["新人"], open_course_today=True),
            SimpleNamespace(id=1, username="teacher_a", first_name="A", last_name=None),
            SimpleNamespace(status="open"),
        ),
        (
            SimpleNamespace(chat_id=-1001, user_id=2, enabled=True, created_at=dt.datetime.now(dt.UTC)),
            SimpleNamespace(region_text="A区", price_text="200", labels=["热门"], open_course_today=False),
            SimpleNamespace(id=2, username="teacher_b", first_name="B", last_name=None),
            SimpleNamespace(status="rest"),
        ),
        (
            SimpleNamespace(chat_id=-1001, user_id=3, enabled=True, created_at=dt.datetime.now(dt.UTC)),
            SimpleNamespace(region_text="B区", price_text="300", labels=[], open_course_today=True),
            SimpleNamespace(id=3, username=None, first_name="Teacher C", last_name=None),
            SimpleNamespace(status="full"),
        ),
    ]
    session = _FakeSession(execute_results=[_ExecuteResult(rows=rows)])

    async def fake_get_settings(session, chat_id: int):
        return SimpleNamespace(
            garage_summary_partition_by="region",
            garage_summary_only_open_course=False,
        )

    async def fake_get_pool_chat_id(session, chat_id: int):
        return chat_id

    monkeypatch.setattr(GarageAuthService, "get_settings", fake_get_settings)
    monkeypatch.setattr(GarageAuthService, "_get_teacher_pool_chat_id", fake_get_pool_chat_id)

    text = await GarageAuthService.build_teacher_summary(session, -1001)

    assert "分区方式：按地区" in text
    assert "【A区】(2人)" in text
    assert "@teacher_a" in text
    assert "Teacher C" in text


@pytest.mark.asyncio
async def test_build_teacher_summary_filters_open_course(monkeypatch):
    rows = [
        (
            SimpleNamespace(chat_id=-1001, user_id=1, enabled=True, created_at=dt.datetime.now(dt.UTC)),
            SimpleNamespace(region_text="A区", price_text="100", labels=["新人"], open_course_today=False),
            SimpleNamespace(id=1, username="teacher_a", first_name="A", last_name=None),
            SimpleNamespace(status="rest"),
        ),
        (
            SimpleNamespace(chat_id=-1001, user_id=2, enabled=True, created_at=dt.datetime.now(dt.UTC)),
            SimpleNamespace(region_text="B区", price_text="200", labels=["热门"], open_course_today=True),
            SimpleNamespace(id=2, username="teacher_b", first_name="B", last_name=None),
            SimpleNamespace(status="open"),
        ),
    ]
    session = _FakeSession(execute_results=[_ExecuteResult(rows=rows)])

    async def fake_get_settings(session, chat_id: int):
        return SimpleNamespace(
            garage_summary_partition_by="price",
            garage_summary_only_open_course=True,
        )

    async def fake_get_pool_chat_id(session, chat_id: int):
        return chat_id

    monkeypatch.setattr(GarageAuthService, "get_settings", fake_get_settings)
    monkeypatch.setattr(GarageAuthService, "_get_teacher_pool_chat_id", fake_get_pool_chat_id)

    text = await GarageAuthService.build_teacher_summary(session, -1001)

    assert "分区方式：按价格" in text
    assert "@teacher_b" in text
    assert "@teacher_a" not in text


@pytest.mark.asyncio
async def test_create_report_and_append_audit_records_pending_report():
    session = _FakeSession()

    report = await CarReviewService.create_report(
        session,
        chat_id=-1001,
        teacher_user_id=11,
        author_user_id=22,
        review_text="老师不错",
        media_file_ids=["file_a"],
        scores={"total_score": 88},
    )

    audits = [obj for obj in session.added if isinstance(obj, CarReviewAuditLog)]
    assert report.report_status == "pending"
    assert report.review_text == "老师不错"
    assert report.media_file_ids == ["file_a"]
    assert audits and audits[0].action == "submitted"


@pytest.mark.asyncio
async def test_approve_report_updates_status_and_audit():
    report = CarReviewReport(
        report_id=3,
        chat_id=-1001,
        teacher_user_id=11,
        author_user_id=22,
        review_text="待审核",
        scores={"total_score": 90},
        media_file_ids=[],
        report_status="pending",
    )
    session = _FakeSession(get_map={(CarReviewReport, 3): report})

    approved = await CarReviewService.approve_report(
        session,
        chat_id=-1001,
        report_id=3,
        approver_user_id=99,
    )

    audits = [obj for obj in session.added if isinstance(obj, CarReviewAuditLog)]
    assert approved is report
    assert report.report_status == "approved"
    assert report.approved_by_user_id == 99
    assert audits and audits[0].action == "approved"


@pytest.mark.asyncio
async def test_list_rankings_aggregates_average_total_score():
    rows = [
        (
            SimpleNamespace(chat_id=-1001, teacher_user_id=11, report_status="approved", scores={"total_score": 80}),
            SimpleNamespace(id=11, username="teacher_a", first_name="A", last_name=None),
        ),
        (
            SimpleNamespace(chat_id=-1001, teacher_user_id=11, report_status="published", scores={"total_score": 100}),
            SimpleNamespace(id=11, username="teacher_a", first_name="A", last_name=None),
        ),
        (
            SimpleNamespace(chat_id=-1001, teacher_user_id=12, report_status="approved", scores={"total_score": 95}),
            SimpleNamespace(id=12, username="teacher_b", first_name="B", last_name=None),
        ),
    ]
    session = _FakeSession(execute_results=[_ExecuteResult(rows=rows)])

    rankings = await CarReviewService.list_rankings(session, -1001, limit=10)

    assert rankings[0]["teacher_user_id"] == 12
    assert rankings[0]["avg_score"] == 95.0
    assert rankings[1]["teacher_user_id"] == 11
    assert rankings[1]["avg_score"] == 90.0


def test_parse_car_review_body_requires_enabled_default_fields():
    fields = [
        SimpleNamespace(field_key="photo_score", field_label="人照", enabled=True),
        SimpleNamespace(field_key="process", field_label="过程", enabled=True),
    ]

    parsed = car_review_hook._parse_review_body("人照：9\n过程：体验很好", fields, require_fields=True)
    missing = car_review_hook._parse_review_body("人照：9", fields, require_fields=True)

    assert parsed.missing_labels == []
    assert parsed.invalid_labels == []
    assert parsed.scores["photo_score"] == 9
    assert parsed.scores["total_score"] == 9
    assert parsed.process_text == "体验很好"
    assert missing.missing_labels == ["过程"]


@pytest.mark.asyncio
async def test_process_garage_features_handles_weekly_car_review_rank(monkeypatch):
    session = _FakeSession()
    db = _FakeDb(session)
    captured: dict[str, object] = {"replies": []}

    async def fake_get_teacher_setting(*args, **kwargs):
        return SimpleNamespace(
            nearby_search_enabled=False,
            attendance_enabled=False,
            force_location_enabled=False,
            footer_button_label=None,
        )

    async def fake_get_car_review_setting(*args, **kwargs):
        return SimpleNamespace(
            enabled=True,
            rank_command="出击排行",
            submit_command="提交报告",
            teacher_lookup_mode="off",
        )

    async def fake_list_rankings(session, chat_id: int, *, limit: int = 10, since=None):
        captured["since"] = since
        return [{"display_name": "@teacher_a", "avg_score": 9.5, "count": 2}]

    async def fake_reply(context, *, chat_id, text, reply_to_message_id=None, **kwargs):
        captured["replies"].append(text)

    async def fake_is_teacher(*args, **kwargs):
        return False

    async def fake_is_whitelisted(*args, **kwargs):
        return False

    monkeypatch.setattr(TeacherSearchService, "get_setting", fake_get_teacher_setting)
    monkeypatch.setattr(CarReviewService, "get_setting", fake_get_car_review_setting)
    monkeypatch.setattr(CarReviewService, "list_rankings", fake_list_rankings)
    monkeypatch.setattr(GarageAuthService, "is_certified_teacher", fake_is_teacher)
    monkeypatch.setattr(GarageAuthService, "is_whitelisted", fake_is_whitelisted)
    monkeypatch.setattr(group_message_handler.PublishService, "reply", fake_reply)

    handled = await _process_garage_features(
        SimpleNamespace(application=SimpleNamespace(bot_data={})),
        db,
        SimpleNamespace(id=-1001, title="测试群"),
        SimpleNamespace(id=42),
        SimpleNamespace(message_id=9, location=None, reply_to_message=None),
        "本周出击排行",
        SimpleNamespace(garage_limit_enabled=False),
        False,
    )

    assert handled is True
    assert captured["since"] is not None
    assert captured["replies"] == ["本周出击排行：\n1. @teacher_a · 均分 9.5 · 2 条"]


@pytest.mark.asyncio
async def test_process_garage_features_car_review_does_not_steal_sign_in_text(monkeypatch):
    session = _FakeSession()
    db = _FakeDb(session)

    async def fake_get_teacher_setting(*args, **kwargs):
        return SimpleNamespace(
            nearby_search_enabled=False,
            attendance_enabled=False,
            force_location_enabled=False,
            footer_button_label=None,
        )

    async def fake_get_car_review_setting(*args, **kwargs):
        return SimpleNamespace(
            enabled=True,
            rank_command="签到",
            submit_command="签到",
            teacher_lookup_mode="off",
        )

    async def forbidden_list_rankings(*args, **kwargs):
        raise AssertionError("reserved sign text must stay available for points sign-in")

    async def fake_is_teacher(*args, **kwargs):
        return False

    async def fake_is_whitelisted(*args, **kwargs):
        return False

    monkeypatch.setattr(TeacherSearchService, "get_setting", fake_get_teacher_setting)
    monkeypatch.setattr(CarReviewService, "get_setting", fake_get_car_review_setting)
    monkeypatch.setattr(CarReviewService, "list_rankings", forbidden_list_rankings)
    monkeypatch.setattr(GarageAuthService, "is_certified_teacher", fake_is_teacher)
    monkeypatch.setattr(GarageAuthService, "is_whitelisted", fake_is_whitelisted)

    handled = await _process_garage_features(
        SimpleNamespace(application=SimpleNamespace(bot_data={})),
        db,
        SimpleNamespace(id=-1001, title="测试群"),
        SimpleNamespace(id=42),
        SimpleNamespace(message_id=9, location=None, reply_to_message=None),
        "签到",
        SimpleNamespace(garage_limit_enabled=False),
        False,
    )

    assert handled is False


@pytest.mark.asyncio
async def test_process_garage_features_exact_lookup_replies_teacher_reviews(monkeypatch):
    session = _FakeSession()
    db = _FakeDb(session)
    replies: list[str] = []
    teacher = SimpleNamespace(id=77, username="teacher77", first_name="T", last_name=None)
    report = SimpleNamespace(
        report_id=5,
        author_user_id=42,
        created_at=dt.datetime(2026, 1, 2, tzinfo=dt.UTC),
        scores={"total_score": 9},
        review_text="体验很好",
    )

    async def fake_get_teacher_setting(*args, **kwargs):
        return SimpleNamespace(
            nearby_search_enabled=False,
            attendance_enabled=False,
            force_location_enabled=False,
            footer_button_label=None,
        )

    async def fake_get_car_review_setting(*args, **kwargs):
        return SimpleNamespace(
            enabled=True,
            rank_command="出击排行",
            submit_command="提交报告",
            teacher_lookup_mode="exact",
        )

    async def fake_find_teacher(session, chat_id: int, username: str):
        return teacher if username == "teacher77" else None

    async def fake_list_reports(session, chat_id: int, teacher_user_id: int, *, limit: int = 5):
        return [(report, SimpleNamespace(id=42, username="author42", first_name="A", last_name=None))]

    async def fake_stats(session, chat_id: int, teacher_user_id: int):
        return {"count": 1, "avg_score": 9}

    async def fake_reply(context, *, chat_id, text, reply_to_message_id=None, **kwargs):
        replies.append(text)

    async def fake_is_teacher(*args, **kwargs):
        return False

    async def fake_is_whitelisted(*args, **kwargs):
        return False

    monkeypatch.setattr(TeacherSearchService, "get_setting", fake_get_teacher_setting)
    monkeypatch.setattr(CarReviewService, "get_setting", fake_get_car_review_setting)
    monkeypatch.setattr(CarReviewService, "find_lookup_teacher_by_username", fake_find_teacher)
    monkeypatch.setattr(CarReviewService, "list_reports_for_teacher", fake_list_reports)
    monkeypatch.setattr(CarReviewService, "get_teacher_review_stats", fake_stats)
    monkeypatch.setattr(GarageAuthService, "is_certified_teacher", fake_is_teacher)
    monkeypatch.setattr(GarageAuthService, "is_whitelisted", fake_is_whitelisted)
    monkeypatch.setattr(group_message_handler.PublishService, "reply", fake_reply)

    handled = await _process_garage_features(
        SimpleNamespace(application=SimpleNamespace(bot_data={})),
        db,
        SimpleNamespace(id=-1001, title="测试群"),
        SimpleNamespace(id=42),
        SimpleNamespace(message_id=9, location=None, reply_to_message=None),
        "@teacher77",
        SimpleNamespace(garage_limit_enabled=False),
        False,
    )

    assert handled is True
    assert replies
    assert "@teacher77 的车评：" in replies[0]
    assert "体验很好" in replies[0]


@pytest.mark.asyncio
async def test_process_garage_features_handles_nearby_command(monkeypatch):
    session = _FakeSession()
    db = _FakeDb(session)
    replies = []

    async def fake_get_teacher_setting(*args, **kwargs):
        return SimpleNamespace(
            nearby_search_enabled=True,
            only_open_course_enabled=True,
            attendance_enabled=False,
            force_location_enabled=False,
            footer_button_label=None,
        )

    async def fake_get_car_review_setting(*args, **kwargs):
        return SimpleNamespace(enabled=False, rank_command="出击排行", submit_command="提交报告")

    async def fake_get_member_location(*args, **kwargs):
        return SimpleNamespace(latitude=31.2304, longitude=121.4738)

    async def fake_list_nearby(*args, **kwargs):
        return [
            {
                "profile": SimpleNamespace(region_text="A区", price_text="100"),
                "display_name": "@teacher_a",
                "distance_text": "500米内",
            }
        ]

    async def fake_reply(context, *, chat_id, text, reply_to_message_id=None, **kwargs):
        replies.append((chat_id, text, reply_to_message_id))

    async def fake_is_teacher(*args, **kwargs):
        return False

    async def fake_is_whitelisted(*args, **kwargs):
        return False

    async def fake_mark_attendance(*args, **kwargs):
        return None

    monkeypatch.setattr(TeacherSearchService, "get_setting", fake_get_teacher_setting)
    monkeypatch.setattr(CarReviewService, "get_setting", fake_get_car_review_setting)
    monkeypatch.setattr(TeacherSearchService, "get_member_location", fake_get_member_location)
    monkeypatch.setattr(TeacherSearchService, "list_nearby_teachers", fake_list_nearby)
    monkeypatch.setattr(TeacherSearchService, "mark_attendance", fake_mark_attendance)
    monkeypatch.setattr(GarageAuthService, "is_certified_teacher", fake_is_teacher)
    monkeypatch.setattr(GarageAuthService, "is_whitelisted", fake_is_whitelisted)
    monkeypatch.setattr(group_message_handler.PublishService, "reply", fake_reply)

    handled = await _process_garage_features(
        SimpleNamespace(application=SimpleNamespace(bot_data={})),
        db,
        SimpleNamespace(id=-1001, title="测试群"),
        SimpleNamespace(id=42),
        SimpleNamespace(message_id=9, location=None, reply_to_message=None),
        "附近",
        SimpleNamespace(garage_limit_enabled=False),
        False,
    )

    assert handled is True
    assert replies and "附近老师" in replies[0][1]


@pytest.mark.asyncio
async def test_process_garage_features_nearby_uses_only_open_setting(monkeypatch):
    session = _FakeSession()
    db = _FakeDb(session)
    seen: dict[str, object] = {}

    async def fake_get_teacher_setting(*args, **kwargs):
        return SimpleNamespace(
            nearby_search_enabled=True,
            only_open_course_enabled=False,
            attendance_enabled=False,
            force_location_enabled=False,
            footer_button_label=None,
            delete_mode="none",
        )

    async def fake_get_car_review_setting(*args, **kwargs):
        return SimpleNamespace(enabled=False, rank_command="出击排行", submit_command="提交报告")

    async def fake_get_member_location(*args, **kwargs):
        return SimpleNamespace(latitude=31.2304, longitude=121.4738)

    async def fake_list_nearby(*args, **kwargs):
        seen["only_open_course"] = kwargs.get("only_open_course")
        return []

    async def fake_reply(*args, **kwargs):
        return None

    async def fake_is_teacher(*args, **kwargs):
        return False

    async def fake_is_whitelisted(*args, **kwargs):
        return False

    monkeypatch.setattr(TeacherSearchService, "get_setting", fake_get_teacher_setting)
    monkeypatch.setattr(CarReviewService, "get_setting", fake_get_car_review_setting)
    monkeypatch.setattr(TeacherSearchService, "get_member_location", fake_get_member_location)
    monkeypatch.setattr(TeacherSearchService, "list_nearby_teachers", fake_list_nearby)
    monkeypatch.setattr(GarageAuthService, "is_certified_teacher", fake_is_teacher)
    monkeypatch.setattr(GarageAuthService, "is_whitelisted", fake_is_whitelisted)
    monkeypatch.setattr(group_message_handler.PublishService, "reply", fake_reply)

    handled = await _process_garage_features(
        SimpleNamespace(application=SimpleNamespace(bot_data={})),
        db,
        SimpleNamespace(id=-1001, title="测试群"),
        SimpleNamespace(id=42),
        SimpleNamespace(message_id=9, location=None, reply_to_message=None),
        "附近",
        SimpleNamespace(garage_limit_enabled=False),
        False,
    )

    assert handled is True
    assert seen["only_open_course"] is False


@pytest.mark.asyncio
async def test_process_garage_features_tag_search_uses_only_open_setting(monkeypatch):
    session = _FakeSession()
    db = _FakeDb(session)
    seen: dict[str, object] = {}

    async def fake_get_teacher_setting(*args, **kwargs):
        return SimpleNamespace(
            tag_search_enabled=True,
            nearby_search_enabled=False,
            only_open_course_enabled=False,
            attendance_enabled=False,
            force_location_enabled=False,
            footer_button_label=None,
            delete_mode="none",
        )

    async def fake_get_car_review_setting(*args, **kwargs):
        return SimpleNamespace(enabled=False, rank_command="出击排行", submit_command="提交报告")

    async def fake_search(*args, **kwargs):
        seen["only_open_course"] = kwargs.get("only_open_course")
        return []

    async def fake_reply(*args, **kwargs):
        return None

    async def fake_is_teacher(*args, **kwargs):
        return False

    async def fake_is_whitelisted(*args, **kwargs):
        return False

    monkeypatch.setattr(TeacherSearchService, "get_setting", fake_get_teacher_setting)
    monkeypatch.setattr(CarReviewService, "get_setting", fake_get_car_review_setting)
    monkeypatch.setattr(TeacherSearchService, "search_teachers_by_keyword", fake_search)
    monkeypatch.setattr(GarageAuthService, "is_certified_teacher", fake_is_teacher)
    monkeypatch.setattr(GarageAuthService, "is_whitelisted", fake_is_whitelisted)
    monkeypatch.setattr(group_message_handler.PublishService, "reply", fake_reply)

    handled = await _process_garage_features(
        SimpleNamespace(application=SimpleNamespace(bot_data={})),
        db,
        SimpleNamespace(id=-1001, title="测试群"),
        SimpleNamespace(id=42),
        SimpleNamespace(message_id=9, location=None, reply_to_message=None),
        "老师搜索 标签",
        SimpleNamespace(garage_limit_enabled=False),
        False,
    )

    assert handled is True
    assert seen["only_open_course"] is False


@pytest.mark.asyncio
async def test_process_garage_features_bare_keyword_runs_tag_search_when_matched(monkeypatch):
    session = _FakeSession()
    db = _FakeDb(session)
    replies: list[str] = []
    seen: list[str] = []

    async def fake_get_teacher_setting(*args, **kwargs):
        return SimpleNamespace(
            tag_search_enabled=True,
            nearby_search_enabled=False,
            only_open_course_enabled=False,
            attendance_enabled=False,
            force_location_enabled=False,
            footer_button_label=None,
            delete_mode="none",
        )

    async def fake_get_car_review_setting(*args, **kwargs):
        return SimpleNamespace(enabled=False, rank_command="出击排行", submit_command="提交报告")

    async def fake_search(session, chat_id: int, keyword: str, **kwargs):
        seen.append(keyword)
        if keyword != "整形":
            return []
        return [
            (
                SimpleNamespace(
                    user_id=77,
                    labels=["整形", "颜值车"],
                    region_text="西河区",
                    price_text="800/50分钟",
                    latitude=None,
                    longitude=None,
                    open_course_today=False,
                    open_course_status=None,
                ),
                SimpleNamespace(id=77, username="jt37373", first_name=None, last_name=None),
            )
        ]

    async def fake_reply(context, *, chat_id, text, reply_to_message_id=None, **kwargs):
        replies.append(text)

    async def fake_is_teacher(*args, **kwargs):
        return False

    async def fake_is_whitelisted(*args, **kwargs):
        return False

    monkeypatch.setattr(TeacherSearchService, "get_setting", fake_get_teacher_setting)
    monkeypatch.setattr(CarReviewService, "get_setting", fake_get_car_review_setting)
    monkeypatch.setattr(TeacherSearchService, "search_teachers_by_keyword", fake_search)
    monkeypatch.setattr(GarageAuthService, "is_certified_teacher", fake_is_teacher)
    monkeypatch.setattr(GarageAuthService, "is_whitelisted", fake_is_whitelisted)
    monkeypatch.setattr(group_message_handler.PublishService, "reply", fake_reply)

    handled = await _process_garage_features(
        SimpleNamespace(application=SimpleNamespace(bot_data={})),
        db,
        SimpleNamespace(id=-1001, title="测试群"),
        SimpleNamespace(id=42),
        SimpleNamespace(message_id=9, location=None, reply_to_message=None),
        "整形",
        SimpleNamespace(garage_limit_enabled=False),
        False,
    )

    assert handled is True
    assert seen == ["整形"]
    assert replies == [
        "老师搜索：整形\n"
        "1. 🤝 @jt37373 · 未开课 · 未定位，资料完整 · 整形 颜值车 / 西河区 / 800/50分钟"
    ]


@pytest.mark.asyncio
async def test_process_garage_features_bare_keyword_ignores_no_match(monkeypatch):
    session = _FakeSession()
    db = _FakeDb(session)

    async def fake_get_teacher_setting(*args, **kwargs):
        return SimpleNamespace(
            tag_search_enabled=True,
            nearby_search_enabled=False,
            only_open_course_enabled=False,
            attendance_enabled=False,
            force_location_enabled=False,
            footer_button_label=None,
            delete_mode="none",
        )

    async def fake_get_car_review_setting(*args, **kwargs):
        return SimpleNamespace(enabled=False, rank_command="出击排行", submit_command="提交报告")

    async def fake_search(*args, **kwargs):
        return []

    async def fake_is_teacher(*args, **kwargs):
        return False

    async def fake_is_whitelisted(*args, **kwargs):
        return False

    monkeypatch.setattr(TeacherSearchService, "get_setting", fake_get_teacher_setting)
    monkeypatch.setattr(CarReviewService, "get_setting", fake_get_car_review_setting)
    monkeypatch.setattr(TeacherSearchService, "search_teachers_by_keyword", fake_search)
    monkeypatch.setattr(GarageAuthService, "is_certified_teacher", fake_is_teacher)
    monkeypatch.setattr(GarageAuthService, "is_whitelisted", fake_is_whitelisted)

    handled = await _process_garage_features(
        SimpleNamespace(application=SimpleNamespace(bot_data={})),
        db,
        SimpleNamespace(id=-1001, title="测试群"),
        SimpleNamespace(id=42),
        SimpleNamespace(message_id=9, location=None, reply_to_message=None),
        "没命中的普通聊天",
        SimpleNamespace(garage_limit_enabled=False),
        False,
    )

    assert handled is False


@pytest.mark.asyncio
async def test_process_garage_features_tag_search_falls_back_to_all_certified_when_only_open_has_no_match(monkeypatch):
    session = _FakeSession()
    db = _FakeDb(session)
    replies: list[str] = []
    seen: list[bool] = []

    async def fake_get_teacher_setting(*args, **kwargs):
        return SimpleNamespace(
            tag_search_enabled=True,
            nearby_search_enabled=False,
            only_open_course_enabled=True,
            attendance_enabled=False,
            force_location_enabled=False,
            footer_button_label=None,
            delete_mode="none",
        )

    async def fake_get_car_review_setting(*args, **kwargs):
        return SimpleNamespace(enabled=False, rank_command="出击排行", submit_command="提交报告")

    async def fake_search(*args, **kwargs):
        only_open = kwargs.get("only_open_course")
        seen.append(only_open)
        if only_open:
            return []
        return [
            (
                SimpleNamespace(
                    user_id=77,
                    labels=[],
                    region_text=None,
                    price_text="500",
                    latitude=None,
                    longitude=None,
                    open_course_today=False,
                    open_course_status=None,
                ),
                SimpleNamespace(id=77, username="teacher500", first_name=None, last_name=None),
            )
        ]

    async def fake_reply(context, *, chat_id, text, reply_to_message_id=None, **kwargs):
        replies.append(text)

    async def fake_is_teacher(*args, **kwargs):
        return False

    async def fake_is_whitelisted(*args, **kwargs):
        return False

    monkeypatch.setattr(TeacherSearchService, "get_setting", fake_get_teacher_setting)
    monkeypatch.setattr(CarReviewService, "get_setting", fake_get_car_review_setting)
    monkeypatch.setattr(TeacherSearchService, "search_teachers_by_keyword", fake_search)
    monkeypatch.setattr(GarageAuthService, "is_certified_teacher", fake_is_teacher)
    monkeypatch.setattr(GarageAuthService, "is_whitelisted", fake_is_whitelisted)
    monkeypatch.setattr(group_message_handler.PublishService, "reply", fake_reply)

    handled = await _process_garage_features(
        SimpleNamespace(application=SimpleNamespace(bot_data={})),
        db,
        SimpleNamespace(id=-1001, title="测试群"),
        SimpleNamespace(id=42),
        SimpleNamespace(message_id=9, location=None, reply_to_message=None),
        "老师搜索 500左右",
        SimpleNamespace(garage_limit_enabled=False),
        False,
    )

    assert handled is True
    assert seen == [True, False]
    assert replies == [
        "老师搜索：500左右\n"
        "未找到今日开课匹配老师，已显示全部认证老师。\n"
        "1. 🤝 @teacher500 · 未开课 · 未定位，资料完整 · 500"
    ]


@pytest.mark.asyncio
async def test_process_garage_features_teacher_search_nearby_condition_runs_nearby(monkeypatch):
    session = _FakeSession()
    db = _FakeDb(session)
    replies: list[str] = []
    seen: dict[str, object] = {}

    async def fake_get_teacher_setting(*args, **kwargs):
        return SimpleNamespace(
            tag_search_enabled=True,
            nearby_search_enabled=True,
            only_open_course_enabled=False,
            attendance_enabled=False,
            force_location_enabled=False,
            footer_button_label=None,
            delete_mode="none",
        )

    async def fake_get_car_review_setting(*args, **kwargs):
        return SimpleNamespace(enabled=False, rank_command="出击排行", submit_command="提交报告")

    async def fake_get_member_location(*args, **kwargs):
        return SimpleNamespace(latitude=31.2304, longitude=121.4738)

    async def fake_list_nearby(*args, **kwargs):
        seen["called"] = True
        seen["keyword"] = kwargs.get("keyword")
        return [
            {
                "profile": SimpleNamespace(region_text="A区", price_text="500", open_course_status=None),
                "display_name": "@teacher_a",
                "distance_text": "500米内",
            }
        ]

    async def fake_reply(context, *, chat_id, text, reply_to_message_id=None, **kwargs):
        replies.append(text)

    async def fake_is_teacher(*args, **kwargs):
        return False

    async def fake_is_whitelisted(*args, **kwargs):
        return False

    monkeypatch.setattr(TeacherSearchService, "get_setting", fake_get_teacher_setting)
    monkeypatch.setattr(CarReviewService, "get_setting", fake_get_car_review_setting)
    monkeypatch.setattr(TeacherSearchService, "get_member_location", fake_get_member_location)
    monkeypatch.setattr(TeacherSearchService, "list_nearby_teachers", fake_list_nearby)
    monkeypatch.setattr(GarageAuthService, "is_certified_teacher", fake_is_teacher)
    monkeypatch.setattr(GarageAuthService, "is_whitelisted", fake_is_whitelisted)
    monkeypatch.setattr(group_message_handler.PublishService, "reply", fake_reply)

    handled = await _process_garage_features(
        SimpleNamespace(application=SimpleNamespace(bot_data={})),
        db,
        SimpleNamespace(id=-1001, title="测试群"),
        SimpleNamespace(id=42),
        SimpleNamespace(message_id=9, location=None, reply_to_message=None),
        "老师搜索 附近+500左右",
        SimpleNamespace(garage_limit_enabled=False),
        False,
    )

    assert handled is True
    assert seen["called"] is True
    assert seen["keyword"] == "500左右"
    assert replies == ["附近老师：500左右\n1. 🤝 @teacher_a · 未开课 · 500米内 · A区 / 500"]


@pytest.mark.asyncio
async def test_process_garage_features_nearby_condition_command_runs_nearby(monkeypatch):
    session = _FakeSession()
    db = _FakeDb(session)
    seen: dict[str, object] = {}

    async def fake_get_teacher_setting(*args, **kwargs):
        return SimpleNamespace(
            tag_search_enabled=True,
            nearby_search_enabled=True,
            only_open_course_enabled=False,
            attendance_enabled=False,
            force_location_enabled=False,
            footer_button_label=None,
            delete_mode="none",
        )

    async def fake_get_car_review_setting(*args, **kwargs):
        return SimpleNamespace(enabled=False, rank_command="出击排行", submit_command="提交报告")

    async def fake_get_member_location(*args, **kwargs):
        return SimpleNamespace(latitude=31.2304, longitude=121.4738)

    async def fake_list_nearby(*args, **kwargs):
        seen["keyword"] = kwargs.get("keyword")
        return []

    async def fake_reply(*args, **kwargs):
        return None

    async def fake_is_teacher(*args, **kwargs):
        return False

    async def fake_is_whitelisted(*args, **kwargs):
        return False

    monkeypatch.setattr(TeacherSearchService, "get_setting", fake_get_teacher_setting)
    monkeypatch.setattr(CarReviewService, "get_setting", fake_get_car_review_setting)
    monkeypatch.setattr(TeacherSearchService, "get_member_location", fake_get_member_location)
    monkeypatch.setattr(TeacherSearchService, "list_nearby_teachers", fake_list_nearby)
    monkeypatch.setattr(GarageAuthService, "is_certified_teacher", fake_is_teacher)
    monkeypatch.setattr(GarageAuthService, "is_whitelisted", fake_is_whitelisted)
    monkeypatch.setattr(group_message_handler.PublishService, "reply", fake_reply)

    handled = await _process_garage_features(
        SimpleNamespace(application=SimpleNamespace(bot_data={})),
        db,
        SimpleNamespace(id=-1001, title="测试群"),
        SimpleNamespace(id=42),
        SimpleNamespace(message_id=9, location=None, reply_to_message=None),
        "附近 500左右",
        SimpleNamespace(garage_limit_enabled=False),
        False,
    )

    assert handled is True
    assert seen["keyword"] == "500左右"


@pytest.mark.asyncio
async def test_process_garage_features_tag_search_displays_status_and_profile_state(monkeypatch):
    session = _FakeSession()
    db = _FakeDb(session)
    replies: list[str] = []

    async def fake_get_teacher_setting(*args, **kwargs):
        return SimpleNamespace(
            tag_search_enabled=True,
            nearby_search_enabled=False,
            only_open_course_enabled=False,
            attendance_enabled=False,
            force_location_enabled=False,
            footer_button_label=None,
            delete_mode="none",
        )

    async def fake_get_car_review_setting(*args, **kwargs):
        return SimpleNamespace(enabled=False, rank_command="出击排行", submit_command="提交报告")

    async def fake_search(*args, **kwargs):
        return [
            (
                SimpleNamespace(
                    user_id=77,
                    labels=[],
                    region_text="A区",
                    price_text=None,
                    latitude=None,
                    longitude=None,
                    open_course_today=False,
                    open_course_status=None,
                ),
                SimpleNamespace(id=77, username="teacher_empty", first_name="空", last_name="资料"),
            )
        ]

    async def fake_reply(context, *, chat_id, text, reply_to_message_id=None, **kwargs):
        replies.append(text)

    async def fake_is_teacher(*args, **kwargs):
        return False

    async def fake_is_whitelisted(*args, **kwargs):
        return False

    monkeypatch.setattr(TeacherSearchService, "get_setting", fake_get_teacher_setting)
    monkeypatch.setattr(CarReviewService, "get_setting", fake_get_car_review_setting)
    monkeypatch.setattr(TeacherSearchService, "search_teachers_by_keyword", fake_search)
    monkeypatch.setattr(GarageAuthService, "is_certified_teacher", fake_is_teacher)
    monkeypatch.setattr(GarageAuthService, "is_whitelisted", fake_is_whitelisted)
    monkeypatch.setattr(group_message_handler.PublishService, "reply", fake_reply)

    handled = await _process_garage_features(
        SimpleNamespace(application=SimpleNamespace(bot_data={})),
        db,
        SimpleNamespace(id=-1001, title="测试群"),
        SimpleNamespace(id=42),
        SimpleNamespace(message_id=9, location=None, reply_to_message=None),
        "老师搜索 teacher_empty",
        SimpleNamespace(garage_limit_enabled=False),
        False,
    )

    assert handled is True
    assert replies == ["老师搜索：teacher_empty\n1. 🤝 @teacher_empty · 未开课 · 未定位，资料完整 · A区"]


@pytest.mark.asyncio
async def test_process_garage_features_car_review_submit_entry_returns_private_link(monkeypatch):
    session = _FakeSession()
    db = _FakeDb(session)
    replies: list[dict[str, object]] = []

    async def fake_get_teacher_setting(*args, **kwargs):
        return SimpleNamespace(
            nearby_search_enabled=False,
            attendance_enabled=False,
            force_location_enabled=False,
            footer_button_label=None,
        )

    async def fake_get_car_review_setting(*args, **kwargs):
        return SimpleNamespace(
            enabled=True,
            rank_command="出击排行",
            submit_command="提交报告",
            approver_user_id=9001,
        )

    async def fake_is_teacher(*args, **kwargs):
        return False

    async def fake_is_whitelisted(*args, **kwargs):
        return False

    async def fake_reply(context, *, chat_id, text, reply_to_message_id=None, reply_markup=None, **kwargs):
        replies.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})

    monkeypatch.setattr(TeacherSearchService, "get_setting", fake_get_teacher_setting)
    monkeypatch.setattr(CarReviewService, "get_setting", fake_get_car_review_setting)
    monkeypatch.setattr(GarageAuthService, "is_certified_teacher", fake_is_teacher)
    monkeypatch.setattr(GarageAuthService, "is_whitelisted", fake_is_whitelisted)
    monkeypatch.setattr(group_message_handler.PublishService, "reply", fake_reply)

    handled = await _process_garage_features(
        SimpleNamespace(application=SimpleNamespace(bot_data={}), bot=SimpleNamespace(username="test_bot")),
        db,
        SimpleNamespace(id=-1001, title="测试群"),
        SimpleNamespace(id=42),
        SimpleNamespace(message_id=9, location=None, reply_to_message=None),
        "提交车评",
        SimpleNamespace(garage_limit_enabled=False),
        False,
    )

    assert handled is True
    assert "到机器人私聊提交车评" in replies[0]["text"]
    button = replies[0]["reply_markup"].inline_keyboard[0][0]
    assert button.url == "https://t.me/test_bot?start=crvsub_-1001"


@pytest.mark.asyncio
async def test_private_car_review_submit_teacher_input_enters_body_state(monkeypatch):
    teacher = SimpleNamespace(id=77, username="teacher77", first_name="T", last_name=None)
    session = _FakeSession(execute_results=[_ExecuteResult(scalar=teacher)], get_map={(TgUser, 77): teacher})
    replies: list[str] = []
    states: list[dict[str, object]] = []

    async def fake_get_setting(*args, **kwargs):
        return SimpleNamespace(enabled=True, approver_user_id=9001)

    async def fake_is_effective_teacher(*args, **kwargs):
        return True

    async def fake_list_custom_fields(*args, **kwargs):
        return [SimpleNamespace(field_label="颜值", enabled=True), SimpleNamespace(field_label="过程", enabled=True)]

    async def fake_set_user_state(session, **kwargs):
        states.append(kwargs)

    async def fake_reply_text(text, **kwargs):
        replies.append(text)

    monkeypatch.setattr(CarReviewService, "get_setting", fake_get_setting)
    monkeypatch.setattr(CarReviewService, "list_custom_fields", fake_list_custom_fields)
    monkeypatch.setattr(GarageAuthService, "is_effective_certified_teacher", fake_is_effective_teacher)
    monkeypatch.setattr(review_submit, "set_user_state", fake_set_user_state)

    await review_submit.handle_car_review_submit_input(
        SimpleNamespace(
            effective_message=SimpleNamespace(reply_text=fake_reply_text),
            effective_user=SimpleNamespace(id=42),
        ),
        SimpleNamespace(),
        session,
        SimpleNamespace(
            chat_id=42,
            state_type=review_submit.TEACHER_STATE,
            state_data={"target_chat_id": -1001},
        ),
        "@teacher77",
    )

    assert states == [
        {
            "chat_id": 42,
            "user_id": 42,
            "state_type": review_submit.BODY_STATE,
            "state_data": {"target_chat_id": -1001, "teacher_user_id": 77},
        }
    ]
    assert "已选择老师" in replies[0]
    assert "颜值" in replies[0]


@pytest.mark.asyncio
async def test_private_car_review_submit_body_creates_pending_report_and_notifies_approver(monkeypatch):
    session = _FakeSession(
        get_map={
            (TgUser, 77): SimpleNamespace(id=77, username="teacher77", first_name="T", last_name=None),
        }
    )
    replies: list[str] = []
    cleared: list[tuple[int, int]] = []
    sent: list[dict[str, object]] = []
    created: list[dict[str, object]] = []

    async def fake_get_setting(*args, **kwargs):
        return SimpleNamespace(enabled=True, approver_user_id=9001, review_mode="simple")

    async def fake_list_custom_fields(*args, **kwargs):
        return []

    async def fake_create_report(session, **kwargs):
        created.append(kwargs)
        return SimpleNamespace(report_id=5)

    async def fake_clear_user_state(session, *, chat_id, user_id):
        cleared.append((chat_id, user_id))

    async def fake_send(context, **kwargs):
        sent.append(kwargs)

    async def fake_reply_text(text, **kwargs):
        replies.append(text)

    monkeypatch.setattr(CarReviewService, "get_setting", fake_get_setting)
    monkeypatch.setattr(CarReviewService, "list_custom_fields", fake_list_custom_fields)
    monkeypatch.setattr(CarReviewService, "create_report", fake_create_report)
    monkeypatch.setattr(review_submit, "clear_user_state", fake_clear_user_state)
    monkeypatch.setattr(review_submit.PublishService, "send", fake_send)

    await review_submit.handle_car_review_submit_input(
        SimpleNamespace(
            effective_message=SimpleNamespace(reply_text=fake_reply_text, photo=None, video=None, document=None),
            effective_user=SimpleNamespace(id=42, username="author42", first_name="A", last_name=None),
        ),
        SimpleNamespace(),
        session,
        SimpleNamespace(
            chat_id=42,
            state_type=review_submit.BODY_STATE,
            state_data={"target_chat_id": -1001, "teacher_user_id": 77},
        ),
        "服务不错",
    )

    assert created[0]["chat_id"] == -1001
    assert created[0]["teacher_user_id"] == 77
    assert created[0]["author_user_id"] == 42
    assert created[0]["review_text"] == "服务不错"
    assert cleared == [(42, 42)]
    assert replies == ["车评已提交，等待审核。报告ID：5"]
    assert sent[0]["chat_id"] == 9001
    assert "报告ID：5" in sent[0]["text"]


@pytest.mark.asyncio
async def test_process_garage_features_submits_car_review_pending_admin_review(monkeypatch):
    session = _FakeSession(get_map={(TgUser, 77): SimpleNamespace(id=77, username="teacher77", first_name="T", last_name=None), (TgUser, 42): SimpleNamespace(id=42, username="author42", first_name="A", last_name=None)})
    db = _FakeDb(session)
    replies = []

    report = SimpleNamespace(report_id=5)

    async def fake_get_teacher_setting(*args, **kwargs):
        return SimpleNamespace(
            nearby_search_enabled=False,
            attendance_enabled=False,
            force_location_enabled=False,
            footer_button_label=None,
        )

    async def fake_get_car_review_setting(*args, **kwargs):
        return SimpleNamespace(
            enabled=True,
            rank_command="出击排行",
            submit_command="提交报告",
            approver_user_id=9001,
            reward_points=100,
            publish_to_main_group=True,
            template_text="【老师】{teacher}\n【留名】{author}\n【评价】{review}\n【综合】{total_score}",
        )

    async def fake_create_report(*args, **kwargs):
        return report

    async def fake_send(context, *, chat_id, text, parse_mode=None, **kwargs):
        return SimpleNamespace(message_id=888)

    async def fake_reply(context, *, chat_id, text, reply_to_message_id=None, **kwargs):
        replies.append(text)

    async def fake_is_teacher(*args, **kwargs):
        return False

    async def fake_is_whitelisted(*args, **kwargs):
        return False

    async def fake_mark_attendance(*args, **kwargs):
        return None

    monkeypatch.setattr(TeacherSearchService, "get_setting", fake_get_teacher_setting)
    monkeypatch.setattr(CarReviewService, "get_setting", fake_get_car_review_setting)
    monkeypatch.setattr(CarReviewService, "create_report", fake_create_report)
    monkeypatch.setattr(TeacherSearchService, "mark_attendance", fake_mark_attendance)
    monkeypatch.setattr(GarageAuthService, "is_certified_teacher", fake_is_teacher)
    monkeypatch.setattr(GarageAuthService, "is_whitelisted", fake_is_whitelisted)
    monkeypatch.setattr(group_message_handler.PublishService, "send", fake_send)
    monkeypatch.setattr(group_message_handler.PublishService, "reply", fake_reply)

    handled = await _process_garage_features(
        SimpleNamespace(application=SimpleNamespace(bot_data={})),
        db,
        SimpleNamespace(id=-1001, title="测试群"),
        SimpleNamespace(id=42, first_name="Author", last_name=None, username=None),
        SimpleNamespace(
            message_id=12,
            location=None,
            reply_to_message=SimpleNamespace(from_user=SimpleNamespace(id=77)),
        ),
        "提交报告 很棒",
        SimpleNamespace(garage_limit_enabled=False),
        False,
    )

    assert handled is True
    assert any("等待审核" in text for text in replies)


@pytest.mark.asyncio
async def test_process_garage_features_respects_nearby_search_switch(monkeypatch):
    session = _FakeSession()
    db = _FakeDb(session)
    replies = []

    async def fake_get_teacher_setting(*args, **kwargs):
        return SimpleNamespace(
            nearby_search_enabled=False,
            attendance_enabled=False,
            force_location_enabled=False,
            footer_button_label=None,
            delete_mode="none",
        )

    async def fake_get_car_review_setting(*args, **kwargs):
        return SimpleNamespace(enabled=False, rank_command="出击排行", submit_command="提交报告")

    async def fake_reply(context, *, chat_id, text, reply_to_message_id=None, **kwargs):
        replies.append(text)

    async def fake_is_teacher(*args, **kwargs):
        return False

    async def fake_is_whitelisted(*args, **kwargs):
        return False

    async def fake_mark_attendance(*args, **kwargs):
        return None

    monkeypatch.setattr(TeacherSearchService, "get_setting", fake_get_teacher_setting)
    monkeypatch.setattr(CarReviewService, "get_setting", fake_get_car_review_setting)
    monkeypatch.setattr(TeacherSearchService, "mark_attendance", fake_mark_attendance)
    monkeypatch.setattr(GarageAuthService, "is_certified_teacher", fake_is_teacher)
    monkeypatch.setattr(GarageAuthService, "is_whitelisted", fake_is_whitelisted)
    monkeypatch.setattr(group_message_handler.PublishService, "reply", fake_reply)

    handled = await _process_garage_features(
        SimpleNamespace(application=SimpleNamespace(bot_data={})),
        db,
        SimpleNamespace(id=-1001, title="测试群"),
        SimpleNamespace(id=42),
        SimpleNamespace(message_id=9, location=None, reply_to_message=None),
        "附近",
        SimpleNamespace(garage_limit_enabled=False),
        False,
    )

    assert handled is True
    assert replies == ["附近搜索已关闭。"]


@pytest.mark.asyncio
async def test_process_garage_features_nearby_without_location_prompts_private_update(monkeypatch):
    session = _FakeSession()
    db = _FakeDb(session)
    replies: list[tuple[str, object]] = []

    async def fake_get_teacher_setting(*args, **kwargs):
        return SimpleNamespace(
            nearby_search_enabled=True,
            only_open_course_enabled=True,
            attendance_enabled=False,
            force_location_enabled=False,
            footer_button_label=None,
            delete_mode="none",
        )

    async def fake_get_car_review_setting(*args, **kwargs):
        return SimpleNamespace(enabled=False, rank_command="出击排行", submit_command="提交报告")

    async def fake_get_member_location(*args, **kwargs):
        return None

    async def fake_reply(context, *, chat_id, text, reply_to_message_id=None, **kwargs):
        replies.append((text, kwargs.get("reply_markup")))

    async def fake_is_teacher(*args, **kwargs):
        return False

    async def fake_is_whitelisted(*args, **kwargs):
        return False

    monkeypatch.setattr(TeacherSearchService, "get_setting", fake_get_teacher_setting)
    monkeypatch.setattr(CarReviewService, "get_setting", fake_get_car_review_setting)
    monkeypatch.setattr(TeacherSearchService, "get_member_location", fake_get_member_location)
    monkeypatch.setattr(GarageAuthService, "is_certified_teacher", fake_is_teacher)
    monkeypatch.setattr(GarageAuthService, "is_whitelisted", fake_is_whitelisted)
    monkeypatch.setattr(group_message_handler.PublishService, "reply", fake_reply)

    handled = await _process_garage_features(
        SimpleNamespace(application=SimpleNamespace(bot_data={}), bot=SimpleNamespace(username="TestBot")),
        db,
        SimpleNamespace(id=-1001, title="测试群"),
        SimpleNamespace(id=42),
        SimpleNamespace(message_id=9, location=None, venue=None, reply_to_message=None),
        "附近",
        SimpleNamespace(garage_limit_enabled=False),
        False,
    )

    assert handled is True
    assert "为了保护隐私" in replies[0][0]
    button = replies[0][1].inline_keyboard[0][0]
    assert button.text == "私聊更新定位"
    assert button.url == "https://t.me/TestBot?start=tloc_-1001"


@pytest.mark.asyncio
async def test_process_garage_features_footer_button_shows_teacher_search_guide(monkeypatch):
    session = _FakeSession()
    db = _FakeDb(session)
    replies: list[str] = []

    async def fake_get_teacher_setting(*args, **kwargs):
        return SimpleNamespace(
            nearby_search_enabled=True,
            attendance_enabled=False,
            force_location_enabled=False,
            footer_button_label=None,
            delete_mode="none",
        )

    async def fake_get_car_review_setting(*args, **kwargs):
        return SimpleNamespace(enabled=False, rank_command="出击排行", submit_command="提交报告")

    async def fake_reply(context, *, chat_id, text, reply_to_message_id=None, **kwargs):
        replies.append(text)

    async def fake_is_teacher(*args, **kwargs):
        return False

    async def fake_is_whitelisted(*args, **kwargs):
        return False

    monkeypatch.setattr(TeacherSearchService, "get_setting", fake_get_teacher_setting)
    monkeypatch.setattr(CarReviewService, "get_setting", fake_get_car_review_setting)
    monkeypatch.setattr(GarageAuthService, "is_certified_teacher", fake_is_teacher)
    monkeypatch.setattr(GarageAuthService, "is_whitelisted", fake_is_whitelisted)
    monkeypatch.setattr(group_message_handler.PublishService, "reply", fake_reply)

    handled = await _process_garage_features(
        SimpleNamespace(application=SimpleNamespace(bot_data={})),
        db,
        SimpleNamespace(id=-1001, title="测试群"),
        SimpleNamespace(id=42),
        SimpleNamespace(message_id=9, location=None, venue=None, reply_to_message=None),
        "老师搜索",
        SimpleNamespace(garage_limit_enabled=False),
        False,
    )

    assert handled is True
    assert "标签搜索：" in replies[0]
    assert "发送“老师搜索 关键词”" in replies[0]
    assert "发送“附近”" in replies[0]
    assert "发送“开课老师”" in replies[0]


@pytest.mark.asyncio
async def test_process_garage_features_does_not_steal_sign_in_text(monkeypatch):
    session = _FakeSession()
    db = _FakeDb(session)
    replies: list[str] = []

    async def fake_get_teacher_setting(*args, **kwargs):
        return SimpleNamespace(
            nearby_search_enabled=True,
            attendance_enabled=False,
            force_location_enabled=False,
            footer_button_label="签到",
            delete_mode="none",
        )

    async def fake_get_car_review_setting(*args, **kwargs):
        return SimpleNamespace(enabled=False, rank_command="出击排行", submit_command="提交报告")

    async def fake_reply(context, *, chat_id, text, reply_to_message_id=None, **kwargs):
        replies.append(text)

    async def fake_is_teacher(*args, **kwargs):
        return False

    async def fake_is_whitelisted(*args, **kwargs):
        return False

    monkeypatch.setattr(TeacherSearchService, "get_setting", fake_get_teacher_setting)
    monkeypatch.setattr(CarReviewService, "get_setting", fake_get_car_review_setting)
    monkeypatch.setattr(GarageAuthService, "is_certified_teacher", fake_is_teacher)
    monkeypatch.setattr(GarageAuthService, "is_whitelisted", fake_is_whitelisted)
    monkeypatch.setattr(group_message_handler.PublishService, "reply", fake_reply)

    handled = await _process_garage_features(
        SimpleNamespace(application=SimpleNamespace(bot_data={})),
        db,
        SimpleNamespace(id=-1001, title="测试群"),
        SimpleNamespace(id=42),
        SimpleNamespace(message_id=9, location=None, venue=None, reply_to_message=None),
        "签到",
        SimpleNamespace(garage_limit_enabled=False),
        False,
    )

    assert handled is False
    assert replies == []


@pytest.mark.asyncio
async def test_process_garage_features_respects_tag_search_switch(monkeypatch):
    session = _FakeSession()
    db = _FakeDb(session)
    replies = []

    async def fake_get_teacher_setting(*args, **kwargs):
        return SimpleNamespace(
            tag_search_enabled=False,
            nearby_search_enabled=False,
            attendance_enabled=False,
            force_location_enabled=False,
            footer_button_label=None,
            delete_mode="none",
        )

    async def fake_get_car_review_setting(*args, **kwargs):
        return SimpleNamespace(enabled=False, rank_command="出击排行", submit_command="提交报告")

    async def fake_reply(context, *, chat_id, text, reply_to_message_id=None, **kwargs):
        replies.append(text)

    async def fake_is_teacher(*args, **kwargs):
        return False

    async def fake_is_whitelisted(*args, **kwargs):
        return False

    async def fake_mark_attendance(*args, **kwargs):
        return None

    monkeypatch.setattr(TeacherSearchService, "get_setting", fake_get_teacher_setting)
    monkeypatch.setattr(CarReviewService, "get_setting", fake_get_car_review_setting)
    monkeypatch.setattr(TeacherSearchService, "mark_attendance", fake_mark_attendance)
    monkeypatch.setattr(GarageAuthService, "is_certified_teacher", fake_is_teacher)
    monkeypatch.setattr(GarageAuthService, "is_whitelisted", fake_is_whitelisted)
    monkeypatch.setattr(group_message_handler.PublishService, "reply", fake_reply)

    handled = await _process_garage_features(
        SimpleNamespace(application=SimpleNamespace(bot_data={})),
        db,
        SimpleNamespace(id=-1001, title="测试群"),
        SimpleNamespace(id=42),
        SimpleNamespace(message_id=9, location=None, reply_to_message=None),
        "老师搜索 标签",
        SimpleNamespace(garage_limit_enabled=False),
        False,
    )

    assert handled is True
    assert replies == ["标签搜索已关闭。"]


@pytest.mark.asyncio
async def test_process_garage_features_records_shared_venue_location(monkeypatch):
    session = _FakeSession()
    db = _FakeDb(session)
    calls: list[tuple[str, float, float]] = []

    async def fake_get_teacher_setting(*args, **kwargs):
        return SimpleNamespace(
            nearby_search_enabled=True,
            attendance_enabled=False,
            force_location_enabled=False,
            footer_button_label=None,
            delete_mode="none",
        )

    async def fake_get_car_review_setting(*args, **kwargs):
        return SimpleNamespace(enabled=False, rank_command="出击排行", submit_command="提交报告")

    async def fake_upsert_member_location(*args, **kwargs):
        calls.append(("member", kwargs["latitude"], kwargs["longitude"]))

    async def fake_upsert_teacher_profile(*args, **kwargs):
        calls.append(("teacher", kwargs["latitude"], kwargs["longitude"]))

    async def fake_send_temporary(*args, **kwargs):
        return None

    async def fake_is_teacher(*args, **kwargs):
        return True

    async def fake_is_whitelisted(*args, **kwargs):
        return False

    monkeypatch.setattr(TeacherSearchService, "get_setting", fake_get_teacher_setting)
    monkeypatch.setattr(CarReviewService, "get_setting", fake_get_car_review_setting)
    monkeypatch.setattr(TeacherSearchService, "upsert_member_location", fake_upsert_member_location)
    monkeypatch.setattr(TeacherSearchService, "upsert_teacher_profile_from_location", fake_upsert_teacher_profile)
    monkeypatch.setattr(GarageAuthService, "is_certified_teacher", fake_is_teacher)
    monkeypatch.setattr(GarageAuthService, "is_whitelisted", fake_is_whitelisted)
    monkeypatch.setattr(group_message_handler.PublishService, "send_temporary", fake_send_temporary)

    handled = await _process_garage_features(
        SimpleNamespace(application=SimpleNamespace(bot_data={})),
        db,
        SimpleNamespace(id=-1001, title="测试群"),
        SimpleNamespace(id=42),
        SimpleNamespace(
            message_id=9,
            location=None,
            venue=SimpleNamespace(location=SimpleNamespace(latitude=31.2, longitude=121.4)),
            reply_to_message=None,
        ),
        "",
        SimpleNamespace(garage_limit_enabled=False),
        False,
    )

    assert handled is True
    assert calls == [("member", 31.2, 121.4), ("teacher", 31.2, 121.4)]


@pytest.mark.asyncio
async def test_process_garage_features_blocks_teacher_without_location(monkeypatch):
    session = _FakeSession()
    db = _FakeDb(session)
    replies: list[tuple[str, object]] = []
    deletes: list[int] = []

    async def fake_get_teacher_setting(*args, **kwargs):
        return SimpleNamespace(
            nearby_search_enabled=False,
            attendance_enabled=True,
            force_location_enabled=True,
            footer_button_label=None,
            delete_mode="none",
        )

    async def fake_get_car_review_setting(*args, **kwargs):
        return SimpleNamespace(enabled=False, rank_command="出击排行", submit_command="提交报告")

    async def fake_is_teacher(*args, **kwargs):
        return True

    async def fake_is_whitelisted(*args, **kwargs):
        return False

    async def fake_has_location(*args, **kwargs):
        return False

    async def fake_mark_attendance(*args, **kwargs):
        raise AssertionError("blocked teacher should not be marked open")

    async def fake_reply(context, *, chat_id, text, reply_to_message_id=None, **kwargs):
        replies.append((text, kwargs.get("reply_markup")))

    async def fake_delete(context, *, chat_id, message_id):
        deletes.append(message_id)

    monkeypatch.setattr(TeacherSearchService, "get_setting", fake_get_teacher_setting)
    monkeypatch.setattr(CarReviewService, "get_setting", fake_get_car_review_setting)
    monkeypatch.setattr(TeacherSearchService, "has_recorded_teacher_location", fake_has_location)
    monkeypatch.setattr(TeacherSearchService, "mark_attendance", fake_mark_attendance)
    monkeypatch.setattr(GarageAuthService, "is_certified_teacher", fake_is_teacher)
    monkeypatch.setattr(GarageAuthService, "is_whitelisted", fake_is_whitelisted)
    monkeypatch.setattr(group_message_handler.PublishService, "reply", fake_reply)
    monkeypatch.setattr(group_message_handler.PublishService, "delete", fake_delete)

    handled = await _process_garage_features(
        SimpleNamespace(application=SimpleNamespace(bot_data={}), bot=SimpleNamespace(username="TestBot")),
        db,
        SimpleNamespace(id=-1001, title="测试群"),
        SimpleNamespace(id=42),
        SimpleNamespace(message_id=9, location=None, venue=None, reply_to_message=None),
        "普通发言",
        SimpleNamespace(garage_limit_enabled=False),
        False,
    )

    assert handled is True
    assert replies and "请先发送开课位置" in replies[0][0]
    button = replies[0][1].inline_keyboard[0][0]
    assert button.url == "https://t.me/TestBot?start=tselfloc_-1001"
    assert deletes == [9]


@pytest.mark.asyncio
async def test_process_garage_features_force_location_does_not_block_explicit_checkin(monkeypatch):
    session = _FakeSession()
    db = _FakeDb(session)
    captured: dict[str, object] = {"replies": []}

    async def fake_get_teacher_setting(*args, **kwargs):
        return SimpleNamespace(
            nearby_search_enabled=False,
            attendance_enabled=True,
            attendance_mode="keyword",
            attendance_open_keyword="开课",
            attendance_full_keyword="满课",
            attendance_rest_keyword="休息",
            force_location_enabled=True,
            footer_button_label=None,
            delete_mode="none",
        )

    async def fake_get_car_review_setting(*args, **kwargs):
        return SimpleNamespace(enabled=False, rank_command="出击排行", submit_command="提交报告")

    async def fake_is_teacher(*args, **kwargs):
        return True

    async def fake_is_whitelisted(*args, **kwargs):
        return False

    async def fake_has_location(*args, **kwargs):
        return False

    async def fake_mark_attendance(session, *, chat_id, user_id, source_message_id, status="open"):
        captured["attendance"] = (chat_id, user_id, source_message_id, status)

    async def fake_reply(context, *, chat_id, text, reply_to_message_id=None, **kwargs):
        captured["replies"].append(text)

    monkeypatch.setattr(TeacherSearchService, "get_setting", fake_get_teacher_setting)
    monkeypatch.setattr(CarReviewService, "get_setting", fake_get_car_review_setting)
    monkeypatch.setattr(TeacherSearchService, "has_recorded_teacher_location", fake_has_location)
    monkeypatch.setattr(TeacherSearchService, "mark_attendance", fake_mark_attendance)
    monkeypatch.setattr(GarageAuthService, "is_certified_teacher", fake_is_teacher)
    monkeypatch.setattr(GarageAuthService, "is_whitelisted", fake_is_whitelisted)
    monkeypatch.setattr(group_message_handler.PublishService, "reply", fake_reply)

    handled = await _process_garage_features(
        SimpleNamespace(application=SimpleNamespace(bot_data={})),
        db,
        SimpleNamespace(id=-1001, title="测试群"),
        SimpleNamespace(id=42),
        SimpleNamespace(message_id=9, location=None, venue=None, reply_to_message=None),
        "开课",
        SimpleNamespace(garage_limit_enabled=False),
        False,
    )

    assert handled is True
    assert captured["attendance"] == (-1001, 42, 9, "open")
    assert captured["replies"] == ["✅ 已记录今日开课打卡。"]


@pytest.mark.asyncio
async def test_process_garage_features_force_location_exempts_admin(monkeypatch):
    session = _FakeSession()
    db = _FakeDb(session)

    async def fake_get_teacher_setting(*args, **kwargs):
        return SimpleNamespace(
            nearby_search_enabled=False,
            attendance_enabled=False,
            force_location_enabled=True,
            footer_button_label=None,
            delete_mode="none",
        )

    async def fake_get_car_review_setting(*args, **kwargs):
        return SimpleNamespace(enabled=False, rank_command="出击排行", submit_command="提交报告")

    async def fake_is_teacher(*args, **kwargs):
        return True

    async def fake_is_whitelisted(*args, **kwargs):
        return False

    async def fake_has_location(*args, **kwargs):
        raise AssertionError("admin should be exempt before location lookup")

    monkeypatch.setattr(TeacherSearchService, "get_setting", fake_get_teacher_setting)
    monkeypatch.setattr(CarReviewService, "get_setting", fake_get_car_review_setting)
    monkeypatch.setattr(TeacherSearchService, "has_recorded_teacher_location", fake_has_location)
    monkeypatch.setattr(GarageAuthService, "is_certified_teacher", fake_is_teacher)
    monkeypatch.setattr(GarageAuthService, "is_whitelisted", fake_is_whitelisted)

    handled = await _process_garage_features(
        SimpleNamespace(application=SimpleNamespace(bot_data={})),
        db,
        SimpleNamespace(id=-1001, title="测试群"),
        SimpleNamespace(id=42),
        SimpleNamespace(message_id=9, location=None, venue=None, reply_to_message=None),
        "普通发言",
        SimpleNamespace(garage_limit_enabled=False),
        True,
    )

    assert handled is False


@pytest.mark.asyncio
async def test_process_garage_features_keyword_attendance_mode_ignores_normal_text(monkeypatch):
    session = _FakeSession()
    db = _FakeDb(session)

    async def fake_get_teacher_setting(*args, **kwargs):
        return SimpleNamespace(
            nearby_search_enabled=False,
            attendance_enabled=True,
            attendance_mode="keyword",
            force_location_enabled=False,
            footer_button_label=None,
            delete_mode="none",
        )

    async def fake_get_car_review_setting(*args, **kwargs):
        return SimpleNamespace(enabled=False, rank_command="出击排行", submit_command="提交报告")

    async def fake_is_teacher(*args, **kwargs):
        return True

    async def fake_is_whitelisted(*args, **kwargs):
        return False

    async def fake_mark_attendance(*args, **kwargs):
        raise AssertionError("keyword mode should not mark normal text")

    monkeypatch.setattr(TeacherSearchService, "get_setting", fake_get_teacher_setting)
    monkeypatch.setattr(CarReviewService, "get_setting", fake_get_car_review_setting)
    monkeypatch.setattr(TeacherSearchService, "mark_attendance", fake_mark_attendance)
    monkeypatch.setattr(GarageAuthService, "is_certified_teacher", fake_is_teacher)
    monkeypatch.setattr(GarageAuthService, "is_whitelisted", fake_is_whitelisted)

    handled = await _process_garage_features(
        SimpleNamespace(application=SimpleNamespace(bot_data={})),
        db,
        SimpleNamespace(id=-1001, title="测试群"),
        SimpleNamespace(id=42),
        SimpleNamespace(message_id=9, location=None, venue=None, reply_to_message=None),
        "普通发言",
        SimpleNamespace(garage_limit_enabled=False),
        False,
    )

    assert handled is False


@pytest.mark.asyncio
async def test_process_garage_features_certified_teacher_reacts_on_normal_text(monkeypatch):
    session = _FakeSession()
    db = _FakeDb(session)
    reactions: list[dict[str, object]] = []

    async def fake_get_teacher_setting(*args, **kwargs):
        return SimpleNamespace(
            nearby_search_enabled=False,
            attendance_enabled=False,
            force_location_enabled=False,
            footer_button_label=None,
            delete_mode="none",
        )

    async def fake_get_car_review_setting(*args, **kwargs):
        return SimpleNamespace(enabled=False, rank_command="出击排行", submit_command="提交报告")

    async def fake_is_teacher(*args, **kwargs):
        return True

    async def fake_is_whitelisted(*args, **kwargs):
        return False

    class _Bot:
        async def set_message_reaction(self, **kwargs):
            reactions.append(kwargs)

    monkeypatch.setattr(TeacherSearchService, "get_setting", fake_get_teacher_setting)
    monkeypatch.setattr(CarReviewService, "get_setting", fake_get_car_review_setting)
    monkeypatch.setattr(GarageAuthService, "is_certified_teacher", fake_is_teacher)
    monkeypatch.setattr(GarageAuthService, "is_whitelisted", fake_is_whitelisted)

    handled = await _process_garage_features(
        SimpleNamespace(application=SimpleNamespace(bot_data={}), bot=_Bot()),
        db,
        SimpleNamespace(id=-1001, title="测试群"),
        SimpleNamespace(id=42, username="teacher42", first_name="老师", last_name=None),
        SimpleNamespace(message_id=9, location=None, venue=None, reply_to_message=None),
        "普通发言",
        SimpleNamespace(
            garage_limit_enabled=False,
            garage_auth_enabled=True,
            garage_auth_badge="🚗",
        ),
        False,
    )

    assert handled is False
    assert reactions == [
        {
            "chat_id": -1001,
            "message_id": 9,
            "reaction": "👍",
        }
    ]
    assert session.commits == 1


@pytest.mark.asyncio
async def test_process_garage_features_certified_teacher_reacts_on_media_without_text(monkeypatch):
    session = _FakeSession()
    db = _FakeDb(session)
    reactions: list[dict[str, object]] = []

    async def fake_get_teacher_setting(*args, **kwargs):
        return SimpleNamespace(
            nearby_search_enabled=False,
            attendance_enabled=False,
            force_location_enabled=False,
            footer_button_label=None,
            delete_mode="none",
        )

    async def fake_get_car_review_setting(*args, **kwargs):
        return SimpleNamespace(enabled=False, rank_command="出击排行", submit_command="提交报告")

    async def fake_is_teacher(*args, **kwargs):
        return True

    async def fake_is_whitelisted(*args, **kwargs):
        return False

    class _Bot:
        async def set_message_reaction(self, **kwargs):
            reactions.append(kwargs)

    monkeypatch.setattr(TeacherSearchService, "get_setting", fake_get_teacher_setting)
    monkeypatch.setattr(CarReviewService, "get_setting", fake_get_car_review_setting)
    monkeypatch.setattr(GarageAuthService, "is_certified_teacher", fake_is_teacher)
    monkeypatch.setattr(GarageAuthService, "is_whitelisted", fake_is_whitelisted)

    handled = await _process_garage_features(
        SimpleNamespace(application=SimpleNamespace(bot_data={}), bot=_Bot()),
        db,
        SimpleNamespace(id=-1001, title="测试群"),
        SimpleNamespace(id=42, username="teacher42", first_name="老师", last_name=None),
        SimpleNamespace(message_id=9, photo=[object()], location=None, venue=None, reply_to_message=None),
        "",
        SimpleNamespace(
            garage_limit_enabled=False,
            garage_auth_enabled=True,
            garage_auth_badge="🚗",
        ),
        False,
    )

    assert handled is False
    assert reactions == [
        {
            "chat_id": -1001,
            "message_id": 9,
            "reaction": "👍",
        }
    ]


@pytest.mark.asyncio
async def test_process_garage_features_keyword_checkin_marks_attendance(monkeypatch):
    session = _FakeSession()
    db = _FakeDb(session)
    captured: dict[str, object] = {"replies": []}

    async def fake_get_teacher_setting(*args, **kwargs):
        return SimpleNamespace(
            nearby_search_enabled=False,
            attendance_enabled=True,
            attendance_mode="keyword",
            force_location_enabled=False,
            footer_button_label=None,
            delete_mode="none",
        )

    async def fake_get_car_review_setting(*args, **kwargs):
        return SimpleNamespace(enabled=False, rank_command="出击排行", submit_command="提交报告")

    async def fake_is_teacher(*args, **kwargs):
        return True

    async def fake_is_whitelisted(*args, **kwargs):
        return False

    async def fake_mark_attendance(session, *, chat_id, user_id, source_message_id, status="open"):
        captured["attendance"] = (chat_id, user_id, source_message_id, status)

    async def fake_reply(context, *, chat_id, text, reply_to_message_id=None, **kwargs):
        captured["replies"].append(text)

    monkeypatch.setattr(TeacherSearchService, "get_setting", fake_get_teacher_setting)
    monkeypatch.setattr(CarReviewService, "get_setting", fake_get_car_review_setting)
    monkeypatch.setattr(TeacherSearchService, "mark_attendance", fake_mark_attendance)
    monkeypatch.setattr(GarageAuthService, "is_certified_teacher", fake_is_teacher)
    monkeypatch.setattr(GarageAuthService, "is_whitelisted", fake_is_whitelisted)
    monkeypatch.setattr(group_message_handler.PublishService, "reply", fake_reply)

    handled = await _process_garage_features(
        SimpleNamespace(application=SimpleNamespace(bot_data={})),
        db,
        SimpleNamespace(id=-1001, title="测试群"),
        SimpleNamespace(id=42),
        SimpleNamespace(message_id=9, location=None, venue=None, reply_to_message=None),
        "开课打卡",
        SimpleNamespace(garage_limit_enabled=False),
        False,
    )

    assert handled is True
    assert captured["attendance"] == (-1001, 42, 9, "open")
    assert captured["replies"] == ["✅ 已记录今日开课打卡。"]


@pytest.mark.asyncio
async def test_process_garage_features_keyword_checkin_accepts_linked_attendance_source_teacher(monkeypatch):
    session = _FakeSession()
    db = _FakeDb(session)
    captured: dict[str, object] = {"replies": []}

    async def fake_get_teacher_setting(*args, **kwargs):
        return SimpleNamespace(
            nearby_search_enabled=False,
            attendance_enabled=True,
            attendance_mode="keyword",
            attendance_open_keyword="开课",
            attendance_full_keyword="满课",
            attendance_rest_keyword="休息",
            force_location_enabled=False,
            footer_button_label=None,
            delete_mode="none",
        )

    async def fake_get_car_review_setting(*args, **kwargs):
        return SimpleNamespace(enabled=False, rank_command="出击排行", submit_command="提交报告")

    async def fake_is_teacher(*args, **kwargs):
        return False

    async def fake_is_attendance_source_teacher(session, source_chat_id: int, user_id: int):
        captured["source_check"] = (source_chat_id, user_id)
        return True

    async def fake_is_whitelisted(*args, **kwargs):
        return False

    async def fake_mark_attendance(session, *, chat_id, user_id, source_message_id, status="open"):
        captured["attendance"] = (chat_id, user_id, source_message_id, status)

    async def fake_reply(context, *, chat_id, text, reply_to_message_id=None, **kwargs):
        captured["replies"].append(text)

    monkeypatch.setattr(TeacherSearchService, "get_setting", fake_get_teacher_setting)
    monkeypatch.setattr(CarReviewService, "get_setting", fake_get_car_review_setting)
    monkeypatch.setattr(TeacherSearchService, "is_certified_teacher_for_attendance_source", fake_is_attendance_source_teacher)
    monkeypatch.setattr(TeacherSearchService, "mark_attendance", fake_mark_attendance)
    monkeypatch.setattr(GarageAuthService, "is_certified_teacher", fake_is_teacher)
    monkeypatch.setattr(GarageAuthService, "is_whitelisted", fake_is_whitelisted)
    monkeypatch.setattr(group_message_handler.PublishService, "reply", fake_reply)

    handled = await _process_garage_features(
        SimpleNamespace(application=SimpleNamespace(bot_data={})),
        db,
        SimpleNamespace(id=-2002, title="打卡群"),
        SimpleNamespace(id=42),
        SimpleNamespace(message_id=9, location=None, venue=None, reply_to_message=None),
        "开课",
        SimpleNamespace(garage_limit_enabled=False),
        False,
    )

    assert handled is True
    assert captured["source_check"] == (-2002, 42)
    assert captured["attendance"] == (-2002, 42, 9, "open")
    assert captured["replies"] == ["✅ 已记录今日开课打卡。"]


@pytest.mark.asyncio
async def test_process_garage_features_fixed_full_and_rest_keywords(monkeypatch):
    session = _FakeSession()
    db = _FakeDb(session)
    captured: dict[str, object] = {"attendance": [], "replies": []}

    async def fake_get_teacher_setting(*args, **kwargs):
        return SimpleNamespace(
            nearby_search_enabled=False,
            attendance_enabled=True,
            attendance_mode="keyword",
            attendance_open_keyword="开课",
            attendance_full_keyword="满课",
            attendance_rest_keyword="休息",
            force_location_enabled=False,
            footer_button_label=None,
            delete_mode="none",
        )

    async def fake_get_car_review_setting(*args, **kwargs):
        return SimpleNamespace(enabled=False, rank_command="出击排行", submit_command="提交报告")

    async def fake_is_teacher(*args, **kwargs):
        return True

    async def fake_is_whitelisted(*args, **kwargs):
        return False

    async def fake_mark_attendance(session, *, chat_id, user_id, source_message_id, status="open"):
        captured["attendance"].append((chat_id, user_id, source_message_id, status))

    async def fake_reply(context, *, chat_id, text, reply_to_message_id=None, **kwargs):
        captured["replies"].append(text)

    monkeypatch.setattr(TeacherSearchService, "get_setting", fake_get_teacher_setting)
    monkeypatch.setattr(CarReviewService, "get_setting", fake_get_car_review_setting)
    monkeypatch.setattr(TeacherSearchService, "mark_attendance", fake_mark_attendance)
    monkeypatch.setattr(GarageAuthService, "is_certified_teacher", fake_is_teacher)
    monkeypatch.setattr(GarageAuthService, "is_whitelisted", fake_is_whitelisted)
    monkeypatch.setattr(group_message_handler.PublishService, "reply", fake_reply)

    for idx, text in enumerate(["满课", "休息"], start=1):
        handled = await _process_garage_features(
            SimpleNamespace(application=SimpleNamespace(bot_data={})),
            db,
            SimpleNamespace(id=-1001, title="测试群"),
            SimpleNamespace(id=42),
            SimpleNamespace(message_id=idx, location=None, venue=None, reply_to_message=None),
            text,
            SimpleNamespace(garage_limit_enabled=False),
            False,
        )
        assert handled is True

    assert captured["attendance"] == [
        (-1001, 42, 1, "full"),
        (-1001, 42, 2, "rest"),
    ]
    assert captured["replies"] == ["✅ 已记录今日满课打卡。", "✅ 已记录今日休息打卡。"]


@pytest.mark.asyncio
async def test_process_garage_features_message_attendance_mode_marks_normal_text(monkeypatch):
    session = _FakeSession()
    db = _FakeDb(session)
    captured: dict[str, object] = {}

    async def fake_get_teacher_setting(*args, **kwargs):
        return SimpleNamespace(
            nearby_search_enabled=False,
            attendance_enabled=True,
            attendance_mode="message",
            force_location_enabled=False,
            footer_button_label=None,
            delete_mode="none",
        )

    async def fake_get_car_review_setting(*args, **kwargs):
        return SimpleNamespace(enabled=False, rank_command="出击排行", submit_command="提交报告")

    async def fake_is_teacher(*args, **kwargs):
        return True

    async def fake_is_whitelisted(*args, **kwargs):
        return False

    async def fake_mark_attendance(session, *, chat_id, user_id, source_message_id, status="open"):
        captured["attendance"] = (chat_id, user_id, source_message_id, status)

    monkeypatch.setattr(TeacherSearchService, "get_setting", fake_get_teacher_setting)
    monkeypatch.setattr(CarReviewService, "get_setting", fake_get_car_review_setting)
    monkeypatch.setattr(TeacherSearchService, "mark_attendance", fake_mark_attendance)
    monkeypatch.setattr(GarageAuthService, "is_certified_teacher", fake_is_teacher)
    monkeypatch.setattr(GarageAuthService, "is_whitelisted", fake_is_whitelisted)

    handled = await _process_garage_features(
        SimpleNamespace(application=SimpleNamespace(bot_data={})),
        db,
        SimpleNamespace(id=-1001, title="测试群"),
        SimpleNamespace(id=42),
        SimpleNamespace(message_id=9, location=None, venue=None, reply_to_message=None),
        "普通发言",
        SimpleNamespace(garage_limit_enabled=False),
        False,
    )

    assert handled is False
    assert captured["attendance"] == (-1001, 42, 9, "open")
