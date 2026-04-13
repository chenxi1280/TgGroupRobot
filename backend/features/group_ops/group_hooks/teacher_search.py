from __future__ import annotations

from telegram.ext import ContextTypes

from backend.features.garage.services.garage_features_service import TeacherSearchService

from .common import _reply_garage_feedback


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
) -> bool:
    if getattr(message, "location", None) is not None and teacher_setting.nearby_search_enabled:
        await _record_teacher_location(context, session, chat, user, message, is_teacher=is_teacher)
        return True

    delete_mode = getattr(teacher_setting, "delete_mode", "none")

    if teacher_setting.attendance_enabled and is_teacher and text and not text.startswith("/"):
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
            text="请继续发送关键词，或发送“附近”“开课老师”查询。",
            delete_mode=delete_mode,
        )
        return True

    return False


async def _record_teacher_location(
    context: ContextTypes.DEFAULT_TYPE,
    session,
    chat,
    user,
    message,
    *,
    is_teacher: bool,
) -> None:
    latitude = float(message.location.latitude)
    longitude = float(message.location.longitude)
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
    if teacher_setting.force_location_enabled and location is None:
        await session.commit()
        await _reply_garage_feedback(
            context,
            chat_id=chat.id,
            message_id=message.message_id,
            text="请先发送位置后再使用附近搜索。",
            delete_mode=delete_mode,
        )
        return
    if location is None:
        await session.commit()
        await _reply_garage_feedback(
            context,
            chat_id=chat.id,
            message_id=message.message_id,
            text="还没有记录到你的位置，请先发送位置。",
            delete_mode=delete_mode,
        )
        return

    nearby = await TeacherSearchService.list_nearby_teachers(
        session,
        chat.id,
        float(location.latitude),
        float(location.longitude),
        only_open_course=True,
        limit=10,
    )
    await session.commit()
    if not nearby:
        await _reply_garage_feedback(
            context,
            chat_id=chat.id,
            message_id=message.message_id,
            text="附近暂无开课老师。",
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
        only_open_course=True,
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
