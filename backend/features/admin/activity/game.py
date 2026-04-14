from __future__ import annotations

from backend.features.admin.support import *
from backend.shared.time_ui import build_copy_time_keyboard, build_hhmm_prompt_text, next_top_of_hour_hhmm

class GameAdminControllerMixin:
    async def _show_game_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            setting = await get_game_setting(session, chat_id)
            rake_owner = await get_game_rake_owner_label(session, setting.rake_owner_user_id)
            await session.commit()
        chat_title = await self._get_chat_title(db, chat_id)
        text = format_game_menu_text(
            chat_title,
            k3_enabled=setting.k3_enabled,
            blackjack_enabled=setting.blackjack_enabled,
            rake_ratio=setting.rake_ratio,
            rake_owner=rake_owner,
            auto_schedule_enabled=setting.auto_schedule_enabled,
            auto_start_time=setting.auto_start_time,
            auto_stop_time=setting.auto_stop_time,
            delete_mode=setting.delete_game_message_mode,
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🎲 快3", callback_data=f"gm:home:{chat_id}"),
                InlineKeyboardButton("✅ 启动" if setting.k3_enabled else "启动", callback_data=f"gm:toggle:{chat_id}:k3:1"),
                InlineKeyboardButton("✅ 关闭" if not setting.k3_enabled else "关闭", callback_data=f"gm:toggle:{chat_id}:k3:0"),
            ],
            [
                InlineKeyboardButton("🃏 黑杰克", callback_data=f"gm:home:{chat_id}"),
                InlineKeyboardButton("✅ 启动" if setting.blackjack_enabled else "启动", callback_data=f"gm:toggle:{chat_id}:blackjack:1"),
                InlineKeyboardButton("✅ 关闭" if not setting.blackjack_enabled else "关闭", callback_data=f"gm:toggle:{chat_id}:blackjack:0"),
            ],
            [
                InlineKeyboardButton("💧 抽水比例", callback_data=f"gm:rake:{chat_id}:ratio"),
                InlineKeyboardButton("👤 抽水归属", callback_data=f"gm:rake:{chat_id}:owner"),
            ],
            [
                InlineKeyboardButton("⏰ 定时启停", callback_data=f"gm:home:{chat_id}"),
                InlineKeyboardButton("✅ 启动" if setting.auto_schedule_enabled else "启动", callback_data=f"gm:auto:{chat_id}:toggle:1"),
                InlineKeyboardButton("✅ 关闭" if not setting.auto_schedule_enabled else "关闭", callback_data=f"gm:auto:{chat_id}:toggle:0"),
            ],
            [
                InlineKeyboardButton("🕒 启动时间", callback_data=f"gm:auto:{chat_id}:start_time"),
                InlineKeyboardButton("🌙 关停时间", callback_data=f"gm:auto:{chat_id}:stop_time"),
            ],
            [
                InlineKeyboardButton("🧹 删除游戏消息：", callback_data=f"gm:home:{chat_id}"),
                InlineKeyboardButton("🗑 删除" + (" ✅" if setting.delete_game_message_mode == "delete" else ""), callback_data=f"gm:delete_mode:{chat_id}:delete"),
                InlineKeyboardButton("💾 不删除" + (" ✅" if setting.delete_game_message_mode == "keep" else ""), callback_data=f"gm:delete_mode:{chat_id}:keep"),
            ],
            [
                InlineKeyboardButton("📋 最近牌局", callback_data=f"gm:rounds:{chat_id}"),
                InlineKeyboardButton("📘 指令帮助", callback_data=f"gm:help:{chat_id}"),
            ],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_game_rounds(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        async with context.application.bot_data["db"].session_factory() as session:
            rounds = await list_recent_game_rounds(session, chat_id, limit=8)
            await session.commit()
        lines = ["📋 最近牌局", ""]
        if not rounds:
            lines.append("暂无牌局记录。")
        else:
            for round_obj in rounds:
                lines.append(
                    f"• #{round_obj.id} | {round_obj.game_type} | {round_obj.status} | {round_obj.created_at.strftime('%m-%d %H:%M')}"
                )
        keyboard_rows = [
            [InlineKeyboardButton(f"🔎 查看 #{round_obj.id}", callback_data=f"gm:detail:{chat_id}:{round_obj.id}")]
            for round_obj in rounds
        ]
        keyboard_rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"gm:home:{chat_id}")])
        await self.message_helper.safe_edit(update, text="\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard_rows))

    async def _show_game_round_detail(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        round_id: int,
    ) -> None:
        async with context.application.bot_data["db"].session_factory() as session:
            rounds = await list_recent_game_rounds(session, chat_id, limit=50)
            round_obj = next((item for item in rounds if item.id == round_id), None)
            participants = await get_game_round_participants(session, round_id)
            await session.commit()
        if round_obj is None:
            await self.message_helper.safe_edit(
                update,
                "未找到该牌局。",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"gm:rounds:{chat_id}")]]),
            )
            return
        result_data = round_obj.result_data or {}
        lines = [
            "🎮 牌局详情",
            "",
            f"🆔 局号：{round_obj.id}",
            f"🎯 类型：{round_obj.game_type}",
            f"📌 状态：{round_obj.status}",
            f"🕒 创建时间：{round_obj.created_at.strftime('%Y-%m-%d %H:%M:%S')}",
        ]
        if round_obj.game_type == "k3":
            lines.append(f"🎲 开奖结果：{result_data.get('dice') or '未开奖'}")
            if result_data.get("label"):
                lines.append(f"🏷 结果标签：{result_data.get('label')}")
        if round_obj.game_type == "blackjack":
            lines.append(f"🃏 玩家牌：{result_data.get('player_cards') or []}")
            lines.append(f"🤖 庄家牌：{result_data.get('dealer_cards') or []}")
        lines.append("")
        lines.append("👥 参与情况：")
        if participants:
            for participant in participants:
                lines.append(
                    f"• 用户 {participant.user_id} | 下注 {participant.bet_points} | 状态 {participant.status} | 结算 {participant.payout_points}"
                )
        else:
            lines.append("• 暂无参与记录")
        await self.message_helper.safe_edit(
            update,
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"gm:rounds:{chat_id}")]]),
        )

    async def _show_game_help(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        text = "\n".join(
            [
                "📘 游戏指令帮助",
                "",
                "🎲 快3：",
                "• 发送 `快3` 查看玩法",
                "• 发送 `快3 大 100` / `快3 小 100` / `快3 单 100` / `快3 双 100` / `快3 豹子 100` 下注",
                "",
                "🃏 黑杰克：",
                "• 发送 `黑杰克` 查看玩法",
                "• 发送 `黑杰克 100` 开局",
                "• 发送 `要牌` / `停牌` 继续本局",
            ]
        )
        await self.message_helper.safe_edit(
            update,
            text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"gm:home:{chat_id}")]]),
        )

    async def _handle_game(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        action = callback_data.get(1)
        db: Database = context.application.bot_data["db"]
        if action == "home":
            await self._show_game_menu(update, context, chat_id)
            return
        if action == "rounds":
            await self._show_game_rounds(update, context, chat_id)
            return
        if action == "detail":
            await self._show_game_round_detail(update, context, chat_id, callback_data.get_int(3, default=0))
            return
        if action == "help":
            await self._show_game_help(update, context, chat_id)
            return
        async with db.session_factory() as session:
            if action == "toggle":
                field = callback_data.get(3)
                enabled = callback_data.get(4) == "1"
                await update_game_setting(session, chat_id, **{f"{field}_enabled": enabled})
                await session.commit()
                await self._show_game_menu(update, context, chat_id)
                return
            if action == "rake":
                sub = callback_data.get(3)
                if sub == "ratio":
                    await self._start_text_input_state(context, update.effective_user.id, update.effective_user.id, "game_wait_rake_ratio", {"target_chat_id": chat_id})
                    await session.commit()
                    await self.message_helper.safe_edit(update, "🎮 游戏 | 抽水比例\n\n请输入抽水比例\n例如：0.1 就是抽水10%", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"gm:home:{chat_id}")]]))
                    return
                if sub == "owner":
                    await self._start_text_input_state(context, update.effective_user.id, update.effective_user.id, "game_wait_rake_owner", {"target_chat_id": chat_id})
                    await session.commit()
                    await self.message_helper.safe_edit(update, "🎮 游戏 | 抽水归属\n\n请输入用户名或用户ID，发送“清空”可注销抽水归属。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"gm:home:{chat_id}")]]))
                    return
            if action == "auto":
                sub = callback_data.get(3)
                if sub == "toggle":
                    await update_game_setting(session, chat_id, auto_schedule_enabled=callback_data.get(4) == "1")
                elif sub == "start_time":
                    await self._start_text_input_state(context, update.effective_user.id, update.effective_user.id, "game_wait_auto_start_time", {"target_chat_id": chat_id})
                    await session.commit()
                    sample_text = next_top_of_hour_hhmm()
                    await self.message_helper.safe_edit(
                        update,
                        build_hhmm_prompt_text(
                            title="🎮 游戏 | 自动启动时间",
                            sample_time_text=sample_text,
                            input_hint="👉 请输入自动启动时间（格式 HH:MM）：",
                        ),
                        reply_markup=build_copy_time_keyboard(f"gm:home:{chat_id}", sample_text),
                        parse_mode="HTML",
                    )
                    return
                elif sub == "stop_time":
                    await self._start_text_input_state(context, update.effective_user.id, update.effective_user.id, "game_wait_auto_stop_time", {"target_chat_id": chat_id})
                    await session.commit()
                    sample_text = next_top_of_hour_hhmm(hours_offset=8)
                    await self.message_helper.safe_edit(
                        update,
                        build_hhmm_prompt_text(
                            title="🎮 游戏 | 自动关停时间",
                            sample_time_text=sample_text,
                            input_hint="👉 请输入自动关停时间（格式 HH:MM）：",
                        ),
                        reply_markup=build_copy_time_keyboard(f"gm:home:{chat_id}", sample_text),
                        parse_mode="HTML",
                    )
                    return
                await session.commit()
                await self._show_game_menu(update, context, chat_id)
                return
            if action == "delete_mode":
                await update_game_setting(session, chat_id, delete_game_message_mode=callback_data.get(3))
                await session.commit()
                await self._show_game_menu(update, context, chat_id)
                return
