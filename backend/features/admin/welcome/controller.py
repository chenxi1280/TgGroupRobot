from __future__ import annotations

from backend.features.admin.support import *
from backend.shared.button_layout_editor import ButtonEditorContext, show_layout_menu


class WelcomeAdminControllerMixin:
    async def _show_welcome_list_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        from backend.features.verification.welcome_service import WelcomeService

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            items = await WelcomeService.list_messages(session, chat_id)
            await session.commit()

        page_total = 1
        lines = [
            "🎉 进群欢迎",
            "",
            "新用户进群后弹出欢迎信息，支持配置多个欢迎文案。但为了减少刷屏，强烈建议只配置一个！",
            "",
        ]
        if not items:
            lines.append("0 条数据，第 1 页/共 1 页")
        else:
            for item in items:
                status = "✅ 启用" if item.enabled else "❌ 关闭"
                lines.append(f"标题：{item.title}（状态：{status}）")
                lines.append(f"┗编号：{item.id}")
                lines.append("")
            lines.append(f"{len(items)} 条数据，第 1 页/共 {page_total} 页")

        keyboard_rows: list[list[InlineKeyboardButton]] = []
        for item in items:
            keyboard_rows.append([
                InlineKeyboardButton(f"编号:{item.id}", callback_data=f"adm:wel:{chat_id}:detail:{item.id}"),
                InlineKeyboardButton("✅启用" if item.enabled else "❌关闭", callback_data=f"adm:wel:{chat_id}:toggle:{item.id}"),
                InlineKeyboardButton("修改", callback_data=f"adm:wel:{chat_id}:detail:{item.id}"),
                InlineKeyboardButton("删除", callback_data=f"adm:wel:{chat_id}:delete:{item.id}"),
            ])
        keyboard_rows.append([InlineKeyboardButton("➕ 添加一条", callback_data=f"adm:wel:{chat_id}:add")])
        keyboard_rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")])
        await self.message_helper.safe_edit(update, "\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard_rows))

    async def _show_welcome_detail_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        welcome_id: int,
    ) -> None:
        from backend.platform.db.schema.models.enums import WelcomeDeleteMode, WelcomeMode
        from backend.features.verification.welcome_service import WelcomeService

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            item = await WelcomeService.get_message(session, chat_id, welcome_id)
            await session.commit()

        mode_label = "验证后欢迎" if item.welcome_mode == WelcomeMode.after_verify.value else "进群欢迎"
        delete_label = {
            WelcomeDeleteMode.keep.value: "不删除",
            WelcomeDeleteMode.delete_prev.value: "删除上一条",
            WelcomeDeleteMode.seconds.value: f"{int(item.delete_delay_seconds or 15)}秒后删除",
        }.get(item.delete_mode, "15秒后删除")
        text = (
            "🎉 进群欢迎\n\n"
            f"🧭 标题备注：{item.title}\n\n"
            f"🪩 欢迎模式：{mode_label}\n\n"
            f"🖼️ 封面设置：{'已设置' if item.cover_media_file_id else '未设置'}\n\n"
            f"📄 文本内容：{item.text_content}\n\n"
            f"⭕ 设置按钮：{'未设置' if not item.buttons else f'{len(item.buttons)} 行已配置'}\n\n"
            f"⏱️ 延迟删除：{delete_label}"
        )
        status_on = "✅ 启用" if item.enabled else "启用"
        status_off = "关闭" if item.enabled else "❌ 关闭"
        mode_after_verify = "✅ 验证后欢迎" if item.welcome_mode == WelcomeMode.after_verify.value else "验证后欢迎"
        mode_on_join = "进群欢迎" if item.welcome_mode == WelcomeMode.after_verify.value else "✅ 进群欢迎"
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("状态：", callback_data=f"adm:wel:{chat_id}:toggle:{welcome_id}"),
                InlineKeyboardButton(status_on, callback_data=f"adm:wel:{chat_id}:toggle:{welcome_id}"),
                InlineKeyboardButton(status_off, callback_data=f"adm:wel:{chat_id}:toggle:{welcome_id}"),
            ],
            [
                InlineKeyboardButton("模式：", callback_data=f"adm:wel:{chat_id}:mode:{welcome_id}"),
                InlineKeyboardButton(mode_after_verify, callback_data=f"adm:wel:{chat_id}:mode:{welcome_id}"),
                InlineKeyboardButton(mode_on_join, callback_data=f"adm:wel:{chat_id}:mode:{welcome_id}"),
            ],
            [
                InlineKeyboardButton("标题备注", callback_data=f"adm:wel:{chat_id}:input:{welcome_id}:title"),
                InlineKeyboardButton("修改封面", callback_data=f"adm:wel:{chat_id}:input:{welcome_id}:cover"),
            ],
            [
                InlineKeyboardButton("修改文本", callback_data=f"adm:wel:{chat_id}:input:{welcome_id}:text"),
                InlineKeyboardButton("修改按钮", callback_data=f"btned:open:welcome:{chat_id}:{welcome_id}"),
            ],
            [
                InlineKeyboardButton("🏖️ 预览效果", callback_data=f"adm:wel:{chat_id}:preview:{welcome_id}"),
                InlineKeyboardButton("⏱️ 延迟删除", callback_data=f"adm:wel:{chat_id}:cycle_delete:{welcome_id}"),
            ],
            [
                InlineKeyboardButton("❌ 删除配置", callback_data=f"adm:wel:{chat_id}:delete:{welcome_id}"),
                InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:welcome:{chat_id}"),
            ],
        ])
        await self.message_helper.safe_edit(update, text, reply_markup=keyboard)

    async def _handle_welcome(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        from backend.platform.db.schema.models.enums import ConversationStateType, WelcomeDeleteMode, WelcomeMode
        from backend.features.verification.welcome_service import WelcomeService

        op = callback_data.get(3)
        db: Database = context.application.bot_data["db"]

        if op == "add":
            async with db.session_factory() as session:
                item = await WelcomeService.create_message(session, chat_id)
                await session.commit()
            await self._show_welcome_detail_menu(update, context, chat_id, item.id)
            return

        if op == "detail":
            welcome_id = callback_data.require_int(4, label="welcome_id")
            await self._show_welcome_detail_menu(update, context, chat_id, welcome_id)
            return

        if op == "toggle":
            welcome_id = callback_data.require_int(4, label="welcome_id")
            async with db.session_factory() as session:
                item = await WelcomeService.get_message(session, chat_id, welcome_id)
                await WelcomeService.update_field(session, chat_id, welcome_id, enabled=not item.enabled)
                await session.commit()
            await self._show_welcome_detail_menu(update, context, chat_id, welcome_id)
            return

        if op == "mode":
            welcome_id = callback_data.require_int(4, label="welcome_id")
            async with db.session_factory() as session:
                item = await WelcomeService.get_message(session, chat_id, welcome_id)
                next_mode = (
                    WelcomeMode.on_join.value
                    if item.welcome_mode == WelcomeMode.after_verify.value
                    else WelcomeMode.after_verify.value
                )
                await WelcomeService.update_field(session, chat_id, welcome_id, welcome_mode=next_mode)
                await session.commit()
            await self._show_welcome_detail_menu(update, context, chat_id, welcome_id)
            return

        if op == "delete":
            welcome_id = callback_data.require_int(4, label="welcome_id")
            async with db.session_factory() as session:
                await WelcomeService.delete_message(session, chat_id, welcome_id)
                await session.commit()
            await self._show_welcome_list_menu(update, context, chat_id)
            return

        if op == "preview":
            welcome_id = callback_data.require_int(4, label="welcome_id")
            async with db.session_factory() as session:
                await WelcomeService.preview(
                    context,
                    session,
                    preview_chat_id=update.effective_user.id,
                    chat_id=chat_id,
                    welcome_id=welcome_id,
                    member=update.effective_user,
                    user_id=update.effective_user.id,
                )
                await session.commit()
            await answer_callback_query_safely(update, "已发送预览到当前私聊", show_alert=False)
            return

        if op == "cycle_delete":
            welcome_id = callback_data.require_int(4, label="welcome_id")
            options: list[tuple[str, int | None]] = [
                (WelcomeDeleteMode.seconds.value, 15),
                (WelcomeDeleteMode.seconds.value, 30),
                (WelcomeDeleteMode.seconds.value, 60),
                (WelcomeDeleteMode.seconds.value, 90),
                (WelcomeDeleteMode.seconds.value, 120),
                (WelcomeDeleteMode.seconds.value, 300),
                (WelcomeDeleteMode.delete_prev.value, None),
                (WelcomeDeleteMode.keep.value, None),
            ]
            async with db.session_factory() as session:
                item = await WelcomeService.get_message(session, chat_id, welcome_id)
                current = (item.delete_mode, item.delete_delay_seconds)
                try:
                    index = options.index(current)
                except ValueError:
                    index = -1
                next_mode, next_delay = options[(index + 1) % len(options)]
                await WelcomeService.update_field(
                    session,
                    chat_id,
                    welcome_id,
                    delete_mode=next_mode,
                    delete_delay_seconds=next_delay,
                )
                await session.commit()
            await self._show_welcome_detail_menu(update, context, chat_id, welcome_id)
            return

        if op == "input":
            welcome_id = callback_data.require_int(4, label="welcome_id")
            field = callback_data.get(5)
            if field == "buttons":
                async with db.session_factory() as session:
                    await show_layout_menu(
                        update,
                        context,
                        ButtonEditorContext("welcome", chat_id, welcome_id),
                        session=session,
                    )
                    await session.commit()
                return
            state_map = {
                "title": ConversationStateType.welcome_title_input.value,
                "text": ConversationStateType.welcome_text_input.value,
                "cover": ConversationStateType.welcome_cover_input.value,
            }
            state_type = state_map.get(field)
            if state_type is None:
                await answer_callback_query_safely(update, "无效配置项", show_alert=True)
                return
            await self._start_text_input_state(
                context,
                update.effective_user.id,
                chat_id,
                state_type,
                {"target_chat_id": chat_id, "welcome_id": welcome_id},
            )
            prompt = {
                "title": "👉 请输入标题备注：",
                "text": "👉 请输入欢迎文本，可使用 {member} {group} {userid} {nickname}：",
                "cover": "👉 请发送图片或视频；发送“清空”可移除封面。",
                "buttons": "👉 请输入按钮 JSON，例如 [[{\"text\":\"联系管理员\",\"url\":\"https://t.me/example\"}]]；发送“清空”可移除按钮。",
            }[field]
            await self.message_helper.safe_edit(
                update,
                prompt,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"adm:wel:{chat_id}:detail:{welcome_id}")]]),
            )
