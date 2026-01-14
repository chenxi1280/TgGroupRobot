"""广告发送任务"""

from bot.services.automation.scheduler.core import ScheduledTask
from bot.services.automation.scheduler.task_config import TASK_CONFIG


class AdsTask(ScheduledTask):
    """广告发送任务"""

    def __init__(self):
        config = TASK_CONFIG["ads"]
        super().__init__(
            name="ads",
            interval=config["interval"],
            enabled=config["enabled"],
            max_consecutive_failures=config["max_consecutive_failures"],
        )

    async def execute(self, app) -> None:
        """执行广告发送逻辑"""
        from bot.services.automation.ad_service import (
            get_scheduled_ads,
            should_send_ad,
            mark_ad_sent,
            lock_ad_for_sending,
        )
        import asyncio
        import structlog

        log = structlog.get_logger(__name__)
        db = app.bot_data["db"]

        async with db.session_factory() as session:
            ads = await get_scheduled_ads(session)
            now = asyncio.get_event_loop().time()

            for ad in ads:
                if should_send_ad(ad):
                    # 尝试锁定广告（防止重复发送）
                    locked_ad = await lock_ad_for_sending(session, ad.id)
                    if not locked_ad:
                        log.info("ad_already_locked", ad_id=ad.id, title=ad.title)
                        continue

                    try:
                        # 发送广告
                        if locked_ad.has_image and locked_ad.image_file_id:
                            await app.bot.send_photo(
                                locked_ad.chat_id,
                                locked_ad.image_file_id,
                                caption=f"【{locked_ad.title}】\n\n{locked_ad.content}"
                            )
                        else:
                            await app.bot.send_message(
                                locked_ad.chat_id,
                                f"【{locked_ad.title}】\n\n{locked_ad.content}"
                            )

                        # 标记已发送并释放锁
                        await mark_ad_sent(session, locked_ad.id)
                        await session.commit()

                        log.info(
                            "ad_sent",
                            ad_id=locked_ad.id,
                            title=locked_ad.title,
                            chat_id=locked_ad.chat_id
                        )
                    except Exception as e:
                        # 发送失败，释放锁
                        locked_ad.send_locked = False
                        await session.commit()
                        log.error("ad_send_failed", ad_id=locked_ad.id, error=str(e))
