from __future__ import annotations

from backend.features.admin.support import *

_SHOW_CAR_REVIEW_REPORTS_MENU_THRESHOLD_3 = 3
_REVIEW_PUBLISH_TEXT = (
    "💯 车评系统 | 报告发送类型\n\n"
    "带图发送：只发首图\n"
    "直接发到主群：审核通过后直接发到主群\n"
    "评论车库帖子：审核通过后发到车库评论区\n"
    "发送指定频道：审核通过后发到绑定频道\n\n"
    "支持多选（一份报告发送到多个地方）"
)


def _review_home_labels(setting, approver) -> tuple[str, str, str]:
    mode = "默认" if setting.review_mode == "default" else "简易"
    lookup = {"exact": "精准", "contains": "包含", "off": "关闭"}.get(
        setting.teacher_lookup_mode, setting.teacher_lookup_mode
    )
    approver_label = f"@{approver.username}" if approver and approver.username else None
    return (
        mode,
        lookup,
        approver_label
        or (
            "未指定" if not setting.approver_user_id else str(setting.approver_user_id)
        ),
    )


def _review_home_text(setting, fields, reports, *, approver) -> str:
    mode_label, lookup_label, approver_label = _review_home_labels(setting, approver)
    pending_count = sum(1 for item in reports if item.report_status == "pending")
    enabled_count = sum(1 for item in fields if item.enabled)
    return (
        "💯 车评系统\n\n群友可以对榜上的老师进行评价，审核通过可以自动发布，并给提交者奖励积分。\n\n"
        f"开关：{'✅ 启动' if setting.enabled else '❌ 关闭'}\n模式：{mode_label}\n"
        f"更新榜单：{'✅ 启动' if getattr(setting, 'auto_refresh_board_enabled', False) else '❌ 关闭'}\n"
        f"查车评：{lookup_label}\n提交评价指令：{setting.submit_command}\n"
        f"查询排行指令：{setting.rank_command} / 本周{setting.rank_command} / 本月{setting.rank_command}\n"
        f"报告发布：主群={'✅' if setting.publish_to_main_group else '❌'} / "
        f"评论区={'✅' if setting.publish_to_comment_group else '❌'} / 频道={'✅' if setting.publish_to_bound_channel else '❌'}\n"
        f"积分奖励：加 {setting.reward_points} 积分\n审核人员：{approver_label}\n"
        f"自定义项：{enabled_count}/{len(fields)} 项启用\n最近报告：{len(reports)} 条（待审核 {pending_count} 条）"
    )


def _review_toggle_rows(setting, chat_id: int) -> list[list[InlineKeyboardButton]]:
    board_enabled = getattr(setting, "auto_refresh_board_enabled", False)
    labels = [
        ("⚙️ 开关：", "✅ 启动" if setting.enabled else "启动", "关闭" if setting.enabled else "❌ 关闭", "toggle", "1", "0"),
        ("⚙️ 模式：", "✅ 默认" if setting.review_mode == "default" else "默认", "✅ 简易" if setting.review_mode == "simple" else "简易", "mode", "default", "simple"),
        ("⚙️ 更新榜单：", "✅ 启动" if board_enabled else "启动", "关闭" if board_enabled else "✅ 关闭", "board", "1", "0"),
        ("⚙️ 查车评：", "✅ 精准" if setting.teacher_lookup_mode == "exact" else "精准", "✅ 包含" if setting.teacher_lookup_mode == "contains" else "包含", "lookup", "exact", "contains"),
    ]
    return [
        [
            InlineKeyboardButton(title, callback_data=f"crv:home:{chat_id}"),
            InlineKeyboardButton(first, callback_data=f"crv:{operation}:{chat_id}:{first_value}"),
            InlineKeyboardButton(second, callback_data=f"crv:{operation}:{chat_id}:{second_value}"),
        ]
        for title, first, second, operation, first_value, second_value in labels
    ]


def _review_action_rows(setting, chat_id: int, *, approver_label: str, fields, reports) -> list[list[InlineKeyboardButton]]:
    pending_count = sum(1 for item in reports if item.report_status == "pending")
    enabled_count = sum(1 for item in fields if item.enabled)
    close_label = "✅ 关闭查车评" if setting.teacher_lookup_mode == "off" else "🚫 关闭查车评"
    return [
        [InlineKeyboardButton(close_label, callback_data=f"crv:lookup:{chat_id}:off"), InlineKeyboardButton("💬 提交指令", callback_data=f"crv:submit_cmd:edit:{chat_id}")],
        [InlineKeyboardButton("🥇 排行指令", callback_data=f"crv:rank_cmd:edit:{chat_id}"), InlineKeyboardButton("📤 报告发布", callback_data=f"crv:publish_target:{chat_id}:menu")],
        [InlineKeyboardButton(f"🪙 奖励 {setting.reward_points} 分", callback_data=f"crv:reward:{chat_id}"), InlineKeyboardButton(f"🕵️ 审核：{approver_label}", callback_data=f"crv:approver:set:{chat_id}")],
        [InlineKeyboardButton(f"✏️ 自定义项 {enabled_count}/{len(fields)}", callback_data=f"crv:fields:{chat_id}"), InlineKeyboardButton("📝 报告模版", callback_data=f"crv:template:edit:{chat_id}")],
        [InlineKeyboardButton(f"📂 评价管理 {pending_count}", callback_data=f"crv:reports:{chat_id}"), InlineKeyboardButton("👩 在榜老师", callback_data=f"tsearch:open_course:list:{chat_id}:0")],
        [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
    ]


def _review_home_keyboard(setting, chat_id: int, *, approver_label: str, fields, reports) -> InlineKeyboardMarkup:
    rows = _review_toggle_rows(setting, chat_id)
    rows.extend(_review_action_rows(setting, chat_id, approver_label=approver_label, fields=fields, reports=reports))
    return InlineKeyboardMarkup(rows)


def _review_fields_content(fields, chat_id: int):
    lines = ["💯 车评系统 | 自定义项", "", "当前展示字段会参与默认模式校验，也可在报告模板里用 {字段键} 引用。", "新增自定义项后，请到“报告模版”补上对应占位符。", ""]
    rows: list[list[InlineKeyboardButton]] = []
    for index, item in enumerate(fields, start=1):
        sort_order = getattr(item, "sort_order", index)
        field_id = getattr(item, "id", index)
        lines.append(f"{item.field_label}（键：{item.field_key}｜排序：{sort_order}｜{'✅ 启用' if item.enabled else '❌ 关闭'}）")
        rows.append([
            InlineKeyboardButton(f"{'✅' if item.enabled else '❌'} {item.field_label}", callback_data=f"crv:field_tog:{chat_id}:{field_id}"),
            InlineKeyboardButton("改名", callback_data=f"crv:field_edit:{chat_id}:{field_id}"),
        ])
    if not fields:
        lines.append("暂无自定义项")
    rows.extend([
        [InlineKeyboardButton("➕ 新增自定义项", callback_data=f"crv:field_add:{chat_id}")],
        [InlineKeyboardButton("📝 修改报告模版", callback_data=f"crv:template:edit:{chat_id}")],
        [InlineKeyboardButton("🔙 返回", callback_data=f"crv:home:{chat_id}")],
    ])
    return lines, rows


def _review_report_menu_content(reports, counts, chat_id: int, *, normalized_status: str):
    selected_code = _car_review_report_status_code(normalized_status)
    status_items = [("all", "📋 全部"), ("pending", "🟡 待审核"), ("approved", "✅ 已通过"), ("published", "📢 已发布"), ("rejected", "❌ 已驳回")]
    status_icons = {"pending": "🟡", "approved": "✅", "published": "📢", "rejected": "❌"}
    status_names = {key: title.split(" ", 1)[-1] for key, title in status_items}
    summary = f"📊 全部 {counts.get('all', 0)}｜🟡 待审核 {counts.get('pending', 0)}｜✅ 已通过 {counts.get('approved', 0)}｜📢 已发布 {counts.get('published', 0)}｜❌ 已驳回 {counts.get('rejected', 0)}"
    lines = ["💯 车评系统 | 评价管理", "", f"当前筛选：{status_names.get(normalized_status, '全部')}", summary, ""]
    filter_rows: list[list[InlineKeyboardButton]] = [[], []]
    for index, (item_status, title) in enumerate(status_items):
        label = f"{title}({counts.get(item_status, 0)})"
        label = f"✅ {label}" if item_status == normalized_status else label
        code = _car_review_report_status_code(item_status)
        row_index = 0 if index < _SHOW_CAR_REVIEW_REPORTS_MENU_THRESHOLD_3 else 1
        filter_rows[row_index].append(InlineKeyboardButton(label, callback_data=f"crv:reports:{chat_id}:{code}"))
    rows = list(filter_rows)
    for report in reports:
        teacher = report.teacher_user_id or "未识别"
        lines.extend([f"报告#{report.report_id}｜老师 {teacher}", f"状态：{report.report_status}｜提交人：{report.author_user_id or '未知'}", ""])
        icon = status_icons.get(report.report_status, "📄")
        rows.append([InlineKeyboardButton(f"{icon} 报告#{report.report_id}｜老师 {teacher}", callback_data=f"crv:report:{chat_id}:detail:{report.report_id}:{selected_code}")])
    if not reports:
        lines.append("0 条数据，第 1 页/共 1 页")
    rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"crv:home:{chat_id}")])
    return lines, rows


def _review_report_detail_content(report, logs) -> list[str]:
    status_text = {"pending": "🟡 待审核", "approved": "✅ 已通过", "published": "📢 已发布", "rejected": "❌ 已驳回"}
    log_lines = ["审核日志："]
    for item in logs:
        timestamp = item.created_at.strftime("%m-%d %H:%M") if item.created_at else "--"
        log_lines.append(f"- {timestamp}｜{item.action}｜操作人 {item.operator_user_id or '-'}")
    if not logs:
        log_lines.append("- 暂无日志")
    return [
        "💯 车评系统 | 报告详情", "", f"报告编号：{report.report_id}",
        f"老师用户：{report.teacher_user_id or '未识别'}", f"提交用户：{report.author_user_id or '未知'}",
        f"当前状态：{status_text.get(report.report_status, report.report_status)}",
        f"综合评分：{(report.scores or {}).get('total_score', '-')}",
        f"评价内容：{(report.review_text or '无').strip()[:200]}", "", *log_lines,
    ]


def _review_report_detail_keyboard(report, chat_id: int, status_code: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if report.report_status == "pending":
        rows.append([
            InlineKeyboardButton("✅ 审核通过", callback_data=f"crv:report:{chat_id}:approve:{report.report_id}:{status_code}"),
            InlineKeyboardButton("❌ 驳回", callback_data=f"crv:report:{chat_id}:reject:{report.report_id}:{status_code}"),
        ])
    rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"crv:reports:{chat_id}:{status_code}")])
    return InlineKeyboardMarkup(rows)


class GarageReviewViewsMixin:
    async def _show_car_review_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        from backend.features.garage.services.garage_features_service import (
            CarReviewService,
        )
        from backend.platform.db.schema.models.core import TgUser

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            setting = await CarReviewService.get_setting(session, chat_id)
            fields = await CarReviewService.list_custom_fields(session, chat_id)
            reports = await CarReviewService.list_recent_reports(
                session, chat_id, limit=20
            )
            approver = (
                await session.get(TgUser, setting.approver_user_id)
                if setting.approver_user_id
                else None
            )
            await session.commit()

        _, _, approver_label = _review_home_labels(setting, approver)
        text = _review_home_text(setting, fields, reports, approver=approver)
        keyboard = _review_home_keyboard(
            setting,
            chat_id,
            approver_label=approver_label,
            fields=fields,
            reports=reports,
        )
        await self.message_helper.safe_edit(update, text, reply_markup=keyboard)

    async def _show_car_review_fields_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        from backend.features.garage.services.garage_features_service import (
            CarReviewService,
        )

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            fields = await CarReviewService.list_custom_fields(session, chat_id)
            await session.commit()

        lines, keyboard_rows = _review_fields_content(fields, chat_id)
        await self.message_helper.safe_edit(
            update,
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(keyboard_rows),
        )

    async def _show_car_review_reports_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *,
        status: str = "all",
    ) -> None:
        from backend.features.garage.services.garage_features_service import (
            CarReviewService,
        )

        normalized_status = _normalize_car_review_report_status(status)
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            reports = await CarReviewService.list_reports(
                session, chat_id, status=normalized_status, limit=10
            )
            counts = await CarReviewService.count_reports_by_status(session, chat_id)
            await session.commit()
        lines, keyboard_rows = _review_report_menu_content(
            reports,
            counts,
            chat_id,
            normalized_status=normalized_status,
        )
        await self.message_helper.safe_edit(
            update,
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(keyboard_rows),
        )

    async def _show_car_review_report_detail(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *,
        report_id: int,
        status: str = "all",
    ) -> None:
        from backend.features.garage.services.garage_features_service import (
            CarReviewService,
        )

        normalized_status = _normalize_car_review_report_status(status)
        status_code = _car_review_report_status_code(normalized_status)
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            report = await CarReviewService.get_report(session, chat_id, report_id)
            logs = await CarReviewService.list_audit_logs(
                session, chat_id=chat_id, report_id=report_id, limit=8
            )
            await session.commit()
        if report is None:
            await answer_callback_query_safely(update, "报告不存在", show_alert=True)
            await self._show_car_review_reports_menu(
                update, context, chat_id, status=normalized_status
            )
            return
        lines = _review_report_detail_content(report, logs)
        keyboard = _review_report_detail_keyboard(report, chat_id, status_code)
        await self.message_helper.safe_edit(update, "\n".join(lines), reply_markup=keyboard)

    async def _show_car_review_publish_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        from backend.features.garage.services.garage_features_service import (
            CarReviewService,
        )

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            setting = await CarReviewService.get_setting(session, chat_id)
            await session.commit()

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🖼️ 首图发送：默认开启", callback_data=f"crv:home:{chat_id}"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        ("✅ " if setting.publish_to_main_group else "")
                        + "直接发到主群",
                        callback_data=f"crv:publish_target:{chat_id}:main",
                    )
                ],
                [
                    InlineKeyboardButton(
                        ("✅ " if setting.publish_to_comment_group else "")
                        + "评论车库帖子",
                        callback_data=f"crv:publish_target:{chat_id}:comment",
                    )
                ],
                [
                    InlineKeyboardButton(
                        ("✅ " if setting.publish_to_bound_channel else "")
                        + "发送指定频道",
                        callback_data=f"crv:publish_target:{chat_id}:channel",
                    )
                ],
                [InlineKeyboardButton("🔙 返回", callback_data=f"crv:home:{chat_id}")],
            ]
        )
        await self.message_helper.safe_edit(update, _REVIEW_PUBLISH_TEXT, reply_markup=keyboard)
