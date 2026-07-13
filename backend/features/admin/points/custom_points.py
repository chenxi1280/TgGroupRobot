from __future__ import annotations

from backend.features.admin.support import *

class CustomPointsAdminControllerMixin:
    async def _handle_custom_points(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, callback_data: CallbackParser,
    ) -> None:
        op = callback_data.get(3)
        if op == "noop":
            await answer_callback_query_safely(update, "请点击右侧按钮进行配置")
            return
        db: Database = context.application.bot_data["db"]
        if op == "add":
            async with db.session_factory() as session:
                item = await PointsExtendedService.create_custom_point_type(session, chat_id, update.effective_user.id)
                await session.commit()
            await self._show_custom_point_detail(update, context, chat_id, type_id=item.id)
            return
        if op == "detail":
            await self._show_custom_point_detail(update, context, chat_id, type_id=callback_data.get_int(4))
            return
        if op == "clear_confirm":
            type_id = callback_data.get_int(4)
            db: Database = context.application.bot_data["db"]
            async with db.session_factory() as session:
                item = await PointsExtendedService.get_custom_point_type(session, chat_id, type_id)
                await session.commit()
            if item is None:
                await answer_callback_query_safely(update, "自定义积分不存在", show_alert=True)
                await self._show_custom_points_menu(update, context, chat_id)
                return
            await self.message_helper.safe_edit(
                update,
                text="\n".join(
                    [
                        "🌐 自定义积分 | 清空积分",
                        "",
                        f"积分名字：{item.name}",
                        "",
                        "确认后将把此积分类型下所有用户余额清空。",
                    ]
                ),
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("确认清空", callback_data=f"adm:cpt:{chat_id}:clear:{type_id}")],
                        [InlineKeyboardButton("🔙 返回", callback_data=f"adm:cpt:{chat_id}:detail:{type_id}")],
                    ]
                ),
            )
            return
        if op == "toggle":
            type_id = callback_data.get_int(4)
            enabled = bool(callback_data.get_int(5))
            async with db.session_factory() as session:
                item = await PointsExtendedService.get_custom_point_type(session, chat_id, type_id)
                if item is not None:
                    await PointsExtendedService.update_custom_point_type(session, item, enabled=enabled)
                await session.commit()
            await self._show_custom_point_detail(update, context, chat_id, type_id=type_id)
            return
        if op == "delete":
            type_id = callback_data.get_int(4)
            async with db.session_factory() as session:
                item = await PointsExtendedService.get_custom_point_type(session, chat_id, type_id)
                if item is not None:
                    await PointsExtendedService.delete_custom_point_type(session, item)
                await session.commit()
            await self._show_custom_points_menu(update, context, chat_id)
            return
        if op == "delete_confirm":
            type_id = callback_data.get_int(4)
            db: Database = context.application.bot_data["db"]
            async with db.session_factory() as session:
                item = await PointsExtendedService.get_custom_point_type(session, chat_id, type_id)
                await session.commit()
            if item is None:
                await answer_callback_query_safely(update, "自定义积分不存在", show_alert=True)
                await self._show_custom_points_menu(update, context, chat_id)
                return
            await self.message_helper.safe_edit(
                update,
                text="\n".join(
                    [
                        "🌐 自定义积分 | 删除积分",
                        "",
                        f"积分名字：{item.name}",
                        "",
                        "确认后将删除该积分类型及其全部余额记录。",
                    ]
                ),
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("确认删除", callback_data=f"adm:cpt:{chat_id}:delete:{type_id}")],
                        [InlineKeyboardButton("🔙 返回", callback_data=f"adm:cpt:{chat_id}:detail:{type_id}")],
                    ]
                ),
            )
            return
        if op == "edit":
            field = callback_data.get(4)
            type_id = callback_data.get_int(5)
            state_type = "custom_points_name_input" if field == "name" else "custom_points_rank_input"
            async with db.session_factory() as session:
                await set_user_state(
                    session,
                    chat_id=update.effective_user.id,
                    user_id=update.effective_user.id,
                    state_type=state_type,
                    state_data={"target_chat_id": chat_id, "type_id": type_id},
                )
                await session.commit()
            prompt = (
                "👉 现在输入积分名字：\n\n保存后会自动生成“积分名字排行”指令。"
                if field == "name"
                else "👉 现在输入排行指令："
            )
            await self.message_helper.safe_edit(
                update,
                text=prompt,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 返回", callback_data=f"adm:cpt:{chat_id}:detail:{type_id}")]]
                ),
            )
            return
        if op == "adjust":
            mode = callback_data.get(4)
            type_id = callback_data.get_int(5)
            if mode not in {"add", "deduct"}:
                await answer_callback_query_safely(update, "无效操作类型", show_alert=True)
                return
            state_type = "custom_points_adjust_input"
            async with db.session_factory() as session:
                await set_user_state(
                    session,
                    chat_id=update.effective_user.id,
                    user_id=update.effective_user.id,
                    state_type=state_type,
                    state_data={"target_chat_id": chat_id, "type_id": type_id, "mode": mode},
                )
                await session.commit()
            prompt = "💡已支持命令快捷操作\n\n👉 请输入用户名，用户ID，或转发成员消息到这里："
            await self.message_helper.safe_edit(
                update,
                text=prompt,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 返回", callback_data=f"adm:cpt:{chat_id}:detail:{type_id}")]]
                ),
            )
            return
        if op == "clear":
            type_id = callback_data.get_int(4)
            async with db.session_factory() as session:
                item = await PointsExtendedService.get_custom_point_type(session, chat_id, type_id)
                if item is not None:
                    cleared = await PointsExtendedService.clear_custom_points(
                        session,
                        chat_id=chat_id,
                        type_id=type_id,
                        operator_user_id=update.effective_user.id,
                        reason_note="管理员清空自定义积分",
                    )
                    await session.commit()
                    await answer_callback_query_safely(update, f"已清空 {cleared} 个账户余额")
                else:
                    await session.commit()
                    await answer_callback_query_safely(update, "自定义积分不存在", show_alert=True)
            await self._show_custom_point_detail(update, context, chat_id, type_id=type_id)
            return
        if op == "export":
            type_id = callback_data.get_int(4)
            async with db.session_factory() as session:
                item = await PointsExtendedService.get_custom_point_type(session, chat_id, type_id)
                logs = await PointsExtendedService.list_custom_point_ledger(
                    session,
                    chat_id=chat_id,
                    type_id=type_id,
                    limit=200,
                )
                await session.commit()
            if item is None:
                await answer_callback_query_safely(update, "自定义积分不存在", show_alert=True)
                return
            if update.effective_chat is None:
                return
            output = io.StringIO()
            output.write(f"自定义积分日志导出：{item.name}\n\n")
            if not logs:
                output.write("暂无日志\n")
            else:
                for row in logs:
                    output.write(
                        f"{row.created_at.isoformat()} | user={row.user_id} | delta={row.delta} | "
                        f"operator={row.operator_user_id or '-'} | note={row.reason_note or '-'}\n"
                    )
            data = output.getvalue().encode("utf-8")
            stream = io.BytesIO(data)
            stream.name = f"custom_points_{chat_id}_{type_id}.txt"
            await update.effective_chat.send_document(document=stream, caption=f"{item.name} 操作日志")
            await answer_callback_query_safely(update, "已导出最近 200 条日志")
            return
        await answer_callback_query_safely(update, "未识别的自定义积分操作，请刷新页面后重试", show_alert=True)
