from __future__ import annotations

from backend.features.admin.support import *


class GarageAuthSearchAdminMixin:
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
        partition_label = {"region": "地区", "price": "价格"}.get(settings.garage_summary_partition_by, settings.garage_summary_partition_by)
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
                InlineKeyboardButton("✅ 启动" if settings.garage_auth_enabled else "启动", callback_data=f"grg:toggle:{chat_id}:1"),
                InlineKeyboardButton("关闭" if settings.garage_auth_enabled else "❌ 关闭", callback_data=f"grg:toggle:{chat_id}:0"),
            ],
            [
                InlineKeyboardButton("⚙️ 认证图标", callback_data=f"grg:badge:{chat_id}"),
                InlineKeyboardButton(settings.garage_auth_badge or "🤝", callback_data=f"grg:badge:{chat_id}"),
            ],
            [InlineKeyboardButton("💌 手动认证老师", callback_data=f"grg:teacher:list:{chat_id}:0")],
            [InlineKeyboardButton("🧾 生成老师汇总信息", callback_data=f"grg:summary:gen:{chat_id}")],
            [
                InlineKeyboardButton("⚙️ 限制发言：", callback_data=f"grg:home:{chat_id}"),
                InlineKeyboardButton("✅ 开启" if settings.garage_limit_enabled else "开启", callback_data=f"grg:limit:toggle:{chat_id}:1"),
                InlineKeyboardButton("关闭" if settings.garage_limit_enabled else "❌ 关闭", callback_data=f"grg:limit:toggle:{chat_id}:0"),
            ],
            [
                InlineKeyboardButton("✅ 图" if settings.garage_limit_mode == "image" else "图", callback_data=f"grg:limit:mode:{chat_id}:image"),
                InlineKeyboardButton("✅ 文+图" if settings.garage_limit_mode == "image_text" else "文+图", callback_data=f"grg:limit:mode:{chat_id}:image_text"),
                InlineKeyboardButton("✅ 关闭" if settings.garage_limit_mode == "none" else "关闭", callback_data=f"grg:limit:mode:{chat_id}:none"),
            ],
            [
                InlineKeyboardButton(f"时间间隔（{settings.garage_limit_interval_sec // 3600}小时）", callback_data=f"grg:limit:interval:{chat_id}"),
                InlineKeyboardButton(f"限制条数（{settings.garage_limit_max_count}条）", callback_data=f"grg:limit:max:{chat_id}"),
            ],
            [InlineKeyboardButton("📄 限制发言白名单", callback_data=f"grg:wl:list:{chat_id}:0")],
            [
                InlineKeyboardButton("✅ 地区" if settings.garage_summary_partition_by == "region" else "地区", callback_data=f"grg:summary:partition:{chat_id}:region"),
                InlineKeyboardButton("✅ 价格" if settings.garage_summary_partition_by == "price" else "价格", callback_data=f"grg:summary:partition:{chat_id}:price"),
            ],
            [
                InlineKeyboardButton("✅ 只显开课：开" if settings.garage_summary_only_open_course else "只显开课：开", callback_data=f"grg:summary:open:{chat_id}:1"),
                InlineKeyboardButton("只显开课：关" if settings.garage_summary_only_open_course else "✅ 只显开课：关", callback_data=f"grg:summary:open:{chat_id}:0"),
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

    async def _show_teacher_search_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        from backend.features.garage.services.garage_features_service import TeacherSearchService

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            setting = await TeacherSearchService.get_setting(session, chat_id)
            open_teachers = await TeacherSearchService.list_open_course_teachers(session, chat_id)
            await session.commit()

        def _toggle_labels(enabled: bool) -> tuple[str, str]:
            return ("✅ 启动", "关闭") if enabled else ("启动", "✅ 关闭")

        tag_on, tag_off = _toggle_labels(setting.tag_search_enabled)
        attendance_on, attendance_off = _toggle_labels(setting.attendance_enabled)
        nearby_on, nearby_off = _toggle_labels(setting.nearby_search_enabled)
        delete_label = "不删除" if setting.delete_mode == "none" else "删除"
        footer_label = setting.footer_button_label or "无"
        text = (
            "🔎 老师搜索\n\n"
            "根据车库频道信息提供群内搜索功能，需要提前找天行者进行车库对接。\n\n"
            "标签搜索：输入车牌名称、地址、服务等信息\n"
            "附近搜索：群友发送附近可查询周边老师\n"
            "开课打卡：当日发言老师可视为开课\n"
            "强制录入：未录入位置可限制功能使用\n\n"
            f"标签搜索：{tag_on if setting.tag_search_enabled else tag_off}\n"
            f"开课打卡：{attendance_on if setting.attendance_enabled else attendance_off}\n"
            f"附近搜索：{nearby_on if setting.nearby_search_enabled else nearby_off}\n"
            f"强制录入：{'✅ 启动' if setting.force_location_enabled else '❌ 关闭'}\n"
            f"底部按钮：{footer_label}\n"
            f"删除消息：{delete_label}\n"
            f"开课老师：{len(open_teachers)} 人"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("标签搜索：", callback_data=f"tsearch:home:{chat_id}"),
                InlineKeyboardButton(tag_on, callback_data=f"tsearch:toggle:tag:{chat_id}:1"),
                InlineKeyboardButton(tag_off, callback_data=f"tsearch:toggle:tag:{chat_id}:0"),
            ],
            [
                InlineKeyboardButton("开课打卡：", callback_data=f"tsearch:attendance:menu:{chat_id}"),
                InlineKeyboardButton(attendance_on, callback_data=f"tsearch:toggle:attendance:{chat_id}:1"),
                InlineKeyboardButton(attendance_off, callback_data=f"tsearch:toggle:attendance:{chat_id}:0"),
            ],
            [
                InlineKeyboardButton("附近搜索：", callback_data=f"tsearch:home:{chat_id}"),
                InlineKeyboardButton(nearby_on, callback_data=f"tsearch:toggle:nearby:{chat_id}:1"),
                InlineKeyboardButton(nearby_off, callback_data=f"tsearch:toggle:nearby:{chat_id}:0"),
            ],
            [
                InlineKeyboardButton("底部按钮：", callback_data=f"tsearch:home:{chat_id}"),
                InlineKeyboardButton(footer_label, callback_data=f"tsearch:home:{chat_id}"),
            ],
            [
                InlineKeyboardButton("删除消息：", callback_data=f"tsearch:home:{chat_id}"),
                InlineKeyboardButton("删除" if setting.delete_mode != "none" else "不删除", callback_data=f"tsearch:delete_mode:{chat_id}:{'delete' if setting.delete_mode == 'none' else 'none'}"),
            ],
            [InlineKeyboardButton("📍 代录老师位置", callback_data=f"tsearch:delegate:start:{chat_id}")],
            [InlineKeyboardButton("返回", callback_data=f"adm:menu:main:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, text, reply_markup=keyboard)

    async def _show_teacher_search_attendance_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        from backend.features.garage.services.garage_features_service import TeacherSearchService

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            setting = await TeacherSearchService.get_setting(session, chat_id)
            open_teachers = await TeacherSearchService.list_open_course_teachers(session, chat_id)
            await session.commit()

        force_on = "✅ 启动" if setting.force_location_enabled else "启动"
        force_off = "关闭" if setting.force_location_enabled else "✅ 关闭"
        open_count = f"{len(open_teachers)} 人"
        text = (
            "🔎 老师搜索 | 开课详情\n\n"
            f"开课打卡：{'✅ 启动' if setting.attendance_enabled else '❌ 关闭'}\n"
            f"强制录入：{'✅ 启动' if setting.force_location_enabled else '❌ 关闭'}\n"
            f"开课老师：{open_count}\n\n"
            "说明：为了保持首页与文档布局一致，强制录入与开课老师查询收纳到本页。"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("强制录入：", callback_data=f"tsearch:attendance:menu:{chat_id}"),
                InlineKeyboardButton(force_on, callback_data=f"tsearch:toggle:force_loc:{chat_id}:1"),
                InlineKeyboardButton(force_off, callback_data=f"tsearch:toggle:force_loc:{chat_id}:0"),
            ],
            [
                InlineKeyboardButton("📚 开课老师", callback_data=f"tsearch:open_course:list:{chat_id}:0"),
                InlineKeyboardButton(open_count, callback_data=f"tsearch:open_course:list:{chat_id}:0"),
            ],
            [InlineKeyboardButton("返回", callback_data=f"tsearch:home:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, text, reply_markup=keyboard)

    async def _handle_garage_auth(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        from backend.platform.db.schema.models.enums import ConversationStateType
        from backend.features.garage.services.garage_features_service import GarageAuthService

        action = callback_data.get(1)
        db: Database = context.application.bot_data["db"]

        if action == "home":
            await self._show_garage_auth_menu(update, context, chat_id)
            return
        if action == "toggle":
            enabled = callback_data.get_int_optional(3)
            if enabled not in {0, 1}:
                await answer_callback_query_safely(update, "无效开关值", show_alert=True)
                return
            async with db.session_factory() as session:
                await GarageAuthService.update_settings(session, chat_id, garage_auth_enabled=bool(enabled))
                await session.commit()
            await self._show_garage_auth_menu(update, context, chat_id)
            return
        if action == "badge":
            await self._start_text_input_state(
                context,
                update.effective_user.id,
                chat_id,
                ConversationStateType.garage_badge_input.value,
                {"target_chat_id": chat_id},
            )
            await self.message_helper.safe_edit(
                update,
                "🚗 车库认证 | 认证图标\n\n👉 请输入新的认证图标：",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"grg:home:{chat_id}")]]),
            )
            return
        if action == "teacher":
            sub = callback_data.get(2)
            if sub == "list":
                await self._show_garage_teacher_list_menu(update, context, chat_id, callback_data.get_int_optional(4) or 0)
                return
            if sub == "add":
                await self._start_text_input_state(
                    context,
                    update.effective_user.id,
                    chat_id,
                    ConversationStateType.garage_teacher_input.value,
                    {"target_chat_id": chat_id},
                )
                await self.message_helper.safe_edit(
                    update,
                    "🚗 车库认证 | 手动添加认证老师\n\n👉 请输入用户名或ID：",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"grg:teacher:list:{chat_id}:0")]]),
                )
                return
            if sub == "del":
                user_id = callback_data.get_int_optional(4)
                if user_id is None:
                    await answer_callback_query_safely(update, "老师参数无效", show_alert=True)
                    return
                async with db.session_factory() as session:
                    await GarageAuthService.remove_teacher(session, chat_id, user_id)
                    await session.commit()
                await self._show_garage_teacher_list_menu(update, context, chat_id, 0)
                return
        if action == "limit":
            sub = callback_data.get(2)
            if sub == "toggle":
                enabled = callback_data.get_int_optional(4)
                if enabled not in {0, 1}:
                    await answer_callback_query_safely(update, "无效开关值", show_alert=True)
                    return
                async with db.session_factory() as session:
                    await GarageAuthService.update_settings(session, chat_id, garage_limit_enabled=bool(enabled))
                    await session.commit()
                await self._show_garage_auth_menu(update, context, chat_id)
                return
            if sub == "mode":
                mode = callback_data.get(4)
                if mode not in {"none", "image", "image_text"}:
                    await answer_callback_query_safely(update, "无效模式", show_alert=True)
                    return
                async with db.session_factory() as session:
                    await GarageAuthService.update_settings(session, chat_id, garage_limit_mode=mode)
                    await session.commit()
                await self._show_garage_auth_menu(update, context, chat_id)
                return
            if sub in {"interval", "max"}:
                await self._start_text_input_state(
                    context,
                    update.effective_user.id,
                    chat_id,
                    ConversationStateType.garage_limit_interval_input.value if sub == "interval" else ConversationStateType.garage_limit_max_count_input.value,
                    {"target_chat_id": chat_id},
                )
                prompt = "🚗 车库认证 | 时间间隔\n\n👉 请输入限制时间间隔（秒）："
                if sub == "max":
                    prompt = "🚗 车库认证 | 限制条数\n\n👉 请输入限制条数："
                await self.message_helper.safe_edit(
                    update,
                    prompt,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"grg:home:{chat_id}")]]),
                )
                return
        if action == "wl":
            sub = callback_data.get(2)
            if sub == "list":
                await self._show_garage_whitelist_menu(update, context, chat_id, callback_data.get_int_optional(4) or 0)
                return
            if sub == "add":
                await self._start_text_input_state(
                    context,
                    update.effective_user.id,
                    chat_id,
                    ConversationStateType.garage_whitelist_input.value,
                    {"target_chat_id": chat_id},
                )
                await self.message_helper.safe_edit(
                    update,
                    "📄 老师发言限制 | 添加白名单\n\n👉 请输入用户名或ID：",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"grg:wl:list:{chat_id}:0")]]),
                )
                return
            if sub == "del":
                user_id = callback_data.get_int_optional(4)
                if user_id is None:
                    await answer_callback_query_safely(update, "白名单参数无效", show_alert=True)
                    return
                async with db.session_factory() as session:
                    await GarageAuthService.remove_whitelist(session, chat_id, user_id)
                    await session.commit()
                await self._show_garage_whitelist_menu(update, context, chat_id, 0)
                return
        if action == "summary":
            sub = callback_data.get(2)
            if sub == "partition":
                value = callback_data.get(4)
                if value not in {"region", "price"}:
                    await answer_callback_query_safely(update, "无效分区类型", show_alert=True)
                    return
                async with db.session_factory() as session:
                    await GarageAuthService.update_settings(session, chat_id, garage_summary_partition_by=value)
                    await session.commit()
                await self._show_garage_auth_menu(update, context, chat_id)
                return
            if sub == "open":
                value = callback_data.get_int_optional(4)
                if value not in {0, 1}:
                    await answer_callback_query_safely(update, "无效开关值", show_alert=True)
                    return
                async with db.session_factory() as session:
                    await GarageAuthService.update_settings(session, chat_id, garage_summary_only_open_course=bool(value))
                    await session.commit()
                await self._show_garage_auth_menu(update, context, chat_id)
                return
            if sub == "gen":
                async with db.session_factory() as session:
                    summary_text = await GarageAuthService.build_teacher_summary(session, chat_id)
                    await session.commit()
                await self.message_helper.safe_edit(
                    update,
                    summary_text,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"grg:home:{chat_id}")]]),
                )
                return
        await self._show_garage_auth_menu(update, context, chat_id)

    async def _handle_teacher_search(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
    ) -> None:
        from backend.platform.db.schema.models.enums import ConversationStateType
        from backend.features.garage.services.garage_features_service import TeacherSearchService

        action = callback_data.get(1)
        db: Database = context.application.bot_data["db"]

        if action == "home":
            await self._show_teacher_search_menu(update, context, chat_id)
            return
        if action == "attendance" and callback_data.get(2) == "menu":
            await self._show_teacher_search_attendance_menu(update, context, chat_id)
            return
        if action == "toggle":
            field = callback_data.get(2)
            value = callback_data.get_int_optional(4)
            if value not in {0, 1}:
                await answer_callback_query_safely(update, "无效开关值", show_alert=True)
                return
            field_map = {
                "tag": "tag_search_enabled",
                "nearby": "nearby_search_enabled",
                "attendance": "attendance_enabled",
                "force_loc": "force_location_enabled",
            }
            setting_field = field_map.get(field)
            if setting_field is None:
                await answer_callback_query_safely(update, "无效配置项", show_alert=True)
                return
            async with db.session_factory() as session:
                await TeacherSearchService.update_setting(session, chat_id, **{setting_field: bool(value)})
                await session.commit()
            if field == "force_loc":
                await self._show_teacher_search_attendance_menu(update, context, chat_id)
            else:
                await self._show_teacher_search_menu(update, context, chat_id)
            return
        if action == "delete_mode":
            mode = callback_data.get(3)
            if mode not in {"none", "delete"}:
                await answer_callback_query_safely(update, "无效删除策略", show_alert=True)
                return
            async with db.session_factory() as session:
                await TeacherSearchService.update_setting(session, chat_id, delete_mode=mode)
                await session.commit()
            await self._show_teacher_search_menu(update, context, chat_id)
            return
        if action == "delegate" and callback_data.get(2) == "start":
            await self._start_text_input_state(
                context,
                update.effective_user.id,
                chat_id,
                ConversationStateType.teacher_search_delegate_target_input.value,
                {"target_chat_id": chat_id},
            )
            await self.message_helper.safe_edit(
                update,
                "📍 代替老师录入位置\n\n👉 请输入上牌老师的用户名或ID：",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"tsearch:home:{chat_id}")]]),
            )
            return
        if action == "open_course" and callback_data.get(2) == "list":
            page = callback_data.get_int_optional(4) or 0
            async with db.session_factory() as session:
                rows = await TeacherSearchService.list_open_course_teachers(session, chat_id)
                await session.commit()
            lines = ["🔎 老师搜索 | 开课老师", ""]
            if not rows:
                lines.append("暂无开课老师")
            else:
                for item, user in rows[page * 10: page * 10 + 10]:
                    name = f"@{user.username}" if user and user.username else str(item.user_id)
                    lines.append(f"- {name}")
            await self.message_helper.safe_edit(
                update,
                "\n".join(lines),
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"tsearch:home:{chat_id}")]]),
            )
            return
        await self._show_teacher_search_menu(update, context, chat_id)

