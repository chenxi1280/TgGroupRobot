"""接龙相关响应格式化类

提供接龙功能的消息格式化方法。
"""
from __future__ import annotations

from backend.platform.db.schema.models.core import Solitaire
_FORMAT_CREATE_PROMPT_THRESHOLD_2 = 2



class SolitaireResponse:
    """接龙响应格式化类

    提供接龙相关的消息格式化方法。
    """

    @staticmethod
    def format_solitaire_menu(chat_title: str | None = None) -> str:
        """格式化接龙菜单

        Args:
            chat_title: 群组标题（可选）

        Returns:
            str: 格式化后的接龙菜单
        """
        title = chat_title or "群组"
        return f"📋 [{title}] 接龙管理\n\n管理群内接龙活动"

    @staticmethod
    def format_solitaire_list(solitaires: list[Solitaire], chat_title: str | None = None) -> str:
        """格式化接龙列表

        Args:
            solitaires: 接龙列表
            chat_title: 群组标题（可选）

        Returns:
            str: 格式化后的接龙列表
        """
        if not solitaires:
            return "📋 接龙列表\n\n暂无接龙，点击「创建接龙」开始"

        title = chat_title or "群组"
        text = f"📋 [{title}] 接龙列表\n\n共 {len(solitaires)} 个接龙\n\n"

        for solitaire in solitaires:
            status_emoji = SolitaireResponse._get_status_emoji(solitaire.status)
            text += f"{status_emoji} {solitaire.title}\n"
            text += f"    ID: {solitaire.id}\n"
            text += f"    参与人数: {solitaire.participant_count}\n"

            if solitaire.deadline:
                text += f"    截止时间: {solitaire.deadline.strftime('%Y-%m-%d %H:%M')}\n"

            text += "\n"

        return text

    @staticmethod
    def format_solitaire_created(solitaire: Solitaire) -> str:
        """格式化创建成功消息

        Args:
            solitaire: 创建的接龙对象

        Returns:
            str: 格式化后的创建成功消息
        """
        text = f"✅ 接龙创建成功！\n\n"
        text += f"📢 标题: {solitaire.title}\n"
        text += f"🎯 接龙ID: {solitaire.id}\n"

        if solitaire.description:
            text += f"📝 描述: {solitaire.description}\n"

        if solitaire.deadline:
            text += f"🕐 截止时间: {solitaire.deadline.strftime('%Y-%m-%d %H:%M')}\n"

        text += f"👥 参与人数: {solitaire.participant_count}\n"

        return text

    @staticmethod
    def format_solitaire_announcement(solitaire: Solitaire) -> str:
        """格式化接龙公告

        Args:
            solitaire: 接龙对象

        Returns:
            str: 格式化后的接龙公告
        """
        text = f"📋【接龙活动】\n\n"
        text += f"📢 {solitaire.title}\n"

        if solitaire.description:
            text += f"\n{solitaire.description}\n"

        text += f"\n🎯 接龙ID: {solitaire.id}\n"
        text += f"👥 已参与: {solitaire.participant_count} 人\n"

        if solitaire.deadline:
            text += f"🕐 截止时间: {solitaire.deadline.strftime('%Y-%m-%d %H:%M')}\n"

        return text

    @staticmethod
    def format_solitaire_participants(solitaire: Solitaire, participants: list[tuple[int, str, str]]) -> str:
        """格式化接龙参与者列表

        Args:
            solitaire: 接龙对象
            participants: 参与者列表 [(user_id, content, username), ...]

        Returns:
            str: 格式化后的参与者列表
        """
        text = f"📋 接龙详情：{solitaire.title}\n\n"

        if solitaire.description:
            text += f"{solitaire.description}\n\n"

        if participants:
            text += "参与列表：\n"
            for i, (user_id, content, username) in enumerate(participants, 1):
                display_name = username or f"用户{user_id}"
                text += f"{i}. {display_name}: {content}\n"
        else:
            text += "暂无参与者"

        return text

    @staticmethod
    def format_solitaire_closed(solitaire: Solitaire, participant_count: int) -> str:
        """格式化接龙关闭消息

        Args:
            solitaire: 接龙对象
            participant_count: 参与人数

        Returns:
            str: 格式化后的关闭消息
        """
        return f"✅ 接龙【{solitaire.title}】已关闭，共 {participant_count} 人参与"

    @staticmethod
    def format_solitaire_detail(solitaire: Solitaire) -> str:
        """格式化接龙详情

        Args:
            solitaire: 接龙对象

        Returns:
            str: 格式化后的接龙详情
        """
        status_emoji = SolitaireResponse._get_status_emoji(solitaire.status)
        status_text = SolitaireResponse._get_status_text(solitaire.status)

        text = f"📋 接龙详情\n\n"
        text += f"📢 标题: {solitaire.title}\n"
        text += f"🆔 ID: {solitaire.id}\n"
        text += f"📊 状态: {status_emoji} {status_text}\n"

        if solitaire.description:
            text += f"📝 描述: {solitaire.description}\n"

        if solitaire.deadline:
            text += f"🕐 截止时间: {solitaire.deadline.strftime('%Y-%m-%d %H:%M')}\n"

        text += f"👥 参与人数: {solitaire.participant_count}\n"

        return text

    @staticmethod
    def format_create_prompt(step: int = 1) -> str:
        """格式化创建接龙提示

        Args:
            step: 当前步骤

        Returns:
            str: 格式化后的创建提示
        """
        if step == 1:
            return "➕ 创建接龙 ( /cancel 取消)\n\n请输入接龙标题"
        elif step == _FORMAT_CREATE_PROMPT_THRESHOLD_2:
            return "请输入接龙描述（可选）\n\n输入 /skip 跳过"
        return "请输入接龙信息"

    @staticmethod
    def _get_status_emoji(status: str) -> str:
        """获取状态表情

        Args:
            status: 状态值

        Returns:
            str: 状态表情
        """
        status_map = {
            "active": "🟢",
            "closed": "✅",
        }
        return status_map.get(status, "⚪")

    @staticmethod
    def _get_status_text(status: str) -> str:
        """获取状态文本

        Args:
            status: 状态值

        Returns:
            str: 状态文本
        """
        status_map = {
            "active": "进行中",
            "closed": "已关闭",
        }
        return status_map.get(status, "未知")
