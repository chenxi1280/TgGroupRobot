from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from sqlalchemy import func, select

from backend.features.admin.points_config_messages import (
    handle_points_config_cancel,
    handle_points_config_message,
)
from backend.features.admin.points_config_shared import (
    WAIT_VALUE,
    resolve_points_target_user as _resolve_points_target_user,
    safe_edit_message as _safe_edit_message,
)
from backend.features.admin.points_config_views import (
    handle_todo,
    handle_view,
    load_settings,
    show_points_home,
    show_rule_page,
)
from backend.platform.db.runtime.session import Database
from backend.shared.handlers.base.base_handler import BaseHandler
from backend.features.admin.ui.points import back_button, points_config_keyboard, points_rule_keyboard
from backend.platform.db.schema.models.core import PointsAccount, PointsTransaction, SignInLog, TgUser, UserDailyStats
from backend.platform.db.schema.models.enums import PointsTxnType
from backend.features.points.services.points_service import change_points, get_balance
from backend.shared.services.chat_service import get_chat_settings
from backend.shared.callback_parser import CallbackParser
_POINTS_CONFIG_CALLBACK_THRESHOLD_4 = 4



class PointsConfigHandler(BaseHandler):
    """积分配置 Handler"""

    def __init__(self) -> None:
        super().__init__()
        # 关闭默认权限检查，因为我们在 process 中自己处理
        self._require_admin_permission = False

    async def process(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
    ) -> None:
        """处理积分配置回调"""
        q = update.callback_query
        await q.answer()

        # 只在私聊中处理
        if not self.chat_resolver.is_private_chat(update):
            await _safe_edit_message(q, "请在私聊中使用此功能")
            return

        # 解析 callback data
        callback_data = CallbackParser.parse(q.data)
        action = callback_data.get(1)
        field = callback_data.get(2)

        # 根据操作类型分发
        if action == "home":
            await self._show_points_home(update, context, target_chat_id, changed=False)
        elif action == "toggle":
            await self._handle_toggle(update, context, target_chat_id, field)
        elif action == "edit":
            return await self._handle_edit(update, context, target_chat_id, field=field)
        elif action == "rule":
            await self._handle_rule(update, context, target_chat_id, rule_type=field)
        elif action == "view":
            await self._handle_view(update, context, target_chat_id, feature=field)
        elif action == "todo":
            return await self._handle_todo(update, context, target_chat_id, feature=field)
        elif action == "cancel":
            await self._handle_cancel(update, context, target_chat_id)
        return None

    async def _load_settings(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
        return await load_settings(context, chat_id, get_chat_settings_func=get_chat_settings)

    async def _show_points_home(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *,
        changed: bool = False,
    ) -> None:
        await show_points_home(
            update,
            context,
            chat_id,
            changed=changed,
            get_chat_settings_func=get_chat_settings,
            safe_edit_func=_safe_edit_message,
        )

    async def _show_rule_page(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, rule_type: str,

        changed: bool = False,
    ) -> None:
        await show_rule_page(
            update,
            context,
            chat_id,
            rule_type=rule_type,
            changed=changed,
            get_chat_settings_func=get_chat_settings,
            safe_edit_func=_safe_edit_message,
        )

    async def _handle_toggle(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, field: str,
    ) -> None:
        """处理开关切换"""
        callback_data = CallbackParser.parse(update.callback_query.data or "")
        db: Database = context.application.bot_data["db"]

        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            explicit_value = callback_data.get_int_optional(4)
            if field == "all_enabled":
                next_value = bool(explicit_value) if explicit_value in {0, 1} else not (
                    settings.sign_enabled or settings.message_points_enabled or settings.invite_points_enabled
                )
                settings.sign_enabled = next_value
                settings.message_points_enabled = next_value
                settings.invite_points_enabled = next_value
                await session.commit()
                await self._show_points_home(update, context, chat_id, changed=True)
                return
            if hasattr(settings, field):
                current = bool(getattr(settings, field))
                next_value = bool(explicit_value) if explicit_value in {0, 1} else not current
                setattr(settings, field, next_value)
                await session.commit()
            await session.commit()

        rule_map = {
            "sign_enabled": "checkin",
            "message_points_enabled": "speech",
            "invite_points_enabled": "invite",
        }
        if field in rule_map:
            await self._show_rule_page(update, context, chat_id, rule_type=rule_map[field], changed=True)
        else:
            await self._show_points_home(update, context, chat_id, changed=True)

    async def _handle_edit(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, field: str,
    ) -> None:
        """处理数值编辑 - 进入对话状态"""
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            await session.commit()

        # 保存编辑状态
        context.user_data["points_edit_field"] = field
        context.user_data["points_edit_chat_id"] = chat_id

        # 根据字段类型显示不同的提示
        prompts = {
            "sign_points": "请输入每次签到获得的积分数：",
            "sign_consecutive": "请输入连续签到奖励（格式：天数,积分，例如 7,10 表示连续7天奖励10积分）：",
            "message_points": "请输入每次发言获得的积分数：",
            "message_daily_limit": "请输入每日发言积分上限（输入 0 表示无限制）：",
            "message_min_length": "请输入最小发言字数（输入 0 表示无限制）：",
            "invite_points": "请输入每次邀请获得的积分数：",
            "invite_daily_limit": "请输入每日邀请积分上限（输入 0 表示无限制）：",
            "points_alias": "请输入积分别名（例如：积分）：",
            "points_rank_alias": "请输入积分排行别名（例如：积分排行）：",
            "transfer": "请输入转让信息：目标用户 金额 原因(可选)\n例如：@alice 20 活动补偿",
            "admin_add": "请输入增加积分信息：目标用户 金额 原因(可选)\n例如：123456 50 手动奖励",
            "admin_deduct": "请输入扣除积分信息：目标用户 金额 原因(可选)\n例如：@alice 10 手动扣分",
            "clear_points": "此操作会清空本群主积分、签到记录和每日统计。\n请输入 CONFIRM 确认执行：",
        }

        prompt = prompts.get(field, "请输入新值：")

        keyboard = back_button(chat_id)
        await _safe_edit_message(update.callback_query, prompt, reply_markup=keyboard)

        # 返回 WAIT_VALUE 状态，让 ConversationHandler 继续监听
        # 注意：这里我们需要返回状态值，但由于使用了 BaseHandler 模式
        # 状态值需要通过其他方式传递
        return WAIT_VALUE

    async def _handle_rule(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, rule_type: str,
    ) -> None:
        await self._show_rule_page(update, context, chat_id, rule_type=rule_type)

    async def _handle_view(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, feature: str,
    ) -> None:
        handled = await handle_view(
            update,
            context,
            chat_id,
            feature=feature,
            get_chat_settings_func=get_chat_settings,
            safe_edit_func=_safe_edit_message,
            show_points_home_func=show_points_home,
        )
        if not handled:
            await self._show_points_home(update, context, chat_id)

    async def _handle_todo(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *, feature: str,
    ) -> int | None:
        return await handle_todo(
            update,
            context,
            chat_id,
            feature=feature,
            edit_handler=self._handle_edit,
            safe_edit_func=_safe_edit_message,
            get_chat_settings_func=get_chat_settings,
        )

    async def _handle_cancel(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """处理取消配置"""
        # 清除编辑状态
        context.user_data.pop("points_edit_field", None)
        context.user_data.pop("points_edit_chat_id", None)

        await self._show_points_home(update, context, chat_id)


# 创建单例实例
_points_config_handler = PointsConfigHandler()


# 适配器函数（供 Router 注册）
async def points_config_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """积分配置回调处理器（适配器函数）"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return

    q = update.callback_query
    data = q.data or ""
    cb = CallbackParser.parse(data)

    if cb.length() < _POINTS_CONFIG_CALLBACK_THRESHOLD_4:
        return

    chat_id = cb.get_int(3)
    if chat_id == 0:
        return

    # 检查管理员权限
    from backend.shared.services.permission_service import is_user_admin
    if not await is_user_admin(context, chat_id, update.effective_user.id):
        await _safe_edit_message(q, "你没有该群组的管理权限")
        return

    # 调用 Handler 处理
    result = await _points_config_handler.process(update, context, chat_id)

    # 如果返回了 WAIT_VALUE，返回 ConversationHandler 继续
    if result == WAIT_VALUE:
        return result


async def points_config_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """积分配置消息处理器"""
    return await handle_points_config_message(update, context)


async def points_config_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """取消配置"""
    return await handle_points_config_cancel(
        update,
        context,
        get_chat_settings_func=get_chat_settings,
        safe_edit_func=_safe_edit_message,
    )
