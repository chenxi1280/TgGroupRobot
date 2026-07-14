"""抽奖相关响应格式化类

提供抽奖功能的消息格式化方法。
"""
from __future__ import annotations

from datetime import datetime

from backend.platform.db.schema.models.core import Lottery


class LotteryResponse:
    """抽奖响应格式化类

    提供抽奖相关的消息格式化方法。
    """

    @staticmethod
    def format_lottery_menu(chat_title: str | None, stats: dict[str, int]) -> str:
        """格式化抽奖菜单

        Args:
            chat_title: 群组标题
            stats: 抽奖统计数据

        Returns:
            str: 格式化后的抽奖菜单
        """
        title = chat_title or "群组"
        text = f"🎁 [{title}] 抽奖\n\n"
        text += f"创建的抽奖次数: {stats['total']}\n\n"
        text += f"已开奖: {stats['completed']}       未开奖: {stats['pending']}       取消: {stats['cancelled']}"
        return text

    @staticmethod
    def format_lottery_list(lotteries: list[Lottery], chat_title: str | None = None) -> str:
        """格式化抽奖列表

        Args:
            lotteries: 抽奖列表
            chat_title: 群组标题（可选）

        Returns:
            str: 格式化后的抽奖列表
        """
        if not lotteries:
            return "📋 抽奖列表\n\n暂无抽奖，点击「创建抽奖」开始"

        title = chat_title or "群组"
        text = f"📋 [{title}] 抽奖列表\n\n共 {len(lotteries)} 个抽奖\n\n"

        for lottery in lotteries:
            status_emoji = LotteryResponse._get_status_emoji(lottery.status)
            text += f"{status_emoji} {lottery.title}\n"
            text += f"    ID: {lottery.id}\n"
            text += f"    参与人数: {lottery.participant_count}\n"

            if lottery.draw_time:
                text += f"    开奖时间: {lottery.draw_time.strftime('%Y-%m-%d %H:%M')}\n"

            text += "\n"

        return text

    @staticmethod
    def format_lottery_created(lottery: Lottery) -> str:
        """格式化创建成功消息

        Args:
            lottery: 创建的抽奖对象

        Returns:
            str: 格式化后的创建成功消息
        """
        text = "✅ 抽奖创建成功！\n\n"
        text += f"📢 标题: {lottery.title}\n"
        text += f"🎯 抽奖ID: {lottery.id}\n"

        if lottery.draw_time:
            text += f"🕐 开奖时间: {lottery.draw_time.strftime('%Y-%m-%d %H:%M:%S')}\n"

        text += f"👥 参与人数限制: {lottery.max_participants or '无限制'}\n"
        text += f"🔖 积分消耗: {lottery.points_cost}\n"

        return text

    @staticmethod
    def format_lottery_announcement(lottery: Lottery) -> str:
        """格式化抽奖公告

        Args:
            lottery: 抽奖对象

        Returns:
            str: 格式化后的抽奖公告
        """
        text = "🎁【抽奖活动】\n\n"
        text += f"📢 {lottery.title}\n"

        if lottery.description:
            text += f"\n{lottery.description}\n"

        text += f"\n🎯 抽奖ID: {lottery.id}\n"

        if lottery.draw_time:
            text += f"🕐 开奖时间: {lottery.draw_time.strftime('%Y-%m-%d %H:%M:%S')}\n"

        text += f"👥 参与人数限制: {lottery.max_participants or '无限制'}\n"
        text += f"🔖 积分消耗: {lottery.points_cost}\n"
        text += f"👥 已参与: {lottery.participant_count} 人\n"

        return text

    @staticmethod
    def format_lottery_joined(lottery: Lottery) -> str:
        """格式化参与成功消息

        Args:
            lottery: 抽奖对象

        Returns:
            str: 格式化后的参与成功消息
        """
        return f"✅ 已参与抽奖【{lottery.title}】！"

    @staticmethod
    def format_lottery_completed(lottery: Lottery, winners: list[tuple[int, str]]) -> str:
        """格式化开奖完成消息

        Args:
            lottery: 抽奖对象
            winners: 中奖者列表 [(user_id, username), ...]

        Returns:
            str: 格式化后的开奖完成消息
        """
        text = f"🎉 抽奖【{lottery.title}】开奖结果\n\n"

        if winners:
            text += "🏆 中奖用户：\n"
            for i, (user_id, username) in enumerate(winners, 1):
                display_name = username or f"用户{user_id}"
                text += f"{i}. {display_name}\n"
        else:
            text += "❌ 本期无人中奖"

        return text

    @staticmethod
    def format_lottery_detail(lottery: Lottery) -> str:
        """格式化抽奖详情

        Args:
            lottery: 抽奖对象

        Returns:
            str: 格式化后的抽奖详情
        """
        status_emoji = LotteryResponse._get_status_emoji(lottery.status)
        status_text = LotteryResponse._get_status_text(lottery.status)

        text = "📋 抽奖详情\n\n"
        text += f"📢 标题: {lottery.title}\n"
        text += f"🆔 ID: {lottery.id}\n"
        text += f"📊 状态: {status_emoji} {status_text}\n"

        if lottery.description:
            text += f"📝 描述: {lottery.description}\n"

        if lottery.draw_time:
            text += f"🕐 开奖时间: {lottery.draw_time.strftime('%Y-%m-%d %H:%M:%S')}\n"

        text += f"👥 参与人数: {lottery.participant_count}/{lottery.max_participants or '无限制'}\n"
        text += f"🔖 积分消耗: {lottery.points_cost}\n"

        return text

    @staticmethod
    def _get_status_emoji(status: str) -> str:
        """获取状态表情

        Args:
            status: 状态值

        Returns:
            str: 状态表情
        """
        status_map = {
            "pending": "🟢",
            "completed": "✅",
            "cancelled": "❌",
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
            "pending": "未开奖",
            "completed": "已开奖",
            "cancelled": "已取消",
        }
        return status_map.get(status, "未知")
