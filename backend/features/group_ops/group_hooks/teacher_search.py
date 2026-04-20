from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from backend.features.garage.services.garage_features_service import TeacherSearchService

from .common import _reply_garage_feedback

TEACHER_SEARCH_HELP_TEXT = (
    "标签搜索：\n"
    "发送“老师搜索 关键词”，可按老师名、车牌名称、地址、价格、服务标签查询。\n\n"
    "附近搜索：\n"
    "发送“附近”，按你最近保存的位置查询附近老师。\n\n"
    "开课老师：\n"
    "发送“开课老师”，查看今天已开课打卡的老师。"
)

LOCATION_UPDATE_PROMPT = (
    "还没有你的定位。\n"
    "为了保护隐私，请点下面按钮到私聊更新定位。\n"
    "更新后回到本群发送“附近”，就能查询附近老师。"
)


async def _process_teacher_search_features(
    context: ContextTypes.DEFAULT_TYPE,
    session,
    chat,
    user,
    message,
    text: str,
    teacher_setting,
    *,
    is_teacher: bool,
    is_admin: bool,
    is_whitelisted: bool,
) -> bool:
    location_recording_enabled = teacher_setting.nearby_search_enabled or (
        teacher_setting.force_location_enabled and is_teacher
    )
    location_pair = await _extract_location_pair(message, text) if location_recording_enabled else None
    if location_pair is not None and location_recording_enabled:
        await _record_teacher_location(
            context,
            session,
            chat,
            user,
            message,
            latitude=location_pair[0],
            longitude=location_pair[1],
            is_teacher=is_teacher,
        )
        return True

    delete_mode = getattr(teacher_setting, "delete_mode", "none")

    if await _block_teacher_without_location(
        context,
        session,
        chat,
        user,
        message,
        text,
        teacher_setting,
        is_teacher=is_teacher,
        is_admin=is_admin,
        is_whitelisted=is_whitelisted,
    ):
        return True

    attendance_mode = getattr(teacher_setting, "attendance_mode", "message") or "message"
    keyword_status = _resolve_attendance_keyword_status(text, teacher_setting)
    if text == "开课打卡" and attendance_mode != "external":
        keyword_status = "open"
    if keyword_status is not None and attendance_mode != "external":
        await _reply_attendance_checkin(
            context,
            session,
            chat,
            user,
            message,
            teacher_setting,
            is_teacher=is_teacher,
            status=keyword_status,
        )
        return True

    if (
        teacher_setting.attendance_enabled
        and attendance_mode == "message"
        and is_teacher
        and text
        and not text.startswith("/")
    ):
        await TeacherSearchService.mark_attendance(
            session,
            chat_id=chat.id,
            user_id=user.id,
            source_message_id=message.message_id,
        )

    if text == "开课老师":
        await _reply_open_course_teachers(context, session, chat, message, delete_mode=delete_mode)
        return True

    if text == "附近":
        await _reply_nearby_teachers(context, session, chat, user, message, teacher_setting, delete_mode=delete_mode)
        return True

    if text.startswith("老师搜索 "):
        await _reply_teacher_keyword_search(context, session, chat, message, teacher_setting, text, delete_mode=delete_mode)
        return True

    footer_label = (teacher_setting.footer_button_label or "").strip()
    if footer_label and text == footer_label:
        await session.commit()
        await _reply_garage_feedback(
            context,
            chat_id=chat.id,
            message_id=message.message_id,
            text=TEACHER_SEARCH_HELP_TEXT,
            delete_mode=delete_mode,
        )
        return True

    return False


def _build_private_location_markup(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> InlineKeyboardMarkup | None:
    bot = getattr(context, "bot", None)
    bot_username = getattr(bot, "username", None)
    if not bot_username:
        return None
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("私聊更新定位", url=f"https://t.me/{bot_username}?start=tloc_{chat_id}")],
    ])


def _build_private_teacher_location_markup(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> InlineKeyboardMarkup | None:
    bot = getattr(context, "bot", None)
    bot_username = getattr(bot, "username", None)
    if not bot_username:
        return None
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("私聊更新定位", url=f"https://t.me/{bot_username}?start=tselfloc_{chat_id}")],
    ])


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
    user,
    message,
    teacher_setting,
    *,
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
    user,
    message,
    text: str,
    teacher_setting,
    *,
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
    user,
    message,
    *,
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


async def _reply_open_course_teachers(
    context: ContextTypes.DEFAULT_TYPE,
    session,
    chat,
    message,
    *,
    delete_mode: str,
) -> None:
    rows = await TeacherSearchService.list_open_course_teachers(session, chat.id)
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
    for idx, (profile, tg_user) in enumerate(rows[:10], start=1):
        name = f"@{tg_user.username}" if tg_user and tg_user.username else (
            tg_user.first_name if tg_user and tg_user.first_name else f"用户{profile.user_id}"
        )
        extra = " / ".join(part for part in [profile.region_text, profile.price_text] if part)
        lines.append(f"{idx}. {name}" + (f"  {extra}" if extra else ""))
    await _reply_garage_feedback(
        context,
        chat_id=chat.id,
        message_id=message.message_id,
        text="\n".join(lines),
        delete_mode=delete_mode,
    )


async def _reply_nearby_teachers(
    context: ContextTypes.DEFAULT_TYPE,
    session,
    chat,
    user,
    message,
    teacher_setting,
    *,
    delete_mode: str,
) -> None:
    if not teacher_setting.nearby_search_enabled:
        await session.commit()
        await _reply_garage_feedback(
            context,
            chat_id=chat.id,
            message_id=message.message_id,
            text="附近搜索已关闭。",
            delete_mode=delete_mode,
        )
        return
    location = await TeacherSearchService.get_member_location(session, chat.id, user.id)
    if location is None:
        await session.commit()
        await _reply_garage_feedback(
            context,
            chat_id=chat.id,
            message_id=message.message_id,
            text=LOCATION_UPDATE_PROMPT,
            reply_markup=_build_private_location_markup(context, chat.id),
            delete_mode=delete_mode,
        )
        return

    nearby = await TeacherSearchService.list_nearby_teachers(
        session,
        chat.id,
        float(location.latitude),
        float(location.longitude),
        only_open_course=getattr(teacher_setting, "only_open_course_enabled", True),
        limit=10,
    )
    await session.commit()
    if not nearby:
        await _reply_garage_feedback(
            context,
            chat_id=chat.id,
            message_id=message.message_id,
            text=(
                "附近暂无开课老师。"
                if getattr(teacher_setting, "only_open_course_enabled", True)
                else "附近暂无老师。"
            ),
            delete_mode=delete_mode,
        )
        return
    lines = ["附近老师："]
    for idx, item in enumerate(nearby, start=1):
        profile = item["profile"]
        extra = " / ".join(part for part in [profile.region_text, profile.price_text] if part)
        lines.append(f"{idx}. {item['display_name']} · {item['distance_text']}" + (f" · {extra}" if extra else ""))
    await _reply_garage_feedback(
        context,
        chat_id=chat.id,
        message_id=message.message_id,
        text="\n".join(lines),
        delete_mode=delete_mode,
    )


async def _reply_teacher_keyword_search(
    context: ContextTypes.DEFAULT_TYPE,
    session,
    chat,
    message,
    teacher_setting,
    text: str,
    *,
    delete_mode: str,
) -> None:
    if not teacher_setting.tag_search_enabled:
        await session.commit()
        await _reply_garage_feedback(
            context,
            chat_id=chat.id,
            message_id=message.message_id,
            text="标签搜索已关闭。",
            delete_mode=delete_mode,
        )
        return
    keyword = text.split(" ", 1)[1].strip()
    rows = await TeacherSearchService.search_teachers_by_keyword(
        session,
        chat.id,
        keyword,
        only_open_course=getattr(teacher_setting, "only_open_course_enabled", True),
        limit=10,
    )
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
    lines = [f"老师搜索：{keyword}"]
    for idx, (profile, tg_user) in enumerate(rows, start=1):
        name = f"@{tg_user.username}" if tg_user and tg_user.username else (
            tg_user.first_name if tg_user and tg_user.first_name else f"用户{profile.user_id}"
        )
        labels = " ".join(profile.labels or [])
        extra = " / ".join(part for part in [labels, profile.region_text, profile.price_text] if part)
        lines.append(f"{idx}. {name}" + (f" · {extra}" if extra else ""))
    await _reply_garage_feedback(
        context,
        chat_id=chat.id,
        message_id=message.message_id,
        text="\n".join(lines),
        delete_mode=delete_mode,
    )
