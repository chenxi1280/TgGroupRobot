from __future__ import annotations

import datetime as dt

import structlog
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select

from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.core import TgUser
from backend.platform.db.schema.models.enums import LotteryDrawMode
from backend.features.activity.services.lottery_service import (
    get_lottery,
    get_lottery_participants,
    get_or_create_lottery_setting,
)
from backend.features.activity.services.lottery_subscription import (
    filter_lottery_subscribed_user_ids,
    get_lottery_subscribe_targets,
    requires_lottery_subscribe,
)
from backend.features.activity.ui.lottery import manual_draw_summary_keyboard

log = structlog.get_logger(__name__)


class LotteryDrawMixin:
    async def handle_draw(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        lottery_id: int,
        target_chat_id: int | None = None,
    ) -> None:
        chat = update.effective_chat
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            lottery = await get_lottery(session, lottery_id)
            if not lottery:
                await self.message_helper.safe_edit(update, "抽奖不存在。")
                await session.commit()
                return

            current_chat_id = target_chat_id if target_chat_id is not None else chat.id
            if lottery.chat_id != current_chat_id:
                await self.message_helper.safe_edit(update, "此抽奖不属于当前群组。")
                await session.commit()
                return
            if lottery.status != "pending":
                await self.message_helper.safe_edit(update, "抽奖已开奖或已取消。")
                await session.commit()
                return

            participants = await get_lottery_participants(session, lottery_id)
            qualification_rules = lottery.qualification_rules or {}
            preset_winner_ids = qualification_rules.get("preset_winner_ids") or qualification_rules.get("fixed_winner_ids") or []
            eligible_user_ids = None
            if requires_lottery_subscribe(lottery):
                candidate_ids = {int(participant.user_id) for participant in participants}
                for raw_user_id in preset_winner_ids:
                    try:
                        user_id = int(raw_user_id)
                    except (TypeError, ValueError):
                        continue
                    if user_id > 0:
                        candidate_ids.add(user_id)
                eligible_user_ids = await filter_lottery_subscribed_user_ids(
                    context,
                    get_lottery_subscribe_targets(qualification_rules),
                    candidate_ids,
                    check_mode=qualification_rules.get("subscribe_check_mode") or "all",
                )
                participants = [participant for participant in participants if int(participant.user_id) in eligible_user_ids]
                filtered_preset_ids = []
                for raw_user_id in preset_winner_ids:
                    try:
                        user_id = int(raw_user_id)
                    except (TypeError, ValueError):
                        continue
                    if user_id in eligible_user_ids:
                        filtered_preset_ids.append(user_id)
                preset_winner_ids = filtered_preset_ids
            if not participants and not preset_winner_ids:
                await self.message_helper.safe_edit(update, "没有人参与抽奖。")
                await session.commit()
                return

            if lottery.draw_mode == LotteryDrawMode.manual.value:
                await session.commit()
                user_ids = [p.user_id for p in participants]
                stmt = select(TgUser).where(TgUser.id.in_(user_ids))
                result = await session.execute(stmt)
                users = {u.id: u for u in result.scalars().all()}
                for participant in participants:
                    participant.user_info = users.get(participant.user_id)

                prize_count = sum(int(prize.get("quantity", 1)) for prize in lottery.prizes)
                text = (
                    "📋 手动选择中奖人\n\n"
                    f"抽奖: {lottery.title}\n"
                    f"参与人数: {len(participants)}\n"
                    f"奖品数量: {prize_count}\n\n"
                    "请为每个奖项选择中奖人："
                )
                await self.message_helper.safe_edit(
                    update,
                    text=text,
                    reply_markup=manual_draw_summary_keyboard(lottery.chat_id, lottery_id, lottery.prizes),
                )
                return

            from backend.features.activity.services.lottery_service import (
                distribute_lottery_rewards,
                generate_lottery_announcement,
                perform_random_draw,
            )

            if eligible_user_ids is None:
                winners = await perform_random_draw(session, lottery)
            else:
                winners = await perform_random_draw(session, lottery, eligible_user_ids=eligible_user_ids)
            if winners:
                user_ids = [winner.user_id for winner in winners]
                user_stmt = select(TgUser).where(TgUser.id.in_(user_ids))
                user_result = await session.execute(user_stmt)
                users = {user.id: user for user in user_result.scalars().all()}

                await distribute_lottery_rewards(session, lottery, winners)
                setting = await get_or_create_lottery_setting(session, lottery.chat_id)
                lottery.status = "completed"
                lottery.drawn_at = dt.datetime.now(dt.timezone.utc)
                announcement = generate_lottery_announcement(lottery, winners, users)

                if target_chat_id is not None and update.effective_chat and update.effective_chat.type == "private":
                    sent = await context.bot.send_message(chat_id=lottery.chat_id, text=announcement, parse_mode="HTML")
                    if setting.result_pin_enabled:
                        try:
                            await context.bot.pin_chat_message(chat_id=lottery.chat_id, message_id=sent.message_id)
                        except Exception as exc:
                            log.warning(
                                "lottery_manual_draw_pin_failed",
                                lottery_id=lottery.id,
                                chat_id=lottery.chat_id,
                                message_id=sent.message_id,
                                error=str(exc),
                            )
                    await session.commit()
                    await self.message_helper.safe_edit(update, text="✅ 已在群内完成开奖并发布结果。")
                else:
                    sent = await self.message_helper.safe_edit(update, text=announcement, parse_mode="HTML")
                    if not sent:
                        await session.rollback()
                        return
                    await session.commit()
            else:
                await self.message_helper.safe_edit(update, "没有人参与抽奖。")
                await session.commit()
