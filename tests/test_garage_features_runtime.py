from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

import backend.features.group_ops.group_message_handler as group_message_handler
import backend.features.group_ops.group_hooks.car_review as car_review_hook
from backend.features.group_ops.group_message_handler import _process_garage_features
from backend.platform.db.schema.models.core import TgUser
from backend.platform.db.schema.models.garage_features import CarReviewAuditLog, CarReviewReport, TeacherProfile, TeacherSearchSetting
from backend.features.garage.services.garage_features_service import CarReviewService, GarageAuthService, TeacherSearchService


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
            SimpleNamespace(id=1, username="nearer", first_name="Near"),
        ),
        (
            SimpleNamespace(user_id=2, latitude=31.2405, longitude=121.4839, region_text="B区", price_text="200", labels=["热门"], updated_at=dt.datetime.now(dt.UTC)),
            SimpleNamespace(id=2, username="farther", first_name="Far"),
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
async def test_build_teacher_summary_groups_by_region(monkeypatch):
    rows = [
        (
            SimpleNamespace(chat_id=-1001, user_id=1, enabled=True, created_at=dt.datetime.now(dt.UTC)),
            SimpleNamespace(region_text="A区", price_text="100", labels=["新人"], open_course_today=True),
            SimpleNamespace(id=1, username="teacher_a", first_name="A"),
        ),
        (
            SimpleNamespace(chat_id=-1001, user_id=2, enabled=True, created_at=dt.datetime.now(dt.UTC)),
            SimpleNamespace(region_text="A区", price_text="200", labels=["热门"], open_course_today=False),
            SimpleNamespace(id=2, username="teacher_b", first_name="B"),
        ),
        (
            SimpleNamespace(chat_id=-1001, user_id=3, enabled=True, created_at=dt.datetime.now(dt.UTC)),
            SimpleNamespace(region_text="B区", price_text="300", labels=[], open_course_today=True),
            SimpleNamespace(id=3, username=None, first_name="Teacher C"),
        ),
    ]
    session = _FakeSession(execute_results=[_ExecuteResult(rows=rows)])

    async def fake_get_settings(session, chat_id: int):
        return SimpleNamespace(
            garage_summary_partition_by="region",
            garage_summary_only_open_course=False,
        )

    monkeypatch.setattr(GarageAuthService, "get_settings", fake_get_settings)

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
            SimpleNamespace(id=1, username="teacher_a", first_name="A"),
        ),
        (
            SimpleNamespace(chat_id=-1001, user_id=2, enabled=True, created_at=dt.datetime.now(dt.UTC)),
            SimpleNamespace(region_text="B区", price_text="200", labels=["热门"], open_course_today=True),
            SimpleNamespace(id=2, username="teacher_b", first_name="B"),
        ),
    ]
    session = _FakeSession(execute_results=[_ExecuteResult(rows=rows)])

    async def fake_get_settings(session, chat_id: int):
        return SimpleNamespace(
            garage_summary_partition_by="price",
            garage_summary_only_open_course=True,
        )

    monkeypatch.setattr(GarageAuthService, "get_settings", fake_get_settings)

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
            SimpleNamespace(id=11, username="teacher_a", first_name="A"),
        ),
        (
            SimpleNamespace(chat_id=-1001, teacher_user_id=11, report_status="published", scores={"total_score": 100}),
            SimpleNamespace(id=11, username="teacher_a", first_name="A"),
        ),
        (
            SimpleNamespace(chat_id=-1001, teacher_user_id=12, report_status="approved", scores={"total_score": 95}),
            SimpleNamespace(id=12, username="teacher_b", first_name="B"),
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
async def test_process_garage_features_exact_lookup_replies_teacher_reviews(monkeypatch):
    session = _FakeSession()
    db = _FakeDb(session)
    replies: list[str] = []
    teacher = SimpleNamespace(id=77, username="teacher77", first_name="T")
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
        return [(report, SimpleNamespace(id=42, username="author42", first_name="A"))]

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
async def test_process_garage_features_submits_car_review_pending_admin_review(monkeypatch):
    session = _FakeSession(get_map={(TgUser, 77): SimpleNamespace(id=77, username="teacher77", first_name="T"), (TgUser, 42): SimpleNamespace(id=42, username="author42", first_name="A")})
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
            approver_user_id=None,
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
        SimpleNamespace(id=42, full_name="Author"),
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
    assert any("等待管理员审核" in text for text in replies)


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
    replies: list[str] = []
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
        replies.append(text)

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
        SimpleNamespace(application=SimpleNamespace(bot_data={})),
        db,
        SimpleNamespace(id=-1001, title="测试群"),
        SimpleNamespace(id=42),
        SimpleNamespace(message_id=9, location=None, venue=None, reply_to_message=None),
        "普通发言",
        SimpleNamespace(garage_limit_enabled=False),
        False,
    )

    assert handled is True
    assert replies and "请先发送开课位置" in replies[0]
    assert deletes == [9]


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
