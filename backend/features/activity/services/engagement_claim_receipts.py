"""Use immutable points facts when projecting legacy UTC reward days."""
import datetime as dt
from sqlalchemy import select
from backend.platform.db.schema.models.points import PointsTransaction
from backend.platform.db.schema.models.expansion_engagement import EngagementChatStat
from backend.shared.time_helper import LOCAL_TIMEZONE


async def reward_receipt(session,chat_id,user_id,*,day):
    start=dt.datetime.combine(day,dt.time.min,tzinfo=LOCAL_TIMEZONE).astimezone(dt.UTC)
    return await session.scalar(select(PointsTransaction).where(PointsTransaction.chat_id==chat_id,
        PointsTransaction.user_id==user_id,PointsTransaction.reason=='水群激励奖励',
        PointsTransaction.txn_type=='reward',PointsTransaction.amount>0,
        PointsTransaction.created_at>=start,PointsTransaction.created_at<start+dt.timedelta(days=1))
        .order_by(PointsTransaction.created_at.desc(),PointsTransaction.id.desc()).limit(1))


async def previous_streak(session,chat_id,user_id,*,day,fallback):
    receipt=await reward_receipt(session,chat_id,user_id,day=day)
    if receipt is None:
        return fallback
    legacy=await session.scalar(select(EngagementChatStat).where(EngagementChatStat.chat_id==chat_id,
        EngagementChatStat.user_id==user_id,EngagementChatStat.biz_date==receipt.created_at.astimezone(dt.UTC).date(),
        EngagementChatStat.reward_claimed.is_(True)))
    return max(1,int(legacy.streak_days or 0)) if legacy is not None else max(1,fallback)
