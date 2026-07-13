from __future__ import annotations

from backend.features.admin.support import *
from backend.shared.button_layout_editor import ButtonEditorContext, show_layout_menu
from backend.shared.ui.message_config_panel import (
    PanelField,
    action_button,
    button_count,
    button_status,
    format_panel,
    mark_configured,
    media_status,
    summarize_text,
)
_SHOW_WELCOME_DETAIL_MENU_THRESHOLD_15 = 15



def format_welcome_text_input_prompt(current_text: str | None) -> str:
    return (
        "🎉 进群欢迎 | 修改文本内容\n\n"
        f"当前的文本内容:{str(current_text or '')}\n\n"
        "替换符\n"
        "└ {member} = 新入群成员名字\n"
        "└ {userid} = 用户id\n"
        "└ {nickname} = 用户昵称\n"
        "└ {group} = 群名称\n\n"
        "👉🏻 现在输入新的文本内容:"
    )


def _welcome_detail_config(item, *, welcome_mode, delete_mode) -> dict:
    title = str(getattr(item, "title", "") or "").strip()
    return {
        "mode_label": "验证后欢迎" if item.welcome_mode == welcome_mode.after_verify.value else "进群欢迎",
        "delete_label": {
            delete_mode.keep.value: "不删除",
            delete_mode.delete_prev.value: "删除上一条",
            delete_mode.seconds.value: f"{int(item.delete_delay_seconds or 15)}秒后删除",
        }.get(item.delete_mode, "15秒后删除"),
        "title": title,
        "title_configured": bool(title and title != "待配置"),
        "cover_configured": bool(getattr(item, "cover_media_file_id", None)),
        "text_configured": bool(str(getattr(item, "text_content", "") or "").strip()),
        "buttons_configured": button_count(getattr(item, "buttons", None)) > 0,
    }


def _welcome_detail_text(item, config: dict) -> str:
    return format_panel(
        "🎉 进群欢迎",
        [
            PanelField("📮", "标题备注", summarize_text(config["title"] if config["title_configured"] else None, limit=80)),
            PanelField("🪩", "欢迎模式", config["mode_label"]),
            PanelField("🏞️", "封面设置", media_status(has_media=config["cover_configured"], media_type=getattr(item, "cover_media_type", None))),
            PanelField("📄", "文本内容", summarize_text(getattr(item, "text_content", None), limit=180)),
            PanelField("⭕", "设置按钮", button_status(getattr(item, "buttons", None))),
        ],
        footer=[
            f"⚙️ 状态: {'✅ 启用' if item.enabled else '❌ 关闭'}",
            f"🕘 延迟删除: {config['delete_label']}",
            "🏖️ 预览: 发送到当前私聊",
        ],
    )


def _welcome_detail_keyboard(item, chat_id: int, welcome_id: int, *, config: dict, welcome_mode, delete_mode) -> InlineKeyboardMarkup:
    is_after_verify = item.welcome_mode == welcome_mode.after_verify.value
    delay_configured = item.delete_mode != delete_mode.seconds.value or int(item.delete_delay_seconds or 15) != _SHOW_WELCOME_DETAIL_MENU_THRESHOLD_15
    rows = [
        [InlineKeyboardButton("⚙️ 状态:", callback_data=f"adm:wel:{chat_id}:toggle:{welcome_id}"), InlineKeyboardButton("✅ 启用" if item.enabled else "启用", callback_data=f"adm:wel:{chat_id}:toggle:{welcome_id}"), InlineKeyboardButton("关闭" if item.enabled else "❌ 关闭", callback_data=f"adm:wel:{chat_id}:toggle:{welcome_id}")],
        [InlineKeyboardButton("🪩 模式:", callback_data=f"adm:wel:{chat_id}:mode:{welcome_id}"), InlineKeyboardButton("✅ 验证后欢迎" if is_after_verify else "验证后欢迎", callback_data=f"adm:wel:{chat_id}:mode:{welcome_id}"), InlineKeyboardButton("进群欢迎" if is_after_verify else "✅ 进群欢迎", callback_data=f"adm:wel:{chat_id}:mode:{welcome_id}")],
        [action_button("标题备注", f"adm:wel:{chat_id}:input:{welcome_id}:title", configured=config["title_configured"]), action_button("设置封面", f"adm:wel:{chat_id}:input:{welcome_id}:cover", configured=config["cover_configured"])],
        [action_button("设置文本", f"adm:wel:{chat_id}:input:{welcome_id}:text", configured=config["text_configured"]), action_button("设置按钮", f"btned:open:welcome:{chat_id}:{welcome_id}", configured=config["buttons_configured"])],
        [InlineKeyboardButton("🏖️ 预览效果", callback_data=f"adm:wel:{chat_id}:preview:{welcome_id}"), InlineKeyboardButton(mark_configured("🕘 延迟删除", delay_configured), callback_data=f"adm:wel:{chat_id}:cycle_delete:{welcome_id}")],
        [InlineKeyboardButton("❌ 删除配置", callback_data=f"adm:wel:{chat_id}:delete:{welcome_id}"), InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:welcome:{chat_id}")],
    ]
    return InlineKeyboardMarkup(rows)


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
        *, welcome_id: int,
    ) -> None:
        from backend.platform.db.schema.models.enums import WelcomeDeleteMode, WelcomeMode
        from backend.features.verification.welcome_service import WelcomeService

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            item = await WelcomeService.get_message(session, chat_id, welcome_id)
            await session.commit()

        config = _welcome_detail_config(item, welcome_mode=WelcomeMode, delete_mode=WelcomeDeleteMode)
        text = _welcome_detail_text(item, config)
        keyboard = _welcome_detail_keyboard(
            item, chat_id, welcome_id, config=config, welcome_mode=WelcomeMode, delete_mode=WelcomeDeleteMode
        )
        await self.message_helper.safe_edit(update, text, reply_markup=keyboard)

    async def _handle_welcome_record_action(self, update, context, chat_id: int, *, op: str, callback_data, service, mode_enum) -> bool:
        db: Database = context.application.bot_data["db"]
        if op == "add":
            async with db.session_factory() as session:
                item = await service.create_message(session, chat_id)
                await session.commit()
            await self._show_welcome_detail_menu(update, context, chat_id, welcome_id=item.id)
            return True
        if op == "detail":
            welcome_id = callback_data.require_int(4, label="welcome_id")
            await self._show_welcome_detail_menu(update, context, chat_id, welcome_id=welcome_id)
            return True
        if op not in {"toggle", "mode", "delete"}:
            return False
        welcome_id = callback_data.require_int(4, label="welcome_id")
        async with db.session_factory() as session:
            if op == "delete":
                await service.delete_message(session, chat_id, welcome_id)
            else:
                item = await service.get_message(session, chat_id, welcome_id)
                if op == "toggle":
                    await service.update_field(session, chat_id, welcome_id, enabled=not item.enabled)
                else:
                    next_mode = mode_enum.on_join.value if item.welcome_mode == mode_enum.after_verify.value else mode_enum.after_verify.value
                    await service.update_field(session, chat_id, welcome_id, welcome_mode=next_mode)
            await session.commit()
        if op == "delete":
            await self._show_welcome_list_menu(update, context, chat_id)
        else:
            await self._show_welcome_detail_menu(update, context, chat_id, welcome_id=welcome_id)
        return True

    async def _preview_welcome(self, update, context, chat_id: int, *, welcome_id: int, service) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            await service.preview(
                context, session, preview_chat_id=update.effective_user.id, chat_id=chat_id,
                welcome_id=welcome_id, member=update.effective_user, user_id=update.effective_user.id,
            )
            await session.commit()
        await answer_callback_query_safely(update, "已发送预览到当前私聊", show_alert=False)

    async def _cycle_welcome_delete(self, update, context, chat_id: int, *, welcome_id: int, service, delete_mode) -> None:
        options = [
            (delete_mode.seconds.value, 15), (delete_mode.seconds.value, 30),
            (delete_mode.seconds.value, 60), (delete_mode.seconds.value, 90),
            (delete_mode.seconds.value, 120), (delete_mode.seconds.value, 300),
            (delete_mode.delete_prev.value, None), (delete_mode.keep.value, None),
        ]
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            item = await service.get_message(session, chat_id, welcome_id)
            current = (item.delete_mode, item.delete_delay_seconds)
            index = options.index(current) if current in options else -1
            next_mode, next_delay = options[(index + 1) % len(options)]
            await service.update_field(
                session, chat_id, welcome_id, delete_mode=next_mode, delete_delay_seconds=next_delay
            )
            await session.commit()
        await self._show_welcome_detail_menu(update, context, chat_id, welcome_id=welcome_id)

    async def _start_welcome_input(self, update, context, chat_id: int, *, callback_data, service, state_enum) -> None:
        welcome_id = callback_data.require_int(4, label="welcome_id")
        field = callback_data.get(5)
        if field == "buttons":
            db: Database = context.application.bot_data["db"]
            async with db.session_factory() as session:
                await show_layout_menu(update, context, ButtonEditorContext("welcome", chat_id, welcome_id), session=session)
                await session.commit()
            return
        state_map = {
            "title": state_enum.welcome_title_input.value,
            "text": state_enum.welcome_text_input.value,
            "cover": state_enum.welcome_cover_input.value,
        }
        state_type = state_map.get(field)
        if state_type is None:
            await answer_callback_query_safely(update, "无效配置项", show_alert=True)
            return
        current_text = await self._load_welcome_text(context, chat_id, welcome_id, service=service) if field == "text" else None
        await self._start_text_input_state(
            context, update.effective_user.id, chat_id, state_type=state_type,
            payload={"target_chat_id": chat_id, "welcome_id": welcome_id},
        )
        prompts = {
            "title": "👉 请输入标题备注：",
            "text": format_welcome_text_input_prompt(current_text),
            "cover": "👉 请发送图片或视频；发送“清空”可移除封面。",
        }
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"adm:wel:{chat_id}:detail:{welcome_id}")]])
        await self.message_helper.safe_edit(update, prompts[field], reply_markup=markup)

    async def _load_welcome_text(self, context, chat_id: int, welcome_id: int, *, service) -> str:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            item = await service.get_message(session, chat_id, welcome_id)
            await session.commit()
        return getattr(item, "text_content", "") or ""

    async def _handle_welcome(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, callback_data: CallbackParser,
    ) -> None:
        from backend.platform.db.schema.models.enums import ConversationStateType, WelcomeDeleteMode, WelcomeMode
        from backend.features.verification.welcome_service import WelcomeService

        op = callback_data.get(3)
        handled = await self._handle_welcome_record_action(
            update, context, chat_id, op=op, callback_data=callback_data,
            service=WelcomeService, mode_enum=WelcomeMode,
        )
        if handled:
            return
        if op == "preview":
            welcome_id = callback_data.require_int(4, label="welcome_id")
            await self._preview_welcome(update, context, chat_id, welcome_id=welcome_id, service=WelcomeService)
            return
        if op == "cycle_delete":
            welcome_id = callback_data.require_int(4, label="welcome_id")
            await self._cycle_welcome_delete(
                update, context, chat_id, welcome_id=welcome_id,
                service=WelcomeService, delete_mode=WelcomeDeleteMode,
            )
            return
        if op == "input":
            await self._start_welcome_input(
                update, context, chat_id, callback_data=callback_data,
                service=WelcomeService, state_enum=ConversationStateType,
            )
            return
        await answer_callback_query_safely(update, "无效欢迎配置操作", show_alert=True)
