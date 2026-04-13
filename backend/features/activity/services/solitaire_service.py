from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.activity.services.solitaire_formatting import *  # noqa: F401,F403
from backend.features.activity.services.solitaire_mutations import *  # noqa: F401,F403
from backend.features.activity.services.solitaire_mutations import close_solitaire as _close_solitaire
from backend.features.activity.services.solitaire_mutations import delete_solitaire as _delete_solitaire
from backend.features.activity.services.solitaire_queries import *  # noqa: F401,F403
from backend.shared.services.result import CloseResult


async def close_solitaire(
    session: AsyncSession,
    solitaire_id: int,
    *,
    chat_id: int | None = None,
) -> CloseResult:
    return await _close_solitaire(
        session,
        solitaire_id,
        chat_id=chat_id,
        lookup=get_solitaire,
        scoped_lookup=get_solitaire_in_chat,
    )


async def delete_solitaire(
    session: AsyncSession,
    solitaire_id: int,
    *,
    chat_id: int | None = None,
) -> bool:
    return await _delete_solitaire(
        session,
        solitaire_id,
        chat_id=chat_id,
        lookup=get_solitaire,
        scoped_lookup=get_solitaire_in_chat,
    )


__all__ = [name for name in globals() if not name.startswith("__")]
