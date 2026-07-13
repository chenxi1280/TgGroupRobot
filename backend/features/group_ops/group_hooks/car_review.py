from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Awaitable, Callable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from backend.features.garage.services.garage_features_service import CarReviewService
from backend.features.group_ops.group_hooks.car_review_parsing import (
    parse_review_body as _parse_review_body_impl,
    render_review_template as _render_review_template,
    resolve_rank_request as _resolve_rank_request,
)
from backend.features.group_ops.group_hooks.car_review_submission import (
    submit_car_review as _submit_car_review,
)
from backend.features.group_ops.text_trigger_runtime import is_reserved_group_text_command_for_chat
from backend.features.nearby.services.nearby_profile_service import build_user_display_name
from backend.platform.db.schema.models.core import TgUser
from backend.shared.services.command_config_service import is_command_enabled
from backend.shared.services.publish_service import PublishService
from backend.shared.time_helper import LOCAL_TIMEZONE

_EXACT_USERNAME_RE = re.compile(r"@?([A-Za-z][A-Za-z0-9_]{2,31})")
_MENTION_RE = re.compile(r"@([A-Za-z][A-Za-z0-9_]{2,31})")


def _parse_review_body(review_body: str, fields: list, *, require_fields: bool):
    return _parse_review_body_impl(review_body, fields, require_fields=require_fields)


@dataclass(frozen=True, slots=True)
class _ReviewRequest:
    context: ContextTypes.DEFAULT_TYPE
    session: object
    chat: object
    user: object
    message: object
    text: str
    setting: object
    chat_settings: object | None


ReviewAction = Callable[[_ReviewRequest], Awaitable[bool]]


async def _publish_car_review_report(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    report,
    setting,
    teacher_user: TgUser | None,
    author_user: TgUser | None,
) -> int | None:
    values = _report_template_values(report, teacher_user=teacher_user, author_user=author_user)
    text = _render_review_template(setting.template_text, values)
    if not getattr(setting, "publish_to_main_group", False):
        return None
    media_file_ids = list(getattr(report, "media_file_ids", None) or [])
    if media_file_ids:
        result = await PublishService.send_photo(
            context,
            chat_id=chat_id,
            photo=media_file_ids[0],
            caption=text,
            parse_mode="HTML",
        )
    else:
        result = await PublishService.send(context, chat_id=chat_id, text=text, parse_mode="HTML")
    return result.message_id


def _report_template_values(report, *, teacher_user: TgUser | None, author_user: TgUser | None) -> dict:
    created_at = report.created_at or dt.datetime.now(dt.UTC)
    return {
        **(report.scores or {}),
        "time": created_at.astimezone(LOCAL_TIMEZONE).strftime("%Y-%m-%d %H:%M"),
        "teacher": _report_user_name(teacher_user, report.teacher_user_id),
        "author": _report_user_name(author_user, report.author_user_id),
        "review": report.review_text or "待审核",
        "process": report.process_text or report.review_text or "无",
    }


def _report_user_name(user: TgUser | None, fallback_user_id: int) -> str:
    if user and user.username:
        return f"@{user.username}"
    if user and user.first_name:
        return user.first_name
    return str(fallback_user_id)


async def _process_car_review_features(
    context: ContextTypes.DEFAULT_TYPE,
    session,
    chat,
    *, user,
    message,
    text: str,
    car_review_setting,
    chat_settings=None,
) -> bool:
    if not getattr(car_review_setting, "enabled", False):
        return False
    request = _ReviewRequest(
        context=context,
        session=session,
        chat=chat,
        user=user,
        message=message,
        text=text,
        setting=car_review_setting,
        chat_settings=chat_settings,
    )
    actions: tuple[ReviewAction, ...] = (
        _handle_review_rank,
        _handle_review_submit_entry,
        _handle_review_submit,
        _handle_review_lookup,
    )
    for action in actions:
        if await action(request):
            return True
    return False


async def _handle_review_rank(request: _ReviewRequest) -> bool:
    rank_request = _resolve_rank_request(request.text, request.setting.rank_command.strip())
    if rank_request is None:
        return False
    if await _reserved_review_command(request):
        return False
    if await _reply_if_command_disabled(request, "car_review_rank"):
        return True
    title, since = rank_request
    await _reply_car_review_rankings(
        request.context,
        request.session,
        request.chat,
        message=request.message,
        title=title,
        since=since,
    )
    return True


async def _handle_review_submit_entry(request: _ReviewRequest) -> bool:
    submit_command = request.setting.submit_command.strip() or "提交报告"
    is_entry = request.text in {submit_command, "提交车评"}
    if not is_entry or getattr(request.message, "reply_to_message", None) is not None:
        return False
    if await _reserved_review_command(request):
        return False
    if await _reply_if_command_disabled(request, "car_review"):
        return True
    await _reply_car_review_submit_entry(
        request.context,
        request.session,
        request.chat,
        message=request.message,
        car_review_setting=request.setting,
    )
    return True


async def _handle_review_submit(request: _ReviewRequest) -> bool:
    submit_command = request.setting.submit_command.strip() or "提交报告"
    if not submit_command or not request.text.startswith(submit_command):
        return False
    if await _reserved_review_command(request):
        return False
    if await _reply_if_command_disabled(request, "car_review"):
        return True
    await _submit_car_review(
        request.context,
        request.session,
        request.chat,
        user=request.user,
        message=request.message,
        text=request.text,
        submit_command=submit_command,
        car_review_setting=request.setting,
    )
    return True


async def _handle_review_lookup(request: _ReviewRequest) -> bool:
    return await _maybe_reply_car_review_lookup(
        request.context,
        request.session,
        request.chat,
        message=request.message,
        text=request.text,
        car_review_setting=request.setting,
    )


async def _reserved_review_command(request: _ReviewRequest) -> bool:
    return await is_reserved_group_text_command_for_chat(
        request.session,
        request.chat.id,
        request.text,
    )


async def _reply_if_command_disabled(request: _ReviewRequest, command: str) -> bool:
    if request.chat_settings is None or is_command_enabled(request.chat_settings, command):
        return False
    await PublishService.reply(
        request.context,
        chat_id=request.chat.id,
        text="该指令已关闭。",
        reply_to_message_id=request.message.message_id,
    )
    return True


async def _reply_car_review_submit_entry(
    context: ContextTypes.DEFAULT_TYPE,
    session,
    chat,
    *, message,
    car_review_setting,
) -> None:
    if not getattr(car_review_setting, "approver_user_id", None):
        await session.commit()
        await PublishService.reply(
            context,
            chat_id=chat.id,
            text="车评系统还没有配置审核人，请管理员先在车评系统里指定审核人。",
            reply_to_message_id=message.message_id,
        )
        return

    bot_username = getattr(getattr(context, "bot", None), "username", None)
    reply_markup = None
    if bot_username:
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("去私聊提交车评", url=f"https://t.me/{bot_username}?start=crvsub_{chat.id}")],
        ])
    await session.commit()
    await PublishService.reply(
        context,
        chat_id=chat.id,
        text="请点击下方按钮到机器人私聊提交车评。进入后先发送老师 @用户名 或 Telegram ID。",
        reply_to_message_id=message.message_id,
        reply_markup=reply_markup,
    )


async def _reply_car_review_rankings(
    context: ContextTypes.DEFAULT_TYPE,
    session,
    chat,
    *, message,

    title: str,
    since: dt.datetime | None,
) -> None:
    rankings = await CarReviewService.list_rankings(session, chat.id, limit=10, since=since)
    await session.commit()
    if not rankings:
        await PublishService.reply(
            context,
            chat_id=chat.id,
            text=f"暂无{title}数据。",
            reply_to_message_id=message.message_id,
        )
        return
    lines = [f"{title}："]
    for idx, row in enumerate(rankings, start=1):
        lines.append(f"{idx}. {row['display_name']} · 均分 {row['avg_score']} · {row['count']} 条")
    await PublishService.reply(
        context,
        chat_id=chat.id,
        text="\n".join(lines),
        reply_to_message_id=message.message_id,
    )


async def _maybe_reply_car_review_lookup(
    context: ContextTypes.DEFAULT_TYPE,
    session,
    chat,
    *, message,
    text: str,
    car_review_setting,
) -> bool:
    lookup_mode = getattr(car_review_setting, "teacher_lookup_mode", "off") or "off"
    if lookup_mode == "off" or not text:
        return False
    teacher_user = await _find_review_lookup_teacher(
        session,
        chat.id,
        text=text,
        lookup_mode=lookup_mode,
    )
    if teacher_user is None:
        return False
    await _reply_teacher_reviews(context, session, chat, message=message, teacher_user=teacher_user)
    return True


async def _find_review_lookup_teacher(
    session,
    chat_id: int,
    *,
    text: str,
    lookup_mode: str,
) -> TgUser | None:
    if lookup_mode == "exact":
        match = _EXACT_USERNAME_RE.fullmatch(text.strip())
        if match is None:
            return None
        return await CarReviewService.find_lookup_teacher_by_username(session, chat_id, match.group(1))
    if lookup_mode == "contains":
        return await _find_contained_review_teacher(session, chat_id, text=text)
    return None


async def _find_contained_review_teacher(session, chat_id: int, *, text: str) -> TgUser | None:
    for username in _MENTION_RE.findall(text):
        teacher = await CarReviewService.find_lookup_teacher_by_username(session, chat_id, username)
        if teacher is not None:
            return teacher
    text_lower = text.lower()
    for candidate in await CarReviewService.list_lookup_teachers(session, chat_id):
        username = (candidate.username or "").lower()
        if username and username in text_lower:
            return candidate
    return None


async def _reply_teacher_reviews(
    context: ContextTypes.DEFAULT_TYPE,
    session,
    chat,
    *, message,
    teacher_user: TgUser,
) -> None:
    reports = await CarReviewService.list_reports_for_teacher(session, chat.id, teacher_user.id, limit=5)
    stats = await CarReviewService.get_teacher_review_stats(session, chat.id, teacher_user.id)
    await session.commit()
    display_name = build_user_display_name(teacher_user, teacher_user.id)
    if not reports:
        await PublishService.reply(
            context,
            chat_id=chat.id,
            text=f"暂无 {display_name} 的车评。",
            reply_to_message_id=message.message_id,
        )
        return
    lines = [
        f"{display_name} 的车评：",
        f"共 {stats['count']} 条，均分 {stats['avg_score']}",
    ]
    for idx, (report, author) in enumerate(reports, start=1):
        score = (report.scores or {}).get("total_score", "-")
        created_at = report.created_at.astimezone(LOCAL_TIMEZONE).strftime("%m-%d") if report.created_at else "--"
        author_name = build_user_display_name(author, report.author_user_id) if author else "匿名"
        summary = " ".join((report.review_text or "无评价内容").split())[:60]
        lines.append(f"{idx}. {created_at} · {score}分 · {author_name}：{summary}")
    await PublishService.reply(
        context,
        chat_id=chat.id,
        text="\n".join(lines),
        reply_to_message_id=message.message_id,
    )
