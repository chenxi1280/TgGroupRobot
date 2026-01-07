"""共享模块 - 提供通用的服务基类、结果对象和工具函数"""

from bot.services.shared.result import (
    ServiceResult,
    OperationResult,
    CreateResult,
    JoinResult,
    CloseResult,
)
from bot.services.shared.validators import (
    validate_user_permission,
    validate_positive_number,
)
from bot.services.shared.formatters import format_user_mention, format_datetime

__all__ = [
    # 结果对象
    "ServiceResult",
    "OperationResult",
    "CreateResult",
    "JoinResult",
    "CloseResult",
    # 验证器
    "validate_user_permission",
    "validate_positive_number",
    # 格式化工具
    "format_user_mention",
    "format_datetime",
]
