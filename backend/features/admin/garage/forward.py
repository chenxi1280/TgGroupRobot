from __future__ import annotations

from backend.features.admin.garage.forward_presenters import (
    build_forward_audit_keyboard,
    build_forward_home_keyboard,
    format_forward_audits,
    format_forward_home,
)
from backend.features.admin.support import *


class GarageForwardAdminMixin:
    async def _show_garage_forward_prompt(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        from backend.features.garage.services.garage_forward_service import (
            GarageForwardService,
        )

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            setting = await GarageForwardService.ensure_setting(session, chat_id)
            sources = await GarageForwardService.list_sources(session, chat_id)
            audit_counts = await GarageForwardService.count_audits_by_result(
                session, chat_id=chat_id
            )
            await session.commit()

        text = format_forward_home(setting, sources, audit_counts)
        keyboard = build_forward_home_keyboard(setting, sources, chat_id)
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_garage_forward_audit_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *,
        result: str = "all",
    ) -> None:
        from backend.features.garage.services.garage_forward_service import (
            GarageForwardService,
        )

        normalized_result = _normalize_gfw_audit_result(result)
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            audits = await GarageForwardService.list_audits(
                session,
                chat_id=chat_id,
                result=normalized_result,
                limit=20,
            )
            counts = await GarageForwardService.count_audits_by_result(
                session, chat_id=chat_id
            )
            await session.commit()

        retention_days = GarageForwardService.AUDIT_RETENTION_DAYS
        text = format_forward_audits(
            audits, counts, normalized_result, retention_days=retention_days
        )
        keyboard = build_forward_audit_keyboard(
            counts, normalized_result, chat_id, retention_days=retention_days
        )
        await self.message_helper.safe_edit(update, text, reply_markup=keyboard)

    async def _handle_garage_forward(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *,
        callback_data: CallbackParser,
    ) -> None:
        from backend.platform.db.schema.models.enums import ConversationStateType
        from backend.features.garage.services.garage_forward_service import (
            GarageForwardService,
        )

        action = callback_data.get(1)
        db: Database = context.application.bot_data["db"]
        if await self._handle_forward_navigation(
            update, context, chat_id=chat_id, action=action, callback_data=callback_data
        ):
            return
        if await self._handle_forward_setting(
            update,
            context,
            db=db,
            service=GarageForwardService,
            chat_id=chat_id,
            action=action,
            callback_data=callback_data,
        ):
            return
        if await self._handle_forward_input(
            update,
            context,
            enum=ConversationStateType,
            chat_id=chat_id,
            action=action,
            callback_data=callback_data,
        ):
            return
        if await self._handle_forward_secondary(
            update,
            context,
            db=db,
            service=GarageForwardService,
            chat_id=chat_id,
            action=action,
            callback_data=callback_data,
        ):
            return
        await self._show_garage_forward_prompt(update, context, chat_id)

    async def _handle_forward_secondary(
        self, update, context, *, db, service, chat_id: int, action: str, callback_data
    ) -> bool:
        if action == "buttons" and callback_data.get(2) == "apply":
            await self._apply_forward_buttons(
                update, context, db=db, service=service, chat_id=chat_id
            )
            return True
        if action == "source" and callback_data.get(2) == "remove":
            await self._remove_forward_source(
                update,
                context,
                db=db,
                service=service,
                chat_id=chat_id,
                callback_data=callback_data,
            )
            return True
        return await self._handle_forward_audit(
            update,
            context,
            db=db,
            service=service,
            chat_id=chat_id,
            action=action,
            callback_data=callback_data,
        )

    async def _handle_forward_navigation(
        self, update, context, *, chat_id: int, action: str, callback_data
    ) -> bool:
        if action == "home":
            await self._show_garage_forward_prompt(update, context, chat_id)
            return True
        if action == "tasks":
            await self._show_garage_forward_tasks(
                update,
                context,
                chat_id=chat_id,
                status_code=callback_data.get(3) or "a",
            )
            return True
        if action != "ops":
            return False
        delivery_id = callback_data.get_int_optional(4)
        if delivery_id is None:
            await answer_callback_query_safely(update, "任务编号无效", show_alert=True)
            return True
        await self._handle_garage_operation(
            update,
            context,
            chat_id=chat_id,
            action=callback_data.get(3),
            delivery_id=delivery_id,
        )
        return True

    async def _handle_forward_setting(
        self, update, context, *, db, service, chat_id: int, action: str, callback_data
    ) -> bool:
        if action in {"toggle", "btn_toggle"}:
            enabled = callback_data.get_int_optional(3)
            if enabled not in {0, 1}:
                await answer_callback_query_safely(
                    update, "无效开关值", show_alert=True
                )
                return True
            field = "enabled" if action == "toggle" else "button_template_enabled"
            values = {field: bool(enabled)}
        elif action == "mode":
            mode = callback_data.get(3)
            if mode not in {"all", "text", "media", "keyword"}:
                await answer_callback_query_safely(
                    update, "无效同步模式", show_alert=True
                )
                return True
            values = {"sync_mode": mode}
        else:
            return False
        async with db.session_factory() as session:
            await service.update_setting(session, chat_id, **values)
            await session.commit()
        await self._show_garage_forward_prompt(update, context, chat_id)
        return True

    async def _handle_forward_input(
        self, update, context, *, enum, chat_id: int, action: str, callback_data
    ) -> bool:
        configs = {
            ("keywords", "input"): (
                enum.garage_forward_keyword_input.value,
                "📡 频道同步 | 关键词规则\n\n👉 请输入关键词，使用空格、逗号或换行分隔：",
            ),
            ("buttons", "input"): (
                enum.garage_forward_buttons_input.value,
                _garage_button_input_prompt(),
            ),
            ("source", "add"): (
                enum.garage_forward_source_input.value,
                "📡 频道同步 | 添加来源频道\n\n👉 请输入来源频道 ID、用户名或邀请链接：",
            ),
        }
        config = configs.get((action, callback_data.get(2)))
        if config is None:
            return False
        await self._start_text_input_state(
            context,
            update.effective_user.id,
            chat_id,
            state_type=config[0],
            payload={"target_chat_id": chat_id},
        )
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 返回", callback_data=f"gfw:home:{chat_id}")]]
        )
        await self.message_helper.safe_edit(update, config[1], reply_markup=keyboard)
        return True

    async def _apply_forward_buttons(
        self, update, context, *, db, service, chat_id: int
    ) -> None:
        async with db.session_factory() as session:
            setting = await service.ensure_setting(session, chat_id)
            template = (
                setting.button_template if setting.button_template_enabled else []
            )
            message_maps = (
                await service.list_recent_message_maps(
                    session, chat_id=chat_id, limit=20
                )
                if template
                else []
            )
            await session.commit()
        if not template:
            await answer_callback_query_safely(
                update, "请先启用并配置按钮模板", show_alert=True
            )
            return
        try:
            reply_markup = service.build_button_markup(template)
        except ValidationError as exc:
            await answer_callback_query_safely(update, str(exc), show_alert=True)
            return
        success, failed = await self._update_forward_buttons(
            context, message_maps, chat_id=chat_id, reply_markup=reply_markup
        )
        await self._record_forward_button_audit(
            db, service, chat_id=chat_id, success=success, failed=failed
        )
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 返回", callback_data=f"gfw:home:{chat_id}")]]
        )
        text = f"已更新最近 {success + failed} 条同步消息按钮（成功 {success} / 失败 {failed}）。"
        await self.message_helper.safe_edit(update, text, reply_markup=keyboard)

    async def _update_forward_buttons(
        self, context, message_maps, *, chat_id: int, reply_markup
    ) -> tuple[int, int]:
        success = failed = 0
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
        return success, failed

    async def _record_forward_button_audit(
        self, db, service, *, chat_id: int, success: int, failed: int
    ) -> None:
        async with db.session_factory() as session:
            await service.append_audit(
                session,
                chat_id=chat_id,
                source_channel_id=0,
                action="buttons_apply",
                result="success" if failed == 0 else "failed",
                reason=f"updated={success},failed={failed}",
            )
            await session.commit()

    async def _remove_forward_source(
        self, update, context, *, db, service, chat_id: int, callback_data
    ) -> None:
        source_id = callback_data.get_int_optional(4)
        if source_id is None:
            await answer_callback_query_safely(update, "无效来源频道", show_alert=True)
            return
        async with db.session_factory() as session:
            deleted = await service.remove_source(
                session, chat_id=chat_id, source_id=source_id
            )
            await session.commit()
        if not deleted:
            await answer_callback_query_safely(
                update, "来源频道不存在", show_alert=True
            )
            return
        await self._show_garage_forward_prompt(update, context, chat_id)

    async def _handle_forward_audit(
        self, update, context, *, db, service, chat_id: int, action: str, callback_data
    ) -> bool:
        if action not in {"audit", "audit_cleanup"}:
            return False
        result = _normalize_gfw_audit_result(callback_data.get(3) or "a")
        if action == "audit_cleanup":
            purge_result = None if result == "all" else result
            async with db.session_factory() as session:
                deleted = await service.purge_expired_audits(
                    session, chat_id=chat_id, result=purge_result
                )
                await session.commit()
            log.info(
                "garage_forward_audit_manual_cleanup",
                chat_id=chat_id,
                result=result,
                deleted_count=deleted,
            )
            await answer_callback_query_safely(update, f"已清理 {deleted} 条超期日志。")
        await self._show_garage_forward_audit_menu(
            update, context, chat_id, result=result
        )
        return True


def _garage_button_input_prompt() -> str:
    return (
        "📡 频道同步 | 按钮模板\n\n"
        "👉 请输入按钮配置，支持两种格式：\n"
        "1. 每行一个按钮或多按钮，用 `文本|链接`，同一行多个用 `;` 分隔\n"
        "2. 直接粘贴 JSON 数组（与定时消息按钮一致）\n\n"
        "示例：\n"
        "官网|https://example.com; 进群|https://t.me/example\n"
        "规则|https://example.com/rules\n\n"
        "输入 /clear 清空按钮模板。"
    )
