"""抽奖自动开奖任务"""

from backend.platform.scheduler.core.core import ScheduledTask
from backend.platform.scheduler.core.task_config import TASK_CONFIG


class LotteryTask(ScheduledTask):
    """抽奖自动开奖任务"""

    def __init__(self):
        config = TASK_CONFIG["lottery"]
        super().__init__(
            name="lottery",
            interval=config["interval"],
            enabled=config["enabled"],
            max_consecutive_failures=config["max_consecutive_failures"],
        )

    async def execute(self, app) -> None:
        """执行开奖逻辑"""
        from sqlalchemy import or_, select
        from backend.platform.db.schema.models.core import Lottery, TgUser
        from backend.features.activity.services.lottery_service import (
            perform_random_draw,
            generate_lottery_announcement,
            distribute_lottery_rewards,
        )
        import datetime as dt
        import structlog

        log = structlog.get_logger(__name__)
        db = app.bot_data["db"]

        async with db.session_factory() as session:
            # 查找待开奖且已过期的抽奖
            now = dt.datetime.now(dt.UTC)
            stmt = select(Lottery).where(
                Lottery.status == "pending",
                Lottery.draw_time <= now,
                or_(
                    Lottery.qualification_rules["draw_trigger"].astext.is_(None),
                    Lottery.qualification_rules["draw_trigger"].astext == "time_deadline",
                ),
            )
            result = await session.execute(stmt)
            lotteries = result.scalars().all()

            for lottery in lotteries:
                try:
                    # 执行随机开奖
                    winners = await perform_random_draw(session, lottery)

                    if winners:
                        # 获取中奖用户信息
                        user_ids = [w.user_id for w in winners]
                        user_stmt = select(TgUser).where(TgUser.id.in_(user_ids))
                        user_result = await session.execute(user_stmt)
                        users = {u.id: u for u in user_result.scalars().all()}

                        await distribute_lottery_rewards(session, lottery, winners)

                        announcement = generate_lottery_announcement(lottery, winners, users)

                        try:
                            await app.bot.send_message(
                                chat_id=lottery.chat_id,
                                text=announcement,
                                parse_mode="HTML"
                            )
                            log.info(
                                "auto_draw_lottery_success",
                                lottery_id=lottery.id,
                                chat_id=lottery.chat_id,
                                winners_count=len(winners),
                            )
                        except Exception as e:
                            log.error("auto_draw_announcement_failed", lottery_id=lottery.id, error=str(e))
                            await session.rollback()
                            continue

                        lottery.status = "completed"
                        lottery.drawn_at = now

                    else:
                        try:
                            await app.bot.send_message(
                                chat_id=lottery.chat_id,
                                text=f"🎉 抽奖【{lottery.title}】开奖结果\n\n😔 因无人参与，本次抽奖流拍。"
                            )
                        except Exception as e:
                            log.error("auto_draw_no_participants_failed", lottery_id=lottery.id, error=str(e))
                            await session.rollback()
                            continue
                        lottery.status = "completed"
                        lottery.drawn_at = now

                    await session.commit()
                    log.info("auto_draw_lottery_success", lottery_id=lottery.id)

                except Exception as e:
                    log.error("auto_draw_lottery_failed", lottery_id=lottery.id, error=str(e))
                    await session.rollback()
                    continue  # 继续处理下一个抽奖
