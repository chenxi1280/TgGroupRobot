"""拍卖自动结算任务"""

from __future__ import annotations

import structlog
from types import SimpleNamespace

from backend.platform.scheduler.core.core import ScheduledTask
from backend.platform.scheduler.core.task_config import TASK_CONFIG
from backend.features.activity.services.auction_service import (
    format_auction_announcement,
    get_or_create_setting,
    list_due_auction_ids,
    settle_due_auction,
)
from backend.shared.services.publish_service import PublishService

log = structlog.get_logger(__name__)


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
            item_ids = await list_due_auction_ids(session)
            await session.commit()
        for item_id in item_ids:
            async with db.session_factory() as session:
                result = await settle_due_auction(session, item_id)
                if result is None:
                    await session.commit()
                    continue
                try:
                    setting = await get_or_create_setting(session, result.item.chat_id)
                    text = format_auction_announcement(
                        result.item,
                        is_final=True,
                        settlement_note=result.note,
                    )
                    context = SimpleNamespace(bot=app.bot, application=app)
                    sent = await PublishService.send(
                        context,
                        chat_id=result.item.chat_id,
                        text=text,
                        parse_mode="Markdown",
                    )
                    result.item.last_announce_message_id = sent.message_id
                    chat_id = int(result.item.chat_id)
                    message_id = int(sent.message_id)
                    if setting.pin_message_enabled:
                        try:
                            await PublishService.pin(
                                context,
                                chat_id=chat_id,
                                message_id=message_id,
                                disable_notification=True,
                            )
                        except Exception as exc:
                            log.warning("auction_result_pin_failed", item_id=item_id, message_id=message_id, error=str(exc))
                except Exception as exc:
                    await session.rollback()
                    log.error("auction_result_announcement_failed", item_id=item_id, error=str(exc))
                    continue
                await session.commit()
            await session.commit()
