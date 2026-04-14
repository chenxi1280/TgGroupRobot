from __future__ import annotations

import html

from telegram import User

from backend.platform.db.schema.models.core import TgUser


def render_welcome_template(template: str, *, default_text: str, member: User | TgUser | None, group_name: str, user_id: int) -> str:
    if isinstance(member, User):
        member_value = member.mention_html()
        nickname = html.escape(member.full_name)
    else:
        full_name = " ".join(
            part for part in [getattr(member, "first_name", None), getattr(member, "last_name", None)] if part
        ).strip()
        nickname = html.escape(full_name or getattr(member, "username", "") or str(user_id))
        member_value = html.escape(full_name or getattr(member, "username", "") or str(user_id))

    return (
        (template or default_text)
        .replace("{member}", member_value)
        .replace("{group}", html.escape(group_name or "本群"))
        .replace("{userid}", str(user_id))
        .replace("{nickname}", nickname)
    )
