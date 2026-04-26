from __future__ import annotations

import datetime as dt

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from sqlalchemy import select

from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.core import TgChat
from backend.features.activity.services.lottery_service import (
    format_lottery_subscribe_targets,
    get_lottery_subscribe_targets,
    format_lottery_stats_message,
    get_chat_lotteries,
    get_lottery,
    get_lottery_participant_count,
    get_lottery_stats,
    get_or_create_lottery_setting,
)
from backend.features.activity.ui.lottery import (
    lottery_draw_condition_keyboard,
    lottery_menu_keyboard,
    lottery_mode_keyboard,
    lottery_type_keyboard,
)


def _lottery_type_title(lottery_type: str) -> str:
    return {
        "common": "🎁 通用抽奖",
        "points": "💰 积分抽奖",
        "invite": "👥 邀请抽奖",
        "activity": "🔥 群活跃抽奖",
        "subscribe": "📣 强制订阅抽奖",
    }.get(lottery_type, "🎁 抽奖")


def _lottery_status_title(status: str) -> str:
    return {
        "all": "全部活动",
        "pending": "待开奖",
        "completed": "已开奖",
        "cancelled": "已取消",
    }.get(status, "活动")


def _format_local_time(value) -> str:
    if value is None:
        return "-"
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")


class LotteryMenuMixin:
    async def show_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            chat_stmt = select(TgChat).where(TgChat.id == target_chat_id)
            chat_result = await session.execute(chat_stmt)
            target_chat = chat_result.scalar_one_or_none()
            stats = await get_lottery_stats(session, target_chat_id)
            await session.commit()

        chat_title = target_chat.title if target_chat else f"群组{target_chat_id}"
        text = (
            f"🎁[{chat_title}]抽奖\n\n"
            f"{format_lottery_stats_message(stats)}\n\n"
            "当前支持 5 类抽奖：通用 / 积分 / 邀请 / 群活跃 / 强制订阅。\n"
            "不同类型会按各自资格条件校验参与资格。"
        )
        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=lottery_menu_keyboard(target_chat_id),
        )

    async def show_create_type_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
    ) -> None:
        text = "\n".join(
            [
                "🎁 发起抽奖活动",
                "",
                "请选择抽奖类型：",
                "• 🎁 通用抽奖：普通参与资格",
                "• 💰 积分抽奖：按积分门槛/费用参与",
                "• 👥 邀请抽奖：按邀请人数参与",
                "• 🔥 群活跃抽奖：按近 N 天发言数参与",
                "• 📣 强制订阅抽奖：单独配置本次抽奖关注目标，需先关注后参与",
            ]
        )
        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=lottery_type_keyboard(target_chat_id),
        )

    async def show_mode_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        lottery_type: str,
    ) -> None:
        text = "\n".join(
            [
                f"{_lottery_type_title(lottery_type)} | 选择玩法",
                "",
                "• 达标随机：满足门槛的成员可手动参与，再随机开奖",
                "• 排名入围随机：系统按排行生成入围名单，再从入围名单随机开奖",
            ]
        )
        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=lottery_mode_keyboard(target_chat_id, lottery_type),
        )

    async def show_draw_condition_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        lottery_type: str,
        selection_mode: str,
    ) -> None:
        mode_label = "🏆 排名入围随机" if selection_mode == "ranking_random" else "🎯 达标随机"
        text = "\n".join(
            [
                f"{_lottery_type_title(lottery_type)} | {mode_label}",
                "",
                "请选择开奖条件：",
                *([] if selection_mode == "ranking_random" else ["• 满人开奖：参与人数达到配置的最大人数后立即开奖"]),
                "• 定时开奖：到配置的开奖时间后截止并开奖",
            ]
        )
        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=lottery_draw_condition_keyboard(target_chat_id, lottery_type, selection_mode),
        )

    async def show_activity_list(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        status: str = "all",
        lottery_type: str = "all",
        page: int = 0,
        page_size: int = 6,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            lotteries = await get_chat_lotteries(
                session,
                target_chat_id,
                None if status == "all" else status,
                lottery_type=lottery_type,
            )
            await session.commit()

        start = max(page, 0) * page_size
        subset = lotteries[start : start + page_size]
        lines = [
            f"📋 抽奖活动列表 | {_lottery_status_title(status)} | "
            f"{_lottery_type_title(lottery_type) if lottery_type != 'all' else '🧭 全部类型'}",
            "",
        ]
        if not subset:
            lines.append("暂无活动。")
        else:
            for lottery in subset:
                rules = lottery.qualification_rules or {}
                mode = rules.get("selection_mode", "threshold_random")
                mode_label = "🏆 排名入围随机" if mode == "ranking_random" else "🎯 达标随机"
                trigger_label = "满人开奖" if rules.get("draw_trigger") == "full_participants" else _format_local_time(lottery.draw_time)[5:]
                lines.append(
                    f"• #{lottery.id} {_lottery_type_title(lottery.lottery_type)} | "
                    f"{mode_label} | {lottery.title} | {lottery.status} | "
                    f"{trigger_label}"
                )

        keyboard_rows = []
        for lottery in subset:
            keyboard_rows.append(
                [
                    InlineKeyboardButton(
                        f"🔎 #{lottery.id} {lottery.title[:16]}",
                        callback_data=f"lot:detail:{target_chat_id}:{lottery.id}",
                    )
                ]
            )
        keyboard_rows.append(
            [
                InlineKeyboardButton(
                    "✅ 全部" if status == "all" else "全部",
                    callback_data=f"lot:list:{target_chat_id}:all:{lottery_type}:0",
                ),
                InlineKeyboardButton(
                    "✅ 待开奖" if status == "pending" else "待开奖",
                    callback_data=f"lot:list:{target_chat_id}:pending:{lottery_type}:0",
                ),
                InlineKeyboardButton(
                    "✅ 已开奖" if status == "completed" else "已开奖",
                    callback_data=f"lot:list:{target_chat_id}:completed:{lottery_type}:0",
                ),
            ]
        )
        keyboard_rows.append(
            [
                InlineKeyboardButton(
                    "✅ 全部类型" if lottery_type == "all" else "全部类型",
                    callback_data=f"lot:list:{target_chat_id}:{status}:all:0",
                ),
                InlineKeyboardButton("🎁 通用", callback_data=f"lot:list:{target_chat_id}:{status}:common:0"),
                InlineKeyboardButton("💰 积分", callback_data=f"lot:list:{target_chat_id}:{status}:points:0"),
                InlineKeyboardButton("📣 关注", callback_data=f"lot:list:{target_chat_id}:{status}:subscribe:0"),
            ]
        )
        keyboard_rows.append(
            [
                InlineKeyboardButton("👥 邀请", callback_data=f"lot:list:{target_chat_id}:{status}:invite:0"),
                InlineKeyboardButton("🔥 活跃", callback_data=f"lot:list:{target_chat_id}:{status}:activity:0"),
            ]
        )
        nav_row = []
        if page > 0:
            nav_row.append(
                InlineKeyboardButton(
                    "⬅️ 上一页",
                    callback_data=f"lot:list:{target_chat_id}:{status}:{lottery_type}:{page - 1}",
                )
            )
        if start + page_size < len(lotteries):
            nav_row.append(
                InlineKeyboardButton(
                    "下一页 ➡️",
                    callback_data=f"lot:list:{target_chat_id}:{status}:{lottery_type}:{page + 1}",
                )
            )
        if nav_row:
            keyboard_rows.append(nav_row)
        keyboard_rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:lottery:{target_chat_id}")])
        await self.message_helper.safe_edit(
            update,
            text="\n".join(lines),
            reply_markup=InlineKeyboardMarkup(keyboard_rows),
        )

    async def show_activity_detail(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        lottery_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            lottery = await get_lottery(session, lottery_id)
            if lottery is None or lottery.chat_id != target_chat_id:
                await session.commit()
                await self.message_helper.safe_edit(
                    update,
                    "抽奖不存在或已被删除。",
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("🔙 返回", callback_data=f"lot:list:{target_chat_id}:all:all:0")]]
                    ),
                )
                return
            participant_count = await get_lottery_participant_count(session, lottery_id)
            await session.commit()

        rules = lottery.qualification_rules or {}
        selection_mode = rules.get("selection_mode", "threshold_random")
        draw_trigger = rules.get("draw_trigger", "time_deadline")
        trigger_label = "👥 满人开奖" if draw_trigger == "full_participants" else "⏰ 定时开奖"
        lines = [
            f"{_lottery_type_title(lottery.lottery_type)} | 活动详情",
            "",
            f"🆔 活动ID：{lottery.id}",
            f"📢 标题：{lottery.title}",
            f"📌 状态：{lottery.status}",
            f"🎛 玩法：{'🏆 排名入围随机' if selection_mode == 'ranking_random' else '🎯 达标随机'}",
            f"🎚 开奖条件：{trigger_label}",
            f"👥 参与人数：{participant_count}",
            f"🎁 奖品数：{sum(int(item.get('quantity', 1)) for item in (lottery.prizes or []))}",
        ]
        if draw_trigger != "full_participants":
            lines.append(f"🕒 截止开奖时间：{_format_local_time(lottery.draw_time)}")
        if lottery.min_points > 0:
            lines.append(f"💰 最低积分：{lottery.min_points}")
        if lottery.participation_cost > 0:
            lines.append(f"💸 参与费用：{lottery.participation_cost}")
        if rules.get("required_invites"):
            lines.append(f"👥 邀请门槛：{rules['required_invites']}（最近 {rules.get('window_days', 7)} 天）")
        if rules.get("required_activity_count"):
            lines.append(f"🔥 活跃门槛：{rules['required_activity_count']}（最近 {rules.get('window_days', 7)} 天）")
        if lottery.lottery_type == "subscribe" or rules.get("requires_lottery_subscribe") or rules.get("requires_force_subscribe"):
            lines.append(f"📣 订阅目标：{format_lottery_subscribe_targets(get_lottery_subscribe_targets(rules))}")
        if selection_mode == "ranking_random":
            lines.append(f"🏆 入围人数：前 {int(rules.get('finalist_limit') or 0)} 名")
        is_private_context = bool(update.effective_chat and update.effective_chat.type == "private")
        if is_private_context and rules.get("preset_winner_ids"):
            lines.append(f"🔒 内定中奖人：{len(rules.get('preset_winner_ids') or [])} 人")

        keyboard_rows = []
        if lottery.status == "pending":
            keyboard_rows.append([InlineKeyboardButton("🎯 立即开奖", callback_data=f"lot:draw:{target_chat_id}:{lottery.id}")])
        keyboard_rows.append([InlineKeyboardButton("🔙 返回列表", callback_data=f"lot:list:{target_chat_id}:all:all:0")])
        await self.message_helper.safe_edit(
            update,
            text="\n".join(lines),
            reply_markup=InlineKeyboardMarkup(keyboard_rows),
        )

    async def show_settings_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            setting = await get_or_create_lottery_setting(session, target_chat_id)
            await session.commit()

        text = "\n".join(
            [
                "⚙️ 抽奖设置",
                "",
                f"📌 发布置顶：{'✅ 开启' if setting.publish_pin_enabled else '❌ 关闭'}",
                f"📣 结果置顶：{'✅ 开启' if setting.result_pin_enabled else '❌ 关闭'}",
                f"🧹 删除参与消息：{'✅ 开启' if setting.delete_join_message_enabled else '❌ 关闭'}",
            ]
        )
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "📌 发布置顶",
                        callback_data=f"lot:setting:{target_chat_id}:publish_pin:{0 if setting.publish_pin_enabled else 1}",
                    ),
                    InlineKeyboardButton(
                        "📣 结果置顶",
                        callback_data=f"lot:setting:{target_chat_id}:result_pin:{0 if setting.result_pin_enabled else 1}",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "🧹 删除参与消息",
                        callback_data=f"lot:setting:{target_chat_id}:delete_join:{0 if setting.delete_join_message_enabled else 1}",
                    ),
                ],
                [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:lottery:{target_chat_id}")],
            ]
        )
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)
