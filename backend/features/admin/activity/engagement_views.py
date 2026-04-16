from __future__ import annotations

from backend.features.admin.support import *


_CHAT_REWARD_DAY_LABELS = ["第一日", "第二日", "第三日", "第四日", "第五日", "第六日", "第七日"]


def _format_chat_reward_plan_lines(plan: list[int], reward_type: str, after_7d_mode: str) -> list[str]:
    values = plan or [30, 50, 70, 90, 110, 130, 150]
    title = "递增激励:" if reward_type == "daily_increment" else "周期激励:"
    lines = [title]
    for label, points in zip(_CHAT_REWARD_DAY_LABELS, values[:7]):
        lines.append(f"└ {label} 达标奖励 {points} 积分")
    if values:
        if after_7d_mode == "reset":
            lines.append("└ 七日后 从首日开始计算")
        else:
            lines.append(f"└ 七日后 达标奖励 {values[min(6, len(values) - 1)]} 积分")
    lines.append("└ 中断后 从首日开始计算")
    return lines


class EngagementAdminViewsMixin:
    async def _show_engagement_home(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            counts = await get_egg_event_counts(session, chat_id)
            latest_running = await get_latest_running_egg_event(session, chat_id)
            reward = await get_engagement_chat_reward(session, chat_id)
            recent_stats = await get_recent_chat_reward_stats(session, chat_id, days=7)
            await session.commit()
        reward_type_label = "📈 递增奖励" if reward.reward_type == "daily_increment" else "🔁 周期奖励"
        recent_claims = sum(item["claim_count"] for item in recent_stats)
        text = "\n".join(
            [
                "✨ 促活工具",
                "",
                "通过有奖彩蛋和水群达标奖励，促进群友持续发言。",
                "",
                "🥚 有奖彩蛋",
                f"└ 活动：总数 {counts['all']} | 运行中 {counts['running']} | 已结束 {counts['finished']}",
                (
                    f"└ 当前：{latest_running.title} | 线索 {latest_running.published_clue_count}/{len(latest_running.clues or [])}"
                    if latest_running is not None
                    else "└ 当前：暂无运行中的彩蛋"
                ),
                "└ 添加彩蛋：复制模板后粘贴，系统按时间发布线索",
                "",
                "🍬 水群激励",
                f"└ 状态：{'✅ 开启' if reward.enabled else '❌ 关闭'} | {reward_type_label}",
                f"└ 达标：每日 {reward.daily_message_target} 条 | 口令：{reward.command_keyword}",
                f"└ 近7日领取次数：{recent_claims}",
            ]
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("➕ 添加彩蛋", callback_data=f"act:egg:{chat_id}:new"),
                InlineKeyboardButton("🥚 彩蛋管理", callback_data=f"act:egg:{chat_id}:list:all"),
            ],
            [
                InlineKeyboardButton("🍬 水群激励", callback_data=f"act:chat:{chat_id}:home"),
                InlineKeyboardButton("📊 水群数据", callback_data=f"act:chat:{chat_id}:stats"),
            ],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_engagement_egg_list(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        status: str = "all",
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            counts = await get_egg_event_counts(session, chat_id)
            events = await list_egg_events(session, chat_id, status=status, limit=12)
            await session.commit()
        lines = [
            "🥚 有奖彩蛋",
            "",
            "不同时段发布线索，第一个猜中答案的用户中奖。",
            "点击“添加彩蛋”可复制模板，粘贴后自动创建活动。",
            "",
            f"📋 全部 {counts['all']} | ⚪ 草稿/暂停 {counts['idle']} | 🟢 运行中 {counts['running']} | ✅ 已结束 {counts['finished']}",
            "",
        ]
        if not events:
            lines.append("• 当前筛选下暂无活动")
        else:
            for event in events:
                status_icon = {"idle": "⚪", "running": "🟢", "finished": "✅"}.get(event.status, "⚪")
                lines.append(
                    f"• #{event.id} {status_icon} {event.title} | 线索 {event.published_clue_count}/{len(event.clues or [])} | {'✅ 开启' if event.enabled else '❌ 关闭'}"
                )
        keyboard_rows = [
            [
                InlineKeyboardButton("➕ 添加彩蛋", callback_data=f"act:egg:{chat_id}:new"),
                InlineKeyboardButton("📚 彩蛋历史", callback_data=f"act:egg:{chat_id}:history"),
            ],
            [
                InlineKeyboardButton("✅ 全部" if status == "all" else "全部", callback_data=f"act:egg:{chat_id}:list:all"),
                InlineKeyboardButton("✅ 运行中" if status == "running" else "运行中", callback_data=f"act:egg:{chat_id}:list:running"),
                InlineKeyboardButton("✅ 已结束" if status == "finished" else "已结束", callback_data=f"act:egg:{chat_id}:list:finished"),
            ],
        ]
        for event in events[:8]:
            keyboard_rows.append(
                [InlineKeyboardButton(f"🔎 #{event.id} {event.title[:18]}", callback_data=f"act:egg:{chat_id}:detail:{event.id}")]
            )
        keyboard_rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"act:home:{chat_id}")])
        keyboard = InlineKeyboardMarkup(keyboard_rows)
        await self.message_helper.safe_edit(update, text="\n".join(lines), reply_markup=keyboard)

    async def _show_engagement_egg(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        event_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            event = await get_egg_event(session, chat_id, event_id)
            await session.commit()
        if event is None:
            await self.message_helper.safe_edit(
                update,
                "❌ 彩蛋活动不存在或已删除。",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"act:egg:{chat_id}:list:all")]]),
            )
            return
        clues = event.clues or []
        rewards = event.clue_rewards or []
        clue_times = event.clue_times or []
        status_icon = {"idle": "⚪", "running": "🟢", "finished": "✅"}.get(event.status, "⚪")
        reward_preview = " / ".join(f"{item}积分" for item in rewards) if rewards else "未配置"
        time_preview = " / ".join(clue_times) if clue_times else "未配置"
        answer_preview = event.answer or "未配置"
        winner_preview = str(event.winner_user_id) if event.winner_user_id else "暂无"
        text = "\n".join(
            [
                f"🥚 有奖彩蛋 | #{event.id} {event.title}",
                "",
                f"📌 状态：{'✅ 开启' if event.enabled else '❌ 关闭'}",
                f"🚦 运行态：{status_icon} {event.status}",
                f"🔐 当前答案：{answer_preview}",
                f"🧩 线索数量：{len(clues)}/4",
                f"📤 已发布线索：{event.published_clue_count}/{len(clues)}",
                f"🎁 奖励数组：{reward_preview}",
                f"⏰ 发布时间：{time_preview}",
                f"🏆 当前中奖者：{winner_preview}",
            ]
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(("✅ 状态" if event.enabled else "❌ 状态"), callback_data=f"act:egg:{chat_id}:toggle:{event.id}:{0 if event.enabled else 1}"),
                InlineKeyboardButton("🧩 编辑模板", callback_data=f"act:egg:{chat_id}:template:{event.id}"),
            ],
            [
                InlineKeyboardButton("👀 预览配置", callback_data=f"act:egg:{chat_id}:preview:{event.id}"),
                InlineKeyboardButton("📤 立即发布", callback_data=f"act:egg:{chat_id}:publish:{event.id}"),
            ],
            [
                InlineKeyboardButton("⏸ 暂停" if event.status == "running" else "▶️ 恢复", callback_data=f"act:egg:{chat_id}:status:{event.id}:{'idle' if event.status == 'running' else 'running'}"),
                InlineKeyboardButton("♻️ 重置活动", callback_data=f"act:egg:{chat_id}:reset:{event.id}"),
            ],
            [InlineKeyboardButton("🔙 返回列表", callback_data=f"act:egg:{chat_id}:list:all")],
        ])
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_engagement_chat_reward(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            reward = await get_engagement_chat_reward(session, chat_id)
            await session.commit()
        plan_lines = _format_chat_reward_plan_lines(reward.reward_points_plan or [], reward.reward_type, reward.after_7d_mode)
        text = "\n".join(
            [
                "🍬 水群激励",
                "",
                "发言量满足设置规则情况下，对用户进行奖励，达到持续促活",
                "",
                f"状态:{'✅ 开启' if reward.enabled else '❌ 关闭'}",
                "发言数量:",
                f"└ 每日发言数量达到 {reward.daily_message_target} 条即为达标",
                *plan_lines,
                "",
                "规则指令:",
                f"└ 群组中发送“{reward.command_keyword}”，查看最新水群活动",
            ]
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("状态:", callback_data=f"act:chat:{chat_id}:home"),
                InlineKeyboardButton("✅ 启动" if reward.enabled else "启动", callback_data=f"act:chat:{chat_id}:toggle:1"),
                InlineKeyboardButton("❌ 关闭" if not reward.enabled else "关闭", callback_data=f"act:chat:{chat_id}:toggle:0"),
            ],
            [
                InlineKeyboardButton("类型:", callback_data=f"act:chat:{chat_id}:home"),
                InlineKeyboardButton("✅ 递增" if reward.reward_type == "daily_increment" else "递增", callback_data=f"act:chat:{chat_id}:type:daily_increment"),
                InlineKeyboardButton("✅ 周期" if reward.reward_type == "weekly_cycle" else "周期", callback_data=f"act:chat:{chat_id}:type:weekly_cycle"),
            ],
            [
                InlineKeyboardButton("⚙️ 发言数量", callback_data=f"act:chat:{chat_id}:target"),
                InlineKeyboardButton("⚙️ 水群奖励", callback_data=f"act:chat:{chat_id}:plan"),
            ],
            [
                InlineKeyboardButton("七日后:", callback_data=f"act:chat:{chat_id}:home"),
                InlineKeyboardButton("✅ 重置" if reward.after_7d_mode == "reset" else "重置", callback_data=f"act:chat:{chat_id}:after7:reset"),
                InlineKeyboardButton("✅ 延续" if reward.after_7d_mode == "continue" else "延续", callback_data=f"act:chat:{chat_id}:after7:continue"),
            ],
            [
                InlineKeyboardButton("⌨️ 领奖口令", callback_data=f"act:chat:{chat_id}:command"),
                InlineKeyboardButton("✅ 套用推荐规则", callback_data=f"act:chat:{chat_id}:preset:default"),
            ],
            [
                InlineKeyboardButton("📈 近7日统计", callback_data=f"act:chat:{chat_id}:stats"),
                InlineKeyboardButton("🧾 领奖记录", callback_data=f"act:chat:{chat_id}:history"),
            ],
            [InlineKeyboardButton("🔙 返回", callback_data=f"act:home:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_engagement_chat_stats(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            stats = await get_recent_chat_reward_stats(session, chat_id, days=7)
            top_users = await get_chat_reward_top_users(session, chat_id, days=7, limit=5)
            await session.commit()
        stat_lines = [f"• {item['biz_date']}: 消息 {item['message_total']} / 领奖 {item['claim_count']} / 发放 {item['reward_total']} 积分" for item in stats] or ["• 暂无统计数据"]
        top_lines = [f"• {item['label']}: {item['message_total']} 条" for item in top_users] or ["• 暂无排行数据"]
        text = "\n".join(
            [
                "📈 水群激励 | 近7日统计",
                "",
                "📊 每日概览：",
                *stat_lines,
                "",
                "🏆 活跃排行：",
                *top_lines,
            ]
        )
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"act:chat:{chat_id}:home")]])
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_engagement_chat_history(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            claims = await get_recent_chat_reward_claims(session, chat_id, limit=10)
            await session.commit()
        lines = [
            f"• {item['biz_date']} | {item['label']} | 奖励 {item['rewarded_points']} | 连续 {item['streak_days']} 天 | 发言 {item['message_count']}"
            for item in claims
        ] or ["• 暂无领奖记录"]
        text = "\n".join(["🧾 水群激励 | 最近领奖记录", "", *lines])
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"act:chat:{chat_id}:home")]])
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_engagement_egg_history(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            history_rows = await list_egg_history(session, chat_id, limit=10)
            await session.commit()
        lines = ["📚 有奖彩蛋 | 历史记录", ""]
        if not history_rows:
            lines.append("• 暂无历史记录")
        else:
            for row in history_rows:
                lines.append(
                    f"• {row.created_at.strftime('%Y-%m-%d %H:%M')} | #{row.event_id or '-'} {row.title or '未命名活动'} | 状态 {row.status} | 中奖者 {row.winner_user_id or '暂无'} | 奖励 {row.reward_points}"
                )
        await self.message_helper.safe_edit(
            update,
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"act:egg:{chat_id}:list:all")]]),
        )
