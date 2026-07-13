from __future__ import annotations

from dataclasses import replace
import structlog

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.enums import ConversationStateType
from backend.shared.services.chat_service import ensure_chat
from backend.platform.state.state_service import clear_user_state, set_user_state
from backend.features.activity.services.lottery_service import (
    ParsedLotteryConfig,
    parse_lottery_config_text,
)
from backend.features.activity.services.lottery_subscription import (
    format_lottery_subscribe_targets,
    validate_lottery_subscribe_targets as validate_lottery_subscribe_targets,
)

from backend.features.activity.lottery_creation_config import (
    _append_lottery_wizard_guide,
    _build_config_from_state as _build_config_from_state,
    _create_parent_callback,
    _format_lottery_wizard_summary as _format_lottery_wizard_summary,
    _is_private_admin_context,
    _lottery_title_prompt,
    _lottery_draft_required_items as _lottery_draft_required_items,
    _point_type_keyboard as _point_type_keyboard,
    _prize_action_keyboard as _prize_action_keyboard,
    _qualification_rules_from_config as _qualification_rules_from_config,
)
from backend.features.activity.lottery_creation_parsing import (
    LOTTERY_CREATE_STEPS,
    _format_local_time,
    _lottery_type_title,
    _prize_slot_count,
    _parse_preset_winner_ids_from_message as _parse_preset_winner_ids_impl,
    _resolve_username_to_user_id as _resolve_username_to_user_id,
    _resolve_preset_winner_refs_from_config_text,
)
from backend.features.activity.lottery_creation_wizard import (
    _create_and_publish_lottery,
    _handle_lottery_wizard_message as _handle_lottery_wizard_message_impl,
    _reply_next_prompt as _reply_next_prompt,
    _reply_preset_confirm as _reply_preset_confirm,
)

from backend.features.activity.lottery_creation_callbacks import (
    handle_lottery_wizard_callback as handle_lottery_wizard_callback,
)

CALLBACK_BASE_PARTS = 4
CALLBACK_ACTION_PARTS = 5
log = structlog.get_logger(__name__)


async def _parse_preset_winner_ids_from_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    *,
    value: str,
    include_message_entities: bool = True,
) -> list[int]:
    return await _parse_preset_winner_ids_impl(
        update,
        context,
        session,
        value=value,
        include_message_entities=include_message_entities,
        resolve_username=_resolve_username_to_user_id,
    )


async def _handle_lottery_wizard_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    *,
    state: object,
    text: str,
) -> None:
    await _handle_lottery_wizard_message_impl(
        update,
        context,
        session,
        state=state,
        text=text,
        resolve_username=_resolve_username_to_user_id,
        validate_subscribe=validate_lottery_subscribe_targets,
    )


def _creation_state_data(
    target_chat_id: int,
    *,
    lottery_type: str,
    selection_mode: str,
    draw_trigger: str,
) -> dict:
    return {
        "step": "title",
        "target_chat_id": target_chat_id,
        "lottery_type": lottery_type,
        "selection_mode": selection_mode,
        "draw_trigger": draw_trigger,
        "qualification_window_days": 7,
        "prizes": [],
        "preset_winner_ids": [],
    }


async def _initialize_creation_state(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    target_chat_id: int,
    *,
    state_data: dict,
) -> None:
    user = update.effective_user
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await ensure_chat(session, chat_id=target_chat_id, chat_type="supergroup", title=None)
        from backend.shared.services.user_service import ensure_user

        await ensure_user(
            session,
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            language_code=user.language_code,
        )
        await set_user_state(
            session,
            chat_id=update.callback_query.message.chat.id,
            user_id=user.id,
            state_type=ConversationStateType.lottery_create.value,
            state_data=state_data,
        )
        await session.commit()


def _creation_keyboard(state_data: dict) -> InlineKeyboardMarkup:
    parent_callback = _create_parent_callback(
        int(state_data["target_chat_id"]),
        str(state_data["lottery_type"]),
        str(state_data["selection_mode"]),
    )
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 返回上级", callback_data=parent_callback)],
        [InlineKeyboardButton(
            "❌ 取消配置",
            callback_data=f"lottery:cancel:{state_data['target_chat_id']}",
        )],
    ])


class LotteryCreationMixin:
    async def start_create_flow(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        *, lottery_type: str = "common",
        selection_mode: str = "threshold_random",
        draw_trigger: str = "time_deadline",
    ) -> None:
        state_data = _creation_state_data(
            target_chat_id,
            lottery_type=lottery_type,
            selection_mode=selection_mode,
            draw_trigger=draw_trigger,
        )
        await _initialize_creation_state(
            update,
            context,
            target_chat_id,
            state_data=state_data,
        )
        text = _append_lottery_wizard_guide(
            _lottery_title_prompt(lottery_type, selection_mode, draw_trigger),
            state_data,
            next_step="填写抽奖名称",
        )
        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=_creation_keyboard(state_data),
        )


async def _parse_legacy_config(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    *,
    state: object,
    text: str,
) -> ParsedLotteryConfig:
    state_data = state.state_data or {}
    config = parse_lottery_config_text(
        text,
        lottery_type=state_data.get("lottery_type", "common"),
        selection_mode=state_data.get("selection_mode", "threshold_random"),
        draw_trigger=state_data.get("draw_trigger", "time_deadline"),
        allow_unresolved_winner_refs=True,
    )
    resolved = await _resolve_preset_winner_refs_from_config_text(
        update,
        context,
        session,
        text=text,
        prizes=config.prizes,
    )
    if resolved is None:
        return config
    winner_ids, assignments = resolved
    if len(winner_ids) > _prize_slot_count(config.prizes):
        raise ValueError("内定中奖人数不能超过奖品总数量")
    return replace(
        config,
        preset_winner_ids=winner_ids,
        preset_winner_assignments=assignments,
    )


def _legacy_success_lines(update: Update, config: ParsedLotteryConfig) -> list[str]:
    trigger = "👥 满人开奖" if config.draw_trigger == "full_participants" else "⏰ 定时开奖"
    lines = [
        f"✅ {_lottery_type_title(config.lottery_type)}创建成功！",
        "",
        f"📢 标题: {config.title}",
        f"🎚 开奖条件: {trigger}",
        f"🎁 奖品数: {len(config.prizes)}",
    ]
    optional = [
        (config.min_points > 0, f"💰 最低积分: {config.min_points}"),
        (config.participation_cost > 0, f"💸 参与费用: {config.participation_cost} {config.point_type_name or '积分'}"),
        (config.required_invites > 0, f"👥 邀请人数门槛: {config.required_invites}"),
        (config.required_activity_count > 0, f"🔥 活跃消息门槛: {config.required_activity_count}"),
        (config.qualification_window_days > 0, f"📊 统计天数: 最近 {config.qualification_window_days} 天"),
        (config.max_participants > 0, f"👥 最大人数: {config.max_participants}"),
        (config.requirement_days > 0, f"📅 入群天数: {config.requirement_days}"),
        (_is_private_admin_context(update) and bool(config.preset_winner_ids), f"🔒 内定中奖人: {len(config.preset_winner_ids)} 人"),
    ]
    lines.extend(text for enabled, text in optional if enabled)
    return lines


def _legacy_success_text(update: Update, config: ParsedLotteryConfig) -> str:
    lines = _legacy_success_lines(update, config)
    if config.draw_trigger == "time_deadline":
        lines.insert(4, f"🕐 截止开奖时间: {_format_local_time(config.draw_time)}")
    if config.lottery_type == "subscribe":
        lines.append(f"📣 订阅目标: {format_lottery_subscribe_targets(config.subscribe_targets or [])}")
    lines.extend(["", "📢 已发送公告到群组"])
    return "\n".join(lines)


def _legacy_success_keyboard(target_chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 返回抽奖管理", callback_data=f"adm:menu:lottery:{target_chat_id}")],
        [InlineKeyboardButton("🏠 返回主菜单", callback_data=f"adm:menu:main:{target_chat_id}")],
    ])


async def _publish_legacy_config(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    *,
    state: object,
    text: str,
) -> None:
    config = await _parse_legacy_config(update, context, session, state=state, text=text)
    target_chat_id = state.state_data.get("target_chat_id") or update.effective_chat.id
    await _create_and_publish_lottery(
        update,
        context,
        session,
        target_chat_id=target_chat_id,
        creator_user_id=update.effective_user.id,
        config=config,
    )
    await clear_user_state(session, chat_id=update.effective_chat.id, user_id=update.effective_user.id)
    await session.commit()
    await update.effective_message.reply_text(
        _legacy_success_text(update, config),
        reply_markup=_legacy_success_keyboard(target_chat_id),
    )


async def parse_lottery_config_message(update: Update, context: ContextTypes.DEFAULT_TYPE, session, *, state: object, text: str) -> None:
    state_step = (getattr(state, "state_data", None) or {}).get("step")
    if state_step in LOTTERY_CREATE_STEPS:
        await _handle_lottery_wizard_message(update, context, session, state=state, text=text)
        return
    try:
        await _publish_legacy_config(update, context, session, state=state, text=text)
    except ValueError as exc:
        await update.effective_message.reply_text(f"❌ 配置错误: {exc}\n\n请重新发送配置，或使用 /cancel 取消。")
        await session.commit()
    except Exception as exc:
        log.exception("lottery_parse_failed", error=str(exc))
        await update.effective_message.reply_text("❌ 解析失败，请检查格式后重新发送。")
        await session.rollback()
