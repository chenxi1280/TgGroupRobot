"""车评提交、校验与审核人通知。"""
from __future__ import annotations

import structlog

from backend.features.garage.services.garage_features_service import CarReviewService
from backend.features.group_ops.group_hooks.car_review_parsing import parse_review_body
from backend.shared.services.formatters import format_user_display_name
from backend.shared.services.publish_service import PublishService

from .common import _extract_car_review_media_file_ids

log = structlog.get_logger(__name__)


async def submit_car_review(
    context,
    session,
    chat,
    *,
    user,
    message,
    text: str,
    submit_command: str,
    car_review_setting,
) -> None:
    targets = await _resolve_submission_targets(
        context,
        session,
        chat,
        message=message,
        setting=car_review_setting,
    )
    if targets is None:
        return
    replied_user, approver_user_id = targets
    parsed = await _parse_submission(
        session,
        chat.id,
        review_body=text[len(submit_command):].strip(),
        review_mode=getattr(car_review_setting, "review_mode", "default"),
    )
    if await _reply_if_invalid(context, session, chat, message=message, parsed=parsed):
        return
    report = await _create_review_report(
        session,
        chat.id,
        teacher_user_id=replied_user.id,
        author_user_id=user.id,
        message=message,
        parsed=parsed,
    )
    await _complete_submission(
        context,
        session,
        chat,
        user=user,
        message=message,
        report=report,
        approver_user_id=approver_user_id,
    )


async def _reply_if_invalid(context, session, chat, *, message, parsed) -> bool:
    if not parsed.invalid_labels and not parsed.missing_labels:
        return False
    await _reply_review_error(
        context,
        session,
        chat,
        message=message,
        text=_review_validation_error(parsed),
    )
    return True


async def _resolve_submission_targets(context, session, chat, *, message, setting):
    replied_user = getattr(getattr(message, "reply_to_message", None), "from_user", None)
    if replied_user is None:
        await _reply_review_error(
            context,
            session,
            chat,
            message=message,
            text="提交车评请回复目标老师的消息后再发送指令。",
        )
        return None
    approver_user_id = getattr(setting, "approver_user_id", None)
    if not approver_user_id:
        await _reply_review_error(
            context,
            session,
            chat,
            message=message,
            text="车评系统还没有配置审核人，请管理员先在车评系统里指定审核人。",
        )
        return None
    return replied_user, approver_user_id


async def _parse_submission(session, chat_id: int, *, review_body: str, review_mode: str):
    fields = await _enabled_review_fields(session, chat_id)
    return parse_review_body(
        review_body,
        fields,
        require_fields=review_mode == "default",
    )


async def _create_review_report(
    session,
    chat_id: int,
    *,
    teacher_user_id: int,
    author_user_id: int,
    message,
    parsed,
):
    return await CarReviewService.create_report(
        session,
        chat_id=chat_id,
        teacher_user_id=teacher_user_id,
        author_user_id=author_user_id,
        review_text=parsed.review_text or "待补充",
        process_text=parsed.process_text,
        media_file_ids=_extract_car_review_media_file_ids(message),
        scores=parsed.scores,
    )


async def _complete_submission(
    context,
    session,
    chat,
    *,
    user,
    message,
    report,
    approver_user_id: int,
) -> None:
    await _notify_review_approver(
        context,
        session,
        chat,
        user=user,
        report=report,
        approver_user_id=approver_user_id,
    )
    await PublishService.reply(
        context,
        chat_id=chat.id,
        text=f"已提交车评报告，等待审核。报告ID：{report.report_id}",
        reply_to_message_id=message.message_id,
    )


async def _reply_review_error(context, session, chat, *, message, text: str) -> None:
    await session.commit()
    await PublishService.reply(
        context,
        chat_id=chat.id,
        text=text,
        reply_to_message_id=message.message_id,
    )


async def _enabled_review_fields(session, chat_id: int) -> list:
    fields = await CarReviewService.list_custom_fields(session, chat_id)
    return [item for item in fields if getattr(item, "enabled", False)]


def _review_validation_error(parsed) -> str:
    parts: list[str] = []
    if parsed.missing_labels:
        parts.append("缺少：" + "、".join(parsed.missing_labels))
    if parsed.invalid_labels:
        parts.append("分数格式不正确：" + "、".join(parsed.invalid_labels))
    return "默认车评模式需要按模板填写完整项目。\n" + "\n".join(parts)


async def _notify_review_approver(
    context,
    session,
    chat,
    *,
    user,
    report,
    approver_user_id: int,
) -> None:
    await session.commit()
    try:
        await PublishService.send(
            context,
            chat_id=approver_user_id,
            text=(
                f"收到新的车评待审核\n群：{chat.title}\n报告ID：{report.report_id}\n"
                f"提交人：{format_user_display_name(user, user.id)}"
            ),
        )
    except Exception as exc:
        log.warning(
            "car_review_notify_approver_failed",
            chat_id=chat.id,
            report_id=report.report_id,
            error=str(exc),
        )
