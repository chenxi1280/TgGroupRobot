from __future__ import annotations

from backend.features.admin.support import *
from backend.shared.services.base import NotFoundError


def _empty_alliance_view(chat_id: int):
    text = "🖐 联盟功能\n\n群组可以组建自己的联盟，在同一联盟中的群组，可以实现同步封禁等共享能力。"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🆕 创建联盟", callback_data=f"ali:create:input:{chat_id}")],
        [InlineKeyboardButton("🤝 加入联盟", callback_data=f"ali:join:input:{chat_id}")],
        [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
    ])
    return text, keyboard


def _alliance_view(alliance, setting, members, *, chat_id: int):
    joint_ban = bool(setting.joint_ban_enabled) if setting is not None else False
    is_owner = alliance.owner_chat_id == chat_id
    text = (
        f"🖐 联盟功能\n\n🟩 联盟名字：{alliance.name}\n\n👥 联盟成员：{len(members)} 个\n"
        f"联合封禁状态：{'✅ 启动' if joint_ban else '❌ 关闭'}\n\n🚫 联合封禁\n"
        "└ 联盟群使用 team 指令封禁用户，该用户加入联合封禁列表\n"
        "└ 联合封禁列表中的用户，在联盟其他群中发言，会被自动封禁\n\n"
        f"邀请码权限：{'创建群可重置' if is_owner else '仅创建群可重置'}"
    )
    rows = [
        [InlineKeyboardButton("💥 查看联盟成员", callback_data=f"ali:members:{chat_id}")],
        [InlineKeyboardButton("📋 联合封禁名单", callback_data=f"ali:jointban:list:{chat_id}")],
        [InlineKeyboardButton("⚙️ 联合封禁：", callback_data=f"ali:home:{chat_id}"), InlineKeyboardButton("✅ 启动" if joint_ban else "启动", callback_data=f"ali:jointban:toggle:{chat_id}:1"), InlineKeyboardButton("关闭" if joint_ban else "✅ 关闭", callback_data=f"ali:jointban:toggle:{chat_id}:0")],
        [InlineKeyboardButton("🔑 邀请密码" if is_owner else "🔑 邀请密码（仅创建群）", callback_data=f"ali:invite:show:{chat_id}" if is_owner else f"ali:invite:denied:{chat_id}"), InlineKeyboardButton("🚪 退出联盟", callback_data=f"ali:leave:{chat_id}:confirm")],
        [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
    ]
    return text, InlineKeyboardMarkup(rows)


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

        text, keyboard = (
            _empty_alliance_view(chat_id)
            if alliance is None
            else _alliance_view(alliance, setting, members, chat_id=chat_id)
        )
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

    async def _show_alliance_joint_ban_menu(
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
            entries = await AllianceService.list_joint_ban_entries(session, chat_id=chat_id, limit=10)
            await session.commit()

        lines = [
            "🖐 联盟功能 | 联合封禁名单",
            "",
            f"联盟：{alliance.name}",
            f"当前记录：{len(entries)} 条",
            "",
        ]
        keyboard_rows: list[list[InlineKeyboardButton]] = []
        if entries:
            for item in entries:
                timestamp = item.created_at.strftime("%m-%d %H:%M") if item.created_at else "--"
                lines.append(
                    f"🚫 #{item.id}｜用户 {item.target_user_id}｜来源群 {item.source_chat_id}｜{timestamp}"
                )
                lines.append(f"原因：{item.reason or '-'}")
                lines.append("")
                keyboard_rows.append(
                    [InlineKeyboardButton(f"🗑 移除 #{item.id} / {item.target_user_id}", callback_data=f"ali:jointban:remove:{chat_id}:{item.id}")]
                )
        else:
            lines.append("暂无联合封禁记录")
        keyboard_rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"ali:home:{chat_id}")])
        await self.message_helper.safe_edit(update, "\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard_rows))

    async def _handle_alliance_input(
        self, update, context, *, enum, chat_id: int, action: str, callback_data
    ) -> bool:
        if callback_data.get(2) != "input":
            return False
        configs = {
            "create": (enum.alliance_create_name_input.value, "🖐 联盟功能 | 创建联盟\n\n👉 请取一个联盟名称："),
            "join": (enum.alliance_join_code_input.value, "🖐 联盟功能 | 加入联盟\n\n👉 请输入联盟邀请码："),
        }
        config = configs.get(action)
        if config is None:
            return False
        await self._start_text_input_state(
            context, update.effective_user.id, chat_id,
            state_type=config[0], payload={"target_chat_id": chat_id},
        )
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 返回", callback_data=f"ali:home:{chat_id}")]]
        )
        await self.message_helper.safe_edit(update, config[1], reply_markup=keyboard)
        return True

    async def _handle_alliance_jointban(
        self, update, context, *, db, service, chat_id: int, callback_data
    ) -> bool:
        if callback_data.get(1) != "jointban":
            return False
        sub = callback_data.get(2)
        if sub == "list":
            await self._show_alliance_joint_ban_menu(update, context, chat_id)
            return True
        value = callback_data.get_int_optional(4)
        if sub == "toggle":
            if value not in {0, 1}:
                await answer_callback_query_safely(update, "无效开关值", show_alert=True)
                return True
            async with db.session_factory() as session:
                await service.set_joint_ban_enabled(
                    session, chat_id=chat_id,
                    operator_user_id=update.effective_user.id, enabled=bool(value),
                )
                await session.commit()
            await self._show_alliance_menu(update, context, chat_id)
            return True
        if sub != "remove":
            return False
        await self._remove_alliance_jointban(
            update, context, db=db, service=service, chat_id=chat_id, entry_id=value
        )
        return True

    async def _remove_alliance_jointban(
        self, update, context, *, db, service, chat_id: int, entry_id: int | None
    ) -> None:
        if entry_id is None:
            await answer_callback_query_safely(update, "无效联合封禁条目", show_alert=True)
            return
        try:
            async with db.session_factory() as session:
                await service.remove_joint_ban_entry(
                    session, chat_id=chat_id,
                    operator_user_id=update.effective_user.id, entry_id=entry_id,
                )
                await session.commit()
        except (NotFoundError, ValidationError) as exc:
            await answer_callback_query_safely(update, str(exc), show_alert=True)
            return
        await answer_callback_query_safely(update, "已移除联合封禁条目")
        await self._show_alliance_joint_ban_menu(update, context, chat_id)

    async def _handle_alliance_invite(
        self, update, *, db, service, chat_id: int, callback_data
    ) -> bool:
        if callback_data.get(1) != "invite":
            return False
        if callback_data.get(2) == "denied":
            await answer_callback_query_safely(
                update, "只有创建群可以重置联盟邀请码。", show_alert=True
            )
            return True
        if callback_data.get(2) != "show":
            return False
        async with db.session_factory() as session:
            try:
                code = await service.rotate_invite_code(
                    session, chat_id=chat_id,
                    operator_user_id=update.effective_user.id,
                )
                await session.commit()
            except ValidationError as exc:
                await session.rollback()
                await answer_callback_query_safely(update, str(exc), show_alert=True)
                return True
        await answer_callback_query_safely(update, f"新的联盟邀请码：{code}", show_alert=True)
        return True

    async def _handle_alliance_leave(
        self, update, context, *, db, service, chat_id: int, callback_data
    ) -> bool:
        if callback_data.get(1) != "leave" or callback_data.get(3) != "confirm":
            return False
        try:
            async with db.session_factory() as session:
                await service.leave_alliance(
                    session, chat_id=chat_id,
                    operator_user_id=update.effective_user.id,
                )
                await session.commit()
        except ValidationError as exc:
            await answer_callback_query_safely(update, str(exc), show_alert=True)
            return True
        await self._show_alliance_menu(update, context, chat_id)
        return True

    async def _handle_alliance(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *,
        callback_data: CallbackParser,
    ) -> None:
        from backend.platform.db.schema.models.enums import ConversationStateType
        from backend.features.garage.services.alliance_service import AllianceService

        action = callback_data.get(1)
        if action == "home":
            await self._show_alliance_menu(update, context, chat_id)
            return
        if action == "members":
            await self._show_alliance_members_menu(update, context, chat_id)
            return
        if await self._handle_alliance_input(
            update, context, enum=ConversationStateType,
            chat_id=chat_id, action=action, callback_data=callback_data,
        ):
            return
        db: Database = context.application.bot_data["db"]
        if await self._handle_alliance_jointban(
            update, context, db=db, service=AllianceService,
            chat_id=chat_id, callback_data=callback_data,
        ):
            return
        if await self._handle_alliance_invite(
            update, db=db, service=AllianceService,
            chat_id=chat_id, callback_data=callback_data,
        ):
            return
        if await self._handle_alliance_leave(
            update, context, db=db, service=AllianceService,
            chat_id=chat_id, callback_data=callback_data,
        ):
            return
        await self._show_alliance_menu(update, context, chat_id)
