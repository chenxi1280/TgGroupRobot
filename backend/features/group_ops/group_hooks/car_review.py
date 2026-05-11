from __future__ import annotations

import datetime as dt
import html
import re
from dataclasses import dataclass

import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from backend.features.garage.services.garage_features_service import CarReviewService
from backend.features.group_ops.text_trigger_runtime import is_reserved_group_text_command_for_chat
from backend.features.nearby.services.nearby_profile_service import build_user_display_name
from backend.platform.db.schema.models.core import TgUser
from backend.shared.services.formatters import format_user_display_name
from backend.shared.services.publish_service import PublishService
from backend.shared.time_helper import LOCAL_TIMEZONE

from .common import _extract_car_review_media_file_ids, _reply_garage_feedback

log = structlog.get_logger(__name__)

_TEMPLATE_FIELD_RE = re.compile(r"\{([A-Za-z][A-Za-z0-9_]*)\}")
_EXACT_USERNAME_RE = re.compile(r"@?([A-Za-z][A-Za-z0-9_]{2,31})")
_MENTION_RE = re.compile(r"@([A-Za-z][A-Za-z0-9_]{2,31})")


@dataclass(frozen=True)
class _ParsedReview:
    review_text: str
    process_text: str | None
    scores: dict
    missing_labels: list[str]
    invalid_labels: list[str]


async def _publish_car_review_report(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    report,
    setting,
    teacher_user: TgUser | None,
    author_user: TgUser | None,
) -> int | None:
    score_payload = report.scores or {}
    teacher_name = (
        f"@{teacher_user.username}"
        if teacher_user and teacher_user.username
        else (teacher_user.first_name if teacher_user and teacher_user.first_name else str(report.teacher_user_id))
    )
    author_name = (
        f"@{author_user.username}"
        if author_user and author_user.username
        else (author_user.first_name if author_user and author_user.first_name else str(report.author_user_id))
    )
    created_at = report.created_at or dt.datetime.now(dt.UTC)
    values = {
        **score_payload,
        "time": created_at.astimezone(LOCAL_TIMEZONE).strftime("%Y-%m-%d %H:%M"),
        "teacher": teacher_name,
        "author": author_name,
        "review": report.review_text or "待审核",
        "process": report.process_text or report.review_text or "无",
    }
    text = _render_review_template(setting.template_text, values)
    published_message_id: int | None = None
    if getattr(setting, "publish_to_main_group", False):
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
        published_message_id = result.message_id
    return published_message_id


async def _process_car_review_features(
    context: ContextTypes.DEFAULT_TYPE,
    session,
    chat,
    user,
    message,
    text: str,
    car_review_setting,
) -> bool:
    if not getattr(car_review_setting, "enabled", False):
        return False

    rank_command = car_review_setting.rank_command.strip()
    rank_request = _resolve_rank_request(text, rank_command)
    if rank_request is not None:
        if await is_reserved_group_text_command_for_chat(session, chat.id, text):
            return False
        title, since = rank_request
        await _reply_car_review_rankings(context, session, chat, message, title=title, since=since)
        return True

    submit_command = car_review_setting.submit_command.strip() or "提交报告"
    if text in {submit_command, "提交车评"} and getattr(message, "reply_to_message", None) is None:
        if await is_reserved_group_text_command_for_chat(session, chat.id, text):
            return False
        await _reply_car_review_submit_entry(context, session, chat, message, car_review_setting)
        return True

    if submit_command and text.startswith(submit_command):
        if await is_reserved_group_text_command_for_chat(session, chat.id, text):
            return False
        await _submit_car_review(context, session, chat, user, message, text, submit_command, car_review_setting)
        return True

    if await _maybe_reply_car_review_lookup(context, session, chat, message, text, car_review_setting):
        return True

    return False


async def _reply_car_review_submit_entry(
    context: ContextTypes.DEFAULT_TYPE,
    session,
    chat,
    message,
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
    message,
    *,
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


async def _submit_car_review(
    context: ContextTypes.DEFAULT_TYPE,
    session,
    chat,
    user,
    message,
    text: str,
    submit_command: str,
    car_review_setting,
) -> None:
    replied_user = getattr(getattr(message, "reply_to_message", None), "from_user", None)
    if replied_user is None:
        await session.commit()
        await PublishService.reply(
            context,
            chat_id=chat.id,
            text="提交车评请回复目标老师的消息后再发送指令。",
            reply_to_message_id=message.message_id,
        )
        return
    if not getattr(car_review_setting, "approver_user_id", None):
        await session.commit()
        await PublishService.reply(
            context,
            chat_id=chat.id,
            text="车评系统还没有配置审核人，请管理员先在车评系统里指定审核人。",
            reply_to_message_id=message.message_id,
        )
        return
    review_body = text[len(submit_command):].strip()
    fields = [
        item
        for item in await CarReviewService.list_custom_fields(session, chat.id)
        if getattr(item, "enabled", False)
    ]
    parsed = _parse_review_body(
        review_body,
        fields,
        require_fields=(getattr(car_review_setting, "review_mode", "default") == "default"),
    )
    if parsed.invalid_labels or parsed.missing_labels:
        parts: list[str] = []
        if parsed.missing_labels:
            parts.append("缺少：" + "、".join(parsed.missing_labels))
        if parsed.invalid_labels:
            parts.append("分数格式不正确：" + "、".join(parsed.invalid_labels))
        await session.commit()
        await PublishService.reply(
            context,
            chat_id=chat.id,
            text="默认车评模式需要按模板填写完整项目。\n" + "\n".join(parts),
            reply_to_message_id=message.message_id,
        )
        return
    media_file_ids = _extract_car_review_media_file_ids(message)
    report = await CarReviewService.create_report(
        session,
        chat_id=chat.id,
        teacher_user_id=replied_user.id,
        author_user_id=user.id,
        review_text=parsed.review_text or "待补充",
        process_text=parsed.process_text,
        media_file_ids=media_file_ids,
        scores=parsed.scores,
    )
    if car_review_setting.approver_user_id:
        await session.commit()
        try:
            await PublishService.send(
                context,
                chat_id=car_review_setting.approver_user_id,
                text=(
                    f"收到新的车评待审核\n群：{chat.title}\n报告ID：{report.report_id}\n"
                    f"提交人：{format_user_display_name(user, user.id)}"
                ),
            )
        except Exception as exc:
            log.warning("car_review_notify_approver_failed", chat_id=chat.id, report_id=report.report_id, error=str(exc))
        await PublishService.reply(
            context,
            chat_id=chat.id,
            text=f"已提交车评报告，等待审核。报告ID：{report.report_id}",
            reply_to_message_id=message.message_id,
        )
        return

    await session.commit()
    await _reply_garage_feedback(
        context,
        chat_id=chat.id,
        message_id=message.message_id,
        text=f"车评已提交，等待管理员审核。报告ID：{report.report_id}",
    )


def _render_review_template(template_text: str, values: dict) -> str:
    def replace(match: re.Match[str]) -> str:
        value = values.get(match.group(1), "-")
        if value is None:
            return "-"
        return html.escape(str(value))

    return _TEMPLATE_FIELD_RE.sub(replace, template_text or "")


def _resolve_rank_request(text: str, rank_command: str) -> tuple[str, dt.datetime | None] | None:
    if not rank_command:
        return None
    now = dt.datetime.now(dt.UTC)
    if text == rank_command:
        return rank_command, None
    if text == f"本周{rank_command}":
        return f"本周{rank_command}", now - dt.timedelta(days=7)
    if text == f"本月{rank_command}":
        return f"本月{rank_command}", now - dt.timedelta(days=30)
    return None


async def _maybe_reply_car_review_lookup(
    context: ContextTypes.DEFAULT_TYPE,
    session,
    chat,
    message,
    text: str,
    car_review_setting,
) -> bool:
    lookup_mode = getattr(car_review_setting, "teacher_lookup_mode", "off") or "off"
    if lookup_mode == "off" or not text:
        return False

    teacher_user: TgUser | None = None
    if lookup_mode == "exact":
        match = _EXACT_USERNAME_RE.fullmatch(text.strip())
        if match is None:
            return False
        teacher_user = await CarReviewService.find_lookup_teacher_by_username(session, chat.id, match.group(1))
    elif lookup_mode == "contains":
        for username in _MENTION_RE.findall(text):
            teacher_user = await CarReviewService.find_lookup_teacher_by_username(session, chat.id, username)
            if teacher_user is not None:
                break
        if teacher_user is None:
            text_lower = text.lower()
            for candidate in await CarReviewService.list_lookup_teachers(session, chat.id):
                username = (candidate.username or "").lower()
                if username and username in text_lower:
                    teacher_user = candidate
                    break
    else:
        return False

    if teacher_user is None:
        return False

    await _reply_teacher_reviews(context, session, chat, message, teacher_user)
    return True


async def _reply_teacher_reviews(
    context: ContextTypes.DEFAULT_TYPE,
    session,
    chat,
    message,
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


def _parse_review_body(review_body: str, fields: list, *, require_fields: bool) -> _ParsedReview:
    field_values: dict[str, str] = {}
    review_lines: list[str] = []
    explicit_review: str | None = None
    for raw_line in (review_body or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        key, value = _match_field_line(line, fields)
        if key is not None:
            field_values[key] = value.strip()
            continue
        label, value = _split_label_value(line)
        if label in {"评价", "车评", "review"}:
            explicit_review = value
        else:
            review_lines.append(line)

    if not review_lines and review_body and not field_values and explicit_review is None:
        review_lines.append(review_body.strip())

    scores: dict = {}
    missing_labels: list[str] = []
    invalid_labels: list[str] = []
    score_values: list[float] = []
    for field in fields:
        field_key = getattr(field, "field_key", "")
        field_label = getattr(field, "field_label", field_key)
        raw_value = field_values.get(field_key, "")
        if require_fields and not raw_value:
            missing_labels.append(field_label)
            continue
        if not raw_value:
            continue
        if _is_score_field(field_key):
            score_value = _parse_score_value(raw_value)
            if score_value is None:
                invalid_labels.append(field_label)
                continue
            scores[field_key] = _compact_number(score_value)
            score_values.append(score_value)
        else:
            scores[field_key] = raw_value

    if score_values:
        scores["total_score"] = _compact_number(sum(score_values) / len(score_values))

    process_text = field_values.get("process")
    review_text = explicit_review if explicit_review is not None else "\n".join(review_lines).strip()
    if not review_text:
        review_text = process_text or ""
    return _ParsedReview(
        review_text=review_text,
        process_text=process_text,
        scores=scores,
        missing_labels=missing_labels,
        invalid_labels=invalid_labels,
    )


def _match_field_line(line: str, fields: list) -> tuple[str | None, str]:
    for field in sorted(fields, key=lambda item: len(getattr(item, "field_label", "")), reverse=True):
        field_key = getattr(field, "field_key", "")
        field_label = getattr(field, "field_label", field_key)
        for label in (field_label, field_key):
            prefix = str(label).strip()
            if not prefix:
                continue
            if line == prefix:
                return field_key, ""
            if line.startswith(prefix):
                rest = line[len(prefix):]
                stripped = rest.strip()
                if stripped.startswith((":", "：")):
                    return field_key, stripped[1:].strip()
                if rest and rest[0].isspace():
                    return field_key, stripped
    return None, ""


def _split_label_value(line: str) -> tuple[str, str]:
    for separator in ("：", ":"):
        if separator in line:
            label, value = line.split(separator, 1)
            return label.strip().lower(), value.strip()
    return line.strip().lower(), ""


def _is_score_field(field_key: str) -> bool:
    return field_key.endswith("_score") or field_key in {"score", "total_score"}


def _parse_score_value(raw_value: str) -> float | None:
    match = re.search(r"\d+(?:\.\d+)?", raw_value)
    if match is None:
        return None
    value = float(match.group(0))
    if value < 0 or value > 100:
        return None
    return value


def _compact_number(value: float) -> int | float:
    rounded = round(value, 2)
    return int(rounded) if rounded.is_integer() else rounded
