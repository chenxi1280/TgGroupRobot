from __future__ import annotations

from backend.features.admin.support import *


class GarageForwardAdminMixin:
    async def _show_garage_forward_prompt(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        from backend.features.garage.services.garage_forward_service import GarageForwardService

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            setting = await GarageForwardService.ensure_setting(session, chat_id)
            sources = await GarageForwardService.list_sources(session, chat_id)
            audit_counts = await GarageForwardService.count_audits_by_result(session, chat_id=chat_id)
            await session.commit()

        button_enabled = bool(getattr(setting, "button_template_enabled", False))
        button_configured = bool(getattr(setting, "button_template", None))
        lines = [
            "📡 频道同步",
            "",
            "此功能用来同步频道消息，防止频道被炸。",
            "支持自动同步其他频道的消息到当前群。",
            "",
            f"状态：{'✅ 启动' if setting.enabled else '❌ 关闭'}",
            f"同步模式：{_garage_forward_mode_label(setting.sync_mode)}",
            f"关键词规则：{('、'.join(str(item) for item in (setting.keyword_rules or [])[:8])) if setting.keyword_rules else '未配置'}",
            f"按钮模板：{'✅ 已启用' if button_enabled else '❌ 未启用'} / {'已配置' if button_configured else '未配置'}",
            (
                f"审计统计：✅ 成功 {audit_counts.get('success', 0)}"
                f"｜🟡 跳过 {audit_counts.get('skipped', 0)}"
                f"｜❌ 失败 {audit_counts.get('failed', 0)}"
            ),
            "同步来源：",
        ]
        if sources:
            for item in sources:
                source_name = item.source_name or str(item.source_channel_id)
                lines.append(f"└ {source_name}（{item.source_channel_id}）")
        else:
            lines.append("└ 暂无来源频道")

        keyboard_rows = [
            [
                InlineKeyboardButton("⚙️ 状态：", callback_data=f"gfw:home:{chat_id}"),
                InlineKeyboardButton("✅ 启动" if setting.enabled else "启动", callback_data=f"gfw:toggle:{chat_id}:1"),
                InlineKeyboardButton("关闭" if setting.enabled else "❌ 关闭", callback_data=f"gfw:toggle:{chat_id}:0"),
            ],
            [
                InlineKeyboardButton("⚙️ 模式：", callback_data=f"gfw:home:{chat_id}"),
                InlineKeyboardButton("✅ 全部" if setting.sync_mode == "all" else "全部", callback_data=f"gfw:mode:{chat_id}:all"),
                InlineKeyboardButton(
                    "✅ 仅文本" if setting.sync_mode == "text" else "仅文本",
                    callback_data=f"gfw:mode:{chat_id}:text",
                ),
            ],
            [
                InlineKeyboardButton(
                    "✅ 仅媒体" if setting.sync_mode == "media" else "仅媒体",
                    callback_data=f"gfw:mode:{chat_id}:media",
                ),
                InlineKeyboardButton(
                    "✅ 关键词" if setting.sync_mode == "keyword" else "关键词",
                    callback_data=f"gfw:mode:{chat_id}:keyword",
                ),
            ],
            [
                InlineKeyboardButton("🔘 自动按钮：", callback_data=f"gfw:home:{chat_id}"),
                InlineKeyboardButton("✅ 启用" if button_enabled else "启用", callback_data=f"gfw:btn_toggle:{chat_id}:1"),
                InlineKeyboardButton("关闭" if button_enabled else "❌ 关闭", callback_data=f"gfw:btn_toggle:{chat_id}:0"),
            ],
            [InlineKeyboardButton("✏️ 按钮模板", callback_data=f"gfw:buttons:input:{chat_id}")],
            [InlineKeyboardButton("🧷 更新最近按钮", callback_data=f"gfw:buttons:apply:{chat_id}")],
            [InlineKeyboardButton("✏️ 关键词规则", callback_data=f"gfw:keywords:input:{chat_id}")],
            [InlineKeyboardButton("➕ 添加来源频道", callback_data=f"gfw:source:add:{chat_id}")],
            [InlineKeyboardButton("📜 转发日志", callback_data=f"gfw:audit:{chat_id}:a")],
            [InlineKeyboardButton("⚠️ 失败任务", callback_data=f"gfw:tasks:{chat_id}:a")],
        ]
        for item in sources[:10]:
            keyboard_rows.append(
                [InlineKeyboardButton(f"🗑 移除 {item.source_name or item.source_channel_id}", callback_data=f"gfw:source:remove:{chat_id}:{item.id}")]
            )
        keyboard_rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")])
        keyboard = InlineKeyboardMarkup(keyboard_rows)
        await self.message_helper.safe_edit(update, text="\n".join(lines), reply_markup=keyboard)

    async def _show_garage_forward_audit_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *,
        result: str = "all",
    ) -> None:
        from backend.features.garage.services.garage_forward_service import GarageForwardService

        normalized_result = _normalize_gfw_audit_result(result)
        title_map = {
            "all": "全部",
            "success": "成功",
            "skipped": "跳过",
            "failed": "失败",
        }
        icon_map = {
            "success": "✅",
            "skipped": "🟡",
            "failed": "❌",
        }

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            audits = await GarageForwardService.list_audits(
                session,
                chat_id=chat_id,
                result=normalized_result,
                limit=20,
            )
            counts = await GarageForwardService.count_audits_by_result(session, chat_id=chat_id)
            await session.commit()

        lines = [
            "🔁 车库转发 | 转发日志",
            "",
            f"当前筛选：{title_map.get(normalized_result, '全部')}",
            f"保留策略：自动保留最近 {GarageForwardService.AUDIT_RETENTION_DAYS} 天日志",
            (
                f"📊 全部 {counts.get('all', 0)}"
                f"｜✅ 成功 {counts.get('success', 0)}"
                f"｜🟡 跳过 {counts.get('skipped', 0)}"
                f"｜❌ 失败 {counts.get('failed', 0)}"
            ),
            "",
        ]
        if audits:
            for item in audits:
                timestamp = item.created_at.strftime("%m-%d %H:%M") if item.created_at else "--"
                icon = icon_map.get(item.result, "📄")
                lines.append(
                    f"{icon} #{item.id}｜{timestamp}｜源 {item.source_channel_id}｜消息 {item.source_message_id or '-'}"
                )
                lines.append(f"动作：{item.action}｜结果：{item.result}｜原因：{item.reason or '-'}")
                lines.append("")
        else:
            lines.append("暂无日志记录")

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    ("✅ " if normalized_result == "all" else "") + f"📋 全部({counts.get('all', 0)})",
                    callback_data=f"gfw:audit:{chat_id}:{_gfw_audit_result_code('all')}",
                ),
                InlineKeyboardButton(
                    ("✅ " if normalized_result == "success" else "") + f"✅ 成功({counts.get('success', 0)})",
                    callback_data=f"gfw:audit:{chat_id}:{_gfw_audit_result_code('success')}",
                ),
            ],
            [
                InlineKeyboardButton(
                    ("✅ " if normalized_result == "skipped" else "") + f"🟡 跳过({counts.get('skipped', 0)})",
                    callback_data=f"gfw:audit:{chat_id}:{_gfw_audit_result_code('skipped')}",
                ),
                InlineKeyboardButton(
                    ("✅ " if normalized_result == "failed" else "") + f"❌ 失败({counts.get('failed', 0)})",
                    callback_data=f"gfw:audit:{chat_id}:{_gfw_audit_result_code('failed')}",
                ),
            ],
            [
                InlineKeyboardButton(
                    f"🧹 清理 {GarageForwardService.AUDIT_RETENTION_DAYS} 天前{title_map.get(normalized_result, '全部')}日志",
                    callback_data=f"gfw:audit_cleanup:{chat_id}:{_gfw_audit_result_code(normalized_result)}",
                )
            ],
            [InlineKeyboardButton("🔙 返回", callback_data=f"gfw:home:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, "\n".join(lines), reply_markup=keyboard)

    async def _handle_garage_forward(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        from backend.platform.db.schema.models.enums import ConversationStateType
        from backend.features.garage.services.garage_forward_service import GarageForwardService

        action = callback_data.get(1)
        db: Database = context.application.bot_data["db"]

        if action == "home":
            await self._show_garage_forward_prompt(update, context, chat_id)
            return

        if action == "tasks":
            await self._show_garage_forward_tasks(
                update,
                context,
                chat_id=chat_id,
                status_code=callback_data.get(3) or "a",
            )
            return

        if action == "ops":
            delivery_id = callback_data.get_int_optional(4)
            if delivery_id is None:
                await answer_callback_query_safely(update, "任务编号无效", show_alert=True)
                return
            await self._handle_garage_operation(
                update,
                context,
                chat_id=chat_id,
                action=callback_data.get(3),
                delivery_id=delivery_id,
            )
            return

        if action == "toggle":
            enabled = callback_data.get_int_optional(3)
            if enabled not in {0, 1}:
                await answer_callback_query_safely(update, "无效开关值", show_alert=True)
                return
            async with db.session_factory() as session:
                await GarageForwardService.update_setting(session, chat_id, enabled=bool(enabled))
                await session.commit()
            await self._show_garage_forward_prompt(update, context, chat_id)
            return

        if action == "btn_toggle":
            enabled = callback_data.get_int_optional(3)
            if enabled not in {0, 1}:
                await answer_callback_query_safely(update, "无效开关值", show_alert=True)
                return
            async with db.session_factory() as session:
                await GarageForwardService.update_setting(
                    session,
                    chat_id,
                    button_template_enabled=bool(enabled),
                )
                await session.commit()
            await self._show_garage_forward_prompt(update, context, chat_id)
            return

        if action == "mode":
            mode = callback_data.get(3)
            if mode not in {"all", "text", "media", "keyword"}:
                await answer_callback_query_safely(update, "无效同步模式", show_alert=True)
                return
            async with db.session_factory() as session:
                await GarageForwardService.update_setting(session, chat_id, sync_mode=mode)
                await session.commit()
            await self._show_garage_forward_prompt(update, context, chat_id)
            return

        if action == "keywords" and callback_data.get(2) == "input":
            await self._start_text_input_state(
                context,
                update.effective_user.id,
                chat_id,
                ConversationStateType.garage_forward_keyword_input.value,
                {"target_chat_id": chat_id},
            )
            await self.message_helper.safe_edit(
                update,
                "📡 频道同步 | 关键词规则\n\n👉 请输入关键词，使用空格、逗号或换行分隔：",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"gfw:home:{chat_id}")]]),
            )
            return

        if action == "buttons" and callback_data.get(2) == "input":
            await self._start_text_input_state(
                context,
                update.effective_user.id,
                chat_id,
                ConversationStateType.garage_forward_buttons_input.value,
                {"target_chat_id": chat_id},
            )
            await self.message_helper.safe_edit(
                update,
                (
                    "📡 频道同步 | 按钮模板\n\n"
                    "👉 请输入按钮配置，支持两种格式：\n"
                    "1. 每行一个按钮或多按钮，用 `文本|链接`，同一行多个用 `;` 分隔\n"
                    "2. 直接粘贴 JSON 数组（与定时消息按钮一致）\n\n"
                    "示例：\n"
                    "官网|https://example.com; 进群|https://t.me/example\n"
                    "规则|https://example.com/rules\n\n"
                    "输入 /clear 清空按钮模板。"
                ),
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"gfw:home:{chat_id}")]]),
            )
            return

        if action == "buttons" and callback_data.get(2) == "apply":
            async with db.session_factory() as session:
                setting = await GarageForwardService.ensure_setting(session, chat_id)
                button_template = setting.button_template if setting.button_template_enabled else []
                if not button_template:
                    await session.commit()
                    await answer_callback_query_safely(update, "请先启用并配置按钮模板", show_alert=True)
                    return
                message_maps = await GarageForwardService.list_recent_message_maps(session, chat_id=chat_id, limit=20)
                await session.commit()

            try:
                reply_markup = GarageForwardService.build_button_markup(button_template)
            except ValidationError as exc:
                await answer_callback_query_safely(update, str(exc), show_alert=True)
                return
            success = 0
            failed = 0
            for item in message_maps:
                try:
                    await context.bot.edit_message_reply_markup(
                        chat_id=chat_id,
                        message_id=int(item.target_message_id),
                        reply_markup=reply_markup,
                    )
                    success += 1
                except Exception as exc:
                    log.warning(
                        "garage_forward_buttons_apply_failed",
                        chat_id=chat_id,
                        message_id=int(item.target_message_id),
                        error=str(exc),
                    )
                    failed += 1

            async with db.session_factory() as session:
                await GarageForwardService.append_audit(
                    session,
                    chat_id=chat_id,
                    source_channel_id=0,
                    action="buttons_apply",
                    result="success" if failed == 0 else "failed",
                    reason=f"updated={success},failed={failed}",
                )
                await session.commit()

            await self.message_helper.safe_edit(
                update,
                f"已更新最近 {success + failed} 条同步消息按钮（成功 {success} / 失败 {failed}）。",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"gfw:home:{chat_id}")]]),
            )
            return

        if action == "source" and callback_data.get(2) == "add":
            await self._start_text_input_state(
                context,
                update.effective_user.id,
                chat_id,
                ConversationStateType.garage_forward_source_input.value,
                {"target_chat_id": chat_id},
            )
            await self.message_helper.safe_edit(
                update,
                "📡 频道同步 | 添加来源频道\n\n👉 请输入来源频道 ID、用户名或邀请链接：",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"gfw:home:{chat_id}")]]),
            )
            return

        if action == "source" and callback_data.get(2) == "remove":
            source_id = callback_data.get_int_optional(4)
            if source_id is None:
                await answer_callback_query_safely(update, "无效来源频道", show_alert=True)
                return
            async with db.session_factory() as session:
                deleted = await GarageForwardService.remove_source(session, chat_id=chat_id, source_id=source_id)
                await session.commit()
            if not deleted:
                await answer_callback_query_safely(update, "来源频道不存在", show_alert=True)
                return
            await self._show_garage_forward_prompt(update, context, chat_id)
            return

        if action == "audit":
            result = _normalize_gfw_audit_result(callback_data.get(3) or "a")
            await self._show_garage_forward_audit_menu(update, context, chat_id, result=result)
            return

        if action == "audit_cleanup":
            result = _normalize_gfw_audit_result(callback_data.get(3) or "a")
            purge_result = None if result == "all" else result
            async with db.session_factory() as session:
                deleted = await GarageForwardService.purge_expired_audits(
                    session,
                    chat_id=chat_id,
                    result=purge_result,
                )
                await session.commit()
            log.info(
                "garage_forward_audit_manual_cleanup",
                chat_id=chat_id,
                result=result,
                deleted_count=deleted,
            )
            await answer_callback_query_safely(update, f"已清理 {deleted} 条超期日志。")
            await self._show_garage_forward_audit_menu(update, context, chat_id, result=result)
            return

        await self._show_garage_forward_prompt(update, context, chat_id)
