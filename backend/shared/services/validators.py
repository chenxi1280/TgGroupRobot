"""通用验证器函数和工具。"""

from __future__ import annotations

from backend.shared.services.validator_db import validate_exists, validate_unique
from backend.shared.services.validator_decorators import validate_params
from backend.shared.services.validator_fields import (
    validate_enum,
    validate_future_time,
    validate_positive_number,
    validate_range,
    validate_regex,
    validate_required,
    validate_string_length,
    validate_url,
)
from backend.shared.services.validator_permissions import (
    validate_bot_permission,
    validate_user_in_group,
    validate_user_is_admin,
    validate_user_permission,
)

__all__ = [
    "validate_bot_permission",
    "validate_enum",
    "validate_exists",
    "validate_future_time",
    "validate_params",
    "validate_positive_number",
    "validate_range",
    "validate_regex",
    "validate_required",
    "validate_string_length",
    "validate_unique",
    "validate_url",
    "validate_user_in_group",
    "validate_user_is_admin",
    "validate_user_permission",
]
