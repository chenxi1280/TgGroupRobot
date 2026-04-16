from __future__ import annotations

import datetime as dt

from backend.features.admin.support import *


def _build_egg_quick_template(chat_id: int, bot_username: str | None) -> str:
    command = f"@{bot_username} 添加彩蛋" if bot_username else "添加彩蛋"
    today = dt.datetime.now().strftime("%Y-%m-%d")
    return "\n".join(
        [
            command,
            "",
            f"【群ID】{chat_id}",
            "【答案】爱情买卖",
            "",
            "【线索1】猜一首歌",
            "【线索1奖励】300积分",
            f"【线索1时间】{today} 09:00",
            "",
            "【线索2】火遍大江南北",
            "【线索2奖励】200积分",
            f"【线索2时间】{today} 11:00",
            "",
            "【线索3】演唱是两个人",
            "【线索3奖励】100积分",
            f"【线索3时间】{today} 14:00",
            "",
            "【线索4】凤凰传奇唱的",
            "【线索4奖励】50积分",
            f"【线索4时间】{today} 16:00",
            "",
            "【颁奖人】@UserName",
        ]
    )


def _copy_text_button(text: str) -> InlineKeyboardButton:
    return InlineKeyboardButton("📋 复制彩蛋模板", api_kwargs={"copy_text": {"text": text}})


def _format_egg_template_prompt(template_text: str, *, editing: bool = False) -> str:
    title = "🥚 有奖彩蛋 | 编辑活动" if editing else "🥚 有奖彩蛋 | 添加彩蛋"
    return "\n".join(
        [
            title,
            "",
            "点击下方“复制彩蛋模板”，把答案、线索、奖励和时间改好后，直接发给我即可创建。",
            "支持你截图里的【字段】格式；奖励只按主积分发放，请填写 300 或 300积分。",
            "",
            "可复制模板：",
            template_text,
        ]
    )


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
            template_text = _build_egg_quick_template(chat_id, getattr(context.bot, "username", None))
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
                _format_egg_template_prompt(template_text),
                reply_markup=InlineKeyboardMarkup([
                    [_copy_text_button(template_text)],
                    [InlineKeyboardButton("🔙 返回", callback_data=f"act:egg:{chat_id}:list:all")],
                ]),
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
            template_text = _build_egg_quick_template(chat_id, getattr(context.bot, "username", None))
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
                _format_egg_template_prompt(template_text, editing=True),
                reply_markup=InlineKeyboardMarkup([
                    [_copy_text_button(template_text)],
                    [InlineKeyboardButton("🔙 返回", callback_data=f"act:egg:{chat_id}:detail:{event_id}" if event_id else f"act:egg:{chat_id}:list:all")],
                ]),
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
                f"🎁 奖励：{[f'{get_clue_reward_points(event, idx)}积分' for idx in range(len(event.clues or []))]}",
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
            event, clue_index, clue_text, reward_summary = published
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"🥚 有奖彩蛋【{event.title}】| 第 {clue_index + 1} 条线索\n"
                    f"🧩 线索：{clue_text}\n"
                    f"🎁 当前命中奖励：{reward_summary}"
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
