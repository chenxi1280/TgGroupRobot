from __future__ import annotations

from backend.features.admin.garage.teacher_search_presenters import (
    _attendance_mode_keyboard,
    _teacher_search_home_keyboard,
    _teacher_search_home_text,
    build_attendance_detail,
    build_attendance_source_menu,
    build_attendance_source_mode_menu,
)
from backend.features.admin.support import *


class TeacherSearchViewsMixin:
    async def _show_teacher_search_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        from backend.features.garage.services.garage_features_service import (
            TeacherSearchService,
        )

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            setting = await TeacherSearchService.get_setting(session, chat_id)
            open_teachers = await TeacherSearchService.list_open_course_teachers(
                session, chat_id
            )
            await session.commit()

        text = _teacher_search_home_text(setting, len(open_teachers))
        keyboard = _teacher_search_home_keyboard(setting, chat_id)
        await self.message_helper.safe_edit(update, text, reply_markup=keyboard)

    async def _show_teacher_search_attendance_mode_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        from backend.features.garage.services.garage_features_service import (
            TeacherSearchService,
        )
        from backend.platform.db.schema.models.core import TgChat

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            setting = await TeacherSearchService.get_setting(session, chat_id)
            source_title = "未设置"
            source_chat_id = getattr(setting, "attendance_source_chat_id", None)
            if source_chat_id is not None:
                source_chat = await session.get(TgChat, int(source_chat_id))
                source_title = (
                    source_chat.title
                    if source_chat and source_chat.title
                    else str(source_chat_id)
                )
            await session.commit()

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
        await self.message_helper.safe_edit(
            update,
            "\n".join(lines),
            reply_markup=_attendance_mode_keyboard(setting, chat_id),
        )

    async def _show_teacher_search_attendance_source_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        from backend.features.garage.services.garage_features_service import (
            TeacherSearchService,
        )

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            setting = await TeacherSearchService.get_setting(session, chat_id)
            current_source = getattr(setting, "attendance_source_chat_id", None)
            await session.commit()

        managed_chats = await get_user_managed_chats(
            db, update.effective_user.id, context.bot
        )
        text, keyboard = build_attendance_source_menu(
            managed_chats, current_source, chat_id
        )
        await self.message_helper.safe_edit(update, text, reply_markup=keyboard)

    async def _show_teacher_search_attendance_source_mode_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *,
        source_chat_id: int,
    ) -> None:
        from backend.platform.db.schema.models.core import TgChat
        from backend.features.garage.services.garage_features_service import (
            TeacherSearchService,
        )

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            source_setting = await TeacherSearchService.get_setting(
                session, source_chat_id
            )
            source_chat = await session.get(TgChat, source_chat_id)
            await session.commit()

        title = (
            source_chat.title
            if source_chat and source_chat.title
            else str(source_chat_id)
        )
        current_mode = (
            getattr(source_setting, "attendance_mode", "message") or "message"
        )
        text, keyboard = build_attendance_source_mode_menu(
            title, current_mode, chat_id, source_chat_id=source_chat_id
        )
        await self.message_helper.safe_edit(update, text, reply_markup=keyboard)

    async def _show_teacher_search_footer_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        from backend.features.garage.services.garage_features_service import (
            TeacherSearchService,
        )

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            config = await TeacherSearchService.get_footer_button_config(
                session, chat_id
            )
            await session.commit()

        button_text = config.button_text or "【未配置】"
        text = (
            "🔍 老师搜索 | 底部按钮\n\n"
            f"按钮文字：{button_text}\n"
            "点击底部按钮会直接发送这个文字，并打开老师搜索说明。"
        )
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "修改文字", callback_data=f"tsearch:footer:text:{chat_id}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "⬅️ 返回", callback_data=f"tsearch:home:{chat_id}"
                    )
                ],
            ]
        )
        await self.message_helper.safe_edit(update, text, reply_markup=keyboard)

    async def _show_teacher_search_attendance_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        from backend.features.garage.services.garage_features_service import (
            TeacherSearchService,
        )

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            setting = await TeacherSearchService.get_setting(session, chat_id)
            open_teachers = await TeacherSearchService.list_open_course_teachers(
                session, chat_id
            )
            await session.commit()

        text, keyboard = build_attendance_detail(setting, len(open_teachers), chat_id)
        await self.message_helper.safe_edit(update, text, reply_markup=keyboard)

    async def _show_teacher_search_open_course_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *,
        page: int = 0,
    ) -> None:
        from backend.features.garage.services.garage_features_service import (
            GarageAuthService,
            TeacherSearchService,
        )
        from backend.features.garage.services.teacher_search_queries import (
            teacher_attendance_status_label,
        )

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            rows = await TeacherSearchService.list_open_course_teachers(
                session, chat_id
            )
            settings = await GarageAuthService.get_settings(session, chat_id)
            badge = getattr(settings, "garage_auth_badge", "🤝") or "🤝"
            await session.commit()

        lines = ["🔎 老师搜索 | 开课老师", ""]
        if not rows:
            lines.append("暂无开课老师")
        else:
            for item, user in rows[page * 10 : page * 10 + 10]:
                name = (
                    f"@{user.username}" if user and user.username else str(item.user_id)
                )
                lines.append(
                    f"- {badge} {name} · {teacher_attendance_status_label(item)}"
                )
        await self.message_helper.safe_edit(
            update,
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔙 返回", callback_data=f"tsearch:home:{chat_id}"
                        )
                    ]
                ]
            ),
        )
