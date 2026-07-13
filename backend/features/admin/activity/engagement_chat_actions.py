from __future__ import annotations

from backend.features.admin.support import *


class EngagementAdminChatActionsMixin:
    async def _show_engagement_chat_preview(
        self, update, context, *, session, chat_id: int
    ) -> None:
        reward = await get_engagement_chat_reward(session, chat_id)
        await session.commit()
        plan = reward.reward_points_plan or [30, 50, 70, 90, 110, 130, 150]
        text = "\n".join([
            "🍬 水群激励 | 群内展示预览", "",
            f"每日发言达到 {reward.daily_message_target} 条即可领取奖励。",
            f"连续奖励：{' / '.join(str(item) for item in plan)} 积分",
            f"七日后：{'从首日重新计算' if reward.after_7d_mode == 'reset' else '延续最高档奖励'}",
            f"领奖口令：{reward.command_keyword}",
        ])
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 返回", callback_data=f"act:chat:{chat_id}:home")]]
        )
        await self.message_helper.safe_edit(update, text, reply_markup=keyboard)

    async def _update_engagement_chat_option(
        self, update, context, *, session, chat_id: int, sub: str, callback_data
    ) -> bool:
        fields = {
            "toggle": ("enabled", callback_data.get(4) == "1"),
            "type": ("reward_type", callback_data.get(4)),
            "after7": ("after_7d_mode", callback_data.get(4)),
        }
        config = fields.get(sub)
        if config is None:
            return False
        await update_engagement_chat_reward(
            session, chat_id, **{config[0]: config[1]}
        )
        await session.commit()
        await self._show_engagement_chat_reward(update, context, chat_id)
        return True

    async def _apply_engagement_chat_preset(
        self, update, context, *, session, chat_id: int
    ) -> None:
        await update_engagement_chat_reward(
            session, chat_id, reward_type="daily_increment",
            daily_message_target=200,
            reward_points_plan=[30, 50, 70, 90, 110, 130, 150],
            after_7d_mode="continue", command_keyword="我爱水群",
        )
        await session.commit()
        await self._show_engagement_chat_reward(update, context, chat_id)

    async def _start_engagement_chat_input(
        self, update, context, *, session, chat_id: int, sub: str
    ) -> bool:
        configs = {
            "target": ("engagement_wait_chat_target", "💬 水群激励 | 发言数量\n\n请输入每日发言达标数，例如：200"),
            "plan": ("engagement_wait_chat_plan", "🍬 水群激励 | 水群奖励\n\n请输入 7 个非递减整数，用空格分隔。\n例如：30 50 70 90 110 130 150"),
            "command": ("engagement_wait_chat_command", "💬 水群激励 | 领奖口令\n\n请输入新的领奖口令，例如：我爱水群"),
        }
        config = configs.get(sub)
        if config is None:
            return False
        await self._start_text_input_state(
            context, update.effective_user.id, update.effective_user.id,
            state_type=config[0], payload={"target_chat_id": chat_id},
        )
        await session.commit()
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 返回", callback_data=f"act:chat:{chat_id}:home")]]
        )
        await self.message_helper.safe_edit(update, config[1], reply_markup=keyboard)
        return True

    async def _handle_engagement_chat(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, callback_data: CallbackParser,
        session,
    ) -> None:
        sub = callback_data.get(3)
        if sub == "home":
            await session.commit()
            await self._show_engagement_chat_reward(update, context, chat_id)
            return
        if await self._update_engagement_chat_option(
            update, context, session=session, chat_id=chat_id,
            sub=sub, callback_data=callback_data,
        ):
            return
        if sub == "preview":
            await self._show_engagement_chat_preview(
                update, context, session=session, chat_id=chat_id
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
        if sub == "preset":
            await self._apply_engagement_chat_preset(
                update, context, session=session, chat_id=chat_id
            )
            return
        if await self._start_engagement_chat_input(
            update, context, session=session, chat_id=chat_id, sub=sub
        ):
            return
        await session.commit()
        await self._show_engagement_chat_reward(update, context, chat_id)
