from __future__ import annotations

from backend.features.admin.support import *


class EngagementAdminEggActionsMixin:
    async def _handle_engagement_egg(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
        session,
    ) -> None:
        sub = callback_data.get(3)
        if sub in {"home", "list"}:
            await session.commit()
            await self._show_engagement_egg_list(update, context, chat_id, status=callback_data.get(4, "all") or "all")
            return
        if sub == "new":
            await self._start_text_input_state(
                context,
                update.effective_user.id,
                update.effective_user.id,
                "engagement_wait_egg_template",
                {"target_chat_id": chat_id},
            )
            await session.commit()
            await self.message_helper.safe_edit(
                update,
                (
                    "🥚 有奖彩蛋 | 新建活动\n\n"
                    "请按以下格式发送：\n"
                    "标题=四月彩蛋（可选）\n"
                    "答案=xxx\n线索1=...\n奖励1=100\n时间1=09:00\n"
                    "线索2=...\n奖励2=80\n时间2=10:00\n"
                    "线索3=...\n奖励3=60\n时间3=11:00\n"
                    "线索4=...\n奖励4=40\n时间4=12:00"
                ),
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"act:egg:{chat_id}:list:all")]]),
            )
            return
        if sub == "detail":
            event_id = callback_data.get_int(4)
            await session.commit()
            if event_id is None:
                await self._show_engagement_egg_list(update, context, chat_id)
                return
            await self._show_engagement_egg(update, context, chat_id, event_id)
            return
        if sub == "history":
            await session.commit()
            await self._show_engagement_egg_history(update, context, chat_id)
            return
        if sub == "toggle":
            event = await get_egg_event(session, chat_id, callback_data.get_int(4))
            enabled = callback_data.get(5) == "1"
            if event is None:
                await session.commit()
                await self._show_engagement_egg_list(update, context, chat_id)
                return
            event.enabled = enabled
            if enabled and event.answer and event.clues and event.clue_times and event.winner_user_id is None:
                event.status = "running"
            elif not enabled and event.status != "finished":
                event.status = "idle"
            await session.commit()
            await self._show_engagement_egg(update, context, chat_id, event.id)
            return
        if sub == "status":
            event = await get_egg_event(session, chat_id, callback_data.get_int(4))
            target_status = callback_data.get(5)
            if event is None:
                await session.commit()
                await self._show_engagement_egg_list(update, context, chat_id)
                return
            if target_status == "running" and event.enabled and event.answer and event.clues and event.clue_times and event.winner_user_id is None:
                event.status = "running"
            elif target_status == "idle":
                event.status = "idle"
            await session.commit()
            await self._show_engagement_egg(update, context, chat_id, event.id)
            return
        if sub == "template":
            event_id = callback_data.get_int(4)
            await self._start_text_input_state(
                context,
                update.effective_user.id,
                update.effective_user.id,
                "engagement_wait_egg_template",
                {"target_chat_id": chat_id, "event_id": event_id},
            )
            await session.commit()
            await self.message_helper.safe_edit(
                update,
                (
                    "🥚 有奖彩蛋 | 模板输入\n\n"
                    "请按以下格式发送：\n"
                    "标题=四月彩蛋（可选）\n"
                    "答案=xxx\n线索1=...\n奖励1=100\n时间1=09:00\n"
                    "线索2=...\n奖励2=80\n时间2=10:00\n"
                    "线索3=...\n奖励3=60\n时间3=11:00\n"
                    "线索4=...\n奖励4=40\n时间4=12:00"
                ),
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"act:egg:{chat_id}:detail:{event_id}" if event_id else f"act:egg:{chat_id}:list:all")]]),
            )
            return
        if sub == "preview":
            event = await get_egg_event(session, chat_id, callback_data.get_int(4))
            await session.commit()
            if event is None:
                await self._show_engagement_egg_list(update, context, chat_id)
                return
            preview_lines = [
                f"🥚 有奖彩蛋 | 预览配置 #{event.id}",
                "",
                f"🏷 活动标题：{event.title}",
                f"🔐 答案：{event.answer or '未配置'}",
                f"🧩 线索：{event.clues or []}",
                f"🎁 奖励：{event.clue_rewards or []}",
                f"⏰ 时间：{event.clue_times or []}",
            ]
            await self.message_helper.safe_edit(
                update,
                "\n".join(preview_lines),
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"act:egg:{chat_id}:detail:{event.id}")]]),
            )
            return
        if sub == "publish":
            event_id = callback_data.get_int(4)
            published = await publish_next_clue(session, chat_id, event_id=event_id)
            await session.commit()
            if published is None:
                await self.message_helper.safe_edit(
                    update,
                    "🥚 当前没有可立即发布的线索，请先启用活动或检查是否已经全部发布。",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"act:egg:{chat_id}:detail:{event_id}" if event_id else f"act:egg:{chat_id}:list:all")]]),
                )
                return
            event, clue_index, clue_text, reward_points = published
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"🥚 有奖彩蛋【{event.title}】| 第 {clue_index + 1} 条线索\n"
                    f"🧩 线索：{clue_text}\n"
                    f"🎁 当前命中奖励：{reward_points} 积分"
                ),
            )
            await self._show_engagement_egg(update, context, chat_id, event.id)
            return
        if sub == "reset":
            event = await get_egg_event(session, chat_id, callback_data.get_int(4))
            if event is None:
                await session.commit()
                await self._show_engagement_egg_list(update, context, chat_id)
                return
            await archive_egg_snapshot(session, event, reward_points=0)
            event.enabled = False
            event.answer = None
            event.clues = []
            event.clue_rewards = []
            event.clue_times = []
            event.winner_user_id = None
            event.status = "idle"
            event.published_clue_count = 0
            await session.commit()
            await self._show_engagement_egg(update, context, chat_id, event.id)
            return
        await session.commit()
        await self._show_engagement_egg_list(update, context, chat_id)
