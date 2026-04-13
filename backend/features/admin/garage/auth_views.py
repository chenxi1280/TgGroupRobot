from __future__ import annotations

from backend.features.admin.support import *


class GarageAuthViewsMixin:
    async def _show_garage_auth_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        from backend.features.garage.services.garage_features_service import GarageAuthService

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            settings = await GarageAuthService.get_settings(session, chat_id)
            teachers = await GarageAuthService.list_certified_teachers(session, chat_id)
            whitelist = await GarageAuthService.list_whitelist(session, chat_id)
            await session.commit()

        limit_mode_label = {
            "none": "关闭",
            "image": "图",
            "image_text": "文+图",
        }.get(settings.garage_limit_mode, settings.garage_limit_mode)
        partition_label = {"region": "地区", "price": "价格"}.get(
            settings.garage_summary_partition_by,
            settings.garage_summary_partition_by,
        )
        text = (
            "🚗 车库认证\n\n"
            "自动对车库频道进行识别，需要提前找天行者进行车库对接。\n\n"
            f"状态：{'✅ 启用' if settings.garage_auth_enabled else '❌ 关闭'}\n"
            f"认证图标：{settings.garage_auth_badge}\n"
            f"手动认证老师：{len(teachers)} 人\n"
            f"限制发言：{'✅ 启用' if settings.garage_limit_enabled else '❌ 关闭'}\n"
            f"限制模式：{limit_mode_label}\n"
            f"时间间隔：{settings.garage_limit_interval_sec // 3600} 小时\n"
            f"限制条数：{settings.garage_limit_max_count} 条\n"
            f"白名单：{len(whitelist)} 人\n"
            f"分区类型：{partition_label}\n"
            f"只显开课：{'✅ 开' if settings.garage_summary_only_open_course else '❌ 关'}"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚙️ 状态：", callback_data=f"grg:home:{chat_id}"),
                InlineKeyboardButton(
                    "✅ 启动" if settings.garage_auth_enabled else "启动",
                    callback_data=f"grg:toggle:{chat_id}:1",
                ),
                InlineKeyboardButton(
                    "关闭" if settings.garage_auth_enabled else "❌ 关闭",
                    callback_data=f"grg:toggle:{chat_id}:0",
                ),
            ],
            [
                InlineKeyboardButton("⚙️ 认证图标", callback_data=f"grg:badge:{chat_id}"),
                InlineKeyboardButton(settings.garage_auth_badge or "🤝", callback_data=f"grg:badge:{chat_id}"),
            ],
            [InlineKeyboardButton("💌 手动认证老师", callback_data=f"grg:teacher:list:{chat_id}:0")],
            [InlineKeyboardButton("🧾 生成老师汇总信息", callback_data=f"grg:summary:gen:{chat_id}")],
            [
                InlineKeyboardButton("⚙️ 限制发言：", callback_data=f"grg:home:{chat_id}"),
                InlineKeyboardButton(
                    "✅ 开启" if settings.garage_limit_enabled else "开启",
                    callback_data=f"grg:limit:toggle:{chat_id}:1",
                ),
                InlineKeyboardButton(
                    "关闭" if settings.garage_limit_enabled else "❌ 关闭",
                    callback_data=f"grg:limit:toggle:{chat_id}:0",
                ),
            ],
            [
                InlineKeyboardButton(
                    "✅ 图" if settings.garage_limit_mode == "image" else "图",
                    callback_data=f"grg:limit:mode:{chat_id}:image",
                ),
                InlineKeyboardButton(
                    "✅ 文+图" if settings.garage_limit_mode == "image_text" else "文+图",
                    callback_data=f"grg:limit:mode:{chat_id}:image_text",
                ),
                InlineKeyboardButton(
                    "✅ 关闭" if settings.garage_limit_mode == "none" else "关闭",
                    callback_data=f"grg:limit:mode:{chat_id}:none",
                ),
            ],
            [
                InlineKeyboardButton(
                    f"时间间隔（{settings.garage_limit_interval_sec // 3600}小时）",
                    callback_data=f"grg:limit:interval:{chat_id}",
                ),
                InlineKeyboardButton(
                    f"限制条数（{settings.garage_limit_max_count}条）",
                    callback_data=f"grg:limit:max:{chat_id}",
                ),
            ],
            [InlineKeyboardButton("📄 限制发言白名单", callback_data=f"grg:wl:list:{chat_id}:0")],
            [
                InlineKeyboardButton(
                    "✅ 地区" if settings.garage_summary_partition_by == "region" else "地区",
                    callback_data=f"grg:summary:partition:{chat_id}:region",
                ),
                InlineKeyboardButton(
                    "✅ 价格" if settings.garage_summary_partition_by == "price" else "价格",
                    callback_data=f"grg:summary:partition:{chat_id}:price",
                ),
            ],
            [
                InlineKeyboardButton(
                    "✅ 只显开课：开" if settings.garage_summary_only_open_course else "只显开课：开",
                    callback_data=f"grg:summary:open:{chat_id}:1",
                ),
                InlineKeyboardButton(
                    "只显开课：关" if settings.garage_summary_only_open_course else "✅ 只显开课：关",
                    callback_data=f"grg:summary:open:{chat_id}:0",
                ),
            ],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, text, reply_markup=keyboard)

    async def _show_garage_teacher_list_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        page: int = 0,
    ) -> None:
        from backend.features.garage.services.garage_features_service import GarageAuthService

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            rows = await GarageAuthService.list_certified_teachers(session, chat_id)
            await session.commit()

        lines = ["🚗 车库认证 | 手动添加认证老师", "", "可以人工设置用户为认证老师，发言也会有认证图标", ""]
        if not rows:
            lines.append("数据为空")
        else:
            start = page * 10
            for item, user in rows[start:start + 10]:
                name = f"@{user.username}" if user and user.username else str(item.user_id)
                lines.append(f"- {name}")
        keyboard_rows = [[InlineKeyboardButton("➕ 添加老师", callback_data=f"grg:teacher:add:{chat_id}")]]
        for item, user in rows[page * 10: page * 10 + 10]:
            title = f"删除 {('@' + user.username) if user and user.username else item.user_id}"
            keyboard_rows.append([InlineKeyboardButton(title[:48], callback_data=f"grg:teacher:del:{chat_id}:{item.user_id}")])
        keyboard_rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"grg:home:{chat_id}")])
        await self.message_helper.safe_edit(update, "\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard_rows))

    async def _show_garage_whitelist_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        page: int = 0,
    ) -> None:
        from backend.features.garage.services.garage_features_service import GarageAuthService

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            rows = await GarageAuthService.list_whitelist(session, chat_id)
            await session.commit()

        lines = ["📄 老师发言限制 | 添加白名单", "", "白名单中的老师可无视发言限制", ""]
        if not rows:
            lines.append("白名单为空")
        else:
            start = page * 10
            for item, user in rows[start:start + 10]:
                name = f"@{user.username}" if user and user.username else str(item.user_id)
                lines.append(f"- {name}")
        keyboard_rows = [[InlineKeyboardButton("➕ 添加白名单", callback_data=f"grg:wl:add:{chat_id}")]]
        for item, user in rows[page * 10: page * 10 + 10]:
            title = f"删除 {('@' + user.username) if user and user.username else item.user_id}"
            keyboard_rows.append([InlineKeyboardButton(title[:48], callback_data=f"grg:wl:del:{chat_id}:{item.user_id}")])
        keyboard_rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"grg:home:{chat_id}")])
        await self.message_helper.safe_edit(update, "\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard_rows))
