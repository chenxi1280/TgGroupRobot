"""键盘模块

提供 Telegram 机器人的各种键盘生成功能。

## 新的子包结构

- **base/**: 基础构建器和辅助函数
  - `CallbackBuilder`: 回调数据构建器
  - `KeyboardBuilder`: 键盘构建器（流式 API）
  - `PaginatedListBuilder`: 分页列表构建器
  - 辅助函数：`create_back_button`, `create_toggle_button` 等

- **formatters/**: 格式化工具
  - `StatusIcons`: 状态图标映射
  - `format_user_label`: 用户名格式化
  - `format_participant_count`: 参与人数格式化
  - `format_datetime`, `format_schedule_info` 等时间格式化

- **admin/**: 管理员相关键盘
- **activity/**: 活动相关键盘（抽奖、接龙）
- **content/**: 内容管理键盘（广告、自动回复、违禁词）
- **integration/**: 集成功能键盘（邀请链接、定时消息）
- **common/**: 通用键盘（验证、开始引导、群组选择）

## 迁移指南

如果之前使用：
```python
from bot.keyboards.lottery import lottery_menu_keyboard
```

现在请使用：
```python
from bot.keyboards.activity.lottery import lottery_menu_keyboard
```

完整映射见各子包的 `__init__.py` 文件。
"""

# === 基础构建器和工具 ===
from bot.keyboards.base import (
    CallbackBuilder,
    KeyboardBuilder,
    PaginatedListBuilder,
    create_action_button,
    create_back_button,
    create_confirmation_buttons,
    create_detail_button,
    create_link_button,
    create_menu_buttons,
    create_separator,
    create_toggle_button,
)

# === 格式化工具 ===
from bot.keyboards.formatters import (
    Icon,
    StatusIconSet,
    StatusIcons,
    format_bool_label,
    format_count_info,
    format_datetime,
    format_item_label,
    format_participant_count,
    format_range,
    format_schedule_info,
    format_user_label,
    truncate_text,
)

__all__ = [
    # === Base ===
    "CallbackBuilder",
    "KeyboardBuilder",
    "PaginatedListBuilder",
    "create_back_button",
    "create_confirmation_buttons",
    "create_toggle_button",
    "create_menu_buttons",
    "create_action_button",
    "create_detail_button",
    "create_link_button",
    "create_separator",
    # === Formatters ===
    "StatusIcons",
    "StatusIconSet",
    "Icon",
    "format_user_label",
    "format_participant_count",
    "format_datetime",
    "format_schedule_info",
    "truncate_text",
    "format_item_label",
    "format_count_info",
    "format_bool_label",
    "format_range",
]
