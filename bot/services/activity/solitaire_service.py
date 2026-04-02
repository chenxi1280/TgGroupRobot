from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.models.core import PointsAccount, Solitaire, SolitaireEntry
from bot.models.enums import SolitaireStatus
from bot.services.base import ServiceBase
from bot.services.shared.result import CloseResult, CreateResult, JoinResult


# ==================== 配置解析 ====================


def parse_config_value(line: str, prefix: str) -> str | None:
    """
    解析配置行中的值，支持中英文冒号

    Args:
        line: 配置行文本
        prefix: 配置项前缀（如"最大人数"、"参与积分"等）

    Returns:
        解析出的值，如果解析失败则返回 None
    """
    # 尝试两种分隔符
    for sep in (":", "："):
        full_prefix = f"{prefix}{sep}"
        if line.startswith(full_prefix):
            value = line[len(full_prefix):].strip()
            return value if value else None
    return None


# ==================== 格式化函数 ====================


def format_solitaire_stats_message(stats: dict[str, int]) -> str:
    """
    格式化接龙统计消息

    Args:
        stats: 统计数据字典，包含 total, active, closed, total_entries

    Returns:
        格式化后的接龙统计消息文本
    """
    return (
        f"📊 接龙统计\n\n"
        f"创建的接龙次数: {stats['total']}\n"
        f"进行中: {stats['active']}       已结束: {stats['closed']}\n"
        f"总参与人数: {stats['total_entries']}"
    )


async def create_solitaire(
    session: AsyncSession,
    chat_id: int,
    created_by_user_id: int,
    title: str,
    description: str | None = None,
    max_participants: int | None = None,
    points_required: int | None = None,
    deadline: dt.datetime | None = None,
) -> CreateResult:
    """
    创建接龙

    Args:
        session: 数据库会话
        chat_id: 群组 ID
        created_by_user_id: 创建者用户 ID
        title: 接龙标题
        description: 接龙描述
        max_participants: 最大参与人数
        points_required: 参与所需积分
        deadline: 截止时间

    Returns:
        CreateResult: 创建结果
    """
    try:
        solitaire = Solitaire(
            chat_id=chat_id,
            created_by_user_id=created_by_user_id,
            title=title,
            description=description,
            status=SolitaireStatus.active.value,
            max_participants=max_participants,
            points_required=points_required,
            deadline=deadline,
        )
        session.add(solitaire)
        await session.flush()

        # 重新查询以正确加载关系
        solitaire = await get_solitaire(session, solitaire.id)
        if solitaire is None:
            return CreateResult(success=False, reason="error", error="接龙创建后查询失败")

        return CreateResult(
            success=True,
            reason="ok",
            entity=solitaire,
            entity_id=solitaire.id,
            message_id=None,
        )
    except Exception:
        return CreateResult(success=False, reason="error")


async def get_chat_solitaires(
    session: AsyncSession,
    chat_id: int,
    active_only: bool = False,
) -> list[Solitaire]:
    """
    获取群组的接龙列表

    Args:
        session: 数据库会话
        chat_id: 群组 ID
        active_only: 是否只返回进行中的接龙

    Returns:
        接龙列表
    """
    # 使用基础查询获取列表
    solitaires = await ServiceBase._get_list(
        session,
        Solitaire,
        filters={"chat_id": chat_id},
        order_by="created_at",
        descending=True,
    )

    # 根据 active_only 过滤
    if active_only:
        solitaires = [s for s in solitaires if s.status == SolitaireStatus.active.value]

    # 为每个接龙加载参与记录
    result = []
    for solitaire in solitaires:
        stmt = select(Solitaire).options(
            selectinload(Solitaire.entries_rel)
        ).where(Solitaire.id == solitaire.id)
        solitaire_result = await session.execute(stmt)
        loaded_solitaire = solitaire_result.scalar_one_or_none()
        if loaded_solitaire:
            result.append(loaded_solitaire)

    return result


async def get_solitaire(
    session: AsyncSession,
    solitaire_id: int,
) -> Solitaire | None:
    """
    获取接龙

    Args:
        session: 数据库会话
        solitaire_id: 接龙 ID

    Returns:
        Solitaire: 接龙对象，如果不存在则返回 None
    """
    stmt = select(Solitaire).options(
        selectinload(Solitaire.entries_rel)
    ).where(Solitaire.id == solitaire_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_solitaire_in_chat(
    session: AsyncSession,
    chat_id: int,
    solitaire_id: int,
) -> Solitaire | None:
    """按群组作用域获取接龙，避免跨群访问。"""
    stmt = select(Solitaire).options(
        selectinload(Solitaire.entries_rel)
    ).where(
        Solitaire.id == solitaire_id,
        Solitaire.chat_id == chat_id,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def join_solitaire(
    session: AsyncSession,
    solitaire_id: int,
    user_id: int,
    username: str | None,
    content: str,
) -> JoinResult:
    """
    参与接龙

    Args:
        session: 数据库会话
        solitaire_id: 接龙 ID
        user_id: 用户 ID
        username: 用户名
        content: 参与内容

    Returns:
        JoinResult: 参与结果
    """
    solitaire = await get_solitaire(session, solitaire_id)
    if not solitaire:
        return JoinResult(success=False, reason="not_found")

    if solitaire.status != SolitaireStatus.active.value:
        return JoinResult(success=False, reason="already_closed", entity=solitaire)

    # 检查截止时间
    if solitaire.deadline:
        now = dt.datetime.now(dt.UTC)
        if now > solitaire.deadline:
            return JoinResult(success=False, reason="expired", entity=solitaire)

    # 检查是否已参与
    existing = await ServiceBase._get_by_filters(
        session,
        SolitaireEntry,
        {"solitaire_id": solitaire_id, "user_id": user_id},
    )
    if existing:
        return JoinResult(success=False, reason="already_joined", entity=solitaire)

    # 检查人数限制
    current_count = len(solitaire.entries_rel)
    if solitaire.max_participants and current_count >= solitaire.max_participants:
        return JoinResult(success=False, reason="full", entity=solitaire)

    # 检查积分限制
    if solitaire.points_required and solitaire.points_required > 0:
        # 如果用户没有积分账户，user_points 默认为 0
        user_points = 0
        points_account = await ServiceBase._get_by_filters(
            session,
            PointsAccount,
            {"chat_id": solitaire.chat_id, "user_id": user_id},
        )
        if points_account:
            user_points = points_account.balance

        if user_points < solitaire.points_required:
            return JoinResult(success=False, reason="insufficient_points", entity=solitaire)

    # 创建参与记录
    entry = SolitaireEntry(
        solitaire_id=solitaire_id,
        user_id=user_id,
        username=username,
        content=content,
        joined_at=dt.datetime.now(dt.UTC),
    )
    session.add(entry)
    return JoinResult(success=True, reason="ok", entity=solitaire)


async def update_entry(
    session: AsyncSession,
    solitaire_id: int,
    user_id: int,
    content: str,
) -> JoinResult:
    """
    更新参与内容

    Args:
        session: 数据库会话
        solitaire_id: 接龙 ID
        user_id: 用户 ID
        content: 新的参与内容

    Returns:
        JoinResult: 更新结果
    """
    solitaire = await get_solitaire(session, solitaire_id)
    if not solitaire:
        return JoinResult(success=False, reason="not_found")

    if solitaire.status != SolitaireStatus.active.value:
        return JoinResult(success=False, reason="already_closed", entity=solitaire)

    # 查找并更新
    entry = await ServiceBase._get_by_filters(
        session,
        SolitaireEntry,
        {"solitaire_id": solitaire_id, "user_id": user_id},
    )

    if entry:
        await ServiceBase._update_entity(
            session,
            entry,
            {
                "content": content,
                "updated_at": dt.datetime.now(dt.UTC),
            },
        )
        return JoinResult(success=True, reason="ok", entity=solitaire)

    return JoinResult(success=False, reason="not_found", entity=solitaire)


async def leave_solitaire(
    session: AsyncSession,
    solitaire_id: int,
    user_id: int,
) -> JoinResult:
    """
    退出接龙

    Args:
        session: 数据库会话
        solitaire_id: 接龙 ID
        user_id: 用户 ID

    Returns:
        JoinResult: 退出结果
    """
    solitaire = await get_solitaire(session, solitaire_id)
    if not solitaire:
        return JoinResult(success=False, reason="not_found")

    if solitaire.status != SolitaireStatus.active.value:
        return JoinResult(success=False, reason="already_closed", entity=solitaire)

    # 查找并删除
    entry = await ServiceBase._get_by_filters(
        session,
        SolitaireEntry,
        {"solitaire_id": solitaire_id, "user_id": user_id},
    )

    if entry:
        await ServiceBase._delete_entity(session, entry)
        return JoinResult(success=True, reason="ok", entity=solitaire)

    return JoinResult(success=False, reason="not_found", entity=solitaire)


async def close_solitaire(
    session: AsyncSession,
    solitaire_id: int,
    *,
    chat_id: int | None = None,
) -> CloseResult:
    """
    结束接龙

    Args:
        session: 数据库会话
        solitaire_id: 接龙 ID

    Returns:
        CloseResult: 结束结果
    """
    solitaire = await (
        get_solitaire_in_chat(session, chat_id, solitaire_id)
        if chat_id is not None
        else get_solitaire(session, solitaire_id)
    )
    if not solitaire:
        return CloseResult(success=False, reason="not_found")

    if solitaire.status != SolitaireStatus.active.value:
        return CloseResult(success=False, reason="already_closed", entity=solitaire)

    await ServiceBase._update_entity(
        session,
        solitaire,
        {"status": SolitaireStatus.closed.value},
    )
    return CloseResult(success=True, reason="ok", entity=solitaire)


async def delete_solitaire(
    session: AsyncSession,
    solitaire_id: int,
    *,
    chat_id: int | None = None,
) -> bool:
    """
    删除接龙

    Args:
        session: 数据库会话
        solitaire_id: 接龙 ID

    Returns:
        是否删除成功
    """
    solitaire = await (
        get_solitaire_in_chat(session, chat_id, solitaire_id)
        if chat_id is not None
        else get_solitaire(session, solitaire_id)
    )
    if not solitaire:
        return False
    await ServiceBase._delete_entity(session, solitaire)
    return True


async def get_solitaire_stats(
    session: AsyncSession,
    chat_id: int,
) -> dict[str, int]:
    """
    获取接龙统计

    Args:
        session: 数据库会话
        chat_id: 群组 ID

    Returns:
        统计数据字典，包含 total, active, closed, total_entries
    """
    solitaires = await get_chat_solitaires(session, chat_id)
    total_entries = 0
    for s in solitaires:
        # 使用 entries_rel 关系获取参与记录数量
        total_entries += len(s.entries_rel)
    return {
        "total": len(solitaires),
        "active": sum(1 for s in solitaires if s.status == SolitaireStatus.active.value),
        "closed": sum(1 for s in solitaires if s.status == SolitaireStatus.closed.value),
        "total_entries": total_entries,
    }


def format_solitaire_message(solitaire: Solitaire, show_closed: bool = True) -> str:
    """
    格式化接龙消息

    Args:
        solitaire: 接龙对象
        show_closed: 是否显示关闭按钮

    Returns:
        格式化后的接龙消息文本
    """
    status_emoji = "🟢" if solitaire.status == SolitaireStatus.active.value else "🔴"
    status_text = "进行中" if solitaire.status == SolitaireStatus.active.value else "已结束"

    text = f"{status_emoji} {solitaire.title}\n"
    text += f"状态: {status_text}"

    # 使用 entries_rel 获取参与记录
    entries_count = len(solitaire.entries_rel)
    if solitaire.max_participants:
        text += f" ({entries_count}/{solitaire.max_participants}人)"
    else:
        text += f" ({entries_count}人)"
    text += "\n"

    # 积分限制
    if solitaire.points_required:
        text += f"💎 需积分: {solitaire.points_required}\n"

    # 截止时间
    if solitaire.deadline:
        deadline_str = solitaire.deadline.strftime("%Y-%m-%d %H:%M")
        text += f"⏰ 截止: {deadline_str}\n"

    if solitaire.description:
        text += f"\n{solitaire.description}\n"

    # 使用 entries_rel 关系显示参与列表
    if solitaire.entries_rel:
        text += "\n参与列表:\n"
        for i, entry in enumerate(solitaire.entries_rel, 1):
            username = entry.username or f"用户{entry.user_id}"
            text += f"{i}. {username}: {entry.content}\n"
    else:
        text += "\n暂无人参与，快来接龙吧！\n"

    if solitaire.status == SolitaireStatus.active.value and show_closed:
        text += "\n💡 回复接龙消息即可参与"

    return text
