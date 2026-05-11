from __future__ import annotations

import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import ContextTypes

from backend.features.garage.services.garage_features_shared import _resolve_user
from backend.features.garage.services.garage_features_service import CarReviewService, GarageAuthService
from backend.features.group_ops.group_hooks.car_review import _parse_review_body
from backend.features.group_ops.group_hooks.common import _extract_car_review_media_file_ids
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.core import TgChat, TgUser
from backend.platform.db.schema.models.enums import ConversationStateType
from backend.platform.state.state_service import clear_user_state, set_user_state
from backend.shared.services.base import ValidationError
from backend.shared.services.formatters import format_user_display_name
from backend.shared.services.publish_service import PublishService

log = structlog.get_logger(__name__)

TEACHER_STATE = ConversationStateType.car_review_submit_teacher_input.value
BODY_STATE = ConversationStateType.car_review_submit_body_input.value


async def start_car_review_submit_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, target_chat_id: int) -> bool:
    if update.effective_message is None or update.effective_user is None:
        return True
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        target_chat = await session.get(TgChat, target_chat_id)
        setting = await CarReviewService.get_setting(session, target_chat_id) if target_chat is not None else None
        if target_chat is None:
            await session.commit()
            await update.effective_message.reply_text("车评提交入口已失效，请回群重新点击“提交车评”。")
            return True
        if setting is None or not getattr(setting, "enabled", False):
            await session.commit()
            await update.effective_message.reply_text("该群暂未启用车评系统。")
            return True
        if not getattr(setting, "approver_user_id", None):
            await session.commit()
            await update.effective_message.reply_text("车评系统还没有配置审核人，请先联系管理员配置后再提交。")
            return True
        await set_user_state(
            session,
            chat_id=update.effective_user.id,
            user_id=update.effective_user.id,
            state_type=TEACHER_STATE,
            state_data={"target_chat_id": target_chat_id},
        )
        await session.commit()

    await update.effective_message.reply_text(
        (
            "提交车评\n\n"
            f"目标群：{target_chat.title or target_chat_id}\n"
            "请先发送目标老师的 @用户名 或 Telegram ID。"
        ),
        reply_markup=ReplyKeyboardRemove(),
    )
    return True


async def handle_car_review_submit_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state,
    message_text: str,
) -> None:
    if update.effective_message is None or update.effective_user is None:
        return
    if state.state_type == TEACHER_STATE:
        await _handle_teacher_input(update, context, session, state, message_text)
        return
    if state.state_type == BODY_STATE:
        await _handle_body_input(update, context, session, state, message_text)
        return
    await clear_user_state(session, chat_id=state.chat_id, user_id=update.effective_user.id)
    await update.effective_message.reply_text("车评提交状态异常，已退出，请回群重新点击“提交车评”。")


async def _handle_teacher_input(update: Update, context: ContextTypes.DEFAULT_TYPE, session, state, message_text: str) -> None:
    data = state.state_data if isinstance(state.state_data, dict) else {}
    target_chat_id = data.get("target_chat_id")
    if not isinstance(target_chat_id, int):
        await clear_user_state(session, chat_id=state.chat_id, user_id=update.effective_user.id)
        await update.effective_message.reply_text("车评提交入口参数异常，请回群重新点击“提交车评”。")
        return

    setting = await CarReviewService.get_setting(session, target_chat_id)
    if not getattr(setting, "approver_user_id", None):
        await clear_user_state(session, chat_id=state.chat_id, user_id=update.effective_user.id)
        await update.effective_message.reply_text("车评系统还没有配置审核人，请先联系管理员配置后再提交。")
        return

    try:
        teacher = await _resolve_user(session, message_text)
    except ValidationError as exc:
        await update.effective_message.reply_text(f"{exc}\n\n请发送老师 @用户名 或 Telegram ID。")
        return

    if not await GarageAuthService.is_effective_certified_teacher(session, target_chat_id, teacher.id):
        await update.effective_message.reply_text("该用户不是当前群有效认证老师，请重新发送老师 @用户名 或 Telegram ID。")
        return

    fields = [item for item in await CarReviewService.list_custom_fields(session, target_chat_id) if getattr(item, "enabled", False)]
    field_lines = [f"- {item.field_label}：分数或内容" for item in fields]
    await set_user_state(
        session,
        chat_id=state.chat_id,
        user_id=update.effective_user.id,
        state_type=BODY_STATE,
        state_data={"target_chat_id": target_chat_id, "teacher_user_id": teacher.id},
    )
    await update.effective_message.reply_text(
        (
            f"已选择老师：{format_user_display_name(teacher, teacher.id)}\n\n"
            "请发送车评内容，也可以附带图片。\n"
            "默认模式请按字段逐行填写，例如：\n"
            + "\n".join(field_lines[:8])
        )
    )


async def _handle_body_input(update: Update, context: ContextTypes.DEFAULT_TYPE, session, state, message_text: str) -> None:
    data = state.state_data if isinstance(state.state_data, dict) else {}
    target_chat_id = data.get("target_chat_id")
    teacher_user_id = data.get("teacher_user_id")
    if not isinstance(target_chat_id, int) or not isinstance(teacher_user_id, int):
        await clear_user_state(session, chat_id=state.chat_id, user_id=update.effective_user.id)
        await update.effective_message.reply_text("车评提交入口参数异常，请回群重新点击“提交车评”。")
        return

    setting = await CarReviewService.get_setting(session, target_chat_id)
    if not getattr(setting, "approver_user_id", None):
        await clear_user_state(session, chat_id=state.chat_id, user_id=update.effective_user.id)
        await update.effective_message.reply_text("车评系统还没有配置审核人，请先联系管理员配置后再提交。")
        return

    fields = [item for item in await CarReviewService.list_custom_fields(session, target_chat_id) if getattr(item, "enabled", False)]
    parsed = _parse_review_body(
        message_text or "",
        fields,
        require_fields=(getattr(setting, "review_mode", "default") == "default"),
    )
    if parsed.invalid_labels or parsed.missing_labels:
        parts: list[str] = []
        if parsed.missing_labels:
            parts.append("缺少：" + "、".join(parsed.missing_labels))
        if parsed.invalid_labels:
            parts.append("分数格式不正确：" + "、".join(parsed.invalid_labels))
        await update.effective_message.reply_text("默认车评模式需要按模板填写完整项目。\n" + "\n".join(parts))
        return

    report = await CarReviewService.create_report(
        session,
        chat_id=target_chat_id,
        teacher_user_id=teacher_user_id,
        author_user_id=update.effective_user.id,
        review_text=parsed.review_text or "待补充",
        process_text=parsed.process_text,
        media_file_ids=_extract_car_review_media_file_ids(update.effective_message),
        scores=parsed.scores,
    )
    await clear_user_state(session, chat_id=state.chat_id, user_id=update.effective_user.id)

    teacher_user = await session.get(TgUser, teacher_user_id)
    target_chat = await session.get(TgChat, target_chat_id)
    report_id = report.report_id
    approver_user_id = int(setting.approver_user_id)
    await session.commit()

    await update.effective_message.reply_text(f"车评已提交，等待审核。报告ID：{report_id}")

    try:
        await PublishService.send(
            context,
            chat_id=approver_user_id,
            text=(
                "收到新的车评待审核\n"
                f"群：{target_chat.title if target_chat and target_chat.title else target_chat_id}\n"
                f"老师：{format_user_display_name(teacher_user, teacher_user_id)}\n"
                f"提交人：{format_user_display_name(update.effective_user, update.effective_user.id)}\n"
                f"报告ID：{report_id}"
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("查看报告", callback_data=f"crv:report:{target_chat_id}:detail:{report_id}:p")],
                [
                    InlineKeyboardButton("通过", callback_data=f"crv:report:{target_chat_id}:approve:{report_id}:p"),
                    InlineKeyboardButton("驳回", callback_data=f"crv:report:{target_chat_id}:reject:{report_id}:p"),
                ],
            ]),
        )
    except Exception as exc:
        log.warning(
            "car_review_private_submit_notify_approver_failed",
            chat_id=target_chat_id,
            report_id=report_id,
            approver_user_id=approver_user_id,
            error=str(exc),
        )
