from __future__ import annotations

from backend.features.activity.game_panels import show_blackjack_panel, show_k3_panel
from backend.features.admin.activity.game_presenters import (
    build_game_menu_keyboard,
    build_game_points_keyboard,
    format_game_round_detail,
    format_game_points_text,
)
from backend.features.admin.support import *
from backend.shared.time_ui import (
    build_copy_time_keyboard,
    build_hhmm_prompt_text,
    next_top_of_hour_hhmm,
)


class GameAdminControllerMixin:
    async def _sync_game_panel_after_toggle(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        db: Database,
        chat_id: int,
        *,
        field: str | None,
        enabled: bool,
    ) -> None:
        try:
            if field == "k3":
                await show_k3_panel(context, db, chat_id, create_if_missing=enabled)
            elif field == "blackjack":
                await show_blackjack_panel(
                    context, db, chat_id, create_if_missing=enabled
                )
        except Exception as exc:
            log.warning(
                "game_panel_sync_failed",
                chat_id=chat_id,
                field=field,
                enabled=enabled,
                error=str(exc),
            )

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
            rake_owner = await get_game_rake_owner_label(
                session, setting.rake_owner_user_id
            )
            points_chat_label = await get_game_points_chat_label(
                session, chat_id, getattr(setting, "points_source_chat_id", None)
            )
            await session.commit()
        chat_title = await self._get_chat_title(db, chat_id)
        text = format_game_menu_text(
            chat_title,
            k3_enabled=setting.k3_enabled,
            blackjack_enabled=setting.blackjack_enabled,
            points_chat_label=points_chat_label,
            rake_ratio=setting.rake_ratio,
            rake_owner=rake_owner,
            auto_schedule_enabled=setting.auto_schedule_enabled,
            auto_start_time=setting.auto_start_time,
            auto_stop_time=setting.auto_stop_time,
            delete_mode=setting.delete_game_message_mode,
        )
        keyboard = build_game_menu_keyboard(setting, chat_id, points_chat_label)
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_game_points_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            setting = await get_game_setting(session, chat_id)
            current_source = getattr(setting, "points_source_chat_id", None)
            current_label = await get_game_points_chat_label(
                session, chat_id, current_source
            )
            await session.commit()

        managed_chats = await get_user_managed_chats(
            db, update.effective_user.id, context.bot
        )
        has_alternative = any(int(item[0]) != int(chat_id) for item in managed_chats)
        text = format_game_points_text(current_label, has_alternative)
        keyboard = build_game_points_keyboard(managed_chats, chat_id, current_source)
        await self.message_helper.safe_edit(update, text, reply_markup=keyboard)

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
            [
                InlineKeyboardButton(
                    f"🔎 查看 #{round_obj.id}",
                    callback_data=f"gm:detail:{chat_id}:{round_obj.id}",
                )
            ]
            for round_obj in rounds
        ]
        keyboard_rows.append(
            [InlineKeyboardButton("🔙 返回", callback_data=f"gm:home:{chat_id}")]
        )
        await self.message_helper.safe_edit(
            update,
            text="\n".join(lines),
            reply_markup=InlineKeyboardMarkup(keyboard_rows),
        )

    async def _show_game_round_detail(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *,
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
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "🔙 返回", callback_data=f"gm:rounds:{chat_id}"
                            )
                        ]
                    ]
                ),
            )
            return
        await self.message_helper.safe_edit(
            update,
            format_game_round_detail(round_obj, participants),
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔙 返回", callback_data=f"gm:rounds:{chat_id}"
                        )
                    ]
                ]
            ),
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
                "🎲 快三：",
                "• 发送 `快三` 查看玩法",
                "• 发送 `快三 大 100` / `快三 小 100` / `快三 对子 100` / `快三 半顺 100` / `快三 三连 100` / `快三 杂六 100` 下注",
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
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 返回", callback_data=f"gm:home:{chat_id}")]]
            ),
        )

    async def _handle_game(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *,
        callback_data: CallbackParser,
    ) -> None:
        action = callback_data.get(1)
        if await self._handle_game_navigation(
            update, context, chat_id=chat_id, action=action, callback_data=callback_data
        ):
            return
        db: Database = context.application.bot_data["db"]
        if action == "points":
            await self._handle_game_points(
                update, context, db=db, chat_id=chat_id, callback_data=callback_data
            )
            return
        async with db.session_factory() as session:
            await self._handle_game_setting_action(
                update,
                context,
                db=db,
                session=session,
                chat_id=chat_id,
                action=action,
                callback_data=callback_data,
            )

    async def _handle_game_navigation(
        self, update, context, *, chat_id: int, action: str, callback_data
    ) -> bool:
        handlers = {
            "home": self._show_game_menu,
            "rounds": self._show_game_rounds,
            "help": self._show_game_help,
        }
        if action == "detail":
            round_id = callback_data.get_int(3, default=0)
            await self._show_game_round_detail(
                update, context, chat_id, round_id=round_id
            )
            return True
        handler = handlers.get(action)
        if handler is None:
            return False
        await handler(update, context, chat_id)
        return True

    async def _handle_game_points(
        self, update, context, *, db, chat_id: int, callback_data
    ) -> None:
        sub = callback_data.get(3)
        if sub == "menu":
            await self._show_game_points_menu(update, context, chat_id)
            return
        if sub == "self":
            await self._save_game_points_source(db, chat_id, None)
            await self._show_game_points_menu(update, context, chat_id)
            return
        if sub != "set":
            return
        source_chat_id = callback_data.get_int_optional(4)
        if source_chat_id is None:
            await self._show_game_points_error(
                update, chat_id, "关联积分参数无效，请返回重试。"
            )
            return
        allowed, error_text = await PermissionPolicyService.require_manage(
            context,
            source_chat_id,
            update.effective_user.id,
            capability="manage",
        )
        if not allowed:
            await self._show_game_points_error(
                update, chat_id, error_text or "你没有该主群的管理权限。"
            )
            return
        source_value = None if int(source_chat_id) == int(chat_id) else source_chat_id
        await self._save_game_points_source(db, chat_id, source_value)
        await self._show_game_points_menu(update, context, chat_id)

    async def _save_game_points_source(
        self, db, chat_id: int, source_chat_id: int | None
    ) -> None:
        async with db.session_factory() as session:
            await update_game_setting(
                session, chat_id, points_source_chat_id=source_chat_id
            )
            await session.commit()

    async def _show_game_points_error(self, update, chat_id: int, text: str) -> None:
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🔙 返回", callback_data=f"gm:points:{chat_id}:menu"
                    )
                ]
            ]
        )
        await self.message_helper.safe_edit(update, text, reply_markup=keyboard)

    async def _handle_game_setting_action(
        self,
        update,
        context,
        *,
        db,
        session,
        chat_id: int,
        action: str,
        callback_data,
    ) -> None:
        if action == "toggle":
            await self._handle_game_toggle(
                update,
                context,
                db=db,
                session=session,
                chat_id=chat_id,
                callback_data=callback_data,
            )
            return
        if action == "rake":
            await self._handle_game_rake(
                update,
                context,
                session=session,
                chat_id=chat_id,
                sub=callback_data.get(3),
            )
            return
        if action == "auto":
            await self._handle_game_auto(
                update,
                context,
                session=session,
                chat_id=chat_id,
                callback_data=callback_data,
            )
            return
        if action != "delete_mode":
            return
        await update_game_setting(
            session, chat_id, delete_game_message_mode=callback_data.get(3)
        )
        await session.commit()
        await self._show_game_menu(update, context, chat_id)

    async def _handle_game_toggle(
        self, update, context, *, db, session, chat_id: int, callback_data
    ) -> None:
        field = callback_data.get(3)
        enabled = callback_data.get(4) == "1"
        await update_game_setting(session, chat_id, **{f"{field}_enabled": enabled})
        await session.commit()
        await self._sync_game_panel_after_toggle(
            context, db, chat_id, field=field, enabled=enabled
        )
        await self._show_game_menu(update, context, chat_id)

    async def _handle_game_rake(
        self, update, context, *, session, chat_id: int, sub: str
    ) -> None:
        prompts = {
            "ratio": (
                "game_wait_rake_ratio",
                "🎮 游戏 | 抽水比例\n\n请输入抽水比例\n例如：0.1 就是抽水10%",
            ),
            "owner": (
                "game_wait_rake_owner",
                "🎮 游戏 | 抽水归属\n\n请输入用户名或用户ID，发送“清空”可注销抽水归属。",
            ),
        }
        prompt = prompts.get(sub)
        if prompt is None:
            return
        await self._start_game_input(
            update,
            context,
            session=session,
            chat_id=chat_id,
            state_type=prompt[0],
            prompt=prompt[1],
        )

    async def _start_game_input(
        self, update, context, *, session, chat_id: int, state_type: str, prompt: str
    ) -> None:
        user_id = update.effective_user.id
        await self._start_text_input_state(
            context,
            user_id,
            user_id,
            state_type=state_type,
            payload={"target_chat_id": chat_id},
        )
        await session.commit()
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 返回", callback_data=f"gm:home:{chat_id}")]]
        )
        await self.message_helper.safe_edit(update, prompt, reply_markup=keyboard)

    async def _handle_game_auto(
        self, update, context, *, session, chat_id: int, callback_data
    ) -> None:
        sub = callback_data.get(3)
        if sub == "toggle":
            enabled = callback_data.get(4) == "1"
            await update_game_setting(session, chat_id, auto_schedule_enabled=enabled)
            await session.commit()
            await self._show_game_menu(update, context, chat_id)
            return
        prompt_configs = {
            "start_time": (
                "game_wait_auto_start_time",
                "🎮 游戏 | 自动启动时间",
                "👉 请输入自动启动时间（格式 HH:MM）：",
                0,
            ),
            "stop_time": (
                "game_wait_auto_stop_time",
                "🎮 游戏 | 自动关停时间",
                "👉 请输入自动关停时间（格式 HH:MM）：",
                8,
            ),
        }
        config = prompt_configs.get(sub)
        if config is None:
            return
        await self._show_game_time_prompt(
            update, context, session=session, chat_id=chat_id, config=config
        )

    async def _show_game_time_prompt(
        self,
        update,
        context,
        *,
        session,
        chat_id: int,
        config: tuple[str, str, str, int],
    ) -> None:
        user_id = update.effective_user.id
        await self._start_text_input_state(
            context,
            user_id,
            user_id,
            state_type=config[0],
            payload={"target_chat_id": chat_id},
        )
        await session.commit()
        sample_text = next_top_of_hour_hhmm(hours_offset=config[3])
        text = build_hhmm_prompt_text(
            title=config[1],
            sample_time_text=sample_text,
            input_hint=config[2],
        )
        await self.message_helper.safe_edit(
            update,
            text,
            reply_markup=build_copy_time_keyboard(f"gm:home:{chat_id}", sample_text),
            parse_mode="HTML",
        )
