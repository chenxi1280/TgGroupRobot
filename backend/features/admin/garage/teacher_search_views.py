from __future__ import annotations

from backend.features.admin.support import *


def _toggle_labels(enabled: bool) -> tuple[str, str]:
    return ("✅ 启动", "关闭") if enabled else ("启动", "✅ 关闭")


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
        attendance_on, attendance_off = _toggle_labels(setting.attendance_enabled)
        nearby_on, nearby_off = _toggle_labels(setting.nearby_search_enabled)
        delete_label = "不删除" if setting.delete_mode == "none" else "删除"
        footer_label = (setting.footer_button_label or "").strip()
        footer_text = footer_label or "无"
        footer_row = [
            InlineKeyboardButton("底部按钮：", callback_data=f"tsearch:footer:menu:{chat_id}"),
            InlineKeyboardButton(footer_text, callback_data=f"tsearch:footer:menu:{chat_id}"),
        ]
        text = (
            "🔎 老师搜索\n\n"
            "根据车库频道信息提供群内搜索功能，需要提前找锅巴洋芋进行车库对接。\n\n"
            "标签搜索：输入车牌名称、地址、服务等信息\n"
            "附近搜索：群友发送附近可查询周边老师\n"
            "开课打卡：当日发言老师可视为开课\n"
            "强制录入：未录入位置可限制功能使用\n\n"
            f"标签搜索：{tag_on if setting.tag_search_enabled else tag_off}\n"
            f"开课打卡：{attendance_on if setting.attendance_enabled else attendance_off}\n"
            f"附近搜索：{nearby_on if setting.nearby_search_enabled else nearby_off}\n"
            f"强制录入：{'✅ 启动' if setting.force_location_enabled else '❌ 关闭'}\n"
            f"底部按钮：{footer_text}\n"
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
            footer_row,
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
        button_url = config.button_url or "【未配置】"
        text = (
            "🔍 老师搜索 | 底部按钮\n\n"
            f"按钮文字：{button_text}\n"
            f"按钮链接：{button_url}"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("修改文字", callback_data=f"tsearch:footer:text:{chat_id}")],
            [InlineKeyboardButton("修改链接", callback_data=f"tsearch:footer:link:{chat_id}")],
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

    async def _show_teacher_search_open_course_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        page: int = 0,
    ) -> None:
        from backend.features.garage.services.garage_features_service import TeacherSearchService

        db: Database = context.application.bot_data["db"]
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
