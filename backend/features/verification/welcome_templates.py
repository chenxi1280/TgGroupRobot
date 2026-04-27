from __future__ import annotations

import html

from telegram import User

from backend.platform.db.schema.models.core import TgUser
from backend.shared.services.formatters import format_user_display_name


def render_welcome_template(template: str, *, default_text: str, member: User | TgUser | None, group_name: str, user_id: int) -> str:
    if isinstance(member, User):
        member_value = member.mention_html()
        nickname = html.escape(format_user_display_name(member, user_id))
    else:
        display_name = format_user_display_name(member, user_id)
        nickname = html.escape(display_name)
        member_value = html.escape(display_name)

    return (
        (template or default_text)
        .replace("{member}", member_value)
        .replace("{group}", html.escape(group_name or "本群"))
        .replace("{userid}", str(user_id))
        .replace("{nickname}", nickname)
    )
