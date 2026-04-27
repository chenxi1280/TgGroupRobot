from __future__ import annotations

from types import SimpleNamespace
from typing import Any


def build_sender_chat_actor(message: Any) -> Any | None:
    """Return a minimal actor for anonymous admin/channel-sent group messages."""
    sender_chat = getattr(message, "sender_chat", None)
    if sender_chat is None:
        return None
    title = sender_chat.title or "sender_chat"
    return SimpleNamespace(
        id=sender_chat.id or 0,
        username=sender_chat.username,
        first_name=title,
        last_name=None,
        language_code=None,
        is_bot=False,
        is_sender_chat=True,
    )


def resolve_message_actor(update: Any) -> Any | None:
    user = getattr(update, "effective_user", None)
    if user is not None:
        return user
    message = getattr(update, "effective_message", None)
    if message is None:
        return None
    return build_sender_chat_actor(message)


def is_sender_chat_actor(actor: Any) -> bool:
    return bool(getattr(actor, "is_sender_chat", False))
