from __future__ import annotations

from backend.features.admin.activity.runtime import clear_private_admin_state
from backend.features.admin.support import *
from backend.shared.time_ui import build_copy_options_keyboard, build_minutes_or_hhmm_prompt_text, next_top_of_hour_hhmm


async def _get_guess_draft_state(session, user_id: int, chat_id: int):
    state = await get_user_state(session, user_id, user_id)
    if state is not None and str(state.state_type).startswith("guess_wait_"):
        return state
    state = await get_user_state(session, chat_id, user_id)
    if state is not None and str(state.state_type).startswith("guess_wait_"):
        return state
    return None


async def _start_guess_input_state(session, *, user_id: int, chat_id: int, state_type: str, draft: dict) -> None:
    await clear_private_admin_state(session, target_chat_id=chat_id, user_id=user_id)
    await set_user_state(
        session,
        chat_id=user_id,
        user_id=user_id,
        state_type=state_type,
        state_data={"target_chat_id": chat_id, **draft},
    )


class GuessAdminControllerMixin:
    async def _show_guess_home(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            counts = await count_events_by_status(session, chat_id)
            await session.commit()
        text = "\n".join(
            [
                "⚽ 竞猜",
                "",
                f"🟡 待开奖：{counts['pending']}",
                f"🟢 进行中：{counts['running']}",
                f"✅ 已开奖：{counts['opened']}",
                f"❌ 已取消：{counts['cancelled']}",
            ]
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 发起竞猜", callback_data=f"guess:create:{chat_id}:start")],
            [
                InlineKeyboardButton(f"🟡 待开奖 ({counts['pending']})", callback_data=f"guess:list:{chat_id}:pending"),
                InlineKeyboardButton(f"🟢 进行中 ({counts['running']})", callback_data=f"guess:list:{chat_id}:running"),
            ],
            [
                InlineKeyboardButton(f"✅ 已开奖 ({counts['opened']})", callback_data=f"guess:list:{chat_id}:opened"),
                InlineKeyboardButton(f"❌ 已取消 ({counts['cancelled']})", callback_data=f"guess:list:{chat_id}:cancelled"),
            ],
            [
                InlineKeyboardButton("⚙️ 规则设置", callback_data=f"guess:settings:{chat_id}:home"),
                InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}"),
            ],
        ])
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_guess_create_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        draft: dict,
    ) -> None:
        text = format_event_preview(draft)
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🏷️ 活动名字", callback_data=f"guess:create:{chat_id}:title"),
                InlineKeyboardButton("🖼️ 活动封面", callback_data=f"guess:create:{chat_id}:cover"),
                InlineKeyboardButton("📝 活动说明", callback_data=f"guess:create:{chat_id}:description"),
            ],
            [
                InlineKeyboardButton("👑 本局庄家", callback_data=f"guess:create:{chat_id}:banker"),
                InlineKeyboardButton("🏦 公共奖池", callback_data=f"guess:create:{chat_id}:pool"),
                InlineKeyboardButton("🎯 竞猜选项", callback_data=f"guess:create:{chat_id}:options"),
            ],
            [
                InlineKeyboardButton("⌨️ 群内指令", callback_data=f"guess:create:{chat_id}:command"),
                InlineKeyboardButton("⏰ 截止时间", callback_data=f"guess:create:{chat_id}:deadline"),
                InlineKeyboardButton("下注限制", callback_data=f"guess:create:{chat_id}:repeat"),
            ],
            [
                InlineKeyboardButton("🏖️ 预览效果", callback_data=f"guess:create:{chat_id}:preview"),
                InlineKeyboardButton("✅ 发布活动", callback_data=f"guess:create:{chat_id}:publish"),
            ],
            [
                InlineKeyboardButton("❌ 清空配置", callback_data=f"guess:create:{chat_id}:clear"),
                InlineKeyboardButton("⬅️ 返回", callback_data=f"guess:home:{chat_id}"),
            ],
        ])
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_guess_settings(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            setting = await get_guess_setting(session, chat_id)
            owner_label = await get_game_rake_owner_label(session, setting.rake_owner_user_id)
            await session.commit()
        text = "\n".join(
            [
                "⚽ 竞猜 | 规则设置",
                "",
                f"💧 抽水比例：{setting.rake_ratio or '未设置'}",
                f"👤 抽水归属：{owner_label}",
                f"🧹 删除消息：{'🗑 删除' if setting.delete_message_mode == 'delete' else '💾 不删除'}",
            ]
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("💧 抽水比例", callback_data=f"guess:settings:{chat_id}:rake_ratio"),
                InlineKeyboardButton("👤 抽水归属", callback_data=f"guess:settings:{chat_id}:rake_owner"),
            ],
            [
                InlineKeyboardButton("🗑 删除消息" + (" ✅" if setting.delete_message_mode == "delete" else ""), callback_data=f"guess:settings:{chat_id}:delete_mode:delete"),
                InlineKeyboardButton("💾 不删除" + (" ✅" if setting.delete_message_mode == "keep" else ""), callback_data=f"guess:settings:{chat_id}:delete_mode:keep"),
            ],
            [InlineKeyboardButton("🔙 返回", callback_data=f"guess:home:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_guess_event_list(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        status: str,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            events = await list_guess_events(session, chat_id, status)
            await session.commit()
        lines = [f"⚽ 竞猜 | {status}", ""]
        if events:
            for event in events:
                lines.append(f"#{event.id} {event.title}｜{event.command_keyword}｜{event.deadline_at.astimezone().strftime('%m-%d %H:%M')}")
        else:
            lines.append("暂无数据")
        keyboard_rows = [[InlineKeyboardButton(f"📄 {event.title}", callback_data=f"guess:detail:{chat_id}:{event.id}")] for event in events]
        keyboard_rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"guess:home:{chat_id}")])
        await self.message_helper.safe_edit(update, "\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard_rows))

    async def _show_guess_event_detail(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        event_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            event = await get_guess_event(session, chat_id, event_id)
            await session.commit()
        if event is None:
            await answer_callback_query_safely(update, "❌ 活动不存在", show_alert=True)
            await self._show_guess_home(update, context, chat_id)
            return
        keyboard_rows = []
        if event.status in {"pending", "running"}:
            open_buttons = [
                InlineKeyboardButton(f"🏁 开 {item['key']}", callback_data=f"guess:open:{chat_id}:{event.id}:{item['key']}")
                for item in (event.options_json or [])
            ]
            keyboard_rows.extend([open_buttons[i:i+2] for i in range(0, len(open_buttons), 2)])
            keyboard_rows.append([InlineKeyboardButton("❌ 取消活动", callback_data=f"guess:cancel:{chat_id}:{event.id}")])
        keyboard_rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"guess:list:{chat_id}:{event.status}")])
        await self.message_helper.safe_edit(update, format_event_runtime(event), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard_rows))

    async def _handle_guess(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        action = callback_data.get(1)
        db: Database = context.application.bot_data["db"]
        if action == "home":
            await self._show_guess_home(update, context, chat_id)
            return
        async with db.session_factory() as session:
            if action == "create":
                sub = callback_data.get(3)
                state = await _get_guess_draft_state(session, update.effective_user.id, chat_id)
                draft = dict(state.state_data or {}) if state else {}
                if sub == "start":
                    await _start_guess_input_state(session, user_id=update.effective_user.id, chat_id=chat_id, state_type="guess_wait_title", draft={})
                    await session.commit()
                    await self.message_helper.safe_edit(update, "⚽ 竞猜 | 活动名字\n\n👉 请输入活动名字：", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"guess:home:{chat_id}")]]))
                    return
                if sub in {"title", "cover", "description", "banker", "pool", "options", "command", "deadline"}:
                    state_map = {
                        "title": "guess_wait_title",
                        "cover": "guess_wait_cover",
                        "description": "guess_wait_description",
                        "banker": "guess_wait_banker",
                        "pool": "guess_wait_pool",
                        "options": "guess_wait_options",
                        "command": "guess_wait_command",
                        "deadline": "guess_wait_deadline",
                    }
                    prompt_map = {
                        "title": "⚽ 竞猜 | 活动名字\n\n👉 请输入活动名字：",
                        "cover": "⚽ 竞猜 | 活动封面\n\n请发送图片，或发送“清空”移除封面。",
                        "description": "⚽ 竞猜 | 活动说明\n\n👉 请输入活动说明：",
                        "banker": "⚽ 竞猜 | 本局庄家\n\n请输入用户名或用户ID，发送“清空”切回无庄模式。",
                        "pool": "⚽ 竞猜 | 公共奖池\n\n👉 请输入公共奖池积分：",
                        "options": "⚽ 竞猜 | 竞猜选项\n\n每行一个选项，支持 `编号:文案`。",
                        "command": "⚽ 竞猜 | 群内指令\n\n👉 请输入群内指令，例如：竞猜",
                    }
                    await _start_guess_input_state(session, user_id=update.effective_user.id, chat_id=chat_id, state_type=state_map[sub], draft=draft)
                    await session.commit()
                    if sub == "deadline":
                        hhmm_sample = next_top_of_hour_hhmm(hours_offset=1)
                        await self.message_helper.safe_edit(
                            update,
                            build_minutes_or_hhmm_prompt_text(
                                title="⚽ 竞猜 | 截止时间",
                                minutes_sample_text="30",
                                hhmm_sample_text=hhmm_sample,
                                input_hint="👉 请输入分钟数或 HH:MM：",
                            ),
                            parse_mode="HTML",
                            reply_markup=build_copy_options_keyboard(
                                f"guess:create:{chat_id}:preview",
                                [("📋 复制 30分钟", "30"), (f"📋 复制 {hhmm_sample}", hhmm_sample)],
                            ),
                        )
                        return
                    await self.message_helper.safe_edit(update, prompt_map[sub], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"guess:create:{chat_id}:preview")]]))
                    return
                if sub == "repeat":
                    draft["allow_repeat_bet"] = not bool(draft.get("allow_repeat_bet", False))
                    await _start_guess_input_state(session, user_id=update.effective_user.id, chat_id=chat_id, state_type="guess_wait_title", draft=draft)
                    await session.commit()
                    await self._show_guess_create_menu(update, context, chat_id, draft)
                    return
                if sub == "clear":
                    await clear_private_admin_state(session, target_chat_id=chat_id, user_id=update.effective_user.id)
                    await session.commit()
                    await self._show_guess_create_menu(update, context, chat_id, {})
                    return
                if sub == "preview":
                    await session.commit()
                    await self._show_guess_create_menu(update, context, chat_id, draft)
                    return
                if sub == "publish":
                    required = {"title", "options", "command_keyword", "deadline_at"}
                    if not required.issubset(set(draft.keys())):
                        await session.commit()
                        await answer_callback_query_safely(update, "❌ 请先补齐活动名字、竞猜选项、群内指令和截止时间。", show_alert=True)
                        return
                    try:
                        event = await create_guess_event(session, chat_id, update.effective_user.id, draft)
                    except ValidationError as exc:
                        await session.rollback()
                        await answer_callback_query_safely(update, f"❌ {exc}", show_alert=True)
                        return
                    sent = await context.bot.send_message(chat_id=chat_id, text=format_event_runtime(event), parse_mode="Markdown")
                    event.announcement_message_id = sent.message_id
                    await clear_private_admin_state(session, target_chat_id=chat_id, user_id=update.effective_user.id)
                    await session.commit()
                    await self._show_guess_event_detail(update, context, chat_id, event.id)
                    return
            if action == "settings":
                sub = callback_data.get(3)
                if sub == "home":
                    await session.commit()
                    await self._show_guess_settings(update, context, chat_id)
                    return
                if sub == "rake_ratio":
                    await _start_guess_input_state(session, user_id=update.effective_user.id, chat_id=chat_id, state_type="guess_wait_rake_ratio", draft={})
                    await session.commit()
                    await self.message_helper.safe_edit(update, "⚽ 竞猜 | 抽水比例\n\n请输入 0 到 1 之间的小数，例如 0.1。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"guess:settings:{chat_id}:home")]]))
                    return
                if sub == "rake_owner":
                    await _start_guess_input_state(session, user_id=update.effective_user.id, chat_id=chat_id, state_type="guess_wait_rake_owner", draft={})
                    await session.commit()
                    await self.message_helper.safe_edit(update, "⚽ 竞猜 | 抽水归属\n\n请输入用户名或用户ID，发送“清空”清除。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"guess:settings:{chat_id}:home")]]))
                    return
                if sub == "delete_mode":
                    await update_guess_setting(session, chat_id, delete_message_mode=callback_data.get(4))
                    await session.commit()
                    await self._show_guess_settings(update, context, chat_id)
                    return
            if action == "list":
                await session.commit()
                await self._show_guess_event_list(update, context, chat_id, callback_data.get(3))
                return
            if action == "detail":
                await session.commit()
                await self._show_guess_event_detail(update, context, chat_id, callback_data.get_int(3))
                return
            if action == "open":
                event = await get_guess_event(session, chat_id, callback_data.get_int(3))
                if event is None:
                    await session.commit()
                    await answer_callback_query_safely(update, "❌ 活动不存在", show_alert=True)
                    return
                note = await settle_guess_event(session, event=event, winner_option=callback_data.get(4))
                await context.bot.send_message(chat_id=chat_id, text=f"{format_event_runtime(event)}\n\n{note}", parse_mode="Markdown")
                await session.commit()
                await self._show_guess_event_detail(update, context, chat_id, event.id)
                return
            if action == "cancel":
                event = await get_guess_event(session, chat_id, callback_data.get_int(3))
                if event is None:
                    await session.commit()
                    await answer_callback_query_safely(update, "❌ 活动不存在", show_alert=True)
                    return
                await cancel_guess_event(session, event=event)
                await session.commit()
                await self._show_guess_event_detail(update, context, chat_id, event.id)
                return
