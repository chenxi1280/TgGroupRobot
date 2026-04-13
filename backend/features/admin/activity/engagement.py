from __future__ import annotations

from backend.features.admin.activity.engagement_chat_actions import EngagementAdminChatActionsMixin
from backend.features.admin.activity.engagement_egg_actions import EngagementAdminEggActionsMixin
from backend.features.admin.activity.engagement_views import EngagementAdminViewsMixin
from backend.features.admin.support import *


class EngagementAdminControllerMixin(
    EngagementAdminViewsMixin,
    EngagementAdminEggActionsMixin,
    EngagementAdminChatActionsMixin,
):
    async def _handle_engagement(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        action = callback_data.get(1)
        db: Database = context.application.bot_data["db"]
        if action == "home":
            await self._show_engagement_home(update, context, chat_id)
            return

        async with db.session_factory() as session:
            if action == "egg":
                await self._handle_engagement_egg(update, context, chat_id, callback_data, session)
                return

            if action == "chat":
                await self._handle_engagement_chat(update, context, chat_id, callback_data, session)
                return
