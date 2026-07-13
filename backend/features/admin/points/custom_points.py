from __future__ import annotations

from backend.features.admin.support import *


class CustomPointsAdminControllerMixin:
    async def _show_custom_point_confirmation(
        self, update, context, *, db, chat_id: int, type_id: int, operation: str
    ) -> None:
        async with db.session_factory() as session:
            item = await PointsExtendedService.get_custom_point_type(
                session, chat_id, type_id
            )
            await session.commit()
        if item is None:
            await answer_callback_query_safely(
                update, "自定义积分不存在", show_alert=True
            )
            await self._show_custom_points_menu(update, context, chat_id)
            return
        configs = {
            "clear": ("清空积分", "确认后将把此积分类型下所有用户余额清空。", "确认清空"),
            "delete": ("删除积分", "确认后将删除该积分类型及其全部余额记录。", "确认删除"),
        }
        title, warning, button = configs[operation]
        text = "\n".join([
            f"🌐 自定义积分 | {title}", "", f"积分名字：{item.name}", "", warning,
        ])
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                button, callback_data=f"adm:cpt:{chat_id}:{operation}:{type_id}"
            )],
            [InlineKeyboardButton(
                "🔙 返回", callback_data=f"adm:cpt:{chat_id}:detail:{type_id}"
            )],
        ])
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _toggle_custom_point(
        self, update, context, *, db, chat_id: int, callback_data
    ) -> None:
        type_id = callback_data.get_int(4)
        async with db.session_factory() as session:
            item = await PointsExtendedService.get_custom_point_type(
                session, chat_id, type_id
            )
            if item is not None:
                await PointsExtendedService.update_custom_point_type(
                    session, item, enabled=bool(callback_data.get_int(5))
                )
            await session.commit()
        await self._show_custom_point_detail(
            update, context, chat_id, type_id=type_id
        )

    async def _delete_custom_point(
        self, update, context, *, db, chat_id: int, type_id: int
    ) -> None:
        async with db.session_factory() as session:
            item = await PointsExtendedService.get_custom_point_type(
                session, chat_id, type_id
            )
            if item is not None:
                await PointsExtendedService.delete_custom_point_type(session, item)
            await session.commit()
        await self._show_custom_points_menu(update, context, chat_id)

    async def _start_custom_point_input(
        self, update, context, *, db, chat_id: int, op: str, callback_data
    ) -> bool:
        if op == "edit":
            field = callback_data.get(4)
            type_id = callback_data.get_int(5)
            configs = {
                "name": ("custom_points_name_input", "👉 现在输入积分名字：\n\n保存后会自动生成“积分名字排行”指令。"),
                "rank": ("custom_points_rank_input", "👉 现在输入排行指令："),
            }
            config = configs.get(field)
            if config is None:
                await answer_callback_query_safely(update, "无效积分字段", show_alert=True)
                return True
            state_type, prompt = config
            state_data = {"target_chat_id": chat_id, "type_id": type_id}
        elif op == "adjust":
            mode = callback_data.get(4)
            type_id = callback_data.get_int(5)
            if mode not in {"add", "deduct"}:
                await answer_callback_query_safely(update, "无效操作类型", show_alert=True)
                return True
            state_type = "custom_points_adjust_input"
            prompt = "💡已支持命令快捷操作\n\n👉 请输入用户名，用户ID，或转发成员消息到这里："
            state_data = {"target_chat_id": chat_id, "type_id": type_id, "mode": mode}
        else:
            return False
        async with db.session_factory() as session:
            await set_user_state(
                session, chat_id=update.effective_user.id,
                user_id=update.effective_user.id,
                state_type=state_type, state_data=state_data,
            )
            await session.commit()
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton(
                "🔙 返回", callback_data=f"adm:cpt:{chat_id}:detail:{type_id}"
            )]]
        )
        await self.message_helper.safe_edit(update, text=prompt, reply_markup=keyboard)
        return True

    async def _clear_custom_point_balances(
        self, update, context, *, db, chat_id: int, type_id: int
    ) -> None:
        async with db.session_factory() as session:
            item = await PointsExtendedService.get_custom_point_type(
                session, chat_id, type_id
            )
            if item is None:
                await session.commit()
                await answer_callback_query_safely(
                    update, "自定义积分不存在", show_alert=True
                )
            else:
                cleared = await PointsExtendedService.clear_custom_points(
                    session, chat_id=chat_id, type_id=type_id,
                    operator_user_id=update.effective_user.id,
                    reason_note="管理员清空自定义积分",
                )
                await session.commit()
                await answer_callback_query_safely(
                    update, f"已清空 {cleared} 个账户余额"
                )
        await self._show_custom_point_detail(
            update, context, chat_id, type_id=type_id
        )

    async def _export_custom_point_log(
        self, update, *, db, chat_id: int, type_id: int
    ) -> None:
        async with db.session_factory() as session:
            item = await PointsExtendedService.get_custom_point_type(
                session, chat_id, type_id
            )
            logs = await PointsExtendedService.list_custom_point_ledger(
                session, chat_id=chat_id, type_id=type_id, limit=200
            )
            await session.commit()
        if item is None:
            await answer_callback_query_safely(
                update, "自定义积分不存在", show_alert=True
            )
            return
        if update.effective_chat is None:
            return
        output = io.StringIO()
        output.write(f"自定义积分日志导出：{item.name}\n\n")
        if not logs:
            output.write("暂无日志\n")
        for row in logs:
            output.write(
                f"{row.created_at.isoformat()} | user={row.user_id} | delta={row.delta} | "
                f"operator={row.operator_user_id or '-'} | note={row.reason_note or '-'}\n"
            )
        stream = io.BytesIO(output.getvalue().encode("utf-8"))
        stream.name = f"custom_points_{chat_id}_{type_id}.txt"
        await update.effective_chat.send_document(
            document=stream, caption=f"{item.name} 操作日志"
        )
        await answer_callback_query_safely(update, "已导出最近 200 条日志")

    async def _handle_custom_point_navigation(
        self, update, context, *, db, chat_id: int, op: str, callback_data
    ) -> bool:
        if op == "add":
            async with db.session_factory() as session:
                item = await PointsExtendedService.create_custom_point_type(
                    session, chat_id, update.effective_user.id
                )
                await session.commit()
            await self._show_custom_point_detail(
                update, context, chat_id, type_id=item.id
            )
            return True
        if op == "detail":
            await self._show_custom_point_detail(
                update, context, chat_id, type_id=callback_data.get_int(4)
            )
            return True
        if op in {"clear_confirm", "delete_confirm"}:
            await self._show_custom_point_confirmation(
                update, context, db=db, chat_id=chat_id,
                type_id=callback_data.get_int(4),
                operation=op.removesuffix("_confirm"),
            )
            return True
        if op == "toggle":
            await self._toggle_custom_point(
                update, context, db=db, chat_id=chat_id,
                callback_data=callback_data,
            )
            return True
        if op != "delete":
            return False
        await self._delete_custom_point(
            update, context, db=db, chat_id=chat_id,
            type_id=callback_data.get_int(4),
        )
        return True

    async def _handle_custom_points(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int,
        *, callback_data: CallbackParser,
    ) -> None:
        op = callback_data.get(3)
        if op == "noop":
            await answer_callback_query_safely(update, "请点击右侧按钮进行配置")
            return
        db: Database = context.application.bot_data["db"]
        if await self._handle_custom_point_navigation(
            update, context, db=db, chat_id=chat_id,
            op=op, callback_data=callback_data,
        ):
            return
        if await self._start_custom_point_input(
            update, context, db=db, chat_id=chat_id,
            op=op, callback_data=callback_data,
        ):
            return
        if op == "clear":
            await self._clear_custom_point_balances(
                update, context, db=db, chat_id=chat_id,
                type_id=callback_data.get_int(4),
            )
            return
        if op == "export":
            await self._export_custom_point_log(
                update, db=db, chat_id=chat_id, type_id=callback_data.get_int(4)
            )
            return
        await answer_callback_query_safely(
            update, "未识别的自定义积分操作，请刷新页面后重试", show_alert=True
        )
