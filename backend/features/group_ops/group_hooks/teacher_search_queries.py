"""老师搜索、附近老师和开课老师查询响应。"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from backend.features.garage.services.garage_features_service import TeacherSearchService
from backend.features.garage.services.teacher_search_queries import teacher_attendance_status_label
from backend.features.group_ops.group_hooks.teacher_search_format import (
    build_teacher_keyword_search_markup,
    format_teacher_keyword_search,
)
from backend.features.group_ops.text_trigger_runtime import is_reserved_group_text_command_for_chat
from backend.shared.services.command_config_service import is_command_enabled

from .common import _reply_garage_feedback

NEARBY_RESULT_LIMIT = 10
OPEN_COURSE_RESULT_LIMIT = 10
LOCATION_UPDATE_PROMPT = (
    "还没有你的定位。\n"
    "为了保护隐私，请点下面按钮到私聊更新定位。\n"
    "更新后回到本群发送“附近”，就能查询附近老师。"
)


async def _get_auth_badge(session, chat_id: int) -> str:
    from backend.features.garage.services.garage_features_service import GarageAuthService

    settings = await GarageAuthService.get_settings(session, chat_id)
    return getattr(settings, "garage_auth_badge", "🤝") or "🤝"


def build_private_location_markup(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
) -> InlineKeyboardMarkup | None:
    bot_username = getattr(getattr(context, "bot", None), "username", None)
    if not bot_username:
        return None
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("私聊更新定位", url=f"https://t.me/{bot_username}?start=tloc_{chat_id}")]]
    )


def build_private_teacher_location_markup(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
) -> InlineKeyboardMarkup | None:
    bot_username = getattr(getattr(context, "bot", None), "username", None)
    if not bot_username:
        return None
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("私聊更新定位", url=f"https://t.me/{bot_username}?start=tselfloc_{chat_id}")]]
    )


async def reply_open_course_teachers(
    context: ContextTypes.DEFAULT_TYPE,
    session,
    chat,
    *,
    message,
    delete_mode: str,
) -> None:
    rows = await TeacherSearchService.list_open_course_teachers(session, chat.id)
    badge = await _get_auth_badge(session, chat.id)
    await session.commit()
    if not rows:
        await _reply_garage_feedback(
            context,
            chat_id=chat.id,
            message_id=message.message_id,
            text="今天还没有开课老师。",
            delete_mode=delete_mode,
        )
        return
    lines = ["今日开课老师："]
    lines.extend(
        _format_open_course_teacher(index, profile, user, badge=badge)
        for index, (profile, user) in enumerate(rows[:OPEN_COURSE_RESULT_LIMIT], start=1)
    )
    await _reply_garage_feedback(
        context,
        chat_id=chat.id,
        message_id=message.message_id,
        text="\n".join(lines),
        delete_mode=delete_mode,
    )


def _format_open_course_teacher(index: int, profile, user, *, badge: str) -> str:
    if user and user.username:
        name = f"@{user.username}"
    elif user and user.first_name:
        name = user.first_name
    else:
        name = f"用户{profile.user_id}"
    extra = " / ".join(part for part in [profile.region_text, profile.price_text] if part)
    status = teacher_attendance_status_label(profile)
    return f"{index}. {badge} {name} · {status}" + (f" · {extra}" if extra else "")


async def reply_nearby_teachers(
    context: ContextTypes.DEFAULT_TYPE,
    session,
    chat,
    *,
    user,
    message,
    teacher_setting,
    keyword: str | None = None,
    delete_mode: str,
) -> None:
    if not teacher_setting.nearby_search_enabled:
        await _reply_nearby_status(
            context,
            session,
            chat,
            message=message,
            text="附近搜索已关闭。",
            delete_mode=delete_mode,
        )
        return
    location = await TeacherSearchService.get_member_location(session, chat.id, user.id)
    if location is None:
        await _reply_location_required(context, session, chat, message=message, delete_mode=delete_mode)
        return
    nearby = await _find_nearby(
        session,
        chat.id,
        location=location,
        teacher_setting=teacher_setting,
        keyword=keyword,
    )
    await _reply_nearby_results(
        context,
        session,
        chat,
        message=message,
        nearby=nearby,
        teacher_setting=teacher_setting,
        keyword=keyword,
        delete_mode=delete_mode,
    )


async def _reply_nearby_results(
    context,
    session,
    chat,
    *,
    message,
    nearby: list[dict],
    teacher_setting,
    keyword: str | None,
    delete_mode: str,
) -> None:
    badge = await _get_auth_badge(session, chat.id)
    await session.commit()
    if not nearby:
        empty_text = _nearby_empty_text(teacher_setting, keyword=keyword)
        await _reply_garage_feedback(
            context,
            chat_id=chat.id,
            message_id=message.message_id,
            text=empty_text,
            delete_mode=delete_mode,
        )
        return
    await _reply_garage_feedback(
        context,
        chat_id=chat.id,
        message_id=message.message_id,
        text=_format_nearby_results(nearby, badge=badge, keyword=keyword),
        delete_mode=delete_mode,
    )


async def _reply_location_required(context, session, chat, *, message, delete_mode: str) -> None:
    await session.commit()
    await _reply_garage_feedback(
        context,
        chat_id=chat.id,
        message_id=message.message_id,
        text=LOCATION_UPDATE_PROMPT,
        reply_markup=build_private_location_markup(context, chat.id),
        delete_mode=delete_mode,
    )


async def _reply_nearby_status(
    context,
    session,
    chat,
    *,
    message,
    text: str,
    delete_mode: str,
) -> None:
    await session.commit()
    await _reply_garage_feedback(
        context,
        chat_id=chat.id,
        message_id=message.message_id,
        text=text,
        delete_mode=delete_mode,
    )


async def _find_nearby(
    session,
    chat_id: int,
    *,
    location,
    teacher_setting,
    keyword: str | None,
):
    return await TeacherSearchService.list_nearby_teachers(
        session,
        chat_id,
        float(location.latitude),
        longitude=float(location.longitude),
        only_open_course=getattr(teacher_setting, "only_open_course_enabled", True),
        keyword=keyword,
        limit=NEARBY_RESULT_LIMIT,
    )


def _nearby_empty_text(teacher_setting, *, keyword: str | None) -> str:
    only_open = getattr(teacher_setting, "only_open_course_enabled", True)
    if keyword:
        return "附近暂无符合条件的开课老师。" if only_open else "附近暂无符合条件的老师。"
    return "附近暂无开课老师。" if only_open else "附近暂无老师。"


def _format_nearby_results(nearby: list[dict], *, badge: str, keyword: str | None) -> str:
    lines = [f"附近老师：{keyword}" if keyword else "附近老师："]
    for index, item in enumerate(nearby, start=1):
        profile = item["profile"]
        extra = " / ".join(part for part in [profile.region_text, profile.price_text] if part)
        status = teacher_attendance_status_label(profile)
        line = f"{index}. {badge} {item['display_name']} · {status} · {item['distance_text']}"
        lines.append(line + (f" · {extra}" if extra else ""))
    return "\n".join(lines)


async def reply_teacher_keyword_search(
    context: ContextTypes.DEFAULT_TYPE,
    session,
    chat,
    *,
    message,
    teacher_setting,
    keyword: str,
    delete_mode: str,
) -> None:
    if not teacher_setting.tag_search_enabled:
        await _reply_nearby_status(
            context,
            session,
            chat,
            message=message,
            text="标签搜索已关闭。",
            delete_mode=delete_mode,
        )
        return
    rows, fallback_note = await _search_teacher_keyword_rows(
        session,
        chat.id,
        keyword,
        teacher_setting=teacher_setting,
    )
    badge = await _get_auth_badge(session, chat.id)
    await session.commit()
    if not rows:
        await _reply_garage_feedback(
            context,
            chat_id=chat.id,
            message_id=message.message_id,
            text="没有找到匹配的老师。",
            delete_mode=delete_mode,
        )
        return
    await _reply_garage_feedback(
        context,
        chat_id=chat.id,
        message_id=message.message_id,
        text=_format_teacher_keyword_search(keyword, rows, badge=badge, fallback_note=fallback_note),
        reply_markup=build_teacher_keyword_search_markup(rows),
        delete_mode=delete_mode,
    )


async def try_reply_bare_keyword_search(
    context: ContextTypes.DEFAULT_TYPE,
    session,
    chat,
    *,
    message,
    keyword: str,
    teacher_setting,
    chat_settings,
    delete_mode: str,
) -> bool:
    if not keyword or keyword.startswith("/") or not getattr(teacher_setting, "tag_search_enabled", False):
        return False
    if chat_settings is not None and not is_command_enabled(chat_settings, "teacher_search"):
        return False
    if await is_reserved_group_text_command_for_chat(session, chat.id, keyword):
        return False
    rows, fallback_note = await _search_teacher_keyword_rows(
        session,
        chat.id,
        keyword,
        teacher_setting=teacher_setting,
    )
    if not rows:
        return False
    badge = await _get_auth_badge(session, chat.id)
    await session.commit()
    await _reply_garage_feedback(
        context,
        chat_id=chat.id,
        message_id=message.message_id,
        text=_format_teacher_keyword_search(keyword, rows, badge=badge, fallback_note=fallback_note),
        reply_markup=build_teacher_keyword_search_markup(rows),
        delete_mode=delete_mode,
    )
    return True


async def _search_teacher_keyword_rows(session, chat_id: int, keyword: str, *, teacher_setting):
    only_open_course = getattr(teacher_setting, "only_open_course_enabled", True)
    rows = await TeacherSearchService.search_teachers_by_keyword(
        session,
        chat_id,
        keyword,
        only_open_course=only_open_course,
        limit=NEARBY_RESULT_LIMIT,
    )
    fallback_note = ""
    if not rows and only_open_course:
        rows = await TeacherSearchService.search_teachers_by_keyword(
            session,
            chat_id,
            keyword,
            only_open_course=False,
            limit=NEARBY_RESULT_LIMIT,
        )
        if rows:
            fallback_note = "未找到今日开课匹配老师，已显示全部认证老师。"
    return rows, fallback_note


def _format_teacher_keyword_search(keyword: str, rows, *, badge: str, fallback_note: str = "") -> str:
    return format_teacher_keyword_search(keyword, rows, badge=badge, fallback_note=fallback_note)
