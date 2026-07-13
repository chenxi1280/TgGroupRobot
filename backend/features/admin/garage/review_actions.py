from __future__ import annotations

import datetime as dt

from backend.features.admin.support import *


class GarageReviewActionsMixin:
    async def _handle_review_setting(
        self, update, context, *, db, service, chat_id: int, action: str, callback_data
    ) -> bool:
        configs = {
            "toggle": ("enabled", {0, 1}, "无效开关值", callback_data.get_int_optional(3)),
            "board": ("auto_refresh_board_enabled", {0, 1}, "无效更新榜单开关值", callback_data.get_int_optional(3)),
            "mode": ("review_mode", {"default", "simple"}, "无效模式", callback_data.get(3)),
            "lookup": ("teacher_lookup_mode", {"exact", "contains", "off"}, "无效查找模式", callback_data.get(3)),
        }
        config = configs.get(action)
        if config is None:
            return False
        field, allowed, error, value = config
        if value not in allowed:
            await answer_callback_query_safely(update, error, show_alert=True)
            return True
        stored_value = bool(value) if action in {"toggle", "board"} else value
        async with db.session_factory() as session:
            await service.update_setting(session, chat_id, **{field: stored_value})
            await session.commit()
        await self._show_car_review_menu(update, context, chat_id)
        return True

    async def _start_review_input(
        self, update, context, *, enum, chat_id: int, action: str, callback_data
    ) -> bool:
        configs = {
            ("submit_cmd", "edit"): (enum.car_review_submit_command_input.value, "💯 车评系统 | 提交报告指令\n\n👉 请输入新的指令："),
            ("rank_cmd", "edit"): (enum.car_review_rank_command_input.value, "💯 车评系统 | 查询排行指令\n\n👉 请输入新的指令："),
            ("approver", "set"): (enum.car_review_approver_input.value, "💯 车评系统 | 指定审核人\n\n👉 请输入用户名或ID，发送“清空”取消："),
            ("template", "edit"): (enum.car_review_template_input.value, "💯 车评系统 | 评价模板\n\n👉 请输入新的模板："),
            ("reward", None): (enum.car_review_reward_points_input.value, "💯 车评系统 | 积分奖励\n\n👉 请输入奖励积分："),
        }
        config = configs.get((action, callback_data.get(2)))
        if config is None and action == "reward":
            config = configs[("reward", None)]
        if config is None:
            return False
        await self._start_text_input_state(
            context, update.effective_user.id, chat_id,
            state_type=config[0], payload={"target_chat_id": chat_id},
        )
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 返回", callback_data=f"crv:home:{chat_id}")]]
        )
        await self.message_helper.safe_edit(update, config[1], reply_markup=keyboard)
        return True

    async def _handle_review_publish_target(
        self, update, context, *, db, service, chat_id: int, callback_data
    ) -> bool:
        if callback_data.get(1) != "publish_target":
            return False
        target = callback_data.get(3)
        if target == "menu":
            await self._show_car_review_publish_menu(update, context, chat_id)
            return True
        fields = {
            "main": "publish_to_main_group", "comment": "publish_to_comment_group",
            "channel": "publish_to_bound_channel",
        }
        field = fields.get(target)
        if field is None:
            await answer_callback_query_safely(update, "无效发布目标", show_alert=True)
            return True
        async with db.session_factory() as session:
            setting = await service.get_setting(session, chat_id)
            await service.update_setting(
                session, chat_id, **{field: not bool(getattr(setting, field))}
            )
            await session.commit()
        await self._show_car_review_publish_menu(update, context, chat_id)
        return True

    async def _handle_review_field_input(
        self, update, context, *, enum, chat_id: int, action: str, callback_data
    ) -> bool:
        if action not in {"field_add", "field_edit"}:
            return False
        payload = {"target_chat_id": chat_id}
        if action == "field_add":
            state_type = enum.car_review_field_add_input.value
            text = "💯 车评系统 | 新增自定义项\n\n👉 请输入“字段键 字段名称”，例如：safe_score 安全感\n新增后请到报告模版添加 {字段键}。"
        else:
            field_id = callback_data.get_int_optional(3)
            if field_id is None:
                await answer_callback_query_safely(update, "字段参数无效", show_alert=True)
                return True
            payload["field_id"] = field_id
            state_type = enum.car_review_field_label_input.value
            text = "💯 车评系统 | 修改自定义项名称\n\n👉 请输入新的字段名称："
        await self._start_text_input_state(
            context, update.effective_user.id, chat_id,
            state_type=state_type, payload=payload,
        )
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 返回", callback_data=f"crv:fields:{chat_id}")]]
        )
        await self.message_helper.safe_edit(update, text, reply_markup=keyboard)
        return True

    async def _handle_review_fields(
        self, update, context, *, db, service, chat_id: int, action: str, callback_data
    ) -> bool:
        if action == "fields":
            await self._show_car_review_fields_menu(update, context, chat_id)
            return True
        if action != "field_tog":
            return False
        field_id = callback_data.get_int_optional(3)
        if field_id is None:
            await answer_callback_query_safely(update, "字段参数无效", show_alert=True)
            return True
        async with db.session_factory() as session:
            item = await service.toggle_custom_field(session, chat_id, field_id)
            await session.commit()
        if item is None:
            await answer_callback_query_safely(update, "字段不存在", show_alert=True)
        await self._show_car_review_fields_menu(update, context, chat_id)
        return True

    async def _review_report_ready(
        self, update, context, session, *, service, chat_id: int,
        report_id: int, status: str,
    ):
        setting = await service.get_setting(session, chat_id)
        report = await service.get_report(session, chat_id, report_id)
        if report is None:
            await session.commit()
            await answer_callback_query_safely(update, "报告不存在", show_alert=True)
            await self._show_car_review_reports_menu(update, context, chat_id, status=status)
            return None
        if report.report_status != "pending":
            await session.commit()
            await answer_callback_query_safely(update, "该报告当前状态不可再次审核", show_alert=True)
            await self._show_car_review_report_detail(
                update, context, chat_id, report_id=report_id, status=status
            )
            return None
        if setting.approver_user_id and update.effective_user.id != setting.approver_user_id:
            approver_is_admin = await is_user_admin(context, chat_id, setting.approver_user_id)
            if approver_is_admin:
                await session.commit()
                await answer_callback_query_safely(update, "仅指定审核人可以处理该报告", show_alert=True)
                await self._show_car_review_report_detail(
                    update, context, chat_id, report_id=report_id, status=status
                )
                return None
            log.warning(
                "car_review_approver_not_admin_allow_admin_fallback", chat_id=chat_id,
                approver_user_id=setting.approver_user_id,
                operator_user_id=update.effective_user.id,
            )
        return setting, report

    async def _publish_approved_review(
        self, update, context, session, *, service, chat_id: int, setting, report
    ) -> int | None:
        from backend.features.group_ops.group_message_handler import _publish_car_review_report
        from backend.platform.db.schema.models.core import TgUser

        teacher = await session.get(TgUser, report.teacher_user_id) if report.teacher_user_id else None
        author = await session.get(TgUser, report.author_user_id) if report.author_user_id else None
        try:
            message_id = await _publish_car_review_report(
                context, chat_id=chat_id, report=report, setting=setting,
                teacher_user=teacher, author_user=author,
            )
        except Exception as exc:
            log.warning(
                "car_review_publish_failed", chat_id=chat_id,
                report_id=report.report_id, error=str(exc),
            )
            return None
        if message_id is None:
            return None
        report.published_message_id = message_id
        report.report_status = "published"
        report.updated_at = dt.datetime.now(dt.UTC)
        if not await self._review_has_audit(
            session, service=service, chat_id=chat_id,
            report_id=report.report_id, action="published",
        ):
            await service.append_audit(
                session, chat_id=chat_id, report_id=report.report_id,
                action="published", operator_user_id=update.effective_user.id,
                payload={"message_id": message_id},
            )
        return message_id

    async def _review_has_audit(
        self, session, *, service, chat_id: int, report_id: int, action: str
    ) -> bool:
        return await service.has_audit_action(
            session, chat_id=chat_id, report_id=report_id, action=action
        )

    async def _refresh_review_board(
        self, update, session, *, service, chat_id: int, setting, report
    ) -> None:
        if not getattr(setting, "auto_refresh_board_enabled", False) or not report.teacher_user_id:
            return
        stats = await service.refresh_teacher_board_info(
            session, chat_id=chat_id, teacher_user_id=report.teacher_user_id
        )
        if await self._review_has_audit(
            session, service=service, chat_id=chat_id,
            report_id=report.report_id, action="board_refreshed",
        ):
            return
        await service.append_audit(
            session, chat_id=chat_id, report_id=report.report_id,
            action="board_refreshed", operator_user_id=update.effective_user.id,
            payload=stats,
        )

    async def _reward_review_author(
        self, update, session, *, service, chat_id: int, setting, report
    ) -> None:
        from backend.features.points.services.points_service import change_points
        from backend.platform.db.schema.models.enums import PointsTxnType

        if not report.author_user_id or setting.reward_points <= 0:
            return
        if await self._review_has_audit(
            session, service=service, chat_id=chat_id,
            report_id=report.report_id, action="rewarded",
        ):
            return
        await change_points(
            session, chat_id, report.author_user_id, amount=setting.reward_points,
            txn_type=PointsTxnType.reward.value, reason="车评审核通过奖励",
        )
        await service.append_audit(
            session, chat_id=chat_id, report_id=report.report_id,
            action="rewarded", operator_user_id=update.effective_user.id,
            payload={"points": setting.reward_points},
        )

    async def _approve_review_report(
        self, update, context, session, *, service, chat_id: int, setting, report
    ) -> str:
        approved = await service.approve_report(
            session, chat_id=chat_id, report_id=report.report_id,
            approver_user_id=update.effective_user.id,
        )
        if approved is None:
            return "报告不存在"
        message_id = await self._publish_approved_review(
            update, context, session, service=service, chat_id=chat_id,
            setting=setting, report=approved,
        )
        await self._refresh_review_board(
            update, session, service=service, chat_id=chat_id,
            setting=setting, report=approved,
        )
        await self._reward_review_author(
            update, session, service=service, chat_id=chat_id,
            setting=setting, report=approved,
        )
        return "报告已通过审核并发布" if message_id is not None else "报告已通过审核，当前未执行自动发布"

    async def _handle_review_report(
        self, update, context, *, db, service, chat_id: int, callback_data
    ) -> None:
        sub = callback_data.get(3)
        report_id = callback_data.get_int_optional(4)
        status = _normalize_car_review_report_status(callback_data.get(5) or "0")
        if report_id is None:
            await answer_callback_query_safely(update, "报告参数无效", show_alert=True)
            await self._show_car_review_reports_menu(update, context, chat_id, status=status)
            return
        if sub == "detail":
            await self._show_car_review_report_detail(
                update, context, chat_id, report_id=report_id, status=status
            )
            return
        async with db.session_factory() as session:
            ready = await self._review_report_ready(
                update, context, session, service=service,
                chat_id=chat_id, report_id=report_id, status=status,
            )
            if ready is None:
                return
            setting, report = ready
            if sub == "approve":
                message = await self._approve_review_report(
                    update, context, session, service=service,
                    chat_id=chat_id, setting=setting, report=report,
                )
            elif sub == "reject":
                rejected = await service.reject_report(
                    session, chat_id=chat_id, report_id=report_id,
                    operator_user_id=update.effective_user.id, reason="管理员驳回",
                )
                message = "报告已驳回" if rejected is not None else "报告不存在"
            else:
                await session.commit()
                await answer_callback_query_safely(update, "暂不支持该审核操作", show_alert=True)
                await self._show_car_review_report_detail(
                    update, context, chat_id, report_id=report_id, status=status
                )
                return
            await session.commit()
        await answer_callback_query_safely(update, message, show_alert=False)
        await self._show_car_review_report_detail(
            update, context, chat_id, report_id=report_id, status=status
        )

    async def _handle_car_review(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *,
        callback_data: CallbackParser,
    ) -> None:
        from backend.features.garage.services.garage_features_service import CarReviewService
        from backend.platform.db.schema.models.enums import ConversationStateType

        action = callback_data.get(1)
        if action == "home":
            await self._show_car_review_menu(update, context, chat_id)
            return
        if await self._handle_review_setting(
            update, context, db=context.application.bot_data["db"], service=CarReviewService,
            chat_id=chat_id, action=action, callback_data=callback_data,
        ):
            return
        if await self._start_review_input(
            update, context, enum=ConversationStateType,
            chat_id=chat_id, action=action, callback_data=callback_data,
        ):
            return
        if await self._handle_review_publish_target(
            update, context, db=context.application.bot_data["db"], service=CarReviewService,
            chat_id=chat_id, callback_data=callback_data,
        ):
            return
        if await self._handle_review_field_input(
            update, context, enum=ConversationStateType,
            chat_id=chat_id, action=action, callback_data=callback_data,
        ):
            return
        if await self._handle_review_fields(
            update, context, db=context.application.bot_data["db"], service=CarReviewService,
            chat_id=chat_id, action=action, callback_data=callback_data,
        ):
            return
        if action == "reports":
            status = _normalize_car_review_report_status(callback_data.get(3) or "0")
            await self._show_car_review_reports_menu(update, context, chat_id, status=status)
            return
        if action == "report":
            await self._handle_review_report(
                update, context, db=context.application.bot_data["db"], service=CarReviewService,
                chat_id=chat_id, callback_data=callback_data,
            )
            return
        await self._show_car_review_menu(update, context, chat_id)
