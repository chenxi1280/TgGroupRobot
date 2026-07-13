from __future__ import annotations

from dataclasses import dataclass

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from backend.platform.db.schema.models.enums import PointsTxnType
from backend.platform.db.runtime.session import Database
from backend.shared.services.formatters import format_user_display_name
from backend.shared.services.permission_service import PermissionPolicyService
_PARSE_ADMIN_ADJUSTMENT_THRESHOLD_2 = 2
_PARSE_ADMIN_ADJUSTMENT_THRESHOLD_3 = 3



_ADMIN_ADD_COMMANDS = {"加积分", "加分"}
_ADMIN_DEDUCT_COMMANDS = {"扣积分", "扣分"}
_ADMIN_ADJUST_COMMANDS = _ADMIN_ADD_COMMANDS | _ADMIN_DEDUCT_COMMANDS
_DEFAULT_POINTS_ALIAS = "积分"
_DEFAULT_POINTS_RANK_ALIAS = "积分排行"
_TODAY_POINTS_ALIAS = "今日积分"
_LEADERBOARD_LIMIT = 10
_MAX_REASON_LENGTH = 255

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class _CustomPointCommandDeps:
    service: object
    message: object
    chat_id: int
    user_id: int


@dataclass(frozen=True)
class _PointsActionDeps:
    ensure_chat: object
    ensure_user: object
    get_settings: object
    extended_service: object
    change_points: object
    sign_in: object
    get_balance: object
    get_user_rank: object
    get_leaderboard: object
    get_daily_leaderboard: object
    format_sign_success: object
    format_sign_already: object
    format_balance: object
    format_leaderboard: object
    format_daily_leaderboard: object
    add_message_points: object
    required_level_permission: object
    should_send_level_notice: object
    show_mall_catalog: object
    require_manage: object


@dataclass(frozen=True)
class _PointsActionOptions:
    text_override: str | None
    allow_admin_adjustment: bool
    allow_level_checks: bool
    allow_message_points: bool


@dataclass(frozen=True)
class _MessageScope:
    update: Update
    context: ContextTypes.DEFAULT_TYPE
    chat: object
    user: object
    message: object
    text: str


def _user_label(user) -> str:
    return format_user_display_name(user, user.id)


def _setting_text(settings, attr_name: str, default: str) -> str:
    value = str(getattr(settings, attr_name, "") or "").strip()
    return value or default


def _setting_keywords(settings, attr_name: str, default: str) -> set[str]:
    configured = _setting_text(settings, attr_name, default)
    return {default, configured}


def _message_text_for_points(message, text_override: str | None) -> str:
    if text_override is not None:
        return text_override.strip()
    return (message.text or message.caption or "").strip()


def _positive_amount(value: str) -> int:
    try:
        amount = int(value)
    except ValueError:
        return 0
    return amount if amount > 0 else 0


def _parse_admin_adjustment(text: str) -> tuple[int, str, str] | None:
    parts = text.strip().split(maxsplit=2)
    if not parts:
        return None
    command = parts[0]
    if command not in _ADMIN_ADJUST_COMMANDS:
        return None
    if len(parts) < _PARSE_ADMIN_ADJUSTMENT_THRESHOLD_2:
        return 0, "", command
    amount = _positive_amount(parts[1])
    if not amount:
        return 0, "", command
    if command in _ADMIN_DEDUCT_COMMANDS:
        amount = -amount
    default_reason = "管理员增加积分" if amount > 0 else "管理员扣除积分"
    reason = parts[2].strip() if len(parts) >= _PARSE_ADMIN_ADJUSTMENT_THRESHOLD_3 and parts[2].strip() else default_reason
    return amount, reason[:_MAX_REASON_LENGTH], command


async def _adjustment_target(session, message, *, usage: str):
    replied_message = getattr(message, "reply_to_message", None)
    target_user = getattr(replied_message, "from_user", None)
    if target_user is not None:
        return target_user
    await session.commit()
    await message.reply_text(f"请回复成员消息使用：{usage}")
    return None


async def _adjustment_allowed(context, session, *, chat_id: int, operator_id: int, message, require_manage_func) -> bool:
    allowed, error_text = await require_manage_func(context, chat_id, operator_id, capability="points")
    if allowed:
        return True
    await session.commit()
    await message.reply_text(error_text or "需要管理员权限")
    return False


async def _apply_admin_adjustment(session, *, target_user, chat_id: int, amount: int, reason: str, deps) -> tuple[bool, int]:
    await deps.ensure_user(
        session,
        user_id=target_user.id,
        username=target_user.username,
        first_name=target_user.first_name,
        last_name=target_user.last_name,
        language_code=target_user.language_code,
    )
    result = await deps.change_points(
        session,
        chat_id,
        target_user.id,
        amount,
        PointsTxnType.admin_adjust.value,
        reason=reason,
    )
    await session.commit()
    return result


async def _handle_admin_adjustment(
    session,
    *,
    scope: _MessageScope,
    deps: _PointsActionDeps,
) -> bool:
    parsed = _parse_admin_adjustment(scope.text)
    if parsed is None:
        return False
    amount, reason, command = parsed
    usage = f"{command} 数字 备注"
    if amount == 0:
        await session.commit()
        await scope.message.reply_text(f"格式错误，请使用：回复成员消息后发送“{usage}”。")
        return True
    target_user = await _adjustment_target(session, scope.message, usage=usage)
    if target_user is None:
        return True
    allowed = await _adjustment_allowed(
        scope.context,
        session,
        chat_id=scope.chat.id,
        operator_id=scope.user.id,
        message=scope.message,
        require_manage_func=deps.require_manage,
    )
    if not allowed:
        return True
    ok, balance = await _apply_admin_adjustment(
        session,
        target_user=target_user,
        chat_id=scope.chat.id,
        amount=amount,
        reason=reason,
        deps=deps,
    )
    if not ok:
        await scope.message.reply_text("目标用户积分不足，无法扣除。")
        return True
    action = "增加" if amount > 0 else "扣除"
    await scope.message.reply_text(
        f"✅ 已为 {_user_label(target_user)} {action} {abs(amount)} 积分，当前积分 {balance}。\n备注：{reason}"
    )
    return True


def _matched_custom_type(custom_types, text: str) -> tuple[object | None, object | None]:
    matched_balance_type = next((item for item in custom_types if text == item.name), None)
    matched_rank_type = next((item for item in custom_types if item.rank_command and text == item.rank_command), None)
    return matched_balance_type, matched_rank_type


async def _handle_custom_point_command(session, text: str, deps: _CustomPointCommandDeps) -> bool:
    if not text:
        return False
    custom_types = await deps.service.list_custom_point_types(session, deps.chat_id)
    matched_balance_type, matched_rank_type = _matched_custom_type(custom_types, text)
    matched_type = matched_balance_type or matched_rank_type
    if matched_type is None:
        return False
    if not matched_type.enabled:
        await session.commit()
        await deps.message.reply_text(f"{matched_type.name} 已关闭。")
        return True
    if matched_balance_type is not None:
        await _reply_custom_balance(session, matched_type, deps)
        return True
    await _reply_custom_leaderboard(session, matched_type, deps)
    return True


async def _reply_custom_balance(session, point_type, deps: _CustomPointCommandDeps) -> None:
    balance = await deps.service.get_custom_point_balance(
        session,
        chat_id=deps.chat_id,
        type_id=point_type.id,
        user_id=deps.user_id,
    )
    await session.commit()
    await deps.message.reply_text(f"💰 你的{point_type.name}：{balance}")


async def _reply_custom_leaderboard(session, point_type, deps: _CustomPointCommandDeps) -> None:
    rows = await deps.service.get_custom_point_leaderboard(
        session,
        chat_id=deps.chat_id,
        type_id=point_type.id,
        limit=_LEADERBOARD_LIMIT,
    )
    await session.commit()
    if not rows:
        await deps.message.reply_text(f"{point_type.name} 暂无排行数据。")
        return
    lines = [f"🌐 {point_type.name} 排行", ""]
    for index, (rank_user_id, balance) in enumerate(rows, start=1):
        lines.append(f"{index}. {rank_user_id}｜{balance}")
    await deps.message.reply_text("\n".join(lines))


async def _ensure_points_entities(session, scope: _MessageScope, deps: _PointsActionDeps):
    await deps.ensure_chat(session, chat_id=scope.chat.id, chat_type=scope.chat.type, title=scope.chat.title)
    await deps.ensure_user(
        session,
        user_id=scope.user.id,
        username=scope.user.username,
        first_name=scope.user.first_name,
        last_name=scope.user.last_name,
        language_code=scope.user.language_code,
    )
    return await deps.get_settings(session, scope.chat.id)


def _sign_message(result, sign_points: int, deps: _PointsActionDeps) -> str:
    if result.success:
        return deps.format_sign_success(
            points=sign_points,
            balance=result.balance,
            consecutive_days=result.consecutive_days,
            bonus_points=result.bonus_points,
        )
    return deps.format_sign_already(balance=result.balance, consecutive_days=result.consecutive_days)


async def _handle_sign_command(session, scope: _MessageScope, *, settings, deps: _PointsActionDeps) -> bool | None:
    if scope.text != "签到":
        return None
    if not bool(getattr(settings, "sign_enabled", False)):
        await session.commit()
        await scope.message.reply_text("本群未开启签到。")
        return True
    sign_points = int(getattr(settings, "sign_points", 0) or 0)
    result = await deps.sign_in(
        session,
        chat_id=scope.chat.id,
        user_id=scope.user.id,
        points=sign_points,
        consecutive_days=int(getattr(settings, "sign_consecutive_days", 0) or 0),
        consecutive_bonus=int(getattr(settings, "sign_consecutive_bonus", 0) or 0),
    )
    await session.commit()
    await scope.message.reply_text(_sign_message(result, sign_points, deps))
    return True


async def _handle_standard_queries(session, scope: _MessageScope, *, settings, deps: _PointsActionDeps) -> bool | None:
    rank_keywords = _setting_keywords(settings, "points_rank_alias", _DEFAULT_POINTS_RANK_ALIAS)
    points_keywords = _setting_keywords(settings, "points_alias", _DEFAULT_POINTS_ALIAS)
    if scope.text in rank_keywords:
        rows = await deps.get_leaderboard(session, scope.chat.id, limit=_LEADERBOARD_LIMIT)
        reply = deps.format_leaderboard(rows)
    elif scope.text == _TODAY_POINTS_ALIAS:
        rows = await deps.get_daily_leaderboard(session, scope.chat.id, limit=_LEADERBOARD_LIMIT)
        reply = deps.format_daily_leaderboard(rows)
    elif scope.text in points_keywords:
        balance = await deps.get_balance(session, scope.chat.id, scope.user.id)
        rank = await deps.get_user_rank(session, scope.chat.id, scope.user.id)
        reply = deps.format_balance(balance, rank)
    else:
        return None
    await session.commit()
    await scope.message.reply_text(reply)
    return True


async def _handle_mall_command(session, scope: _MessageScope, *, setting, deps: _PointsActionDeps) -> bool | None:
    if not scope.text or scope.text != setting.entry_command:
        return None
    if not setting.enabled:
        await session.commit()
        await scope.message.reply_text("积分商城未开启。")
        return True
    products = await deps.extended_service.list_on_sale_products(session, scope.chat.id)
    await session.commit()
    if not products:
        await scope.message.reply_text("积分商城暂时没有可兑换商品。")
        return True
    await deps.show_mall_catalog(scope.update, scope.context, scope.chat.id, products=products)
    return True


async def _handle_extended_commands(session, scope: _MessageScope, deps: _PointsActionDeps) -> tuple[bool | None, object]:
    mall_setting = await deps.extended_service.get_or_create_mall_setting(session, scope.chat.id)
    level_setting = await deps.extended_service.get_or_create_level_setting(session, scope.chat.id)
    mall_result = await _handle_mall_command(session, scope, setting=mall_setting, deps=deps)
    if mall_result is not None:
        return mall_result, level_setting
    custom_result = await _handle_custom_point_command(
        session,
        scope.text,
        _CustomPointCommandDeps(
            service=deps.extended_service,
            message=scope.message,
            chat_id=scope.chat.id,
            user_id=scope.user.id,
        ),
    )
    return (True if custom_result else None), level_setting


async def _delete_blocked_message(scope: _MessageScope) -> None:
    try:
        await scope.message.delete()
    except Exception as exc:
        log.warning("points_block_message_delete_failed", chat_id=scope.chat.id, user_id=scope.user.id, error=str(exc))


async def _send_level_notice(scope: _MessageScope, deps: _PointsActionDeps) -> None:
    if not deps.should_send_level_notice(scope.context, scope.chat.id, scope.user.id):
        return
    try:
        await scope.chat.send_message("当前积分等级不足，无法发送此类消息。")
    except Exception as exc:
        log.warning("points_level_block_notice_failed", chat_id=scope.chat.id, user_id=scope.user.id, error=str(exc))


async def _handle_level_restriction(session, scope: _MessageScope, *, setting, deps: _PointsActionDeps) -> bool:
    if not setting.enabled:
        return False
    if setting.exclude_teacher_enabled:
        teacher_exempt = await deps.extended_service.is_teacher_exempt(session, scope.chat.id, scope.user.id)
        if teacher_exempt:
            await session.commit()
            return True
    level = await deps.extended_service.resolve_user_level(session, scope.chat.id, scope.user.id)
    required_permission = deps.required_level_permission(scope.message)
    if required_permission is None:
        return False
    if level is None or bool(getattr(level, required_permission, False)):
        return False
    await session.commit()
    await _delete_blocked_message(scope)
    await _send_level_notice(scope, deps)
    return True


async def _award_message_points(session, scope: _MessageScope, *, settings, deps: _PointsActionDeps, enabled: bool) -> bool:
    if not scope.text or not settings.message_points_enabled or not enabled:
        await session.commit()
        return False
    await deps.add_message_points(
        session,
        chat_id=scope.chat.id,
        user_id=scope.user.id,
        points=settings.message_points,
        daily_limit=settings.message_points_daily_limit,
        min_length=settings.message_min_length,
        message_length=len(scope.text),
    )
    await session.commit()
    return True


async def _run_points_action(session, scope: _MessageScope, *, deps: _PointsActionDeps, options: _PointsActionOptions) -> bool:
    settings = await _ensure_points_entities(session, scope, deps)
    if options.allow_admin_adjustment and await _handle_admin_adjustment(session, scope=scope, deps=deps):
        return True
    sign_result = await _handle_sign_command(session, scope, settings=settings, deps=deps)
    if sign_result is not None:
        return sign_result
    query_result = await _handle_standard_queries(session, scope, settings=settings, deps=deps)
    if query_result is not None:
        return query_result
    extended_result, level_setting = await _handle_extended_commands(session, scope, deps)
    if extended_result is not None:
        return extended_result
    if not options.allow_level_checks:
        await session.commit()
        return False
    if await _handle_level_restriction(session, scope, setting=level_setting, deps=deps):
        return True
    return await _award_message_points(session, scope, settings=settings, deps=deps, enabled=options.allow_message_points)


async def handle_message_points_action(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, ensure_chat_func, ensure_user_func, get_chat_settings_func,
    points_extended_service, change_points_func, sign_in_func, get_balance_func, get_user_rank_func,
    get_leaderboard_func, get_daily_points_leaderboard_func, format_sign_in_success_message_func,
    format_sign_in_already_message_func, format_balance_message_func, format_leaderboard_message_func,
    format_daily_points_leaderboard_message_func, add_message_points_func, required_level_permission_func,
    should_send_level_block_notice_func, show_mall_catalog_func, require_manage_func=PermissionPolicyService.require_manage,
    text_override: str | None = None, allow_admin_adjustment: bool = True, allow_level_checks: bool = True,
    allow_message_points: bool = True,
) -> bool:
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return False
    if update.effective_chat.type not in {"group", "supergroup"}:
        return False
    deps = _PointsActionDeps(
        ensure_chat=ensure_chat_func, ensure_user=ensure_user_func, get_settings=get_chat_settings_func,
        extended_service=points_extended_service, change_points=change_points_func, sign_in=sign_in_func,
        get_balance=get_balance_func, get_user_rank=get_user_rank_func, get_leaderboard=get_leaderboard_func,
        get_daily_leaderboard=get_daily_points_leaderboard_func, format_sign_success=format_sign_in_success_message_func,
        format_sign_already=format_sign_in_already_message_func, format_balance=format_balance_message_func,
        format_leaderboard=format_leaderboard_message_func, format_daily_leaderboard=format_daily_points_leaderboard_message_func,
        add_message_points=add_message_points_func, required_level_permission=required_level_permission_func,
        should_send_level_notice=should_send_level_block_notice_func, show_mall_catalog=show_mall_catalog_func,
        require_manage=require_manage_func,
    )
    options = _PointsActionOptions(
        text_override=text_override,
        allow_admin_adjustment=allow_admin_adjustment,
        allow_level_checks=allow_level_checks,
        allow_message_points=allow_message_points,
    )
    scope = _MessageScope(
        update=update,
        context=context,
        chat=update.effective_chat,
        user=update.effective_user,
        message=update.effective_message,
        text=_message_text_for_points(update.effective_message, text_override),
    )
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        return await _run_points_action(session, scope, deps=deps, options=options)
