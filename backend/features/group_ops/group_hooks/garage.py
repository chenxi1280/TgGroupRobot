from __future__ import annotations

import datetime as dt
import html

import structlog
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.core import TgUser
from backend.features.garage.services.garage_features_service import (
    CarReviewService,
    GarageAuthService,
    TeacherSearchService,
)
from backend.shared.services.action_executor import ActionExecutor
from backend.shared.services.publish_service import PublishService

from .common import _extract_car_review_media_file_ids, _reply_garage_feedback

log = structlog.get_logger(__name__)


def _garage_limit_hits_message(message, message_text: str, mode: str) -> bool:
    has_media = any(
        getattr(message, attr, None)
        for attr in ("photo", "video", "document", "animation")
    )
    if mode == "image":
        return bool(has_media)
    if mode == "image_text":
        return bool(has_media or message_text.strip())
    return False


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


async def _process_garage_features(
    context: ContextTypes.DEFAULT_TYPE,
    db: Database,
    chat,
    user,
    message,
    message_text: str,
    settings,
    is_admin: bool,
) -> bool:
    text = (message_text or "").strip()
    async with db.session_factory() as session:
        teacher_setting = await TeacherSearchService.get_setting(session, chat.id)
        car_review_setting = await CarReviewService.get_setting(session, chat.id)
        is_teacher = await GarageAuthService.is_certified_teacher(session, chat.id, user.id)
        is_whitelisted = await GarageAuthService.is_whitelisted(session, chat.id, user.id)

        if getattr(settings, "garage_limit_enabled", False) and not is_admin and is_teacher and not is_whitelisted:
            mode = getattr(settings, "garage_limit_mode", "none")
            if _garage_limit_hits_message(message, text, mode):
                tracker = context.application.bot_data.setdefault("garage_limit_tracker", {})
                key = (chat.id, user.id)
                now_ts = dt.datetime.now(dt.UTC).timestamp()
                interval = max(int(getattr(settings, "garage_limit_interval_sec", 3600) or 3600), 1)
                max_count = max(int(getattr(settings, "garage_limit_max_count", 1) or 1), 1)
                history = [ts for ts in tracker.get(key, []) if now_ts - ts < interval]
                history.append(now_ts)
                tracker[key] = history
                if len(history) > max_count:
                    await session.commit()
                    try:
                        await ActionExecutor.execute(
                            context,
                            action="delete",
                            chat_id=chat.id,
                            user_id=user.id,
                            reason="车库发言限制",
                            actor_user_id=None,
                            message_id=message.message_id,
                            sender_chat_id=getattr(getattr(message, "sender_chat", None), "id", None),
                        )
                    except Exception as exc:
                        log.warning("garage_limit_delete_failed", chat_id=chat.id, user_id=user.id, error=str(exc))
                    await PublishService.send_temporary(
                        context,
                        chat_id=chat.id,
                        text="当前老师发言过于频繁，消息已被限制。",
                        delete_after_seconds=15,
                    )
                    return True

        if getattr(message, "location", None) is not None and teacher_setting.nearby_search_enabled:
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
            await PublishService.send_temporary(
                context,
                chat_id=chat.id,
                text="已记录当前位置。",
                delete_after_seconds=10,
                reply_to_message_id=message.message_id,
            )
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
                return True
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
            return True

        if text == "附近":
            if not teacher_setting.nearby_search_enabled:
                await session.commit()
                await _reply_garage_feedback(
                    context,
                    chat_id=chat.id,
                    message_id=message.message_id,
                    text="附近搜索已关闭。",
                    delete_mode=delete_mode,
                )
                return True
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
                return True
            if location is None:
                await session.commit()
                await _reply_garage_feedback(
                    context,
                    chat_id=chat.id,
                    message_id=message.message_id,
                    text="还没有记录到你的位置，请先发送位置。",
                    delete_mode=delete_mode,
                )
                return True

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
                return True
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
            return True

        if text.startswith("老师搜索 "):
            if not teacher_setting.tag_search_enabled:
                await session.commit()
                await _reply_garage_feedback(
                    context,
                    chat_id=chat.id,
                    message_id=message.message_id,
                    text="标签搜索已关闭。",
                    delete_mode=delete_mode,
                )
                return True
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
                return True
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

        if car_review_setting.enabled and text == car_review_setting.rank_command.strip():
            rankings = await CarReviewService.list_rankings(session, chat.id, limit=10)
            await session.commit()
            if not rankings:
                await PublishService.reply(
                    context,
                    chat_id=chat.id,
                    text="暂无车评排行数据。",
                    reply_to_message_id=message.message_id,
                )
                return True
            lines = ["出击排行："]
            for idx, row in enumerate(rankings, start=1):
                lines.append(f"{idx}. {row['display_name']} · 均分 {row['avg_score']} · {row['count']} 条")
            await PublishService.reply(
                context,
                chat_id=chat.id,
                text="\n".join(lines),
                reply_to_message_id=message.message_id,
            )
            return True

        submit_command = car_review_setting.submit_command.strip()
        if car_review_setting.enabled and submit_command and text.startswith(submit_command):
            replied_user = getattr(getattr(message, "reply_to_message", None), "from_user", None)
            if replied_user is None:
                await session.commit()
                await PublishService.reply(
                    context,
                    chat_id=chat.id,
                    text="提交车评请回复目标老师的消息后再发送指令。",
                    reply_to_message_id=message.message_id,
                )
                return True
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
                return True

            await session.commit()
            await _reply_garage_feedback(
                context,
                chat_id=chat.id,
                message_id=message.message_id,
                text=f"车评已提交，等待管理员审核。报告ID：{report.report_id}",
            )
            return True

        await session.commit()
    return False
