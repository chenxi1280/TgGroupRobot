from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

from telegram.ext import ContextTypes

from backend.features.garage.services.garage_features_service import TeacherSearchService
from backend.features.group_ops.group_hooks.teacher_search_queries import (
    _format_teacher_keyword_search as _format_teacher_keyword_search_impl,
    build_private_teacher_location_markup as _build_private_teacher_location_markup,
    reply_nearby_teachers as _reply_nearby_teachers,
    reply_open_course_teachers as _reply_open_course_teachers,
    reply_teacher_keyword_search as _reply_teacher_keyword_search,
    try_reply_bare_keyword_search as _try_reply_bare_keyword_search,
)
from backend.features.group_ops.text_trigger_runtime import is_reserved_group_text_command_for_chat
from backend.shared.services.command_config_service import is_command_enabled

from .common import _reply_garage_feedback

TEACHER_SEARCH_HELP_TEXT = (
    "标签搜索：\n"
    "发送“老师搜索 关键词”，可按老师名、车牌名称、地址、价格、服务标签查询。\n\n"
    "附近搜索：\n"
    "发送“附近”，按你最近保存的位置查询附近老师。\n\n"
    "开课老师：\n"
    "发送“开课老师”，查看今天已开课打卡的老师。"
)

@dataclass(frozen=True, slots=True)
class _TeacherSearchRequest:
    context: ContextTypes.DEFAULT_TYPE
    session: object
    chat: object
    user: object
    message: object
    text: str
    teacher_setting: object
    chat_settings: object | None
    is_teacher: bool
    is_attendance_teacher: bool
    is_admin: bool
    is_whitelisted: bool

    @property
    def delete_mode(self) -> str:
        return getattr(self.teacher_setting, "delete_mode", "none")


TeacherSearchAction = Callable[[_TeacherSearchRequest], Awaitable[bool]]


def _parse_nearby_condition(text: str) -> str | None:
    cleaned = (text or "").strip()
    for prefix in ("附近老师", "附近"):
        if not cleaned.startswith(prefix):
            continue
        keyword = cleaned[len(prefix):].strip()
        keyword = keyword.lstrip("+＋,，:：- ")
        return keyword
    return None


async def _process_teacher_search_features(
    context: ContextTypes.DEFAULT_TYPE,
    session,
    chat,
    *, user,
    message,
    text: str,
    teacher_setting,
    chat_settings=None,

    is_teacher: bool,
    is_attendance_teacher: bool | None = None,
    is_admin: bool,
    is_whitelisted: bool,
) -> bool:
    request = _TeacherSearchRequest(
        context=context,
        session=session,
        chat=chat,
        user=user,
        message=message,
        text=text,
        teacher_setting=teacher_setting,
        chat_settings=chat_settings,
        is_teacher=is_teacher,
        is_attendance_teacher=is_teacher if is_attendance_teacher is None else is_attendance_teacher,
        is_admin=is_admin,
        is_whitelisted=is_whitelisted,
    )
    actions: tuple[TeacherSearchAction, ...] = (
        _handle_location_update,
        _handle_attendance_keyword,
        _handle_missing_teacher_location,
        _record_message_attendance,
        _handle_open_course_search,
        _handle_nearby_search,
        _handle_explicit_teacher_search,
        _handle_teacher_search_entry,
        _handle_bare_teacher_search,
    )
    for action in actions:
        if await action(request):
            return True
    return False


async def _handle_location_update(request: _TeacherSearchRequest) -> bool:
    setting = request.teacher_setting
    enabled = setting.nearby_search_enabled or (setting.force_location_enabled and request.is_teacher)
    if not enabled:
        return False
    location = await _extract_location_pair(request.message, request.text)
    if location is None:
        return False
    await _record_teacher_location(
        request.context,
        request.session,
        request.chat,
        user=request.user,
        message=request.message,
        latitude=location[0],
        longitude=location[1],
        is_teacher=request.is_teacher,
    )
    return True


async def _handle_attendance_keyword(request: _TeacherSearchRequest) -> bool:
    mode = getattr(request.teacher_setting, "attendance_mode", "message") or "message"
    status = _resolve_attendance_keyword_status(request.text, request.teacher_setting)
    if request.text == "开课打卡" and mode != "external":
        status = "open"
    if status is None or mode == "external":
        return False
    await _reply_attendance_checkin(
        request.context,
        request.session,
        request.chat,
        user=request.user,
        message=request.message,
        teacher_setting=request.teacher_setting,
        is_teacher=request.is_attendance_teacher,
        status=status,
    )
    return True


async def _handle_missing_teacher_location(request: _TeacherSearchRequest) -> bool:
    return await _block_teacher_without_location(
        request.context,
        request.session,
        request.chat,
        user=request.user,
        message=request.message,
        text=request.text,
        teacher_setting=request.teacher_setting,
        is_teacher=request.is_teacher,
        is_admin=request.is_admin,
        is_whitelisted=request.is_whitelisted,
    )


async def _record_message_attendance(request: _TeacherSearchRequest) -> bool:
    setting = request.teacher_setting
    mode = getattr(setting, "attendance_mode", "message") or "message"
    should_record = (
        setting.attendance_enabled
        and mode == "message"
        and request.is_attendance_teacher
        and request.text
        and not request.text.startswith("/")
    )
    if should_record:
        await TeacherSearchService.mark_attendance(
            request.session,
            chat_id=request.chat.id,
            user_id=request.user.id,
            source_message_id=request.message.message_id,
        )
    return False


def _command_disabled(request: _TeacherSearchRequest, command: str) -> bool:
    return request.chat_settings is not None and not is_command_enabled(request.chat_settings, command)


async def _handle_open_course_search(request: _TeacherSearchRequest) -> bool:
    if request.text != "开课老师":
        return False
    if _command_disabled(request, "open_teachers"):
        await request.message.reply_text("该指令已关闭。")
        return True
    await _reply_open_course_teachers(
        request.context,
        request.session,
        request.chat,
        message=request.message,
        delete_mode=request.delete_mode,
    )
    return True


async def _handle_nearby_search(request: _TeacherSearchRequest) -> bool:
    condition = _parse_nearby_condition(request.text)
    if condition is None:
        return False
    if _command_disabled(request, "nearby"):
        await request.message.reply_text("该指令已关闭。")
        return True
    await _reply_nearby_teachers(
        request.context,
        request.session,
        request.chat,
        user=request.user,
        message=request.message,
        teacher_setting=request.teacher_setting,
        keyword=condition or None,
        delete_mode=request.delete_mode,
    )
    return True


async def _handle_explicit_teacher_search(request: _TeacherSearchRequest) -> bool:
    if not request.text.startswith("老师搜索 "):
        return False
    if _command_disabled(request, "teacher_search"):
        await request.message.reply_text("该指令已关闭。")
        return True
    keyword = request.text.split(" ", 1)[1].strip()
    await _reply_explicit_teacher_search(request, keyword)
    return True


async def _reply_explicit_teacher_search(request: _TeacherSearchRequest, keyword: str) -> None:
    nearby_keyword = _parse_nearby_condition(keyword)
    if nearby_keyword is not None:
        await _reply_nearby_teachers(
            request.context,
            request.session,
            request.chat,
            user=request.user,
            message=request.message,
            teacher_setting=request.teacher_setting,
            keyword=nearby_keyword or None,
            delete_mode=request.delete_mode,
        )
        return
    if keyword in {"开课", "开课老师"}:
        await _reply_open_course_teachers(
            request.context,
            request.session,
            request.chat,
            message=request.message,
            delete_mode=request.delete_mode,
        )
        return
    await _reply_teacher_keyword_search(
        request.context,
        request.session,
        request.chat,
        message=request.message,
        teacher_setting=request.teacher_setting,
        keyword=keyword,
        delete_mode=request.delete_mode,
    )


async def _handle_teacher_search_entry(request: _TeacherSearchRequest) -> bool:
    footer_label = (request.teacher_setting.footer_button_label or "").strip()
    is_entry = request.text == "老师搜索" or bool(footer_label and request.text == footer_label)
    if not is_entry:
        return False
    if await is_reserved_group_text_command_for_chat(request.session, request.chat.id, request.text):
        return False
    if _command_disabled(request, "teacher_search"):
        await request.message.reply_text("该指令已关闭。")
        return True
    await request.session.commit()
    await _reply_garage_feedback(
        request.context,
        chat_id=request.chat.id,
        message_id=request.message.message_id,
        text=TEACHER_SEARCH_HELP_TEXT,
        delete_mode=request.delete_mode,
    )
    return True


async def _handle_bare_teacher_search(request: _TeacherSearchRequest) -> bool:
    return await _try_reply_bare_keyword_search(
        request.context,
        request.session,
        request.chat,
        message=request.message,
        keyword=request.text,
        teacher_setting=request.teacher_setting,
        chat_settings=request.chat_settings,
        delete_mode=request.delete_mode,
    )


def _resolve_attendance_keyword_status(text: str, teacher_setting) -> str | None:
    if not text or (getattr(teacher_setting, "attendance_mode", "message") or "message") != "keyword":
        return None
    keywords = {
        "open": getattr(teacher_setting, "attendance_open_keyword", "开课") or "开课",
        "full": getattr(teacher_setting, "attendance_full_keyword", "满课") or "满课",
        "rest": getattr(teacher_setting, "attendance_rest_keyword", "休息") or "休息",
    }
    for status, keyword in keywords.items():
        if text == keyword:
            return status
    return None


async def _reply_attendance_checkin(
    context: ContextTypes.DEFAULT_TYPE,
    session,
    chat,
    *, user,
    message,
    teacher_setting,

    is_teacher: bool,
    status: str = "open",
) -> None:
    delete_mode = getattr(teacher_setting, "delete_mode", "none")
    if not teacher_setting.attendance_enabled:
        await session.commit()
        await _reply_garage_feedback(
            context,
            chat_id=chat.id,
            message_id=message.message_id,
            text="开课打卡已关闭。",
            delete_mode=delete_mode,
        )
        return
    if not is_teacher:
        await session.commit()
        await _reply_garage_feedback(
            context,
            chat_id=chat.id,
            message_id=message.message_id,
            text="只有上牌老师可以开课打卡。",
            delete_mode=delete_mode,
        )
        return

    await TeacherSearchService.mark_attendance(
        session,
        chat_id=chat.id,
        user_id=user.id,
        source_message_id=message.message_id,
        status=status,
    )
    await session.commit()
    status_label = {"open": "开课", "full": "满课", "rest": "休息"}.get(status, "开课")
    await _reply_garage_feedback(
        context,
        chat_id=chat.id,
        message_id=message.message_id,
        text=f"✅ 已记录今日{status_label}打卡。",
        delete_mode=delete_mode,
    )


async def _extract_location_pair(message, text: str) -> tuple[float, float] | None:
    location = getattr(message, "location", None)
    if location is None:
        venue = getattr(message, "venue", None)
        location = getattr(venue, "location", None) if venue is not None else None
    if location is not None:
        return float(location.latitude), float(location.longitude)

    if text:
        from backend.features.admin.garage.teacher_search_inputs import _parse_coordinates_from_map_link

        return await _parse_coordinates_from_map_link(text)
    return None


async def _block_teacher_without_location(
    context: ContextTypes.DEFAULT_TYPE,
    session,
    chat,
    *, user,
    message,
    text: str,
    teacher_setting,

    is_teacher: bool,
    is_admin: bool,
    is_whitelisted: bool,
) -> bool:
    if not teacher_setting.force_location_enabled:
        return False
    if not is_teacher or is_admin or is_whitelisted:
        return False
    if text.startswith("/"):
        return False
    if await TeacherSearchService.has_recorded_teacher_location(session, chat.id, user.id):
        return False
    await session.commit()
    await _reply_garage_feedback(
        context,
        chat_id=chat.id,
        message_id=message.message_id,
        text=(
            "请先发送开课位置后再发言。\n"
            "为了保护隐私，也可以点下面按钮到私聊更新定位。\n"
            "更新后回到本群即可正常使用。"
        ),
        reply_markup=_build_private_teacher_location_markup(context, chat.id),
        delete_mode="delete",
    )
    return True


async def _record_teacher_location(
    context: ContextTypes.DEFAULT_TYPE,
    session,
    chat,
    *, user,
    message,

    latitude: float,
    longitude: float,
    is_teacher: bool,
) -> None:
    await TeacherSearchService.upsert_member_location(
        session,
        chat_id=chat.id,
        user_id=user.id,
        latitude=latitude,
        longitude=longitude,
        operator_user_id=user.id,
    )
    if is_teacher:
        await TeacherSearchService.upsert_teacher_profile_from_location(
            session,
            chat_id=chat.id,
            user_id=user.id,
            latitude=latitude,
            longitude=longitude,
        )
    await session.commit()
    from backend.shared.services.publish_service import PublishService

    await PublishService.send_temporary(
        context,
        chat_id=chat.id,
        text="已记录当前位置。",
        delete_after_seconds=10,
        reply_to_message_id=message.message_id,
    )


def _format_teacher_keyword_search(keyword: str, rows, *, badge: str, fallback_note: str = "") -> str:
    return _format_teacher_keyword_search_impl(
        keyword,
        rows,
        badge=badge,
        fallback_note=fallback_note,
    )
