"""响应格式化模块 - 统一消息格式化"""

from bot.responses.common import CommonResponse
from bot.responses.lottery import LotteryResponse
from bot.responses.solitaire import SolitaireResponse

__all__ = [
    "CommonResponse",
    "LotteryResponse",
    "SolitaireResponse",
]
