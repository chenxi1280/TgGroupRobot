"""Bounded level/custom-point pages, with return positions scoped per group."""
from sqlalchemy import func, select

from backend.platform.db.schema.models.core import CustomPointType, PointsLevel

PAGE_SIZE = 8


def remembered_page(context, chat_id, feature, *, page=None):
    positions = context.user_data.setdefault("points_list_pages", {})
    key = f"{chat_id}:{feature}"
    if page is not None:
        positions[key] = max(0, int(page))
    return positions.get(key, 0)


async def point_page(session, chat_id, *, feature, page):
    model = PointsLevel if feature == "levels" else CustomPointType
    order = (PointsLevel.point_threshold, PointsLevel.level_no) if feature == "levels" else (CustomPointType.type_no, CustomPointType.id)
    total = int(await session.scalar(select(func.count()).select_from(model).where(model.chat_id == chat_id)))
    page = min(max(0, page), max(0, (total - 1) // PAGE_SIZE))
    rows = list((await session.scalars(select(model).where(model.chat_id == chat_id)
                                     .order_by(*order).offset(page * PAGE_SIZE).limit(PAGE_SIZE))).all())
    return rows, total, page
