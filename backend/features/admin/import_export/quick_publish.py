from __future__ import annotations

from backend.features.admin.support import *


class QuickPublishAdminMixin:
    async def _handle_quick_publish(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        from backend.platform.db.schema.models.enums import ConversationStateType
        from backend.shared.services.permission_service import PermissionPolicyService
        from backend.features.garage.services.garage_forward_service import GarageForwardService

        if update.effective_user is None:
            return

        allowed, error_text = await PermissionPolicyService.require_manage(
            context,
            chat_id,
            update.effective_user.id,
            capability="automation",
        )
        if not allowed:
            if error_text:
                await answer_callback_query_safely(update, error_text, show_alert=True)
            return

        action = callback_data.get(1)
        if action in {None, "home"}:
            await self._show_quick_publish_menu(update, context, chat_id)
            return

        if action == "input":
            field = callback_data.get(3)
            if field not in {"text", "media", "buttons"}:
                await answer_callback_query_safely(update, "未识别的输入类型", show_alert=True)
                return
            await self._start_text_input_state(
                context,
                update.effective_user.id,
                update.effective_user.id,
                ConversationStateType.quick_publish_input.value,
                {"target_chat_id": chat_id, "field": field},
            )
            prompt_map = {
                "text": "请输入要发布的文本内容：",
                "media": "请发送要发布的图片/视频/文件（可带说明文字）：",
                "buttons": "请输入按钮配置（文本|链接，每行多个按钮用 ; 分隔，或直接粘贴 JSON）：",
            }
            await self.message_helper.safe_edit(
                update,
                prompt_map[field],
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"qpub:home:{chat_id}")]]),
            )
            return

        if action == "clear":
            draft = _get_quick_publish_draft(context, chat_id)
            draft.update({"text": "", "media_type": None, "media_file_id": None, "buttons": []})
            await self._show_quick_publish_menu(update, context, chat_id)
            return

        if action == "send":
            draft = _get_quick_publish_draft(context, chat_id)
            text = (draft.get("text") or "").strip()
            media_type = draft.get("media_type")
            media_file_id = draft.get("media_file_id")
            buttons = draft.get("buttons") or []

            if not text and not media_file_id:
                await answer_callback_query_safely(update, "请先设置文本或媒体内容", show_alert=True)
                return

            reply_markup = None
            if buttons:
                try:
                    reply_markup = GarageForwardService.build_button_markup(buttons)
                except ValidationError as exc:
                    await answer_callback_query_safely(update, str(exc), show_alert=True)
                    return

            if media_file_id:
                if media_type == "photo":
                    await context.bot.send_photo(chat_id=chat_id, photo=media_file_id, caption=text or None, reply_markup=reply_markup)
                elif media_type == "video":
                    await context.bot.send_video(chat_id=chat_id, video=media_file_id, caption=text or None, reply_markup=reply_markup)
                elif media_type == "document":
                    await context.bot.send_document(chat_id=chat_id, document=media_file_id, caption=text or None, reply_markup=reply_markup)
                elif media_type == "animation":
                    await context.bot.send_animation(chat_id=chat_id, animation=media_file_id, caption=text or None, reply_markup=reply_markup)
                else:
                    await context.bot.send_message(chat_id=chat_id, text=text or "（无文本）", reply_markup=reply_markup)
            else:
                await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)

            draft.update({"text": "", "media_type": None, "media_file_id": None, "buttons": []})
            await self._show_quick_publish_menu(update, context, chat_id)
            return

        await self._show_quick_publish_menu(update, context, chat_id)

    async def _show_quick_publish_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示快捷发布菜单。"""
        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        chat_title = await self._get_chat_title(db, chat_id)

        draft = _get_quick_publish_draft(context, chat_id)
        text_preview = (draft.get("text") or "").strip()
        if len(text_preview) > 80:
            text_preview = text_preview[:80] + "..."
        media_type = draft.get("media_type")
        media_label = f"已设置（{media_type}）" if media_type else "未设置"
        buttons_count = len(draft.get("buttons") or [])

        lines = [
            "⚡ 快捷发布",
            "",
            f"目标群组：{chat_title}",
            f"文本：{text_preview or '未设置'}",
            f"媒体：{media_label}",
            f"按钮：{buttons_count} 行" if buttons_count else "按钮：未设置",
            "",
            "提示：按钮支持 文本|链接 格式，每行多个按钮用 ; 分隔。",
        ]

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✍️ 设置文本", callback_data=f"qpub:input:{chat_id}:text"),
                InlineKeyboardButton("🖼️ 设置媒体", callback_data=f"qpub:input:{chat_id}:media"),
            ],
            [
                InlineKeyboardButton("🔗 设置按钮", callback_data=f"qpub:input:{chat_id}:buttons"),
                InlineKeyboardButton("🧹 清空草稿", callback_data=f"qpub:clear:{chat_id}"),
            ],
            [InlineKeyboardButton("🚀 立即发送", callback_data=f"qpub:send:{chat_id}")],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, "\n".join(lines), reply_markup=keyboard)
