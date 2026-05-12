from __future__ import annotations

import datetime as dt

from backend.features.admin.support import *


class GarageReviewActionsMixin:
    async def _handle_car_review(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        from backend.features.garage.services.garage_features_service import CarReviewService
        from backend.features.group_ops.group_message_handler import _publish_car_review_report
        from backend.features.points.services.points_service import change_points
        from backend.platform.db.schema.models.core import TgUser
        from backend.platform.db.schema.models.enums import ConversationStateType, PointsTxnType

        action = callback_data.get(1)
        db: Database = context.application.bot_data["db"]

        if action == "home":
            await self._show_car_review_menu(update, context, chat_id)
            return
        if action == "toggle":
            enabled = callback_data.get_int_optional(3)
            if enabled not in {0, 1}:
                await answer_callback_query_safely(update, "无效开关值", show_alert=True)
                return
            async with db.session_factory() as session:
                await CarReviewService.update_setting(session, chat_id, enabled=bool(enabled))
                await session.commit()
            await self._show_car_review_menu(update, context, chat_id)
            return
        if action == "mode":
            mode = callback_data.get(3)
            if mode not in {"default", "simple"}:
                await answer_callback_query_safely(update, "无效模式", show_alert=True)
                return
            async with db.session_factory() as session:
                await CarReviewService.update_setting(session, chat_id, review_mode=mode)
                await session.commit()
            await self._show_car_review_menu(update, context, chat_id)
            return
        if action == "board":
            enabled = callback_data.get_int_optional(3)
            if enabled not in {0, 1}:
                await answer_callback_query_safely(update, "无效更新榜单开关值", show_alert=True)
                return
            async with db.session_factory() as session:
                await CarReviewService.update_setting(session, chat_id, auto_refresh_board_enabled=bool(enabled))
                await session.commit()
            await self._show_car_review_menu(update, context, chat_id)
            return
        if action == "lookup":
            mode = callback_data.get(3)
            if mode not in {"exact", "contains", "off"}:
                await answer_callback_query_safely(update, "无效查找模式", show_alert=True)
                return
            async with db.session_factory() as session:
                await CarReviewService.update_setting(session, chat_id, teacher_lookup_mode=mode)
                await session.commit()
            await self._show_car_review_menu(update, context, chat_id)
            return
        if action == "submit_cmd" and callback_data.get(2) == "edit":
            await self._start_text_input_state(context, update.effective_user.id, chat_id, ConversationStateType.car_review_submit_command_input.value, {"target_chat_id": chat_id})
            await self.message_helper.safe_edit(update, "💯 车评系统 | 提交报告指令\n\n👉 请输入新的指令：", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"crv:home:{chat_id}")]]))
            return
        if action == "rank_cmd" and callback_data.get(2) == "edit":
            await self._start_text_input_state(context, update.effective_user.id, chat_id, ConversationStateType.car_review_rank_command_input.value, {"target_chat_id": chat_id})
            await self.message_helper.safe_edit(update, "💯 车评系统 | 查询排行指令\n\n👉 请输入新的指令：", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"crv:home:{chat_id}")]]))
            return
        if action == "publish_target":
            target = callback_data.get(3)
            if target == "menu":
                await self._show_car_review_publish_menu(update, context, chat_id)
                return
            field_map = {
                "main": "publish_to_main_group",
                "comment": "publish_to_comment_group",
                "channel": "publish_to_bound_channel",
            }
            setting_field = field_map.get(target)
            if setting_field is None:
                await answer_callback_query_safely(update, "无效发布目标", show_alert=True)
                return
            async with db.session_factory() as session:
                setting = await CarReviewService.get_setting(session, chat_id)
                await CarReviewService.update_setting(session, chat_id, **{setting_field: not bool(getattr(setting, setting_field))})
                await session.commit()
            await self._show_car_review_publish_menu(update, context, chat_id)
            return
        if action == "approver" and callback_data.get(2) == "set":
            await self._start_text_input_state(context, update.effective_user.id, chat_id, ConversationStateType.car_review_approver_input.value, {"target_chat_id": chat_id})
            await self.message_helper.safe_edit(update, "💯 车评系统 | 指定审核人\n\n👉 请输入用户名或ID，发送“清空”取消：", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"crv:home:{chat_id}")]]))
            return
        if action == "template" and callback_data.get(2) == "edit":
            await self._start_text_input_state(context, update.effective_user.id, chat_id, ConversationStateType.car_review_template_input.value, {"target_chat_id": chat_id})
            await self.message_helper.safe_edit(update, "💯 车评系统 | 评价模板\n\n👉 请输入新的模板：", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"crv:home:{chat_id}")]]))
            return
        if action == "reward":
            await self._start_text_input_state(context, update.effective_user.id, chat_id, ConversationStateType.car_review_reward_points_input.value, {"target_chat_id": chat_id})
            await self.message_helper.safe_edit(update, "💯 车评系统 | 积分奖励\n\n👉 请输入奖励积分：", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"crv:home:{chat_id}")]]))
            return
        if action == "fields":
            await self._show_car_review_fields_menu(update, context, chat_id)
            return
        if action == "field_add":
            await self._start_text_input_state(
                context,
                update.effective_user.id,
                chat_id,
                ConversationStateType.car_review_field_add_input.value,
                {"target_chat_id": chat_id},
            )
            await self.message_helper.safe_edit(
                update,
                "💯 车评系统 | 新增自定义项\n\n👉 请输入“字段键 字段名称”，例如：safe_score 安全感\n新增后请到报告模版添加 {字段键}。",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"crv:fields:{chat_id}")]]),
            )
            return
        if action == "field_edit":
            field_id = callback_data.get_int_optional(3)
            if field_id is None:
                await answer_callback_query_safely(update, "字段参数无效", show_alert=True)
                return
            await self._start_text_input_state(
                context,
                update.effective_user.id,
                chat_id,
                ConversationStateType.car_review_field_label_input.value,
                {"target_chat_id": chat_id, "field_id": field_id},
            )
            await self.message_helper.safe_edit(
                update,
                "💯 车评系统 | 修改自定义项名称\n\n👉 请输入新的字段名称：",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"crv:fields:{chat_id}")]]),
            )
            return
        if action == "field_tog":
            field_id = callback_data.get_int_optional(3)
            if field_id is None:
                await answer_callback_query_safely(update, "字段参数无效", show_alert=True)
                return
            async with db.session_factory() as session:
                item = await CarReviewService.toggle_custom_field(session, chat_id, field_id)
                await session.commit()
            if item is None:
                await answer_callback_query_safely(update, "字段不存在", show_alert=True)
            await self._show_car_review_fields_menu(update, context, chat_id)
            return
        if action == "reports":
            status = _normalize_car_review_report_status(callback_data.get(3) or "0")
            await self._show_car_review_reports_menu(update, context, chat_id, status=status)
            return
        if action == "report":
            sub = callback_data.get(3)
            report_id = callback_data.get_int_optional(4)
            status = _normalize_car_review_report_status(callback_data.get(5) or "0")
            if report_id is None:
                await answer_callback_query_safely(update, "报告参数无效", show_alert=True)
                await self._show_car_review_reports_menu(update, context, chat_id, status=status)
                return
            if sub == "detail":
                await self._show_car_review_report_detail(update, context, chat_id, report_id, status=status)
                return
            async with db.session_factory() as session:
                setting = await CarReviewService.get_setting(session, chat_id)
                current = await CarReviewService.get_report(session, chat_id, report_id)
                if current is None:
                    await session.commit()
                    await answer_callback_query_safely(update, "报告不存在", show_alert=True)
                    await self._show_car_review_reports_menu(update, context, chat_id, status=status)
                    return
                if current.report_status != "pending":
                    await session.commit()
                    await answer_callback_query_safely(update, "该报告当前状态不可再次审核", show_alert=True)
                    await self._show_car_review_report_detail(update, context, chat_id, report_id, status=status)
                    return
                if setting.approver_user_id and update.effective_user.id != setting.approver_user_id:
                    approver_is_admin = await is_user_admin(context, chat_id, setting.approver_user_id)
                    if not approver_is_admin:
                        log.warning(
                            "car_review_approver_not_admin_allow_admin_fallback",
                            chat_id=chat_id,
                            approver_user_id=setting.approver_user_id,
                            operator_user_id=update.effective_user.id,
                        )
                    else:
                        await session.commit()
                        await answer_callback_query_safely(update, "仅指定审核人可以处理该报告", show_alert=True)
                        await self._show_car_review_report_detail(update, context, chat_id, report_id, status=status)
                        return
                if sub == "approve":
                    report = await CarReviewService.approve_report(
                        session,
                        chat_id=chat_id,
                        report_id=report_id,
                        approver_user_id=update.effective_user.id,
                    )
                    message = "报告已通过审核" if report is not None else "报告不存在"
                    if report is not None:
                        teacher_row = await session.get(TgUser, report.teacher_user_id) if report.teacher_user_id else None
                        author_row = await session.get(TgUser, report.author_user_id) if report.author_user_id else None
                        published_message_id: int | None = None
                        try:
                            published_message_id = await _publish_car_review_report(
                                context,
                                chat_id=chat_id,
                                report=report,
                                setting=setting,
                                teacher_user=teacher_row,
                                author_user=author_row,
                            )
                        except Exception as exc:
                            log.warning(
                                "car_review_publish_failed",
                                chat_id=chat_id,
                                report_id=report.report_id,
                                error=str(exc),
                            )
                        if published_message_id is not None:
                            report.published_message_id = published_message_id
                            report.report_status = "published"
                            report.updated_at = dt.datetime.now(dt.UTC)
                            if not await CarReviewService.has_audit_action(
                                session,
                                chat_id=chat_id,
                                report_id=report.report_id,
                                action="published",
                            ):
                                await CarReviewService.append_audit(
                                    session,
                                    chat_id=chat_id,
                                    report_id=report.report_id,
                                    action="published",
                                    operator_user_id=update.effective_user.id,
                                    payload={"message_id": published_message_id},
                                )
                            message = "报告已通过审核并发布"
                        if getattr(setting, "auto_refresh_board_enabled", False) and report.teacher_user_id:
                            stats = await CarReviewService.refresh_teacher_board_info(
                                session,
                                chat_id=chat_id,
                                teacher_user_id=report.teacher_user_id,
                            )
                            if not await CarReviewService.has_audit_action(
                                session,
                                chat_id=chat_id,
                                report_id=report.report_id,
                                action="board_refreshed",
                            ):
                                await CarReviewService.append_audit(
                                    session,
                                    chat_id=chat_id,
                                    report_id=report.report_id,
                                    action="board_refreshed",
                                    operator_user_id=update.effective_user.id,
                                    payload=stats,
                                )
                        if (
                            report.author_user_id
                            and setting.reward_points > 0
                            and not await CarReviewService.has_audit_action(
                                session,
                                chat_id=chat_id,
                                report_id=report.report_id,
                                action="rewarded",
                            )
                        ):
                            await change_points(
                                session,
                                chat_id,
                                report.author_user_id,
                                setting.reward_points,
                                PointsTxnType.reward.value,
                                reason="车评审核通过奖励",
                            )
                            await CarReviewService.append_audit(
                                session,
                                chat_id=chat_id,
                                report_id=report.report_id,
                                action="rewarded",
                                operator_user_id=update.effective_user.id,
                                payload={"points": setting.reward_points},
                            )
                        elif published_message_id is None:
                            message = "报告已通过审核，当前未执行自动发布"
                elif sub == "reject":
                    report = await CarReviewService.reject_report(
                        session,
                        chat_id=chat_id,
                        report_id=report_id,
                        operator_user_id=update.effective_user.id,
                        reason="管理员驳回",
                    )
                    message = "报告已驳回" if report is not None else "报告不存在"
                else:
                    await session.commit()
                    await answer_callback_query_safely(update, "暂不支持该审核操作", show_alert=True)
                    await self._show_car_review_report_detail(update, context, chat_id, report_id, status=status)
                    return
                await session.commit()
            await answer_callback_query_safely(update, message, show_alert=False)
            await self._show_car_review_report_detail(update, context, chat_id, report_id, status=status)
            return
        await self._show_car_review_menu(update, context, chat_id)
