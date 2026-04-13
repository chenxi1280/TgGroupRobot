from __future__ import annotations

from backend.features.admin.support import *


class GarageAllianceAdminMixin:
    async def _show_alliance_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        from backend.features.garage.services.alliance_service import AllianceService

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            alliance = await AllianceService.get_alliance_by_chat(session, chat_id)
            setting = await AllianceService.get_setting(session, chat_id)
            members = await AllianceService.list_members(session, alliance.alliance_id) if alliance is not None else []
            await session.commit()

        if alliance is None:
            text = (
                "🖐 联盟功能\n\n"
                "群组可以组建自己的联盟，在同一联盟中的群组，可以实现同步封禁等共享能力。"
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🆕 创建联盟", callback_data=f"ali:create:input:{chat_id}")],
                [InlineKeyboardButton("🤝 加入联盟", callback_data=f"ali:join:input:{chat_id}")],
                [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
            ])
            await self.message_helper.safe_edit(update, text, reply_markup=keyboard)
            return

        joint_ban_enabled = bool(setting.joint_ban_enabled) if setting is not None else False
        is_owner = alliance.owner_chat_id == chat_id
        text = (
            "🖐 联盟功能\n\n"
            f"🟩 联盟名字：{alliance.name}\n\n"
            f"👥 联盟成员：{len(members)} 个\n"
            f"联合封禁状态：{'✅ 启动' if joint_ban_enabled else '❌ 关闭'}\n\n"
            "🚫 联合封禁\n"
            "└ 联盟群使用 t 指令封禁用户，该用户加入联合封禁列表\n"
            "└ 联合封禁列表中的用户，在联盟其他群中发言，会被自动封禁\n\n"
            f"邀请码权限：{'创建群可重置' if is_owner else '仅创建群可重置'}"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💥 查看联盟成员", callback_data=f"ali:members:{chat_id}")],
            [
                InlineKeyboardButton("⚙️ 联合封禁：", callback_data=f"ali:home:{chat_id}"),
                InlineKeyboardButton("✅ 启动" if joint_ban_enabled else "启动", callback_data=f"ali:jointban:toggle:{chat_id}:1"),
                InlineKeyboardButton("关闭" if joint_ban_enabled else "✅ 关闭", callback_data=f"ali:jointban:toggle:{chat_id}:0"),
            ],
            [
                InlineKeyboardButton(
                    "🔑 邀请密码" if is_owner else "🔑 邀请密码（仅创建群）",
                    callback_data=f"ali:invite:show:{chat_id}" if is_owner else f"ali:invite:denied:{chat_id}",
                ),
                InlineKeyboardButton("🚪 退出联盟", callback_data=f"ali:leave:{chat_id}:confirm"),
            ],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, text, reply_markup=keyboard)

    async def _show_alliance_members_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        from backend.features.garage.services.alliance_service import AllianceService

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            alliance = await AllianceService.get_alliance_by_chat(session, chat_id)
            if alliance is None:
                await session.commit()
                await self._show_alliance_menu(update, context, chat_id)
                return
            members = await AllianceService.list_members(session, alliance.alliance_id)
            await session.commit()

        lines = [
            "🖐 联盟功能 | 联盟成员",
            "",
            f"联盟：{alliance.name}",
            "",
        ]
        for index, (member, chat) in enumerate(members, start=1):
            title = chat.title if chat and chat.title else str(member.chat_id)
            owner_mark = "（创建群）" if alliance.owner_chat_id == member.chat_id else ""
            lines.append(f"{index}. {title}{owner_mark}")
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"ali:home:{chat_id}")]])
        await self.message_helper.safe_edit(update, "\n".join(lines), reply_markup=keyboard)

    async def _handle_alliance(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        from backend.platform.db.schema.models.enums import ConversationStateType
        from backend.features.garage.services.alliance_service import AllianceService

        action = callback_data.get(1)
        db: Database = context.application.bot_data["db"]

        if action == "home":
            await self._show_alliance_menu(update, context, chat_id)
            return

        if action == "members":
            await self._show_alliance_members_menu(update, context, chat_id)
            return

        if action == "create" and callback_data.get(2) == "input":
            await self._start_text_input_state(
                context,
                update.effective_user.id,
                chat_id,
                ConversationStateType.alliance_create_name_input.value,
                {"target_chat_id": chat_id},
            )
            await self.message_helper.safe_edit(
                update,
                "🖐 联盟功能 | 创建联盟\n\n👉 请取一个联盟名称：",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"ali:home:{chat_id}")]]),
            )
            return

        if action == "join" and callback_data.get(2) == "input":
            await self._start_text_input_state(
                context,
                update.effective_user.id,
                chat_id,
                ConversationStateType.alliance_join_code_input.value,
                {"target_chat_id": chat_id},
            )
            await self.message_helper.safe_edit(
                update,
                "🖐 联盟功能 | 加入联盟\n\n👉 请输入联盟邀请码：",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"ali:home:{chat_id}")]]),
            )
            return

        if action == "jointban" and callback_data.get(2) == "toggle":
            enabled = callback_data.get_int_optional(4)
            if enabled not in {0, 1}:
                await answer_callback_query_safely(update, "无效开关值", show_alert=True)
                return
            async with db.session_factory() as session:
                await AllianceService.set_joint_ban_enabled(
                    session,
                    chat_id=chat_id,
                    operator_user_id=update.effective_user.id,
                    enabled=bool(enabled),
                )
                await session.commit()
            await self._show_alliance_menu(update, context, chat_id)
            return

        if action == "invite" and callback_data.get(2) == "show":
            async with db.session_factory() as session:
                try:
                    invite_code = await AllianceService.rotate_invite_code(
                        session,
                        chat_id=chat_id,
                        operator_user_id=update.effective_user.id,
                    )
                    await session.commit()
                except ValidationError as exc:
                    await session.rollback()
                    await answer_callback_query_safely(update, str(exc), show_alert=True)
                    return
            await answer_callback_query_safely(update, f"新的联盟邀请码：{invite_code}", show_alert=True)
            return

        if action == "invite" and callback_data.get(2) == "denied":
            await answer_callback_query_safely(update, "只有创建群可以重置联盟邀请码。", show_alert=True)
            return

        if action == "leave" and callback_data.get(3) == "confirm":
            try:
                async with db.session_factory() as session:
                    await AllianceService.leave_alliance(
                        session,
                        chat_id=chat_id,
                        operator_user_id=update.effective_user.id,
                    )
                    await session.commit()
            except ValidationError as exc:
                await answer_callback_query_safely(update, str(exc), show_alert=True)
                return
            await self._show_alliance_menu(update, context, chat_id)
            return

        await self._show_alliance_menu(update, context, chat_id)

