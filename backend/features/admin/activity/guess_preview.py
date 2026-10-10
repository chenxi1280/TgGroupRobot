from backend.features.activity.services.activity_publication_service import publication_payload
from backend.features.activity.services.guess_service_runtime import build_draft_event
from backend.features.activity.services.guess_service import format_event_runtime
from backend.platform.telegram.errors import answer_callback_query_safely
from backend.shared.services.base import ValidationError


async def preview_guess(update, session, *, chat_id, draft):
    try:
        from backend.platform.db.schema.models.activity_publications import ActivityPublication
        record = await session.get(ActivityPublication, draft["publication_token"]) if draft.get("publication_token") else None
        if record is not None and record.entity_id is not None:
            payload = record.payload
        else:
            preview_event = build_draft_event(chat_id, update.effective_user.id, draft)
            payload = publication_payload(draft["publication_token"], {"text": format_event_runtime(preview_event), "photo": draft.get("cover_file_id"), "media_type": draft.get("cover_media_type")})
        await update.effective_message.reply_text("以下为私聊预览，活动尚未发布。")
        if payload["photo"] and payload.get("media_type") == "document":
            await update.effective_message.reply_document(document=payload["photo"], caption=payload["text"], parse_mode=None)
        elif payload["photo"]:
            await update.effective_message.reply_photo(photo=payload["photo"], caption=payload["text"], parse_mode=None)
        else:
            await update.effective_message.reply_text(payload["text"], parse_mode=None)
    except ValidationError as exc:
        await answer_callback_query_safely(update, str(exc), show_alert=True)


async def published_draft_locked(update, session, *, sub, draft):
    if draft.get("publication_token") and sub not in {"publish", "preview", "start"}:
        from backend.platform.db.schema.models.activity_publications import ActivityPublication
        record = await session.get(ActivityPublication, draft["publication_token"])
        if record is not None and record.entity_id is not None:
            await answer_callback_query_safely(update, "本次发布内容已锁定，请先处理原发布结果；修改内容须明确新建活动。", show_alert=True)
            return True
    return False
