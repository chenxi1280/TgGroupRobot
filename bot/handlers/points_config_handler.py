from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from telegram.error import BadRequest

from bot.db.session import Database
from bot.handlers.base.base_handler import BaseHandler
from bot.keyboards.admin.points import back_button, points_config_keyboard, points_rule_keyboard
from bot.services.core.chat_service import get_chat_settings
from bot.utils.callback_parser import CallbackParser

log = structlog.get_logger(__name__)

# 对话状态
WAIT_VALUE = 0


async def _safe_edit_message(q, text: str, **kwargs) -> None:
    """安全地编辑消息"""
    try:
        await q.edit_message_text(text, **kwargs)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            log.debug("message_not_modified", callback_data=q.data)
        else:
            raise


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
            await self.message_helper.safe_edit(update, "请在私聊中使用此功能")
            return

        # 解析 callback data
        callback_data = CallbackParser.parse(q.data)
        action = callback_data.get(1)
        field = callback_data.get(2)

        # 根据操作类型分发
        if action == "home":
            await self._show_points_home(update, context, target_chat_id, changed=False)
        if action == "toggle":
            await self._handle_toggle(update, context, target_chat_id, field)
        elif action == "edit":
            await self._handle_edit(update, context, target_chat_id, field)
        elif action == "rule":
            await self._handle_rule(update, context, target_chat_id, field)
        elif action == "todo":
            await self._handle_todo(update, target_chat_id, field)
        elif action == "cancel":
            await self._handle_cancel(update, context, target_chat_id)

    async def _load_settings(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            await session.commit()
        return settings

    async def _show_points_home(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *,
        changed: bool = False,
    ) -> None:
        settings = await self._load_settings(context, chat_id)
        text = "💰 主积分（基础版）\n\n"
        if changed:
            text += "配置已更新。\n\n"
        text += (
            f"状态：{'✅ 启动' if (settings.sign_enabled or settings.message_points_enabled or settings.invite_points_enabled) else '❌ 关闭'}\n"
            f"签到：{'✅ 启动' if settings.sign_enabled else '❌ 关闭'}｜{settings.sign_points}分\n"
            f"发言：{'✅ 启动' if settings.message_points_enabled else '❌ 关闭'}｜{settings.message_points}分\n"
            f"邀请：{'✅ 启动' if settings.invite_points_enabled else '❌ 关闭'}｜{settings.invite_points}分\n"
            f"积分别名：{settings.points_alias}\n"
            f"排行别名：{settings.points_rank_alias}\n\n"
            "说明：当前先提供基础版积分中心，文档中的转让、日志导出、清空积分等入口已收口为待实现。"
        )
        await self.message_helper.safe_edit(update, text=text, reply_markup=points_config_keyboard(settings, chat_id))

    async def _show_rule_page(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        rule_type: str,
        *,
        changed: bool = False,
    ) -> None:
        settings = await self._load_settings(context, chat_id)
        if rule_type == "checkin":
            text = (
                "💰 主积分 | 签到规则\n\n"
                f"状态：{'✅ 启动' if settings.sign_enabled else '❌ 关闭'}\n"
                f"获得数量：{settings.sign_points}\n"
                f"连续奖励：{settings.sign_consecutive_days}天 + {settings.sign_consecutive_bonus}分\n"
            )
        elif rule_type == "speech":
            daily_limit = settings.message_points_daily_limit or "无限制"
            min_length = settings.message_min_length or "无限制"
            text = (
                "💰 主积分 | 发言规则\n\n"
                f"状态：{'✅ 启动' if settings.message_points_enabled else '❌ 关闭'}\n"
                f"获得数量：{settings.message_points}\n"
                f"每日上限：{daily_limit}\n"
                f"最小字数：{min_length}\n"
            )
        else:
            daily_limit = settings.invite_points_daily_limit or "无限制"
            text = (
                "💰 主积分 | 邀请规则\n\n"
                f"状态：{'✅ 启动' if settings.invite_points_enabled else '❌ 关闭'}\n"
                f"获得数量：{settings.invite_points}\n"
                f"每日上限：{daily_limit}\n"
            )
        if changed:
            text += "\n配置已更新。"
        await self.message_helper.safe_edit(update, text=text, reply_markup=points_rule_keyboard(rule_type, settings, chat_id))

    async def _handle_toggle(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        field: str,
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
            await self._show_rule_page(update, context, chat_id, rule_map[field], changed=True)
        else:
            await self._show_points_home(update, context, chat_id, changed=True)

    async def _handle_edit(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        field: str,
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
        }

        prompt = prompts.get(field, "请输入新值：")

        keyboard = back_button(chat_id)
        await self.message_helper.safe_edit(
            update,
            text=prompt,
            reply_markup=keyboard
        )

        # 返回 WAIT_VALUE 状态，让 ConversationHandler 继续监听
        # 注意：这里我们需要返回状态值，但由于使用了 BaseHandler 模式
        # 状态值需要通过其他方式传递
        return WAIT_VALUE

    async def _handle_rule(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        rule_type: str,
    ) -> None:
        await self._show_rule_page(update, context, chat_id, rule_type)

    async def _handle_todo(
        self,
        update: Update,
        chat_id: int,
        feature: str,
    ) -> None:
        title_map = {
            "display_rules": "展示规则",
            "speech_rank": "发言总排行",
            "personal_speech": "个人发言量",
            "transfer": "转让积分",
            "admin_add": "增加积分",
            "admin_deduct": "扣除积分",
            "lottery": "积分抽奖",
            "extra_rules": "额外规则",
            "export_logs": "导出操作日志",
            "clear_points": "清空积分",
        }
        title = title_map.get(feature, "该功能")
        text = (
            f"💰 主积分 | {title}\n\n"
            "当前只有重构设计，基础版积分中心尚未接入这一能力。\n"
            "本轮已保留入口位置，避免首页继续和文档细节错位。"
        )
        await self.message_helper.safe_edit(update, text=text, reply_markup=back_button(chat_id))

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
async def points_config_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """积分配置回调处理器（适配器函数）"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return

    q = update.callback_query
    data = q.data or ""
    cb = CallbackParser.parse(data)

    if cb.length() < 4:
        return

    chat_id = cb.get_int(3)
    if chat_id == 0:
        return

    # 检查管理员权限
    from bot.services.core.permission_service import is_user_admin
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
    if update.effective_chat is None or update.effective_message is None:
        return ConversationHandler.END

    if update.effective_chat.type != "private":
        return ConversationHandler.END

    text = update.effective_message.text
    if not text:
        return ConversationHandler.END

    # 检查是否在编辑状态
    field = context.user_data.get("points_edit_field")
    chat_id = context.user_data.get("points_edit_chat_id")

    if not field or chat_id is None:
        return ConversationHandler.END

    db: Database = context.application.bot_data["db"]

    try:
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)

            # 处理特殊字段
            if field == "sign_consecutive":
                # 格式：天数,积分
                parts = text.split(",")
                if len(parts) != 2:
                    await update.effective_message.reply_text("格式错误，请输入：天数,积分（例如 7,10）")
                    return WAIT_VALUE

                days = int(parts[0].strip())
                bonus = int(parts[1].strip())

                settings.sign_consecutive_days = days
                settings.sign_consecutive_bonus = bonus

            elif field in ["message_daily_limit", "message_min_length", "invite_daily_limit"]:
                # 0 表示无限制（None）
                value = int(text.strip())
                setattr(settings, field, value if value > 0 else None)

            elif field in ["points_alias", "points_rank_alias"]:
                # 字符串
                setattr(settings, field, text.strip())

            else:
                # 普通整数
                value = int(text.strip())
                setattr(settings, field, value)

            await session.commit()

            # 获取更新后的设置
            settings = await get_chat_settings(session, chat_id)
            await session.commit()

        # 显示更新后的键盘
        from bot.keyboards.admin.points import points_config_keyboard

        keyboard = points_config_keyboard(settings, chat_id)
        await update.effective_message.reply_text("✅ 配置已更新", reply_markup=keyboard)

        # 清除编辑状态
        context.user_data.pop("points_edit_field", None)
        context.user_data.pop("points_edit_chat_id", None)

        return ConversationHandler.END

    except ValueError:
        await update.effective_message.reply_text("输入格式错误，请输入有效的数字")
        return WAIT_VALUE
    except Exception as e:
        log.error("points_config_error", error=str(e))
        await update.effective_message.reply_text(f"配置失败：{str(e)}")
        return ConversationHandler.END


async def points_config_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """取消配置"""
    # 清除编辑状态
    context.user_data.pop("points_edit_field", None)
    context.user_data.pop("points_edit_chat_id", None)

    if update.callback_query:
        field = context.user_data.get("points_edit_field")
        chat_id = context.user_data.get("points_edit_chat_id")

        if chat_id:
            from bot.keyboards.admin.points import points_config_keyboard

            db: Database = context.application.bot_data["db"]
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                await session.commit()

            keyboard = points_config_keyboard(settings, chat_id)
            await update.callback_query.edit_message_text("💰 积分配置", reply_markup=keyboard)

    return ConversationHandler.END
