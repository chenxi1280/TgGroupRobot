from __future__ import annotations

from backend.platform.db.schema.models.core import Solitaire
from backend.platform.db.schema.models.enums import SolitaireStatus


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


def _format_solitaire_header(solitaire: Solitaire) -> list[str]:
    active = solitaire.status == SolitaireStatus.active.value
    status_emoji = "🟢" if active else "🔴"
    status_text = "进行中" if active else "已结束"
    entries_count = len(solitaire.entries_rel)
    count_text = (
        f"{entries_count}/{solitaire.max_participants}人"
        if solitaire.max_participants
        else f"{entries_count}人"
    )
    lines = [f"{status_emoji} {solitaire.title}", f"状态: {status_text} ({count_text})"]
    if solitaire.points_required:
        lines.append(f"💎 需积分: {solitaire.points_required}")
    if solitaire.deadline:
        lines.append(f"⏰ 截止: {solitaire.deadline.strftime('%Y-%m-%d %H:%M')}")
    if solitaire.description:
        lines.extend(["", solitaire.description])
    return lines


def _format_solitaire_entries(solitaire: Solitaire) -> list[str]:
    if not solitaire.entries_rel:
        return ["", "暂无人参与，快来接龙吧！"]
    lines = ["", "参与列表:"]
    for index, entry in enumerate(solitaire.entries_rel, 1):
        username = entry.username or f"用户{entry.user_id}"
        lines.append(f"{index}. {username}: {entry.content}")
    return lines


def format_solitaire_message(solitaire: Solitaire, show_closed: bool = True) -> str:
    """
    格式化接龙消息

    Args:
        solitaire: 接龙对象
        show_closed: 是否显示关闭按钮

    Returns:
        格式化后的接龙消息文本
    """
    lines = _format_solitaire_header(solitaire)
    lines.extend(_format_solitaire_entries(solitaire))
    if solitaire.status == SolitaireStatus.active.value and show_closed:
        lines.extend(["", "💡 回复接龙消息即可参与"])
    return "\n".join(lines)
