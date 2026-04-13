"""接龙自动结束任务"""

from backend.platform.scheduler.core.core import ScheduledTask
from backend.platform.scheduler.core.task_config import TASK_CONFIG


class SolitaireTask(ScheduledTask):
    """接龙自动结束任务"""

    def __init__(self):
        config = TASK_CONFIG["solitaire"]
        super().__init__(
            name="solitaire",
            interval=config["interval"],
            enabled=config["enabled"],
            max_consecutive_failures=config["max_consecutive_failures"],
        )

    async def execute(self, app) -> None:
        """执行过期接龙关闭逻辑"""
        from sqlalchemy import select
        from backend.platform.db.schema.models.core import Solitaire
        from backend.platform.db.schema.models.enums import SolitaireStatus
        from backend.features.activity.services.solitaire_service import close_solitaire, format_solitaire_message
        import datetime as dt
        import structlog

        log = structlog.get_logger(__name__)
        db = app.bot_data["db"]

        async with db.session_factory() as session:
            # 查询所有进行中且有截止时间的接龙
            stmt = select(Solitaire).where(
                Solitaire.status == SolitaireStatus.active.value,
                Solitaire.deadline.isnot(None)
            )
            result = await session.execute(stmt)
            solitaires = result.scalars().all()

            now = dt.datetime.now(dt.timezone.utc)
            closed_count = 0

            for solitaire in solitaires:
                # 检查是否过期
                if solitaire.deadline and now > solitaire.deadline:
                    close_result = await close_solitaire(session, solitaire.id)
                    if close_result.success:
                        closed_count += 1

                        # 获取参与人数
                        entries_count = len(close_result.solitaire.entries_rel)

                        # 在群组中发送过期通知
                        try:
                            await app.bot.send_message(
                                chat_id=solitaire.chat_id,
                                text=f"⏰ 接龙已截止\n\n{solitaire.title}\n参与人数: {entries_count} 人"
                            )
                        except Exception as e:
                            log.error("solitaire_expired_notification_failed", solitaire_id=solitaire.id, error=str(e))

                        # 更新群组中的原始接龙消息
                        if solitaire.message_id:
                            try:
                                group_text = format_solitaire_message(close_result.solitaire, show_closed=False)
                                await app.bot.edit_message_text(
                                    chat_id=solitaire.chat_id,
                                    message_id=solitaire.message_id,
                                    text=group_text
                                )
                            except Exception as e:
                                log.error("solitaire_update_group_message_failed", solitaire_id=solitaire.id, error=str(e))

            await session.commit()

            if closed_count > 0:
                log.info("solitaires_auto_closed", count=closed_count)
