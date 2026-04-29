from __future__ import annotations

from backend.features.admin.support import *


def _toggle_labels(enabled: bool) -> tuple[str, str]:
    return ("✅ 启动", "关闭") if enabled else ("启动", "✅ 关闭")


def _attendance_mode_label(mode: str) -> str:
    return {
        "external": "不在此群打卡",
        "message": "发言就是打卡",
        "keyword": "固定话术打卡",
    }.get(mode, "发言就是打卡")


class TeacherSearchViewsMixin:
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

        tag_on, tag_off = _toggle_labels(setting.tag_search_enabled)
        only_open_course_enabled = getattr(setting, "only_open_course_enabled", True)
        only_open_on, only_open_off = _toggle_labels(only_open_course_enabled)
        attendance_on, attendance_off = _toggle_labels(setting.attendance_enabled)
        attendance_mode = getattr(setting, "attendance_mode", "message") or "message"
        mode_label = _attendance_mode_label(attendance_mode)
        nearby_on, nearby_off = _toggle_labels(setting.nearby_search_enabled)
        force_on, force_off = _toggle_labels(setting.force_location_enabled)
        delete_label = "不删除" if setting.delete_mode == "none" else "删除"
        text_lines = [
            "🔎 老师搜索",
            "",
            "根据车库频道信息提供群内搜索功能，需要提前找锅巴洋芋进行车库对接。",
            "",
            "标签搜索：输入车牌名称、地址、服务等信息",
            "开课打卡：按打卡模式记录当天开课",
        ]
        if setting.attendance_enabled:
            text_lines.append("只显开课：只展示当天开课打卡的老师")
        text_lines.append("附近搜索：群友发送附近可查询周边老师")
        if getattr(setting, "nearby_search_enabled", False):
            text_lines.append("强制录入：未录入位置的老师无法正常发言")
        text_lines.extend([
            "",
            f"标签搜索：{tag_on if setting.tag_search_enabled else tag_off}",
            f"开课打卡：{attendance_on if setting.attendance_enabled else attendance_off}",
        ])
        if setting.attendance_enabled:
            text_lines.extend([
                f"打卡模式：{mode_label}",
                f"只显开课：{'✅ 启动' if only_open_course_enabled else '❌ 关闭'}",
            ])
        text_lines.append(f"附近搜索：{nearby_on if setting.nearby_search_enabled else nearby_off}")
        if getattr(setting, "nearby_search_enabled", False):
            text_lines.append(f"强制录入：{'✅ 启动' if setting.force_location_enabled else '❌ 关闭'}")
        text_lines.extend([
            f"删除消息：{delete_label}",
            f"开课老师：{len(open_teachers)} 人",
        ])

        keyboard_rows = [
            [
                InlineKeyboardButton("标签搜索：", callback_data=f"tsearch:home:{chat_id}"),
                InlineKeyboardButton(tag_on, callback_data=f"tsearch:toggle:tag:{chat_id}:1"),
                InlineKeyboardButton(tag_off, callback_data=f"tsearch:toggle:tag:{chat_id}:0"),
            ],
            [
                InlineKeyboardButton("开课打卡：", callback_data=f"tsearch:home:{chat_id}"),
                InlineKeyboardButton(attendance_on, callback_data=f"tsearch:toggle:attendance:{chat_id}:1"),
                InlineKeyboardButton(attendance_off, callback_data=f"tsearch:toggle:attendance:{chat_id}:0"),
            ],
        ]
        if setting.attendance_enabled:
            keyboard_rows.extend([
                [
                    InlineKeyboardButton("打卡模式：", callback_data=f"tsearch:home:{chat_id}"),
                    InlineKeyboardButton(mode_label, callback_data=f"tsearch:attendance_mode:menu:{chat_id}"),
                ],
                [
                    InlineKeyboardButton("只显开课：", callback_data=f"tsearch:home:{chat_id}"),
                    InlineKeyboardButton(only_open_on, callback_data=f"tsearch:toggle:only_open:{chat_id}:1"),
                    InlineKeyboardButton(only_open_off, callback_data=f"tsearch:toggle:only_open:{chat_id}:0"),
                ],
                [InlineKeyboardButton("📝 手动替老师打卡", callback_data=f"tsearch:attendance:manual:{chat_id}")],
            ])
        keyboard_rows.append(
            [
                InlineKeyboardButton("附近搜索：", callback_data=f"tsearch:home:{chat_id}"),
                InlineKeyboardButton(nearby_on, callback_data=f"tsearch:toggle:nearby:{chat_id}:1"),
                InlineKeyboardButton(nearby_off, callback_data=f"tsearch:toggle:nearby:{chat_id}:0"),
            ]
        )
        if getattr(setting, "nearby_search_enabled", False):
            keyboard_rows.append(
                [
                    InlineKeyboardButton("强制录入：", callback_data=f"tsearch:home:{chat_id}"),
                    InlineKeyboardButton(force_on, callback_data=f"tsearch:toggle:force_loc:{chat_id}:1"),
                    InlineKeyboardButton(force_off, callback_data=f"tsearch:toggle:force_loc:{chat_id}:0"),
                ]
            )
        keyboard_rows.extend([
            [
                InlineKeyboardButton("删除消息：", callback_data=f"tsearch:home:{chat_id}"),
                InlineKeyboardButton(
                    "删除" if setting.delete_mode != "none" else "不删除",
                    callback_data=f"tsearch:delete_mode:{chat_id}:{'delete' if setting.delete_mode == 'none' else 'none'}",
                ),
            ],
            [InlineKeyboardButton("📍 代录老师位置", callback_data=f"tsearch:delegate:start:{chat_id}")],
            [InlineKeyboardButton("返回", callback_data=f"adm:menu:main:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, "\n".join(text_lines), reply_markup=InlineKeyboardMarkup(keyboard_rows))

    async def _show_teacher_search_attendance_mode_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        from backend.features.garage.services.garage_features_service import TeacherSearchService
        from backend.platform.db.schema.models.core import TgChat

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            setting = await TeacherSearchService.get_setting(session, chat_id)
            source_title = "未设置"
            source_chat_id = getattr(setting, "attendance_source_chat_id", None)
            if source_chat_id is not None:
                source_chat = await session.get(TgChat, int(source_chat_id))
                source_title = source_chat.title if source_chat and source_chat.title else str(source_chat_id)
            await session.commit()

        mode = getattr(setting, "attendance_mode", "message") or "message"
        open_word = getattr(setting, "attendance_open_keyword", "开课") or "开课"
        full_word = getattr(setting, "attendance_full_keyword", "满课") or "满课"
        rest_word = getattr(setting, "attendance_rest_keyword", "休息") or "休息"
        lines = [
            "🔍 老师搜索 | 选择打卡模式",
            "",
            "不在此群打卡：",
            "└ 本群不能打卡，",
            "└ 用途：比如你有两个群，可以选择一个群用来打卡，一个群用来搜索",
            f"└ 当前打卡群：{source_title}",
            "",
            "发言就是打卡：",
            "└ 老师今日在本群发言就算打卡了",
            "固定话术打卡：",
            "└ 老师今日发送固定话术才算打卡",
        ]
        keyboard_rows = [
            [InlineKeyboardButton(("✅ " if mode == "external" else "") + "不在此群打卡", callback_data=f"tsearch:attendance_source:menu:{chat_id}")],
            [InlineKeyboardButton(("✅ " if mode == "message" else "") + "发言就是打卡", callback_data=f"tsearch:attendance_mode:set:{chat_id}:message")],
            [InlineKeyboardButton(("✅ " if mode == "keyword" else "") + "固定话术打卡", callback_data=f"tsearch:attendance_mode:set:{chat_id}:keyword")],
        ]
        if mode == "keyword":
            keyboard_rows.extend([
                [
                    InlineKeyboardButton("🟡 开课词：", callback_data=f"tsearch:attendance_word:open:{chat_id}"),
                    InlineKeyboardButton(open_word, callback_data=f"tsearch:attendance_word:open:{chat_id}"),
                ],
                [
                    InlineKeyboardButton("🔴 满课词：", callback_data=f"tsearch:attendance_word:full:{chat_id}"),
                    InlineKeyboardButton(full_word, callback_data=f"tsearch:attendance_word:full:{chat_id}"),
                ],
                [
                    InlineKeyboardButton("⚪ 休息词：", callback_data=f"tsearch:attendance_word:rest:{chat_id}"),
                    InlineKeyboardButton(rest_word, callback_data=f"tsearch:attendance_word:rest:{chat_id}"),
                ],
            ])
        keyboard_rows.append([InlineKeyboardButton("⬅️ 返回", callback_data=f"tsearch:home:{chat_id}")])
        await self.message_helper.safe_edit(
            update,
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(keyboard_rows),
        )

    async def _show_teacher_search_attendance_source_menu(
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
            current_source = getattr(setting, "attendance_source_chat_id", None)
            await session.commit()

        managed_chats = await get_user_managed_chats(db, update.effective_user.id, context.bot)
        rows = []
        for source_chat_id, title, _ in managed_chats:
            if int(source_chat_id) == int(chat_id):
                continue
            prefix = "✅ " if current_source is not None and int(current_source) == int(source_chat_id) else ""
            rows.append([
                InlineKeyboardButton(
                    f"{prefix}{title}",
                    callback_data=f"tsearch:attendance_source:set:{chat_id}:{source_chat_id}",
                )
            ])
        rows.append([InlineKeyboardButton("⬅️ 返回", callback_data=f"tsearch:attendance_mode:menu:{chat_id}")])
        text = (
            "🔍 老师搜索 | 关联打卡群\n\n"
            "请选择用于打卡的群。当前群只负责搜索，开课状态会读取关联群的打卡记录。"
        )
        if len(rows) == 1:
            text += "\n\n暂无可关联的其他管理群。"
        await self.message_helper.safe_edit(update, text, reply_markup=InlineKeyboardMarkup(rows))

    async def _show_teacher_search_attendance_source_mode_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        source_chat_id: int,
    ) -> None:
        from backend.platform.db.schema.models.core import TgChat
        from backend.features.garage.services.garage_features_service import TeacherSearchService

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            source_setting = await TeacherSearchService.get_setting(session, source_chat_id)
            source_chat = await session.get(TgChat, source_chat_id)
            await session.commit()

        title = source_chat.title if source_chat and source_chat.title else str(source_chat_id)
        current_mode = getattr(source_setting, "attendance_mode", "message") or "message"
        text = (
            "🔍 老师搜索 | 关联打卡群\n\n"
            f"打卡群：{title}\n\n"
            "请选择这个打卡群自己的打卡方式："
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    ("✅ " if current_mode == "message" else "") + "发言就是打卡",
                    callback_data=f"tsearch:attendance_source_mode:set:{chat_id}:{source_chat_id}:message",
                )
            ],
            [
                InlineKeyboardButton(
                    ("✅ " if current_mode == "keyword" else "") + "固定话术打卡",
                    callback_data=f"tsearch:attendance_source_mode:set:{chat_id}:{source_chat_id}:keyword",
                )
            ],
            [InlineKeyboardButton("⬅️ 返回", callback_data=f"tsearch:attendance_source:menu:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, text, reply_markup=keyboard)

    async def _show_teacher_search_footer_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        from backend.features.garage.services.garage_features_service import TeacherSearchService

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            config = await TeacherSearchService.get_footer_button_config(session, chat_id)
            await session.commit()

        button_text = config.button_text or "【未配置】"
        text = (
            "🔍 老师搜索 | 底部按钮\n\n"
            f"按钮文字：{button_text}\n"
            "点击底部按钮会直接发送这个文字，并打开老师搜索说明。"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("修改文字", callback_data=f"tsearch:footer:text:{chat_id}")],
            [InlineKeyboardButton("⬅️ 返回", callback_data=f"tsearch:home:{chat_id}")],
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

        open_count = f"{len(open_teachers)} 人"
        lines = [
            "🔎 老师搜索 | 开课详情",
            "",
            f"开课打卡：{'✅ 启动' if setting.attendance_enabled else '❌ 关闭'}",
        ]
        keyboard_rows = []
        if setting.attendance_enabled:
            lines.append(f"开课老师：{open_count}")
            keyboard_rows.append(
                [
                    InlineKeyboardButton("📚 开课老师", callback_data=f"tsearch:open_course:list:{chat_id}:0"),
                    InlineKeyboardButton(open_count, callback_data=f"tsearch:open_course:list:{chat_id}:0"),
                ]
            )
        if getattr(setting, "nearby_search_enabled", False):
            force_on = "✅ 启动" if setting.force_location_enabled else "启动"
            force_off = "关闭" if setting.force_location_enabled else "✅ 关闭"
            lines.append(f"强制录入：{'✅ 启动' if setting.force_location_enabled else '❌ 关闭'}")
            keyboard_rows.append(
                [
                    InlineKeyboardButton("强制录入：", callback_data=f"tsearch:attendance:menu:{chat_id}"),
                    InlineKeyboardButton(force_on, callback_data=f"tsearch:toggle:force_loc:{chat_id}:1"),
                    InlineKeyboardButton(force_off, callback_data=f"tsearch:toggle:force_loc:{chat_id}:0"),
                ]
            )
        keyboard_rows.append([InlineKeyboardButton("返回", callback_data=f"tsearch:home:{chat_id}")])
        keyboard = InlineKeyboardMarkup(keyboard_rows)
        await self.message_helper.safe_edit(update, "\n".join(lines), reply_markup=keyboard)

    async def _show_teacher_search_open_course_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        page: int = 0,
    ) -> None:
        from backend.features.garage.services.garage_features_service import GarageAuthService, TeacherSearchService
        from backend.features.garage.services.teacher_search_queries import teacher_attendance_status_label

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            rows = await TeacherSearchService.list_open_course_teachers(session, chat_id)
            settings = await GarageAuthService.get_settings(session, chat_id)
            badge = getattr(settings, "garage_auth_badge", "🤝") or "🤝"
            await session.commit()

        lines = ["🔎 老师搜索 | 开课老师", ""]
        if not rows:
            lines.append("暂无开课老师")
        else:
            for item, user in rows[page * 10: page * 10 + 10]:
                name = f"@{user.username}" if user and user.username else str(item.user_id)
                lines.append(f"- {badge} {name} · {teacher_attendance_status_label(item)}")
        await self.message_helper.safe_edit(
            update,
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"tsearch:home:{chat_id}")]]),
        )
