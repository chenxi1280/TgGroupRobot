from __future__ import annotations


from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update

from backend.features.activity.services.lottery_service import (
    ParsedLotteryConfig,
)
from backend.features.activity.services.lottery_service_parsing import (
    encode_lottery_type,
    encode_selection_mode,
    lottery_draw_trigger_label,
)
from backend.features.activity.services.lottery_subscription import (
    format_lottery_subscribe_targets,
)
from backend.shared.ui.message_config_panel import format_completion_lines

from backend.features.activity.lottery_creation_parsing import (
    _default_deadline_text,
    _format_local_time,
    _lottery_type_title,
    _prize_slot_count,
)


def _is_private_admin_context(update: Update) -> bool:
    chat = getattr(update, "effective_chat", None)
    if chat is None:
        return True
    return chat.type == "private"


def _summary_header(config: ParsedLotteryConfig) -> list[str]:
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
    return lines


def _assignments_by_prize(config: ParsedLotteryConfig) -> dict[str, list[int]]:
    assignments: dict[str, list[int]] = {}
    for item in config.preset_winner_assignments or []:
        if item.get("user_id") and item.get("prize_name"):
            assignments.setdefault(str(item["prize_name"]), []).append(int(item["user_id"]))
    return assignments


def _prize_summary_line(
    prize: dict,
    *,
    assignments: dict[str, list[int]],
    has_assignments: bool,
) -> str:
    line = f"• {prize['name']} × {prize['quantity']}"
    assigned_ids = assignments.get(str(prize["name"])) or []
    if not assigned_ids:
        return f"{line}（随机）" if has_assignments else line
    assigned_text = "、".join(str(user_id) for user_id in assigned_ids)
    remaining = max(0, int(prize.get("quantity") or 0) - len(assigned_ids))
    random_suffix = f"；剩余 {remaining} 个随机" if remaining else ""
    return f"{line}（内定：{assigned_text}{random_suffix}）"


def _prize_summary_lines(
    config: ParsedLotteryConfig,
    *,
    include_sensitive: bool,
) -> list[str]:
    assignments = _assignments_by_prize(config) if include_sensitive else {}
    has_assignments = include_sensitive and bool(config.preset_winner_assignments)
    lines = ["奖品："]
    for prize in config.prizes:
        lines.append(_prize_summary_line(
            prize,
            assignments=assignments,
            has_assignments=has_assignments,
        ))
    lines.append(f"中奖人数：{_prize_slot_count(config.prizes)}")
    return lines


def _condition_summary_lines(config: ParsedLotteryConfig) -> list[str]:
    lines: list[str] = []
    if config.lottery_type == "points":
        lines.append(f"扣除积分：{config.participation_cost} {config.point_type_name or '积分'}")
    if config.required_invites > 0:
        lines.append(f"邀请门槛：{config.required_invites} 人")
    if config.required_activity_count > 0:
        lines.append(f"活跃门槛：{config.required_activity_count} 条消息")
    if config.lottery_type == "subscribe":
        lines.append(f"订阅目标：{format_lottery_subscribe_targets(config.subscribe_targets or [])}")
    if config.selection_mode == "ranking_random":
        lines.append(f"入围人数：{config.finalist_limit}")
    return lines


def _preset_summary_line(config: ParsedLotteryConfig) -> str:
    if not config.preset_winner_ids:
        return "内定中奖人：未设置"
    assignment_by_user = {
        int(item.get("user_id")): str(item.get("prize_name"))
        for item in (config.preset_winner_assignments or [])
        if item.get("user_id") and item.get("prize_name")
    }
    labels = [
        f"{user_id}（{assignment_by_user[user_id]}）" if user_id in assignment_by_user else str(user_id)
        for user_id in config.preset_winner_ids
    ]
    return f"内定中奖人：{', '.join(labels)}"


def _format_lottery_wizard_summary(config: ParsedLotteryConfig, *, include_sensitive: bool = True) -> str:
    lines = _summary_header(config)
    lines.extend(_prize_summary_lines(config, include_sensitive=include_sensitive))
    lines.extend(_condition_summary_lines(config))
    if include_sensitive:
        lines.append(_preset_summary_line(config))
    lines.extend(
        format_completion_lines(
            _lottery_config_required_items(config),
            next_step="确认无误后发布到群",
            test_step="发布后用测试账号点击参与，确认门槛和扣分正确",
        )
    )
    return "\n".join(lines)


def _lottery_condition_progress_from_values(
    *,
    lottery_type: str,
    selection_mode: str,
    participation_cost_configured: bool,
    required_invites: int,
    required_activity_count: int,
    finalist_limit: int,
    subscribe_targets_configured: bool,
) -> tuple[str, bool]:
    if lottery_type == "points":
        return "参与扣分", participation_cost_configured
    if lottery_type == "invite":
        if selection_mode == "ranking_random":
            return "排行入围条件", finalist_limit > 0
        return "邀请门槛", required_invites > 0
    if lottery_type == "activity":
        if selection_mode == "ranking_random":
            return "排行入围条件", finalist_limit > 0
        return "活跃门槛", required_activity_count > 0
    if lottery_type == "subscribe":
        return "关注目标", subscribe_targets_configured
    return "参与条件（无额外要求）", True


def _lottery_config_required_items(config: ParsedLotteryConfig) -> list[tuple[str, bool]]:
    condition_label, condition_done = _lottery_condition_progress_from_values(
        lottery_type=config.lottery_type,
        selection_mode=config.selection_mode,
        participation_cost_configured=True,
        required_invites=config.required_invites,
        required_activity_count=config.required_activity_count,
        finalist_limit=config.finalist_limit,
        subscribe_targets_configured=bool(config.subscribe_targets),
    )
    return [
        ("抽奖名称", bool(config.title)),
        ("奖品和中奖人数", bool(config.prizes) and _prize_slot_count(config.prizes) > 0),
        (
            "开奖条件",
            (config.draw_trigger == "time_deadline" and bool(config.draw_time))
            or (config.draw_trigger == "full_participants" and config.max_participants > 0),
        ),
        (condition_label, condition_done),
    ]


def _lottery_draft_required_items(data: dict) -> list[tuple[str, bool]]:
    draw_trigger = data.get("draw_trigger", "time_deadline")
    lottery_type = data.get("lottery_type", "common")
    selection_mode = data.get("selection_mode", "threshold_random")
    condition_label, condition_done = _lottery_condition_progress_from_values(
        lottery_type=lottery_type,
        selection_mode=selection_mode,
        participation_cost_configured="participation_cost" in data,
        required_invites=int(data.get("required_invites") or 0),
        required_activity_count=int(data.get("required_activity_count") or 0),
        finalist_limit=int(data.get("finalist_limit") or 0),
        subscribe_targets_configured=bool(data.get("subscribe_targets")),
    )
    return [
        ("抽奖名称", bool(str(data.get("title") or "").strip())),
        ("奖品和中奖人数", bool(data.get("prizes"))),
        ("开奖条件", bool(data.get("draw_time")) if draw_trigger == "time_deadline" else int(data.get("max_participants") or 0) > 0),
        (condition_label, condition_done),
    ]


def _append_lottery_wizard_guide(text: str, data: dict, *, next_step: str | None = None) -> str:
    lines = format_completion_lines(
        _lottery_draft_required_items(data),
        next_step=next_step,
        test_step="发布后到群里用测试账号点一次参与",
    )
    return text if not lines else text + "\n" + "\n".join(lines)


def _lottery_title_prompt(lottery_type: str, selection_mode: str, draw_trigger: str) -> str:
    text = f"{_lottery_type_title(lottery_type)} | 创建抽奖  ( /cancel 取消)\n\n"
    if selection_mode == "ranking_random":
        text += "当前玩法：🏆 排名入围随机\n\n"
    elif lottery_type in {"invite", "activity"}:
        text += "当前玩法：🎯 达标随机\n\n"
    text += f"开奖条件：{'👥 满人开奖' if draw_trigger == 'full_participants' else '⏰ 定时开奖'}\n\n"
    if lottery_type == "subscribe":
        text += "本类型会单独配置本次抽奖的关注目标，不读取“发言强制关注”的配置。\n\n"
    text += (
        "本步只输入抽奖名称。\n"
        "格式：抽奖名称\n"
        "完整示例：周末福利抽奖\n"
        "如果需要描述，格式：抽奖名称|描述\n"
        "带描述完整示例：周末福利抽奖|仅限本群成员参与"
    )
    return text


def _prize_name_prompt(example: str) -> str:
    return (
        "本步只输入奖品名称，不要带中奖人数。\n"
        "格式：奖品名称\n"
        f"完整示例：{example}\n"
        "下一步会单独填写这个奖品的中奖人数/份数。"
    )


def _subscribe_targets_prompt() -> str:
    return (
        "本步只输入本次抽奖要求关注的频道/群组。\n"
        "格式：@频道或群组用户名\n"
        "完整示例：@channel_a\n"
        "多个目标完整示例：@channel_a,@group_b\n"
        "私有群/频道完整示例：-1001234567890|https://t.me/+invite"
    )


def _prize_quantity_prompt(prize_name: object) -> str:
    return (
        f"本步只输入「{prize_name}」的中奖人数/份数，不要再输入奖品名称。\n"
        "格式：正整数\n"
        "完整示例：1"
    )


def _full_participants_prompt() -> str:
    return (
        "本步只输入满员开奖人数。\n"
        "格式：正整数\n"
        "完整示例：100"
    )


def _deadline_prompt() -> str:
    return (
        "本步只输入截止开奖时间。\n"
        "格式：YYYY-MM-DD HH:MM\n"
        f"完整示例：<code>{_default_deadline_text()}</code>\n"
        "可以直接复制上面的示例后修改。"
    )


def _participation_cost_prompt(point_name: str) -> str:
    return (
        f"本步只输入每人参与需要扣除的 {point_name} 数量，不要带单位。\n"
        "格式：非负整数\n"
        "完整示例：0"
    )


def _invite_requirement_prompt(selection_mode: str) -> str:
    if selection_mode == "ranking_random":
        return (
            "本步只输入邀请入围最低人数，0 表示不设最低门槛。\n"
            "格式：非负整数\n"
            "完整示例：0"
        )
    return (
        "本步只输入参与抽奖需要邀请的人数。\n"
        "格式：正整数\n"
        "完整示例：3"
    )


def _activity_requirement_prompt(selection_mode: str) -> str:
    if selection_mode == "ranking_random":
        return (
            "本步只输入活跃入围最低消息数，0 表示不设最低门槛。\n"
            "格式：非负整数\n"
            "完整示例：0"
        )
    return (
        "本步只输入参与抽奖需要达到的活跃消息数。\n"
        "格式：正整数\n"
        "完整示例：200"
    )


def _finalist_limit_prompt() -> str:
    return (
        "本步只输入开奖时从排行榜取前多少名入围。\n"
        "格式：正整数\n"
        "完整示例：10"
    )


def _preset_confirm_keyboard(target_chat_id: int, has_preset: bool = False, *, include_sensitive: bool = True) -> InlineKeyboardMarkup:
    rows = []
    if include_sensitive:
        rows.append([InlineKeyboardButton("➕ 添加/修改内定中奖人", callback_data=f"lot:wiz:{target_chat_id}:preset")])
        publish_label = "✅ 确认发布抽奖" if has_preset else "✅ 不设置内定，发布抽奖"
    else:
        publish_label = "✅ 确认发布抽奖"
    rows.append([InlineKeyboardButton(publish_label, callback_data=f"lot:wiz:{target_chat_id}:publish")])
    rows.append([InlineKeyboardButton("🔙 返回上级", callback_data=f"lot:wiz:{target_chat_id}:back")])
    rows.append([InlineKeyboardButton("❌ 取消配置", callback_data=f"lottery:cancel:{target_chat_id}")])
    return InlineKeyboardMarkup(rows)


def _wizard_nav_keyboard(target_chat_id: int, *, back_callback: str | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if back_callback:
        rows.append([InlineKeyboardButton("🔙 返回上级", callback_data=back_callback)])
    rows.append([InlineKeyboardButton("❌ 取消配置", callback_data=f"lottery:cancel:{target_chat_id}")])
    return InlineKeyboardMarkup(rows)


def _wizard_back_callback(target_chat_id: int) -> str:
    return f"lot:wiz:{target_chat_id}:back"


def _create_parent_callback(target_chat_id: int, lottery_type: str, selection_mode: str) -> str:
    return (
        f"lot:draw_cond:{target_chat_id}:"
        f"{encode_lottery_type(lottery_type)}:"
        f"{encode_selection_mode(selection_mode)}"
    )


def _prize_action_keyboard(target_chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ 添加下一个奖品", callback_data=f"lot:wiz:{target_chat_id}:prize:add")],
            [InlineKeyboardButton("✅ 奖品设置完成", callback_data=f"lot:wiz:{target_chat_id}:prize:done")],
            [InlineKeyboardButton("🔙 返回上级", callback_data=f"lot:wiz:{target_chat_id}:back")],
            [InlineKeyboardButton("❌ 取消配置", callback_data=f"lottery:cancel:{target_chat_id}")],
        ]
    )


def _point_type_keyboard(target_chat_id: int, custom_point_types: list[object]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [[InlineKeyboardButton("积分", callback_data=f"lot:wiz:{target_chat_id}:pt:0")]]
    for item in custom_point_types:
        if getattr(item, "enabled", True):
            rows.append([InlineKeyboardButton(getattr(item, "name", f"积分{item.id}"), callback_data=f"lot:wiz:{target_chat_id}:pt:{item.id}")])
    rows.append([InlineKeyboardButton("🔙 返回上级", callback_data=f"lot:wiz:{target_chat_id}:back")])
    rows.append([InlineKeyboardButton("❌ 取消配置", callback_data=f"lottery:cancel:{target_chat_id}")])
    return InlineKeyboardMarkup(rows)

