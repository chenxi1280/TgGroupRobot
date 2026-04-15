from __future__ import annotations

from types import SimpleNamespace
from typing import Any


def build_sender_chat_actor(message: Any) -> Any | None:
    """Return a minimal actor for anonymous admin/channel-sent group messages."""
    sender_chat = getattr(message, "sender_chat", None)
    if sender_chat is None:
        return None
    return SimpleNamespace(
        id=getattr(sender_chat, "id", 0) or 0,
        username=getattr(sender_chat, "username", None),
        first_name=getattr(sender_chat, "title", None) or "sender_chat",
        last_name=None,
        language_code=None,
        is_bot=False,
        is_sender_chat=True,
        full_name=getattr(sender_chat, "title", None) or "sender_chat",
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
