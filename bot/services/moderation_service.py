from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.core import ChatSettings, ModerationViolation


def _has_link(text: str) -> bool:
    t = text.lower()
    return "http://" in t or "https://" in t or "t.me/" in t or "www." in t


async def check_text_and_record(
    session: AsyncSession,
    settings: ChatSettings,
    chat_id: int,
    user_id: int,
    message_id: int | None,
    text: str,
) -> tuple[bool, str]:
    """
    返回 (should_delete, reason)
    """
    if not settings.moderation_enabled:
        return False, ""

    if settings.moderation_block_links and _has_link(text):
        session.add(
            ModerationViolation(
                chat_id=chat_id,
                user_id=user_id,
                message_id=message_id,
                rule="block_links",
                detail="link detected",
                action=settings.moderation_action,
            )
        )
        await session.flush()
        return True, "block_links"

    keywords = settings.moderation_keywords or []
    for kw in keywords:
        if kw and kw in text:
            session.add(
                ModerationViolation(
                    chat_id=chat_id,
                    user_id=user_id,
                    message_id=message_id,
                    rule="keyword",
                    detail=f"keyword={kw}",
                    action=settings.moderation_action,
                )
            )
            await session.flush()
            return True, "keyword"

    return False, ""



