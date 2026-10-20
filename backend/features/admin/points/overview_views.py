from __future__ import annotations

from backend.features.admin.support import *
from backend.features.admin.points.list_paging import remembered_page, point_page, PAGE_SIZE


class PointsOverviewViewsMixin:
    async def _show_points_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """显示积分设置菜单"""
        from backend.features.admin.ui.points import format_points_home_text, points_config_keyboard

        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            await session.commit()

        chat_title = await self._get_chat_title(db, chat_id)
        getattr(context, "user_data", {}).setdefault("points_sections", {})[str(chat_id)] = "main"
        text = format_points_home_text(settings, chat_title=chat_title)

        from backend.features.admin.menu_origins import with_menu_origin
        keyboard = with_menu_origin(points_config_keyboard(settings, chat_id), context, chat_id=chat_id, feature="points")

        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _show_custom_points_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, page: int | None = None,
    ) -> None:
        """显示自定义积分列表页"""
        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        async with db.session_factory() as session:
            items, total, page = await point_page(session, chat_id, feature="custom",
                page=remembered_page(context, chat_id, "custom", page=page))
            remembered_page(context, chat_id, "custom", page=page)
            await session.commit()

        lines = [
            "🌐 自定义积分",
            "",
            "可以创建多种积分类型，但是此积分只能通过管理员进行加减，使用场景：诚心分、贡献值等！",
            "",
        ]
        if items:
            for item in items:
                lines.extend(
                    [
                        f"{item.name}（状态：{'✅ 启用' if item.enabled else '❌ 关闭'}）",
                        f"└编号：{item.type_no}",
                        "",
                    ]
                )
            lines.append(f"{total} 条数据，第 {page + 1} 页/共 {max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)} 页")
        else:
            lines.append("0 条数据，第 1 页/共 1 页")

        await self.message_helper.safe_edit(
            update,
            text="\n".join(lines),
            reply_markup=custom_points_list_keyboard(items, chat_id, page=page, total=total),
        )

    async def _show_custom_points_add_entry(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """兼容旧入口：添加后进入详情页。"""
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            item = await PointsExtendedService.create_custom_point_type(session, chat_id, update.effective_user.id)
            _, _, page = await point_page(session, chat_id, feature="custom", page=2**31)
            remembered_page(context, chat_id, "custom", page=page)
            await session.commit()
        await self._show_custom_point_detail(update, context, chat_id, type_id=item.id)

    async def _show_points_level_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, page: int | None = None,
    ) -> None:
        """显示积分等级列表页"""
        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)

        async with db.session_factory() as session:
            setting = await PointsExtendedService.get_or_create_level_setting(session, chat_id)
            levels, total, page = await point_page(session, chat_id, feature="levels",
                page=remembered_page(context, chat_id, "levels", page=page))
            remembered_page(context, chat_id, "levels", page=page)
            await session.commit()

        level_lines = []
        if levels:
            for level in levels:
                perms = [
                    f"文字{'✅' if level.allow_text else '❌'}",
                    f"音频{'✅' if level.allow_audio else '❌'}",
                    f"图片{'✅' if level.allow_photo else '❌'}",
                    f"视频{'✅' if level.allow_video else '❌'}",
                    f"贴纸{'✅' if level.allow_sticker else '❌'}",
                    f"文件{'✅' if level.allow_document else '❌'}",
                    f"提到{'✅' if level.allow_mention else '❌'}",
                ]
                level_lines.extend([f"#{level.id} {level.level_name[:40]}（积分门槛线 ≥ {level.point_threshold}）", "└" + " ".join(perms), ""])
        else:
            level_lines.append("待配置（积分门槛可设为 0）")
            level_lines.append("")
        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        text = "\n".join(
            [
                "👨‍💻 积分等级",
                "",
                "通过主积分数量划分用户等级，并设置不同等级的权限",
                "未匹配启用等级时沿用历史放行；负积分不匹配 0 门槛。标签显示独立配置；不覆盖其他来源标签。",
                "",
                *level_lines,
                f"{total} 条数据，第 {page + 1} 页/共 {total_pages} 页",
            ]
        )

        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=points_level_list_keyboard(setting, levels, chat_id, page=page, total=total),
        )

    async def _show_points_level_add_entry(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """兼容旧入口：创建等级并进入详情页。"""
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            level = await PointsExtendedService.create_level(session, chat_id)
            _, _, page = await point_page(session, chat_id, feature="levels", page=2**31)
            remembered_page(context, chat_id, "levels", page=page)
            await session.commit()
        await self._show_points_level_detail(update, context, chat_id, level_id=level.id)
