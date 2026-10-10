"""Suspend input only after an authorized, explicitly scoped navigation."""
from types import SimpleNamespace

from backend.platform.state.edit_drafts import suspend_inputs
from backend.shared.services.permission_service import PermissionPolicyService

_NAVIGATION = {"menu", "home", "list", "detail", "back", "back_to_main", "back_to_menu", "rule", "view", "whitelist"}
_ADMIN_PREFIXES = {"adm", "ads", "auto_reply", "inv", "sm", "ali", "gfw", "grg", "tsearch", "crv", "auc", "btm", "gm", "guess", "act", "qpub", "btned", "gg", "pts"}


async def suspend_for_private_navigation(application, update):
    query, user, chat = update.callback_query, update.effective_user, update.effective_chat
    if query is None or user is None or chat is None or chat.type != "private":
        return
    target = _navigation_target(query)
    if target is None:
        return
    db = application.bot_data.get("db")
    if db is None:
        return
    context = SimpleNamespace(application=application, bot=application.bot)
    if not await PermissionPolicyService.can_manage(context, target, user.id):
        return
    async with db.session_factory() as session:
        await suspend_inputs(session, user.id)
        await session.commit()
    # Points editing uses PTB user_data rather than a persisted ConversationState.
    # Clear its pending target after the same authorized navigation check.
    user_data = application.user_data.get(user.id)
    if user_data is not None:
        user_data.pop("points_edit_field", None)
        user_data.pop("points_edit_chat_id", None)


def _navigation_target(query):
    parts = (query.data or "").split(":")
    if not parts or parts[0] not in _ADMIN_PREFIXES or not (_NAVIGATION & set(parts[1:])):
        return
    targets = [int(part) for part in parts[1:] if part.startswith("-") and part[1:].isdigit()]
    if len(targets) != 1:
        return
    return targets[0]
