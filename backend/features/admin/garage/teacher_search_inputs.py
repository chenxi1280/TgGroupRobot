from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from telegram import ReplyKeyboardRemove, Update
from telegram.ext import ContextTypes

from backend.features.admin.garage.input_runtime import (
    admin_handler_instance,
    clear_admin_input_state,
)
from backend.shared.services.base import ValidationError

CLEAR_VALUES = {"清空", "无"}
DELEGATE_TARGET_STATE = "teacher_delegate_target_input"
DELEGATE_LOCATION_STATE = "teacher_delegate_location_input"
ATTENDANCE_TARGET_STATE = "teacher_attend_target_input"
ATTENDANCE_KEYWORD_STATES = {
    "teacher_att_open_input": "open",
    "teacher_att_full_input": "full",
    "teacher_att_rest_input": "rest",
}
_MAP_URL_RE = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)
_AT_COORD_RE = re.compile(r"@(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)")
_BANG_COORD_RE = re.compile(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)")
_QUERY_COORD_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)")


def _delegate_location_prompt() -> str:
    return (
        "📍 请发送这位老师的位置。\n\n"
        "手机端可以直接发送位置；桌面端请点输入框旁的回形针 → 位置 → 在地图上选择/搜索地点后发送。\n"
        "也可以粘贴 Google 地图定位链接。\n"
        "不要手动输入经纬度。"
    )


def _delegate_location_retry_prompt() -> str:
    return "请通过回形针 → 位置 发送地点，或粘贴 Google 地图定位链接。"


def _coordinate_pair(latitude_raw: str, longitude_raw: str) -> tuple[float, float] | None:
    try:
        latitude = float(latitude_raw)
        longitude = float(longitude_raw)
    except (TypeError, ValueError):
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    return latitude, longitude


def _parse_coordinates_from_map_text(value: str) -> tuple[float, float] | None:
    text = value.strip()
    for _ in range(3):
        decoded = unquote(text)
        if decoded == text:
            break
        text = decoded

    for pattern in (_AT_COORD_RE, _BANG_COORD_RE):
        match = pattern.search(text)
        if match:
            pair = _coordinate_pair(match.group(1), match.group(2))
            if pair is not None:
                return pair

    parsed = urlparse(text)
    query_values = parse_qs(parsed.query)
    for key in ("q", "query", "ll", "center", "destination"):
        for raw_value in query_values.get(key, []):
            match = _QUERY_COORD_RE.match(raw_value)
            if match:
                pair = _coordinate_pair(match.group(1), match.group(2))
                if pair is not None:
                    return pair

    if parsed.scheme == "geo":
        match = _QUERY_COORD_RE.match(parsed.path)
        if match:
            return _coordinate_pair(match.group(1), match.group(2))
    return None


def _extract_map_urls(text: str) -> list[str]:
    urls: list[str] = []
    for match in _MAP_URL_RE.finditer(text):
        url = match.group(0).strip(" \t\r\n\"'<>),，。")
        host = urlparse(url).netloc.lower()
        if "google" in host or "goo.gl" in host:
            urls.append(url)
    return urls


def _is_short_map_url(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return host in {"maps.app.goo.gl", "goo.gl"} or host.endswith(".goo.gl")


async def _expand_map_url(url: str) -> str | None:
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=5.0) as client:
            response = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            return str(response.url)
    except httpx.HTTPError:
        return None


async def _parse_coordinates_from_map_link(text: str) -> tuple[float, float] | None:
    for url in _extract_map_urls(text):
        pair = _parse_coordinates_from_map_text(url)
        if pair is not None:
            return pair
        if _is_short_map_url(url):
            expanded_url = await _expand_map_url(url)
            if expanded_url:
                pair = _parse_coordinates_from_map_text(expanded_url)
                if pair is not None:
                    return pair
    return None


async def handle_teacher_search_feature_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state,
    target_chat_id: int,
    text_value: str,
) -> bool:
    if state.state_type in {"teacher_footer_text_input", "teacher_footer_button_input"}:
        await _handle_footer_button_text_input(update, context, session, target_chat_id, text_value)
        return True

    if state.state_type == "teacher_footer_link_input":
        await _handle_footer_button_link_input(update, context, session, target_chat_id, text_value)
        return True

    if state.state_type == DELEGATE_TARGET_STATE:
        await _handle_delegate_target_input(update, session, target_chat_id, text_value)
        return True

    if state.state_type == ATTENDANCE_TARGET_STATE:
        await _handle_attendance_target_input(update, context, session, target_chat_id, text_value)
        return True

    if state.state_type in ATTENDANCE_KEYWORD_STATES:
        await _handle_attendance_keyword_input(
            update,
            context,
            session,
            target_chat_id,
            ATTENDANCE_KEYWORD_STATES[state.state_type],
            text_value,
        )
        return True

    if state.state_type == DELEGATE_LOCATION_STATE:
        await _handle_delegate_location_input(update, context, session, state, target_chat_id, text_value)
        return True

    return False


def _is_clear_input(value: str) -> bool:
    return value.strip().lower().startswith("/clear") or value.strip() in CLEAR_VALUES


async def _finish_footer_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    target_chat_id: int,
    reply_text: str,
) -> None:
    if update.effective_user is None or update.effective_message is None:
        return
    await clear_admin_input_state(session, target_chat_id=target_chat_id, user_id=update.effective_user.id)
    await session.commit()
    await update.effective_message.reply_text(reply_text)
    await admin_handler_instance()._show_teacher_search_footer_menu(update, context, target_chat_id)


async def _handle_footer_button_text_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    target_chat_id: int,
    text_value: str,
) -> None:
    from backend.features.garage.services.garage_features_service import TeacherSearchService

    if update.effective_message is None:
        return

    label = None if _is_clear_input(text_value) else text_value
    try:
        config = await TeacherSearchService.update_footer_button_text(session, target_chat_id, label)
    except ValidationError as exc:
        await update.effective_message.reply_text(str(exc))
        return
    await _finish_footer_input(
        update,
        context,
        session,
        target_chat_id,
        f"已设置底部按钮文字：{config.button_text}" if config.button_text else "已清空底部按钮文字。",
    )


async def _handle_footer_button_link_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    target_chat_id: int,
    text_value: str,
) -> None:
    from backend.features.garage.services.garage_features_service import TeacherSearchService

    if update.effective_message is None:
        return

    url = None if _is_clear_input(text_value) else text_value
    try:
        config = await TeacherSearchService.update_footer_button_url(session, target_chat_id, url)
    except ValidationError as exc:
        await update.effective_message.reply_text(str(exc))
        return
    await _finish_footer_input(
        update,
        context,
        session,
        target_chat_id,
        f"已设置底部按钮链接：{config.button_url}" if config.button_url else "已清空底部按钮链接。",
    )


async def _handle_delegate_target_input(
    update: Update,
    session,
    target_chat_id: int,
    text_value: str,
) -> None:
    from backend.features.garage.services.garage_features_service import TeacherSearchService
    from backend.platform.state.state_service import set_user_state

    if update.effective_user is None or update.effective_message is None:
        return

    try:
        user = await TeacherSearchService.resolve_delegate_user(session, text_value)
    except ValidationError as exc:
        await update.effective_message.reply_text(str(exc))
        return

    await clear_admin_input_state(session, target_chat_id=target_chat_id, user_id=update.effective_user.id)
    await set_user_state(
        session,
        chat_id=target_chat_id,
        user_id=update.effective_user.id,
        state_type=DELEGATE_LOCATION_STATE,
        state_data={"target_chat_id": target_chat_id, "delegate_user_id": user.id},
    )
    await session.commit()
    await update.effective_message.reply_text(
        _delegate_location_prompt(),
        reply_markup=ReplyKeyboardRemove(),
    )


async def _handle_attendance_target_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    target_chat_id: int,
    text_value: str,
) -> None:
    from backend.features.garage.services.garage_features_service import GarageAuthService, TeacherSearchService

    if update.effective_user is None or update.effective_message is None:
        return

    try:
        user = await TeacherSearchService.resolve_delegate_user(session, text_value)
    except ValidationError as exc:
        await update.effective_message.reply_text(str(exc))
        return

    if not await GarageAuthService.is_certified_teacher(session, target_chat_id, user.id):
        await update.effective_message.reply_text("该用户不是当前群的上牌老师，无法替他打卡。")
        return

    await TeacherSearchService.mark_attendance(
        session,
        chat_id=target_chat_id,
        user_id=user.id,
        source_message_id=update.effective_message.message_id,
    )
    await clear_admin_input_state(session, target_chat_id=target_chat_id, user_id=update.effective_user.id)
    await session.commit()
    display_name = f"@{user.username}" if getattr(user, "username", None) else str(user.id)
    await update.effective_message.reply_text(f"✅ 已替 {display_name} 记录今日开课打卡。")
    await admin_handler_instance()._show_teacher_search_menu(update, context, target_chat_id)


async def _handle_attendance_keyword_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    target_chat_id: int,
    kind: str,
    text_value: str,
) -> None:
    from backend.features.garage.services.garage_features_service import TeacherSearchService

    if update.effective_user is None or update.effective_message is None:
        return

    try:
        await TeacherSearchService.update_attendance_keyword(session, target_chat_id, kind, text_value)
    except ValidationError as exc:
        await update.effective_message.reply_text(str(exc))
        return

    label_map = {"open": "开课词", "full": "满课词", "rest": "休息词"}
    await clear_admin_input_state(session, target_chat_id=target_chat_id, user_id=update.effective_user.id)
    await session.commit()
    await update.effective_message.reply_text(f"✅ 已更新{label_map[kind]}：{text_value.strip()}")
    await admin_handler_instance()._show_teacher_search_attendance_mode_menu(update, context, target_chat_id)


async def _handle_delegate_location_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state,
    target_chat_id: int,
    text_value: str,
) -> None:
    from backend.features.garage.services.garage_features_service import TeacherSearchService

    if update.effective_user is None or update.effective_message is None:
        return

    location = getattr(update.effective_message, "location", None)
    if location is None:
        venue = getattr(update.effective_message, "venue", None)
        location = getattr(venue, "location", None) if venue is not None else None

    if location is not None:
        latitude = float(location.latitude)
        longitude = float(location.longitude)
    else:
        parsed_pair = await _parse_coordinates_from_map_link(text_value)
        if parsed_pair is not None:
            latitude, longitude = parsed_pair
        else:
            await update.effective_message.reply_text(
                _delegate_location_retry_prompt(),
                reply_markup=ReplyKeyboardRemove(),
            )
            return

    delegate_user_id = state.state_data.get("delegate_user_id")
    if not isinstance(delegate_user_id, int):
        await clear_admin_input_state(session, target_chat_id=target_chat_id, user_id=update.effective_user.id)
        await session.commit()
        await update.effective_message.reply_text(
            "代录状态异常，请重新进入。",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    await TeacherSearchService.upsert_member_location(
        session,
        chat_id=target_chat_id,
        user_id=delegate_user_id,
        latitude=latitude,
        longitude=longitude,
        operator_user_id=update.effective_user.id,
    )
    await TeacherSearchService.upsert_teacher_profile_from_location(
        session,
        chat_id=target_chat_id,
        user_id=delegate_user_id,
        latitude=latitude,
        longitude=longitude,
    )
    await clear_admin_input_state(session, target_chat_id=target_chat_id, user_id=update.effective_user.id)
    await session.commit()
    await update.effective_message.reply_text("✅ 已为该老师录入位置。", reply_markup=ReplyKeyboardRemove())
    await admin_handler_instance()._show_teacher_search_menu(update, context, target_chat_id)
