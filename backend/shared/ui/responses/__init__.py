"""响应格式化模块 - 统一消息格式化"""

from backend.shared.ui.responses.common import CommonResponse
from backend.shared.ui.responses.lottery import LotteryResponse
from backend.shared.ui.responses.solitaire import SolitaireResponse

__all__ = [
    "CommonResponse",
    "LotteryResponse",
    "SolitaireResponse",
]
