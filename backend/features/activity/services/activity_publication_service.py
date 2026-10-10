"""Commit a publication identity before transport; never replay an unknown send."""
from __future__ import annotations
import datetime as dt
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError

from backend.platform.db.schema.models.activity_publications import ActivityPublication
from backend.platform.db.schema.models.expansion import GuessEvent, AuctionItem
from backend.shared.services.publish_service import PublishService


async def prepare_publication(session, *, token, domain, chat_id, creator_user_id, create_entity, render):
    await session.execute(insert(ActivityPublication).values(
        token=token, domain=domain, chat_id=chat_id, creator_user_id=creator_user_id,
        status="pending", payload={}, updated_at=dt.datetime.now(dt.UTC),
    ).on_conflict_do_nothing(index_elements=[ActivityPublication.token]))
    record = (await session.execute(select(ActivityPublication).where(
        ActivityPublication.token == token,
    ).with_for_update().execution_options(populate_existing=True))).scalar_one()
    if (record.domain, record.chat_id, record.creator_user_id) != (domain, chat_id, creator_user_id):
        raise ValueError("Publication scope mismatch")
    if record.entity_id is None:
        entity = await create_entity()
        record.entity_id = entity.id
        record.payload = render(entity)
        record.payload = publication_payload(token, record.payload)
        entity.status = "publishing"
    await session.commit()
    return record


async def send_publication(session, context, record):
    record = (await session.execute(select(ActivityPublication).where(
        ActivityPublication.token == record.token,
    ).with_for_update().execution_options(populate_existing=True))).scalar_one()
    if record.status not in {"pending", "retryable_failed", "permanent_failed"}:
        await session.commit()
        return record
    model = GuessEvent if record.domain == "guess" else AuctionItem
    entity = await session.get(model, record.entity_id)
    deadline = entity.deadline_at if record.domain == "guess" else entity.end_at
    if deadline <= dt.datetime.now(dt.UTC):
        record.status, record.error = "permanent_failed", "截止时间已过，不能继续发布。"
        await session.commit()
        return record
    # Lock release after this commit is intentional: a competing request sees processing.
    record.status = "processing"
    record.updated_at = dt.datetime.now(dt.UTC)
    await session.commit()
    try:
        result = await _transport_publication(context, record)
    except RetryAfter:
        record.status, record.error = "retryable_failed", "发送受限，请稍后手动重试"
    except (BadRequest, Forbidden):
        record.status, record.error = "permanent_failed", "Telegram 明确拒绝，请检查权限或内容后重试"
    except TelegramError:
        record.status, record.error = "uncertain", "发布结果待核实，禁止重复发送"
    except Exception:
        record.status, record.error = "uncertain", "发布结果待核实，禁止重复发送"
    else:
        record.status, record.message_id, record.error = "succeeded", result.message_id, None
        await associate_publication_entity(session, record, result.message_id)
    record.updated_at = dt.datetime.now(dt.UTC)
    await session.commit()
    return record


def validate_publication_payload(payload):
    maximum = 1024 if payload.get("photo") else 4096
    if len(payload["text"].encode("utf-16-le")) // 2 > maximum:
        from backend.shared.services.base import ValidationError
        raise ValidationError(f"发布内容过长，请缩短到 {maximum} 字符以内。")
    return payload


def publication_payload(token, payload):
    """The draft token exists before an entity and is identical in preview/send."""
    return validate_publication_payload({**payload, "text": f"发布编号 {token}\n" + payload["text"]})


async def _transport_publication(context, record):
    payload = record.payload
    if payload.get("photo") and payload.get("media_type") == "document":
        result = await PublishService.send_document(context, chat_id=record.chat_id,
            document=payload["photo"], caption=payload["text"], parse_mode=None)
    elif payload.get("photo"):
        result = await PublishService.send_photo(context, chat_id=record.chat_id,
            photo=payload["photo"], caption=payload["text"], parse_mode=None)
    else:
        kwargs = {"reply_to_message_id": payload["reply_to_message_id"]} if payload.get("reply_to_message_id") else {}
        result = await PublishService.send(context, chat_id=record.chat_id,
            text=payload["text"], parse_mode=None, **kwargs)
    return result


async def associate_publication_entity(session, record, message_id):
    model = GuessEvent if record.domain == "guess" else AuctionItem
    entity = await session.get(model, record.entity_id)
    if record.domain == "guess":
        entity.announcement_message_id = message_id
        entity.status = "running" if entity.deadline_at > dt.datetime.now(dt.UTC) else "pending"
    else:
        entity.last_announce_message_id = message_id
        entity.status = "running" if entity.end_at > dt.datetime.now(dt.UTC) else "ended"
