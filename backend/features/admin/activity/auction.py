from __future__ import annotations

from backend.features.admin.support import *

class AuctionAdminControllerMixin:
    async def _show_auction_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            setting = await get_auction_setting(session, chat_id)
            auctions = await list_recent_auctions(session, chat_id, limit=5)
            await session.commit()
        chat_title = await self._get_chat_title(db, chat_id)
        lines = [format_auction_settings_text(chat_title, setting), "", "📋 最近拍卖："]
        if auctions:
            for item in auctions:
                lines.append(f"#{item.id} {item.title or '未命名'}｜{item.status}｜当前价 {item.current_price}")
        else:
            lines.append("暂无拍卖记录")
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚙️ 状态：", callback_data=f"auc:home:{chat_id}"),
                InlineKeyboardButton("✅ 启动" if setting.enabled else "启动", callback_data=f"auc:toggle:{chat_id}:enabled:1"),
                InlineKeyboardButton("✅ 关闭" if not setting.enabled else "关闭", callback_data=f"auc:toggle:{chat_id}:enabled:0"),
            ],
            [
                InlineKeyboardButton("📌 消息置顶：", callback_data=f"auc:home:{chat_id}"),
                InlineKeyboardButton("✅ 启动" if setting.pin_message_enabled else "启动", callback_data=f"auc:toggle:{chat_id}:pin:1"),
                InlineKeyboardButton("✅ 关闭" if not setting.pin_message_enabled else "关闭", callback_data=f"auc:toggle:{chat_id}:pin:0"),
            ],
            [
                InlineKeyboardButton("⏱ 自动延时：", callback_data=f"auc:home:{chat_id}"),
                InlineKeyboardButton("✅ 启动" if setting.auto_extend_enabled else "启动", callback_data=f"auc:toggle:{chat_id}:auto_extend:1"),
                InlineKeyboardButton("✅ 关闭" if not setting.auto_extend_enabled else "关闭", callback_data=f"auc:toggle:{chat_id}:auto_extend:0"),
            ],
            [
                InlineKeyboardButton("🚫 不关联" + (" ✅" if setting.points_mode == "none" else ""), callback_data=f"auc:points_mode:{chat_id}:none"),
                InlineKeyboardButton("🌑 主积分" + (" ✅" if setting.points_mode == "group_points" else ""), callback_data=f"auc:points_mode:{chat_id}:group_points"),
            ],
            [InlineKeyboardButton("📋 活动列表", callback_data=f"auc:list:{chat_id}:0")],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, text="\n".join(lines), reply_markup=keyboard)

    async def _show_auction_list(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, page: int = 0,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            items, total_count = await list_auctions(session, chat_id, page=page, page_size=10)
            await session.commit()
        total_pages = max(1, (total_count + 9) // 10)
        current_page = min(max(page, 0), total_pages - 1)
        lines = [
            "💰 拍卖 | 活动列表",
            "",
            f"{total_count} 条数据，第 {current_page + 1} 页/共 {total_pages} 页",
            "",
        ]
        if items:
            for item in items:
                lines.extend(
                    [
                        f"#{item.id} {item.title or '未命名拍卖'}",
                        f"状态：{item.status}｜当前价：{item.current_price}",
                        "",
                    ]
                )
        else:
            lines.append("暂无拍卖记录")

        keyboard_rows: list[list[InlineKeyboardButton]] = []
        for item in items:
            keyboard_rows.append([
                InlineKeyboardButton(
                    f"📄 #{item.id} {item.title or '未命名拍卖'}"[:48],
                    callback_data=f"auc:detail:{chat_id}:{item.id}",
                )
            ])
        nav_row: list[InlineKeyboardButton] = []
        if current_page > 0:
            nav_row.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"auc:list:{chat_id}:{current_page - 1}"))
        if current_page < total_pages - 1:
            nav_row.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"auc:list:{chat_id}:{current_page + 1}"))
        if nav_row:
            keyboard_rows.append(nav_row)
        keyboard_rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"auc:home:{chat_id}")])
        await self.message_helper.safe_edit(update, text="\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard_rows))

    async def _show_auction_detail(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, auction_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            item = await get_auction(session, chat_id, auction_id)
            await session.commit()
        if item is None:
            await self.message_helper.safe_edit(
                update,
                text="❌ 拍卖不存在",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回列表", callback_data=f"auc:list:{chat_id}:0")]]),
            )
            return
        text = "\n".join(
            [
                f"💰 拍卖详情 #{item.id}",
                "",
                f"标题：{item.title or '未命名拍卖'}",
                f"状态：{item.status}",
                f"起拍价：{item.start_price}",
                f"当前价：{item.current_price}",
                f"创建时间：{item.created_at.astimezone().strftime('%Y-%m-%d %H:%M:%S')}",
                f"截止时间：{item.end_at.astimezone().strftime('%Y-%m-%d %H:%M:%S') if item.end_at else '未设置'}",
                f"中标用户：{item.winner_user_id or '未结算'}",
            ]
        )
        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回列表", callback_data=f"auc:list:{chat_id}:0")]]),
        )

    async def _handle_auction(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, callback_data: CallbackParser,
    ) -> None:
        action = callback_data.get(1)
        db: Database = context.application.bot_data["db"]
        if action == "home":
            await self._show_auction_menu(update, context, chat_id)
            return
        if action == "list":
            await self._show_auction_list(update, context, chat_id, page=callback_data.get_int_optional(3) or 0)
            return
        if action == "detail":
            await self._show_auction_detail(update, context, chat_id, auction_id=callback_data.get_int(3))
            return

        async with db.session_factory() as session:
            if action == "toggle":
                field = callback_data.get(3)
                enabled = callback_data.get(4) == "1"
                updates = {
                    "enabled": enabled,
                    "pin_message_enabled": enabled if field == "pin" else None,
                    "auto_extend_enabled": enabled if field == "auto_extend" else None,
                }
                if field == "enabled":
                    updates = {"enabled": enabled}
                elif field == "pin":
                    updates = {"pin_message_enabled": enabled}
                elif field == "auto_extend":
                    updates = {"auto_extend_enabled": enabled}
                await update_auction_setting(session, chat_id, **updates)
            elif action == "perm":
                await update_auction_setting(session, chat_id, create_permission=callback_data.get(3))
            elif action == "points_mode":
                await update_auction_setting(session, chat_id, points_mode=callback_data.get(3))
            await session.commit()
        await self._show_auction_menu(update, context, chat_id)
