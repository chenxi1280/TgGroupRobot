from __future__ import annotations

import datetime as dt
import html

import structlog
from telegram.ext import ContextTypes

from backend.features.garage.services.garage_features_service import CarReviewService
from backend.platform.db.schema.models.core import TgUser
from backend.shared.services.publish_service import PublishService

from .common import _extract_car_review_media_file_ids, _reply_garage_feedback

log = structlog.get_logger(__name__)


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
    text = (
        setting.template_text
        .replace("{time}", report.created_at.astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"))
        .replace("{teacher}", html.escape(teacher_name))
        .replace("{author}", html.escape(author_name))
        .replace("{review}", html.escape(report.review_text or "待审核"))
        .replace("{photo_score}", str(score_payload.get("photo_score", "-")))
        .replace("{face_score}", str(score_payload.get("face_score", "-")))
        .replace("{body_score}", str(score_payload.get("body_score", "-")))
        .replace("{service_score}", str(score_payload.get("service_score", "-")))
        .replace("{attitude_score}", str(score_payload.get("attitude_score", "-")))
        .replace("{env_score}", str(score_payload.get("env_score", "-")))
        .replace("{total_score}", str(score_payload.get("total_score", "-")))
        .replace("{process}", html.escape(report.process_text or report.review_text or "无"))
    )
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
    if rank_command and text == rank_command:
        await _reply_car_review_rankings(context, session, chat, message)
        return True

    submit_command = car_review_setting.submit_command.strip()
    if submit_command and text.startswith(submit_command):
        await _submit_car_review(context, session, chat, user, message, text, submit_command, car_review_setting)
        return True

    return False


async def _reply_car_review_rankings(
    context: ContextTypes.DEFAULT_TYPE,
    session,
    chat,
    message,
) -> None:
    rankings = await CarReviewService.list_rankings(session, chat.id, limit=10)
    await session.commit()
    if not rankings:
        await PublishService.reply(
            context,
            chat_id=chat.id,
            text="暂无车评排行数据。",
            reply_to_message_id=message.message_id,
        )
        return
    lines = ["出击排行："]
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
    review_text = text[len(submit_command):].strip() or "待补充"
    media_file_ids = _extract_car_review_media_file_ids(message)
    report = await CarReviewService.create_report(
        session,
        chat_id=chat.id,
        teacher_user_id=replied_user.id,
        author_user_id=user.id,
        review_text=review_text,
        media_file_ids=media_file_ids,
        scores={"total_score": 0},
    )
    if car_review_setting.approver_user_id:
        await session.commit()
        try:
            await PublishService.send(
                context,
                chat_id=car_review_setting.approver_user_id,
                text=f"收到新的车评待审核\n群：{chat.title}\n报告ID：{report.report_id}\n提交人：{user.full_name}",
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
