"""消息分发器模块

提供统一的消息分发机制，根据消息来源和用户角色，将消息分发到对应的处理器。
"""
from __future__ import annotations

from bot.handlers.dispatcher.message_dispatcher import MessageDispatcher
from bot.handlers.dispatcher.private_config_handler import PrivateConfigHandler
from bot.handlers.dispatcher.group_message_handler import GroupMessageHandler

__all__ = [
    "MessageDispatcher",
    "PrivateConfigHandler",
    "GroupMessageHandler",
]
