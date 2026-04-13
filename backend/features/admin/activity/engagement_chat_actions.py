from __future__ import annotations

from backend.features.admin.support import *


class EngagementAdminChatActionsMixin:
    async def _handle_engagement_chat(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        callback_data: CallbackParser,
        session,
    ) -> None:
        sub = callback_data.get(3)
        if sub == "home":
            await session.commit()
            await self._show_engagement_chat_reward(update, context, chat_id)
            return
        if sub == "toggle":
            await update_engagement_chat_reward(session, chat_id, enabled=callback_data.get(4) == "1")
            await session.commit()
            await self._show_engagement_chat_reward(update, context, chat_id)
            return
        if sub == "preview":
            reward = await get_engagement_chat_reward(session, chat_id)
            await session.commit()
            preview_text = "\n".join(
                [
                    "💬 水群激励 | 预览配置",
                    "",
                    f"🎯 达标发言：{reward.daily_message_target}",
                    f"🎁 奖励计划：{reward.reward_points_plan or []}",
                    f"🗓 7日后策略：{reward.after_7d_mode}",
                    f"⌨️ 领奖口令：{reward.command_keyword}",
                ]
            )
            await self.message_helper.safe_edit(
                update,
                preview_text,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"act:chat:{chat_id}:home")]]),
            )
            return
        if sub == "stats":
            await session.commit()
            await self._show_engagement_chat_stats(update, context, chat_id)
            return
        if sub == "history":
            await session.commit()
            await self._show_engagement_chat_history(update, context, chat_id)
            return
        if sub == "type":
            await update_engagement_chat_reward(session, chat_id, reward_type=callback_data.get(4))
            await session.commit()
            await self._show_engagement_chat_reward(update, context, chat_id)
            return
        if sub == "after7":
            await update_engagement_chat_reward(session, chat_id, after_7d_mode=callback_data.get(4))
            await session.commit()
            await self._show_engagement_chat_reward(update, context, chat_id)
            return
        if sub in {"target", "plan", "command"}:
            state_map = {
                "target": "engagement_wait_chat_target",
                "plan": "engagement_wait_chat_plan",
                "command": "engagement_wait_chat_command",
            }
            prompt_map = {
                "target": "💬 水群激励 | 发言数量\n\n请输入每日发言达标数，例如：200",
                "plan": "💬 水群激励 | 奖励设置\n\n请输入 7 个非递减整数，用空格分隔。\n例如：10 20 30 40 50 60 70",
                "command": "💬 水群激励 | 领奖口令\n\n请输入新的领奖口令，例如：我爱水群",
            }
            await self._start_text_input_state(
                context,
                update.effective_user.id,
                update.effective_user.id,
                state_map[sub],
                {"target_chat_id": chat_id},
            )
            await session.commit()
            await self.message_helper.safe_edit(
                update,
                prompt_map[sub],
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"act:chat:{chat_id}:home")]]),
            )
            return
        await session.commit()
        await self._show_engagement_chat_reward(update, context, chat_id)
