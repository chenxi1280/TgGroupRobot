"""拍卖自动结算任务"""

from __future__ import annotations

from backend.platform.scheduler.core.core import ScheduledTask
from backend.platform.scheduler.core.task_config import TASK_CONFIG
from backend.features.activity.services.auction_service import format_auction_announcement, get_or_create_setting, settle_due_auctions


class AuctionTask(ScheduledTask):
    def __init__(self) -> None:
        config = TASK_CONFIG["auction"]
        super().__init__(
            name="auction",
            interval=config["interval"],
            enabled=config["enabled"],
            max_consecutive_failures=config["max_consecutive_failures"],
        )

    async def execute(self, app) -> None:
        db = app.bot_data["db"]
        async with db.session_factory() as session:
            results = await settle_due_auctions(session)
            for result in results:
                setting = await get_or_create_setting(session, result.item.chat_id)
                text = format_auction_announcement(
                    result.item,
                    is_final=True,
                    settlement_note=result.note,
                )
                sent = await app.bot.send_message(
                    chat_id=result.item.chat_id,
                    text=text,
                    parse_mode="Markdown",
                )
                result.item.last_announce_message_id = sent.message_id
                if setting.pin_message_enabled:
                    try:
                        await app.bot.pin_chat_message(result.item.chat_id, sent.message_id, disable_notification=True)
                    except Exception:
                        pass
            await session.commit()
