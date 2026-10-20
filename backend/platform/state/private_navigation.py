"""Suspend input only after an authorized, explicitly scoped navigation."""
from types import SimpleNamespace

from backend.platform.state.edit_drafts import suspend_inputs
from backend.shared.services.permission_service import PermissionPolicyService

_RULE_PARTS, _SECTION_PARTS = 3, 5

_NAVIGATION = {"menu", "home", "list", "detail", "back", "back_to_main", "back_to_menu", "rule", "view", "whitelist"}
_ADMIN_PREFIXES = {"adm", "ads", "auto_reply", "inv", "sm", "ali", "gfw", "grg", "tsearch", "crv", "auc", "btm", "gm", "guess", "act", "qpub", "btned", "gg", "pts", "gperm", "signcfg", "gnote", "anote", "eff", "ltag", "asan"}


async def suspend_for_private_navigation(application, update):
    query, user, chat = update.callback_query, update.effective_user, update.effective_chat
    if query is None or user is None or chat is None or chat.type != "private":
        return
    target = _navigation_target(query)
    if not await _navigation_allowed(application, update, target):
        return
    db = application.bot_data["db"]
    async with db.session_factory() as session:
        await suspend_inputs(session, user.id)
        await session.commit()
    # Points editing uses PTB user_data rather than a persisted ConversationState.
    # Clear its pending target after the same authorized navigation check.
    user_data = application.user_data.get(user.id)
    if user_data is not None:
        user_data.pop("ui_confirmations", None)
        user_data.pop("points_edit_field", None)
        user_data.pop("points_edit_chat_id", None)


async def _navigation_allowed(application, update, target):
    if application.bot_data.get("db") is None:
        return False
    if target is None:
        return (update.callback_query.data or "").split(":")[:2] in [["adm", "switch_group"], ["adm", "back_to_main"]]
    context = SimpleNamespace(application=application, bot=application.bot)
    return await PermissionPolicyService.can_manage(context, target, update.effective_user.id)


def _navigation_target(query):
    parts = (query.data or "").split(":")
    is_exit = any(check(parts) for check in (_scheduled_input_exit, _other_input_exit, _bottom_input_exit))
    if not parts or parts[0] not in _ADMIN_PREFIXES:
        return
    if not is_exit and not (_NAVIGATION & set(parts[1:])):
        return
    targets = _group_ids(parts)
    if len(targets) != 1:
        return
    return targets[0]


def _scheduled_input_exit(parts):
    if parts[:2] == ["sm", "open"]:
        return True
    return parts[:2] == ["sm", "edit"] and parts[4:] == ["time_range"]


def _other_input_exit(parts):
    # Explicit menu routes only: do not suspend activity drafts on preview/save.
    if parts[:2] == ["ads", "rules"] and len(parts) == _RULE_PARTS:
        return True
    if parts[:2] == ["adm", "night"] and len(parts) == _SECTION_PARTS and parts[3] == "section":
        return True
    if parts[:2] in (["adm", "lvl"], ["adm", "cpt"], ["adm", "wel"]) and parts[3:4] == ["page"]:
        return True
    return parts[:2] == ["sm", "edit"] and parts[4:] == ["repeat"]


def _group_ids(parts):
    return [int(part) for part in parts[1:] if part.startswith("-") and part[1:].isdigit()]


def _bottom_input_exit(parts):
    return parts[:2] == ["btm", "layout"] and parts[3:] == ["edit"]
