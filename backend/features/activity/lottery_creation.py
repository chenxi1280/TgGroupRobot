from __future__ import annotations

import datetime as dt
import re
import structlog

from sqlalchemy import func, select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.core import TgUser
from backend.platform.db.schema.models.enums import ConversationStateType
from backend.shared.services.chat_service import ensure_chat
from backend.platform.state.state_service import clear_user_state, set_user_state
from backend.features.activity.services.lottery_service import (
    ParsedLotteryConfig,
    create_lottery,
    format_lottery_announcement_text,
    get_or_create_lottery_setting,
    parse_lottery_config_text,
)
from backend.features.activity.services.lottery_service_parsing import (
    collect_winner_reference_values,
    extract_winner_usernames,
    lottery_draw_trigger_label,
    parse_direct_winner_ids,
)

log = structlog.get_logger(__name__)

LOTTERY_CREATE_STEPS = {
    "title",
    "prize_name",
    "prize_quantity",
    "draw_param",
    "point_type",
    "participation_cost",
    "prize_action",
    "invite_requirement",
    "activity_requirement",
    "finalist_limit",
    "preset_confirm",
    "preset_winners",
}
PRESET_CLEAR_WORDS = {"无", "不设置", "跳过", "0", "可选", "留空"}


def _lottery_type_title(lottery_type: str) -> str:
    return {
        "common": "🎁 通用抽奖",
        "points": "💰 积分抽奖",
        "invite": "👥 邀请抽奖",
        "activity": "🔥 群活跃抽奖",
    }.get(lottery_type, "🎁 抽奖")


def _prize_slot_count(prizes: list[dict]) -> int:
    return sum(max(0, int(prize.get("quantity") or 0)) for prize in prizes)


def _format_local_time(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")


def _default_deadline_text() -> str:
    local_tz = dt.timezone(dt.timedelta(hours=8))
    return (dt.datetime.now(local_tz) + dt.timedelta(hours=24)).strftime("%Y-%m-%d %H:%M")


def _parse_positive_int(value: str, field_name: str) -> int:
    try:
        number = int(value.strip())
    except ValueError:
        raise ValueError(f"{field_name}必须是数字")
    if number <= 0:
        raise ValueError(f"{field_name}必须大于 0")
    return number


def _parse_non_negative_int(value: str, field_name: str) -> int:
    try:
        number = int(value.strip())
    except ValueError:
        raise ValueError(f"{field_name}必须是数字")
    if number < 0:
        raise ValueError(f"{field_name}不能小于 0")
    return number


def _parse_future_time(value: str) -> dt.datetime:
    match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{1,2})", value.strip())
    if not match:
        raise ValueError("开奖时间格式错误，请使用 YYYY-MM-DD HH:MM")
    year, month, day, hour, minute = map(int, match.groups())
    local_tz = dt.timezone(dt.timedelta(hours=8))
    draw_time = dt.datetime(year, month, day, hour, minute, tzinfo=local_tz).astimezone(dt.timezone.utc)
    if draw_time <= dt.datetime.now(dt.timezone.utc):
        raise ValueError("开奖时间必须是未来时间")
    return draw_time


def _add_unique_user_id(user_ids: list[int], user_id: int | None) -> None:
    if isinstance(user_id, int) and user_id > 0 and user_id not in user_ids:
        user_ids.append(user_id)


def _message_entity_text(message: object, entity: object) -> str:
    parse_entity = getattr(message, "parse_entity", None)
    if callable(parse_entity):
        try:
            return parse_entity(entity)
        except Exception:
            pass
    text = getattr(message, "text", None) or getattr(message, "caption", None) or ""
    offset = int(getattr(entity, "offset", 0) or 0)
    length = int(getattr(entity, "length", 0) or 0)
    return text[offset : offset + length]


async def _resolve_username_to_user_id(session, context: ContextTypes.DEFAULT_TYPE, username: str) -> int | None:
    normalized = username.strip().lstrip("@").lower()
    if not normalized:
        return None
    result = await session.execute(
        select(TgUser)
        .where(func.lower(TgUser.username) == normalized)
        .order_by(TgUser.updated_at.desc())
        .limit(1)
    )
    stored_user = result.scalars().first()
    if stored_user is not None:
        return int(stored_user.id)
    bot = getattr(context, "bot", None)
    if bot is None:
        return None
    try:
        target_chat = await bot.get_chat(f"@{normalized}")
    except Exception:
        return None
    target_id = getattr(target_chat, "id", None)
    if isinstance(target_id, int) and target_id > 0:
        return target_id
    return None


async def _parse_preset_winner_ids_from_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    value: str,
    *,
    include_message_entities: bool = True,
) -> list[int]:
    normalized = value.strip()
    if not normalized or normalized in PRESET_CLEAR_WORDS:
        return []

    winner_ids = parse_direct_winner_ids(normalized)
    usernames = extract_winner_usernames(normalized)
    if include_message_entities:
        message = getattr(update, "effective_message", None)
        for entity in getattr(message, "entities", None) or []:
            entity_type = getattr(
                getattr(entity, "type", None),
                "value",
                getattr(entity, "type", None),
            )
            if entity_type == "text_mention" and getattr(entity, "user", None) is not None:
                _add_unique_user_id(winner_ids, getattr(entity.user, "id", None))
                continue
            if entity_type == "text_link":
                entity_value = getattr(entity, "url", "") or ""
            elif entity_type in {"mention", "url"}:
                entity_value = _message_entity_text(message, entity)
            else:
                continue
            for user_id in parse_direct_winner_ids(entity_value):
                _add_unique_user_id(winner_ids, user_id)
            for username in extract_winner_usernames(entity_value):
                if username.lower() not in {item.lower() for item in usernames}:
                    usernames.append(username)

    unresolved_usernames: list[str] = []
    for username in usernames:
        user_id = await _resolve_username_to_user_id(session, context, username)
        if user_id is None:
            unresolved_usernames.append(username)
            continue
        _add_unique_user_id(winner_ids, user_id)

    if unresolved_usernames:
        raise ValueError(
            "无法识别内定中奖人："
            + "、".join(f"@{username}" for username in unresolved_usernames)
            + "。请确认用户已在群内出现过，或改发数字ID / tg://user?id= 链接"
        )
    if not winner_ids:
        raise ValueError("内定中奖人请发送数字ID、@用户名或用户链接，多个用户用逗号分隔")
    return winner_ids


async def _resolve_preset_winner_refs_from_config_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    text: str,
) -> list[int] | None:
    values = collect_winner_reference_values(text)
    if not values:
        return None
    merged_ids: list[int] = []
    for value in values:
        for user_id in await _parse_preset_winner_ids_from_message(
            update,
            context,
            session,
            value,
            include_message_entities=False,
        ):
            _add_unique_user_id(merged_ids, user_id)
    return merged_ids


def _state_data(state: object) -> dict:
    return dict(getattr(state, "state_data", None) or {})


def _save_state_data(state: object, data: dict) -> None:
    data["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    state.state_data = data


def _draw_time_from_draft(data: dict) -> dt.datetime:
    raw = data.get("draw_time")
    if raw:
        parsed = dt.datetime.fromisoformat(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    return dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=3650)


def _build_config_from_state(data: dict) -> ParsedLotteryConfig:
    lottery_type = data.get("lottery_type", "common")
    selection_mode = data.get("selection_mode", "threshold_random")
    draw_trigger = data.get("draw_trigger", "time_deadline")
    prizes = list(data.get("prizes") or [])
    if not prizes:
        raise ValueError("至少需要设置一个奖品")
    preset_winner_ids = [int(user_id) for user_id in data.get("preset_winner_ids") or []]
    if len(preset_winner_ids) > _prize_slot_count(prizes):
        raise ValueError("内定中奖人数不能超过中奖人数")
    max_participants = int(data.get("max_participants") or 0)
    if draw_trigger == "full_participants" and max_participants <= 0:
        raise ValueError("满人开奖必须设置满员人数")
    if draw_trigger == "time_deadline" and not data.get("draw_time"):
        raise ValueError("定时开奖必须设置开奖时间")
    required_invites = int(data.get("required_invites") or 0)
    required_activity_count = int(data.get("required_activity_count") or 0)
    finalist_limit = int(data.get("finalist_limit") or 0)
    if lottery_type == "invite" and selection_mode == "threshold_random" and required_invites <= 0:
        raise ValueError("邀请抽奖必须设置邀请人数")
    if lottery_type == "activity" and selection_mode == "threshold_random" and required_activity_count <= 0:
        raise ValueError("群活跃抽奖必须设置活跃消息数")
    if selection_mode == "ranking_random" and finalist_limit <= 0:
        raise ValueError("排名入围随机玩法必须设置入围人数")
    title = str(data.get("title") or "").strip()
    if not title:
        raise ValueError("抽奖名称不能为空")
    return ParsedLotteryConfig(
        lottery_type=lottery_type,
        title=title,
        description=data.get("description") or None,
        draw_time=_draw_time_from_draft(data),
        draw_trigger=draw_trigger,
        min_points=0,
        participation_cost=int(data.get("participation_cost") or 0),
        max_participants=max_participants,
        requirement_days=0,
        qualification_window_days=int(data.get("qualification_window_days") or 7),
        required_invites=required_invites,
        required_activity_count=required_activity_count,
        finalist_limit=finalist_limit,
        selection_mode=selection_mode,
        preset_winner_ids=preset_winner_ids,
        prizes=prizes,
        point_type_id=data.get("point_type_id"),
        point_type_name=data.get("point_type_name"),
    )


def _format_lottery_wizard_summary(config: ParsedLotteryConfig) -> str:
    lines = [
        "请确认本次抽奖配置：",
        "",
        f"{_lottery_type_title(config.lottery_type)}",
        f"抽奖名称：{config.title}",
        f"开奖方式：{lottery_draw_trigger_label(config.draw_trigger)}",
    ]
    if config.draw_trigger == "time_deadline":
        lines.append(f"开奖时间：{_format_local_time(config.draw_time)}")
    else:
        lines.append(f"满员人数：{config.max_participants}")
    lines.append("奖品：")
    for prize in config.prizes:
        lines.append(f"• {prize['name']} × {prize['quantity']}")
    lines.append(f"中奖人数：{_prize_slot_count(config.prizes)}")
    if config.lottery_type == "points":
        lines.append(f"扣除积分：{config.participation_cost} {config.point_type_name or '积分'}")
    if config.required_invites > 0:
        lines.append(f"邀请门槛：{config.required_invites} 人")
    if config.required_activity_count > 0:
        lines.append(f"活跃门槛：{config.required_activity_count} 条消息")
    if config.selection_mode == "ranking_random":
        lines.append(f"入围人数：{config.finalist_limit}")
    if config.preset_winner_ids:
        lines.append(f"内定中奖人：{', '.join(str(user_id) for user_id in config.preset_winner_ids)}")
    else:
        lines.append("内定中奖人：未设置")
    return "\n".join(lines)


def _preset_confirm_keyboard(target_chat_id: int, has_preset: bool = False) -> InlineKeyboardMarkup:
    publish_label = "✅ 确认发布抽奖" if has_preset else "✅ 不设置内定，发布抽奖"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ 添加/修改内定中奖人", callback_data=f"lot:wiz:{target_chat_id}:preset")],
            [InlineKeyboardButton(publish_label, callback_data=f"lot:wiz:{target_chat_id}:publish")],
            [InlineKeyboardButton("❌ 取消创建", callback_data=f"lottery:cancel:{target_chat_id}")],
        ]
    )


def _prize_action_keyboard(target_chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ 添加下一个奖品", callback_data=f"lot:wiz:{target_chat_id}:prize:add")],
            [InlineKeyboardButton("✅ 奖品设置完成", callback_data=f"lot:wiz:{target_chat_id}:prize:done")],
            [InlineKeyboardButton("❌ 取消创建", callback_data=f"lottery:cancel:{target_chat_id}")],
        ]
    )


def _point_type_keyboard(target_chat_id: int, custom_point_types: list[object]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [[InlineKeyboardButton("积分", callback_data=f"lot:wiz:{target_chat_id}:pt:0")]]
    for item in custom_point_types:
        if getattr(item, "enabled", True):
            rows.append([InlineKeyboardButton(getattr(item, "name", f"积分{item.id}"), callback_data=f"lot:wiz:{target_chat_id}:pt:{item.id}")])
    rows.append([InlineKeyboardButton("❌ 取消创建", callback_data=f"lottery:cancel:{target_chat_id}")])
    return InlineKeyboardMarkup(rows)


def _next_step_after_draw_param(data: dict) -> str:
    lottery_type = data.get("lottery_type")
    if lottery_type == "points":
        return "point_type"
    if lottery_type == "invite":
        return "invite_requirement"
    if lottery_type == "activity":
        return "activity_requirement"
    if data.get("selection_mode") == "ranking_random":
        return "finalist_limit"
    return "preset_confirm"


def _next_step_after_points(data: dict) -> str:
    if data.get("lottery_type") == "invite":
        return "invite_requirement"
    if data.get("lottery_type") == "activity":
        return "activity_requirement"
    if data.get("selection_mode") == "ranking_random":
        return "finalist_limit"
    return "preset_confirm"


def _qualification_rules_from_config(config: ParsedLotteryConfig) -> dict:
    rules = {
        "draw_trigger": config.draw_trigger,
        "preset_winner_ids": config.preset_winner_ids,
        "window_days": config.qualification_window_days,
        "required_invites": config.required_invites,
        "required_activity_count": config.required_activity_count,
        "finalist_limit": config.finalist_limit,
        "selection_mode": config.selection_mode,
    }
    if config.point_type_id:
        rules["point_type_id"] = config.point_type_id
        rules["point_type_name"] = config.point_type_name
    return rules


async def _create_and_publish_lottery(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    *,
    target_chat_id: int,
    creator_user_id: int,
    config: ParsedLotteryConfig,
):
    lottery = await create_lottery(
        session,
        chat_id=target_chat_id,
        created_by_user_id=creator_user_id,
        title=config.title,
        draw_time=config.draw_time,
        prizes=config.prizes,
        description=config.description,
        lottery_type=config.lottery_type,
        draw_mode="random",
        qualification_rules=_qualification_rules_from_config(config),
        min_points=config.min_points,
        max_participants=config.max_participants,
        participation_cost=config.participation_cost,
        join_end_time=config.draw_time if config.draw_trigger == "time_deadline" else None,
        requirement_days=config.requirement_days,
    )

    announcement_text = format_lottery_announcement_text(config)
    keyboard = None
    if config.selection_mode != "ranking_random":
        from backend.features.activity.ui.lottery import get_join_keyboard

        keyboard = get_join_keyboard(lottery.id)
    sent_message = await context.bot.send_message(
        chat_id=target_chat_id,
        text=announcement_text,
        reply_markup=keyboard,
    )
    lottery.message_id = getattr(sent_message, "message_id", None)
    setting = await get_or_create_lottery_setting(session, target_chat_id)
    if setting.publish_pin_enabled and lottery.message_id:
        try:
            await context.bot.pin_chat_message(chat_id=target_chat_id, message_id=lottery.message_id)
        except Exception:
            pass
    log.info("lottery_announcement_sent", lottery_id=lottery.id, target_chat_id=target_chat_id)
    return lottery


async def _reply_point_type_prompt(update: Update, session, state: object, data: dict) -> None:
    from backend.features.points.services.points_extended_service import PointsExtendedService

    data["step"] = "point_type"
    _save_state_data(state, data)
    custom_types = await PointsExtendedService.list_custom_point_types(session, int(data["target_chat_id"]))
    await update.effective_message.reply_text(
        "请选择本次积分抽奖扣除哪一种积分。",
        reply_markup=_point_type_keyboard(int(data["target_chat_id"]), custom_types),
    )


async def _reply_preset_confirm(update: Update, state: object, data: dict) -> None:
    data["step"] = "preset_confirm"
    _save_state_data(state, data)
    config = _build_config_from_state(data)
    await update.effective_message.reply_text(
        _format_lottery_wizard_summary(config),
        reply_markup=_preset_confirm_keyboard(int(data["target_chat_id"]), bool(config.preset_winner_ids)),
    )


async def _reply_next_prompt(update: Update, session, state: object, data: dict, next_step: str) -> None:
    data["step"] = next_step
    _save_state_data(state, data)
    if next_step == "point_type":
        await _reply_point_type_prompt(update, session, state, data)
    elif next_step == "prize_name":
        await update.effective_message.reply_text("请输入第一个奖品的名称，例如：1USDT")
    elif next_step == "prize_quantity":
        await update.effective_message.reply_text(f"请输入 {data.get('pending_prize_name')} 的中奖人数/份数，例如：1")
    elif next_step == "prize_action":
        prize_lines = [f"• {prize['name']} × {prize['quantity']}" for prize in data.get("prizes") or []]
        await update.effective_message.reply_text(
            "当前奖品：\n"
            + "\n".join(prize_lines)
            + "\n\n还需要继续添加奖品吗？",
            reply_markup=_prize_action_keyboard(int(data["target_chat_id"])),
        )
    elif next_step == "draw_param":
        if data.get("draw_trigger") == "full_participants":
            await update.effective_message.reply_text("请输入满员开奖人数，例如：100")
        else:
            await update.effective_message.reply_text(
                f"请输入截止开奖时间，直接复制：<code>{_default_deadline_text()}</code>",
                parse_mode="HTML",
            )
    elif next_step == "participation_cost":
        point_name = data.get("point_type_name") or "积分"
        await update.effective_message.reply_text(f"请输入每人参与需要扣除多少 {point_name}，0 表示不扣。")
    elif next_step == "invite_requirement":
        if data.get("selection_mode") == "ranking_random":
            await update.effective_message.reply_text("请输入邀请入围最低人数，0 表示不设最低门槛。")
        else:
            await update.effective_message.reply_text("请输入参与抽奖需要邀请多少人，例如：3")
    elif next_step == "activity_requirement":
        if data.get("selection_mode") == "ranking_random":
            await update.effective_message.reply_text("请输入活跃入围最低消息数，0 表示不设最低门槛。")
        else:
            await update.effective_message.reply_text("请输入参与抽奖需要达到多少条活跃消息，例如：200")
    elif next_step == "finalist_limit":
        await update.effective_message.reply_text("请输入开奖时从排行榜取前多少名入围，例如：10")
    elif next_step == "preset_confirm":
        await _reply_preset_confirm(update, state, data)


async def _handle_lottery_wizard_message(update: Update, context: ContextTypes.DEFAULT_TYPE, session, state: object, text: str) -> None:
    data = _state_data(state)
    step = data.get("step")
    try:
        if step == "title":
            title_line = text.strip()
            if "|" in title_line:
                title, description = title_line.split("|", 1)
                data["title"] = title.strip()
                data["description"] = description.strip()
            else:
                data["title"] = title_line
                data["description"] = None
            if not data["title"]:
                raise ValueError("抽奖名称不能为空")
            await _reply_next_prompt(update, session, state, data, "prize_name")
        elif step == "prize_name":
            prize_name = text.strip()
            if not prize_name:
                raise ValueError("奖品名称不能为空")
            data["pending_prize_name"] = prize_name[:128]
            await _reply_next_prompt(update, session, state, data, "prize_quantity")
        elif step == "prize_quantity":
            quantity = _parse_positive_int(text, "中奖人数/份数")
            prize_name = data.pop("pending_prize_name", "").strip()
            if not prize_name:
                raise ValueError("奖品名称丢失，请重新开始创建")
            prizes = list(data.get("prizes") or [])
            prizes.append({"name": prize_name, "quantity": quantity, "points_reward": 0})
            data["prizes"] = prizes
            await _reply_next_prompt(update, session, state, data, "prize_action")
        elif step == "prize_action":
            await update.effective_message.reply_text("请使用按钮选择继续添加奖品，或完成奖品设置。")
        elif step == "draw_param":
            if data.get("draw_trigger") == "full_participants":
                data["max_participants"] = _parse_positive_int(text, "满员人数")
            else:
                data["draw_time"] = _parse_future_time(text).isoformat()
                data["max_participants"] = 0
            await _reply_next_prompt(update, session, state, data, _next_step_after_draw_param(data))
        elif step == "point_type":
            await update.effective_message.reply_text("请使用按钮选择积分类型。")
        elif step == "participation_cost":
            data["participation_cost"] = _parse_non_negative_int(text, "扣除积分")
            await _reply_next_prompt(update, session, state, data, _next_step_after_points(data))
        elif step == "invite_requirement":
            if data.get("selection_mode") == "ranking_random":
                data["required_invites"] = _parse_non_negative_int(text, "邀请入围最低人数")
            else:
                data["required_invites"] = _parse_positive_int(text, "邀请人数")
            if data.get("selection_mode") == "ranking_random":
                await _reply_next_prompt(update, session, state, data, "finalist_limit")
            else:
                await _reply_next_prompt(update, session, state, data, "preset_confirm")
        elif step == "activity_requirement":
            if data.get("selection_mode") == "ranking_random":
                data["required_activity_count"] = _parse_non_negative_int(text, "活跃入围最低消息数")
            else:
                data["required_activity_count"] = _parse_positive_int(text, "活跃消息数")
            if data.get("selection_mode") == "ranking_random":
                await _reply_next_prompt(update, session, state, data, "finalist_limit")
            else:
                await _reply_next_prompt(update, session, state, data, "preset_confirm")
        elif step == "finalist_limit":
            data["finalist_limit"] = _parse_positive_int(text, "入围人数")
            await _reply_next_prompt(update, session, state, data, "preset_confirm")
        elif step == "preset_winners":
            preset_ids = await _parse_preset_winner_ids_from_message(update, context, session, text)
            if len(preset_ids) > _prize_slot_count(list(data.get("prizes") or [])):
                raise ValueError("内定中奖人数不能超过中奖人数")
            data["preset_winner_ids"] = preset_ids
            await _reply_next_prompt(update, session, state, data, "preset_confirm")
        else:
            await update.effective_message.reply_text("当前抽奖创建状态异常，请取消后重新创建。")
        await session.commit()
    except ValueError as exc:
        await update.effective_message.reply_text(f"❌ {exc}\n请重新输入，或使用 /cancel 取消。")
        await session.commit()


class LotteryCreationMixin:
    async def start_create_flow(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        lottery_type: str = "common",
        selection_mode: str = "threshold_random",
        draw_trigger: str = "time_deadline",
    ) -> None:
        q = update.callback_query
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
                chat_id=q.message.chat.id,
                user_id=user.id,
                state_type=ConversationStateType.lottery_create.value,
                state_data={
                    "step": "title",
                    "target_chat_id": target_chat_id,
                    "lottery_type": lottery_type,
                    "selection_mode": selection_mode,
                    "draw_trigger": draw_trigger,
                    "qualification_window_days": 7,
                    "prizes": [],
                    "preset_winner_ids": [],
                },
            )
            await session.commit()

        text = f"{_lottery_type_title(lottery_type)} | 创建抽奖  ( /cancel 取消)\n\n"
        if selection_mode == "ranking_random":
            text += "当前玩法：🏆 排名入围随机\n\n"
        elif lottery_type in {"invite", "activity"}:
            text += "当前玩法：🎯 达标随机\n\n"
        text += f"开奖条件：{'👥 满人开奖' if draw_trigger == 'full_participants' else '⏰ 定时开奖'}\n\n"
        text += "请回复这次抽奖的名称。\n"
        text += "如果需要描述，可以使用：抽奖名称|描述"

        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("❌ 取消配置", callback_data=f"lottery:cancel:{target_chat_id}")]]
        )
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)


async def parse_lottery_config_message(update: Update, context: ContextTypes.DEFAULT_TYPE, session, state: object, text: str) -> None:
    state_step = (getattr(state, "state_data", None) or {}).get("step")
    if state_step in LOTTERY_CREATE_STEPS:
        await _handle_lottery_wizard_message(update, context, session, state, text)
        return
    try:
        lottery_type = state.state_data.get("lottery_type", "common")
        selection_mode = state.state_data.get("selection_mode", "threshold_random")
        draw_trigger = state.state_data.get("draw_trigger", "time_deadline")
        config: ParsedLotteryConfig = parse_lottery_config_text(
            text,
            lottery_type=lottery_type,
            selection_mode=selection_mode,
            draw_trigger=draw_trigger,
            allow_unresolved_winner_refs=True,
        )
        resolved_preset_ids = await _resolve_preset_winner_refs_from_config_text(update, context, session, text)
        if resolved_preset_ids is not None:
            prize_slot_count = _prize_slot_count(config.prizes)
            if len(resolved_preset_ids) > prize_slot_count:
                raise ValueError("内定中奖人数不能超过奖品总数量")
            config.preset_winner_ids = resolved_preset_ids

        target_chat_id = state.state_data.get("target_chat_id") or update.effective_chat.id
        lottery = await _create_and_publish_lottery(
            update,
            context,
            session,
            target_chat_id=target_chat_id,
            creator_user_id=update.effective_user.id,
            config=config,
        )

        await clear_user_state(session, chat_id=update.effective_chat.id, user_id=update.effective_user.id)
        await session.commit()

        reply_text = f"✅ {_lottery_type_title(config.lottery_type)}创建成功！\n\n"
        reply_text += f"📢 标题: {config.title}\n"
        reply_text += f"🎚 开奖条件: {'👥 满人开奖' if config.draw_trigger == 'full_participants' else '⏰ 定时开奖'}\n"
        if config.draw_trigger == "time_deadline":
            reply_text += f"🕐 截止开奖时间: {_format_local_time(config.draw_time)}\n"
        reply_text += f"🎁 奖品数: {len(config.prizes)}\n"
        if config.min_points > 0:
            reply_text += f"💰 最低积分: {config.min_points}\n"
        if config.participation_cost > 0:
            reply_text += f"💸 参与费用: {config.participation_cost} {config.point_type_name or '积分'}\n"
        if config.required_invites > 0:
            reply_text += f"👥 邀请人数门槛: {config.required_invites}\n"
        if config.required_activity_count > 0:
            reply_text += f"🔥 活跃消息门槛: {config.required_activity_count}\n"
        if config.qualification_window_days > 0:
            reply_text += f"📊 统计天数: 最近 {config.qualification_window_days} 天\n"
        if config.max_participants > 0:
            reply_text += f"👥 最大人数: {config.max_participants}\n"
        if config.requirement_days > 0:
            reply_text += f"📅 入群天数: {config.requirement_days}\n"
        if config.preset_winner_ids:
            reply_text += f"🔒 内定中奖人: {len(config.preset_winner_ids)} 人\n"
        reply_text += "\n📢 已发送公告到群组"

        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("🔙 返回抽奖管理", callback_data=f"adm:menu:lottery:{target_chat_id}")],
                [InlineKeyboardButton("🏠 返回主菜单", callback_data=f"adm:menu:main:{target_chat_id}")],
            ]
        )
        await update.effective_message.reply_text(reply_text, reply_markup=keyboard)
    except ValueError as exc:
        await update.effective_message.reply_text(f"❌ 配置错误: {exc}\n\n请重新发送配置，或使用 /cancel 取消。")
        await session.commit()
    except Exception as exc:
        await update.effective_message.reply_text(f"❌ 解析失败: {exc}\n\n请检查格式后重新发送。")
        await session.rollback()


async def handle_lottery_wizard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()
    data_parts = (q.data or "").split(":")
    if len(data_parts) < 4:
        return
    try:
        target_chat_id = int(data_parts[2])
    except ValueError:
        await q.answer("群组参数无效", show_alert=True)
        return
    action = data_parts[3]
    user = update.effective_user
    chat = update.effective_chat
    state_chat_id = user.id if chat is None or chat.type == "private" else chat.id
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        from backend.platform.state.state_service import get_user_state
        from backend.features.points.services.points_extended_service import PointsExtendedService

        state = await get_user_state(session, state_chat_id, user.id)
        if state is None or state.state_type != ConversationStateType.lottery_create.value:
            await q.edit_message_text("创建状态已失效，请重新进入抽奖创建。")
            await session.commit()
            return
        data = _state_data(state)
        if int(data.get("target_chat_id") or 0) != target_chat_id:
            await q.answer("这不是当前创建中的群组", show_alert=True)
            await session.commit()
            return
        try:
            if action == "pt":
                if len(data_parts) < 5:
                    await q.answer("积分类型参数无效", show_alert=True)
                    await session.commit()
                    return
                type_id = int(data_parts[4])
                if type_id <= 0:
                    data["point_type_id"] = None
                    data["point_type_name"] = "积分"
                else:
                    item = await PointsExtendedService.get_custom_point_type(session, target_chat_id, type_id)
                    if item is None or not getattr(item, "enabled", True):
                        await q.answer("该积分类型不可用", show_alert=True)
                        await session.commit()
                        return
                    data["point_type_id"] = int(item.id)
                    data["point_type_name"] = item.name
                data["step"] = "participation_cost"
                _save_state_data(state, data)
                await session.commit()
                await q.edit_message_text(f"已选择：{data['point_type_name']}\n\n请输入每人参与需要扣除多少 {data['point_type_name']}，0 表示不扣。")
                return
            if action == "preset":
                data["step"] = "preset_winners"
                _save_state_data(state, data)
                await session.commit()
                await q.edit_message_text(
                    "请发送内定中奖人，支持数字ID、@用户名、用户资料链接，多个用户用逗号分隔。\n"
                    "例如：123456789,@alice,tg://user?id=987654321\n\n"
                    "发送“无”可清空内定名单。"
                )
                return
            if action == "prize":
                if len(data_parts) < 5:
                    await q.answer("奖品操作参数无效", show_alert=True)
                    await session.commit()
                    return
                prize_action = data_parts[4]
                if prize_action == "add":
                    data["step"] = "prize_name"
                    _save_state_data(state, data)
                    await session.commit()
                    await q.edit_message_text("请输入下一个奖品的名称，例如：2USDT")
                    return
                if prize_action == "done":
                    data["step"] = "draw_param"
                    _save_state_data(state, data)
                    await session.commit()
                    if data.get("draw_trigger") == "full_participants":
                        await q.edit_message_text("请输入满员开奖人数，例如：100")
                    else:
                        await q.edit_message_text(
                            f"请输入截止开奖时间，直接复制：<code>{_default_deadline_text()}</code>",
                            parse_mode="HTML",
                        )
                    return
                await q.answer("奖品操作参数无效", show_alert=True)
                await session.commit()
                return
            if action == "publish":
                config = _build_config_from_state(data)
                lottery = await _create_and_publish_lottery(
                    update,
                    context,
                    session,
                    target_chat_id=target_chat_id,
                    creator_user_id=user.id,
                    config=config,
                )
                await clear_user_state(session, chat_id=state_chat_id, user_id=user.id)
                await session.commit()
                reply_text = f"✅ {_lottery_type_title(config.lottery_type)}创建成功！\n\n"
                reply_text += _format_lottery_wizard_summary(config)
                reply_text += f"\n\n📢 已发送公告到群组\n抽奖ID：{lottery.id}"
                await q.edit_message_text(
                    reply_text,
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [InlineKeyboardButton("🔙 返回抽奖管理", callback_data=f"adm:menu:lottery:{target_chat_id}")],
                            [InlineKeyboardButton("🏠 返回主菜单", callback_data=f"adm:menu:main:{target_chat_id}")],
                        ]
                    ),
                )
                return
        except ValueError as exc:
            await q.answer(str(exc), show_alert=True)
            await session.commit()
            return
        except Exception as exc:
            log.exception("lottery_wizard_callback_error", error=str(exc))
            await session.rollback()
            await q.edit_message_text(f"❌ 创建失败: {exc}")
            return
        await session.commit()
