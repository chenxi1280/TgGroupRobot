from __future__ import annotations

from backend.features.admin.support import *
from backend.shared.time_ui import build_copy_options_keyboard, build_numeric_duration_prompt_text


class GarageAuthActionsMixin:
    async def _start_garage_auth_input(
        self, update, context, *, enum, chat_id: int, state_type,
        prompt: str, back_callback: str,
    ) -> None:
        await self._start_text_input_state(
            context, update.effective_user.id, chat_id,
            state_type=state_type, payload={"target_chat_id": chat_id},
        )
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 返回", callback_data=back_callback)]]
        )
        await self.message_helper.safe_edit(update, prompt, reply_markup=keyboard)

    async def _update_garage_auth_setting(
        self, update, context, *, db, service, chat_id: int, changes: dict,
        summary: bool = False,
    ) -> None:
        async with db.session_factory() as session:
            await service.update_settings(session, chat_id, **changes)
            await session.commit()
        if summary:
            await self._show_garage_summary_menu(update, context, chat_id)
            return
        await self._show_garage_auth_menu(update, context, chat_id)

    async def _handle_garage_auth_toggle(
        self, update, context, *, db, service, chat_id: int, callback_data
    ) -> None:
        enabled = callback_data.get_int_optional(3)
        if enabled not in {0, 1}:
            await answer_callback_query_safely(update, "无效开关值", show_alert=True)
            return
        await self._update_garage_auth_setting(
            update, context, db=db, service=service, chat_id=chat_id,
            changes={"garage_auth_enabled": bool(enabled)},
        )

    async def _handle_garage_identity_list(
        self, update, context, *, db, service, enum, chat_id: int,
        action: str, callback_data,
    ) -> bool:
        configs = {
            "teacher": {
                "state": enum.garage_teacher_input.value,
                "prompt": "🚗 车库认证 | 手动添加认证老师\n\n👉 请输入用户名或ID：",
                "back": f"grg:teacher:list:{chat_id}:0", "error": "老师参数无效",
                "remove": service.remove_teacher, "view": self._show_garage_teacher_list_menu,
            },
            "wl": {
                "state": enum.garage_whitelist_input.value,
                "prompt": "📄 老师发言限制 | 添加白名单\n\n👉 请输入用户名或ID：",
                "back": f"grg:wl:list:{chat_id}:0", "error": "白名单参数无效",
                "remove": service.remove_whitelist, "view": self._show_garage_whitelist_menu,
            },
        }
        config = configs.get(action)
        if config is None:
            return False
        sub = callback_data.get(2)
        if sub == "list":
            await config["view"](
                update, context, chat_id, page=callback_data.get_int_optional(4) or 0
            )
            return True
        if sub == "add":
            await self._start_garage_auth_input(
                update, context, enum=enum, chat_id=chat_id,
                state_type=config["state"], prompt=config["prompt"],
                back_callback=config["back"],
            )
            return True
        if sub != "del":
            return False
        user_id = callback_data.get_int_optional(4)
        if user_id is None:
            await answer_callback_query_safely(update, config["error"], show_alert=True)
            return True
        async with db.session_factory() as session:
            await config["remove"](session, chat_id, user_id)
            await session.commit()
        await config["view"](update, context, chat_id, page=0)
        return True

    async def _start_garage_limit_input(
        self, update, context, *, enum, chat_id: int, sub: str
    ) -> None:
        if sub == "interval":
            await self._start_text_input_state(
                context, update.effective_user.id, chat_id,
                state_type=enum.garage_limit_interval_input.value,
                payload={"target_chat_id": chat_id},
            )
            await self.message_helper.safe_edit(
                update,
                build_numeric_duration_prompt_text(
                    title="🚗 车库认证 | 时间间隔", unit_label="秒",
                    sample_value_text="3600", input_hint="👉 请输入限制时间间隔（秒）：",
                ),
                parse_mode="HTML",
                reply_markup=build_copy_options_keyboard(
                    f"grg:home:{chat_id}",
                    [("📋 复制 3600秒", "3600"), ("📋 复制 7200秒", "7200")],
                ),
            )
            return
        await self._start_garage_auth_input(
            update, context, enum=enum, chat_id=chat_id,
            state_type=enum.garage_limit_max_count_input.value,
            prompt="🚗 车库认证 | 限制条数\n\n👉 请输入限制条数：",
            back_callback=f"grg:home:{chat_id}",
        )

    async def _handle_garage_limit(
        self, update, context, *, db, service, enum, chat_id: int, callback_data
    ) -> bool:
        if callback_data.get(1) != "limit":
            return False
        sub = callback_data.get(2)
        if sub in {"interval", "max"}:
            await self._start_garage_limit_input(
                update, context, enum=enum, chat_id=chat_id, sub=sub
            )
            return True
        value = callback_data.get_int_optional(4) if sub == "toggle" else callback_data.get(4)
        valid = value in {0, 1} if sub == "toggle" else value in {"none", "image", "image_text"}
        if sub not in {"toggle", "mode"} or not valid:
            await answer_callback_query_safely(
                update, "无效开关值" if sub == "toggle" else "无效模式",
                show_alert=True,
            )
            return True
        changes = (
            {"garage_limit_enabled": bool(value)}
            if sub == "toggle" else {"garage_limit_mode": value}
        )
        await self._update_garage_auth_setting(
            update, context, db=db, service=service,
            chat_id=chat_id, changes=changes,
        )
        return True

    async def _handle_garage_summary(
        self, update, context, *, db, service, chat_id: int, callback_data
    ) -> bool:
        if callback_data.get(1) != "summary":
            return False
        sub = callback_data.get(2)
        if sub == "menu":
            await self._show_garage_summary_menu(update, context, chat_id)
            return True
        if sub == "gen":
            async with db.session_factory() as session:
                text = await service.build_teacher_summary(session, chat_id)
                await session.commit()
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 返回汇总设置", callback_data=f"grg:summary:menu:{chat_id}")],
                [InlineKeyboardButton("返回车库认证", callback_data=f"grg:home:{chat_id}")],
            ])
            await self.message_helper.safe_edit(update, text, reply_markup=keyboard)
            return True
        value = callback_data.get(4)
        valid = value in {"region", "price"} if sub == "partition" else value in {"0", "1"}
        if sub not in {"partition", "open"} or not valid:
            await answer_callback_query_safely(update, "无效汇总设置", show_alert=True)
            return True
        changes = (
            {"garage_summary_partition_by": value}
            if sub == "partition" else {"garage_summary_only_open_course": value == "1"}
        )
        await self._update_garage_auth_setting(
            update, context, db=db, service=service, chat_id=chat_id,
            changes=changes, summary=True,
        )
        return True

    async def _handle_garage_auth(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int,
        *, callback_data: CallbackParser,
    ) -> None:
        from backend.features.garage.services.garage_features_service import GarageAuthService
        from backend.platform.db.schema.models.enums import ConversationStateType

        action = callback_data.get(1)
        if action == "home":
            await self._show_garage_auth_menu(update, context, chat_id)
            return
        db: Database = context.application.bot_data["db"]
        if action == "toggle":
            await self._handle_garage_auth_toggle(
                update, context, db=db, service=GarageAuthService,
                chat_id=chat_id, callback_data=callback_data,
            )
            return
        if action == "badge":
            await self._start_garage_auth_input(
                update, context, enum=ConversationStateType, chat_id=chat_id,
                state_type=ConversationStateType.garage_badge_input.value,
                prompt="🚗 车库认证 | 认证图标\n\n👉 请输入新的认证图标：",
                back_callback=f"grg:home:{chat_id}",
            )
            return
        if await self._handle_garage_identity_list(
            update, context, db=db, service=GarageAuthService,
            enum=ConversationStateType, chat_id=chat_id,
            action=action, callback_data=callback_data,
        ):
            return
        if await self._handle_garage_limit(
            update, context, db=db, service=GarageAuthService,
            enum=ConversationStateType, chat_id=chat_id, callback_data=callback_data,
        ):
            return
        if await self._handle_garage_summary(
            update, context, db=db, service=GarageAuthService,
            chat_id=chat_id, callback_data=callback_data,
        ):
            return
        await self._show_garage_auth_menu(update, context, chat_id)
