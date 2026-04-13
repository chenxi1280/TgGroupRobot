from __future__ import annotations

import csv
import io

from sqlalchemy import func, select
from telegram import Update
from telegram.ext import ContextTypes

from backend.features.admin.points_config_shared import safe_edit_message
from backend.features.admin.ui.points import back_button, points_config_keyboard, points_rule_keyboard
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.core import PointsTransaction, TgUser, UserDailyStats
from backend.platform.db.schema.models.enums import PointsTxnType
from backend.shared.services.chat_service import get_chat_settings


async def load_settings(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    *,
    get_chat_settings_func=get_chat_settings,
):
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings_func(session, chat_id)
        await session.commit()
    return settings


async def show_points_home(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    *,
    changed: bool = False,
    get_chat_settings_func=get_chat_settings,
    safe_edit_func=safe_edit_message,
) -> None:
    settings = await load_settings(
        context,
        chat_id,
        get_chat_settings_func=get_chat_settings_func,
    )
    text = "💰 主积分\n\n"
    if changed:
        text += "配置已更新。\n\n"
    text += (
        f"状态：{'✅ 启动' if (settings.sign_enabled or settings.message_points_enabled or settings.invite_points_enabled) else '❌ 关闭'}\n"
        f"签到：{'✅ 启动' if settings.sign_enabled else '❌ 关闭'}｜{settings.sign_points}分\n"
        f"发言：{'✅ 启动' if settings.message_points_enabled else '❌ 关闭'}｜{settings.message_points}分\n"
        f"邀请：{'✅ 启动' if settings.invite_points_enabled else '❌ 关闭'}｜{settings.invite_points}分\n"
        f"积分别名：{settings.points_alias}\n"
        f"排行别名：{settings.points_rank_alias}\n\n"
        "说明：支持签到、发言、邀请、转让、管理员加减分、日志导出与清空积分。"
    )
    await safe_edit_func(update.callback_query, text, reply_markup=points_config_keyboard(settings, chat_id))


async def show_rule_page(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    rule_type: str,
    *,
    changed: bool = False,
    get_chat_settings_func=get_chat_settings,
    safe_edit_func=safe_edit_message,
) -> None:
    settings = await load_settings(
        context,
        chat_id,
        get_chat_settings_func=get_chat_settings_func,
    )
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
    await safe_edit_func(update.callback_query, text, reply_markup=points_rule_keyboard(rule_type, settings, chat_id))


async def handle_view(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    feature: str,
    *,
    get_chat_settings_func=get_chat_settings,
    safe_edit_func=safe_edit_message,
    show_points_home_func=show_points_home,
) -> bool:
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings_func(session, chat_id)
        if feature == "display_rules":
            daily_limit = settings.message_points_daily_limit or "无限制"
            min_length = settings.message_min_length or "无限制"
            invite_limit = settings.invite_points_daily_limit or "无限制"
            text = (
                "💰 主积分 | 展示规则\n\n"
                f"查询指令：{settings.points_alias}\n"
                f"排行指令：{settings.points_rank_alias}\n\n"
                f"签到：{'开启' if settings.sign_enabled else '关闭'}｜{settings.sign_points}分\n"
                f"连续签到：每 {settings.sign_consecutive_days or 0} 天奖励 {settings.sign_consecutive_bonus} 分\n"
                f"发言：{'开启' if settings.message_points_enabled else '关闭'}｜{settings.message_points}分\n"
                f"发言每日上限：{daily_limit}\n"
                f"最小字数：{min_length}\n"
                f"邀请：{'开启' if settings.invite_points_enabled else '关闭'}｜{settings.invite_points}分\n"
                f"邀请每日上限：{invite_limit}"
            )
            await session.commit()
            await safe_edit_func(update.callback_query, text, reply_markup=back_button(chat_id))
            return True

        if feature == "tasks":
            daily_limit = settings.message_points_daily_limit or "无限制"
            invite_limit = settings.invite_points_daily_limit or "无限制"
            min_length = settings.message_min_length or "无限制"
            lines = [
                "💰 主积分 | 积分任务",
                "",
                "当前任务基于群内积分规则自动发放：",
                f"1. 签到：{'✅ 开启' if settings.sign_enabled else '❌ 关闭'}｜{settings.sign_points} 分",
                f"2. 发言：{'✅ 开启' if settings.message_points_enabled else '❌ 关闭'}｜{settings.message_points} 分",
                f"   - 每日上限：{daily_limit}",
                f"   - 最小字数：{min_length}",
                f"3. 邀请：{'✅ 开启' if settings.invite_points_enabled else '❌ 关闭'}｜{settings.invite_points} 分",
                f"   - 每日上限：{invite_limit}",
                "",
                "说明：任务积分会写入主积分流水，可在“导出操作日志”查看详情。",
            ]
            await session.commit()
            await safe_edit_func(update.callback_query, "\n".join(lines), reply_markup=back_button(chat_id))
            return True

        if feature == "speech_rank":
            rows = await session.execute(
                select(
                    PointsTransaction.user_id,
                    func.count(PointsTransaction.id).label("message_count"),
                    func.coalesce(func.sum(PointsTransaction.amount), 0).label("message_points"),
                    TgUser.username,
                    TgUser.first_name,
                )
                .join(TgUser, TgUser.id == PointsTransaction.user_id, isouter=True)
                .where(
                    PointsTransaction.chat_id == chat_id,
                    PointsTransaction.txn_type == PointsTxnType.message.value,
                )
                .group_by(PointsTransaction.user_id, TgUser.username, TgUser.first_name)
                .order_by(func.count(PointsTransaction.id).desc(), func.sum(PointsTransaction.amount).desc())
                .limit(10)
            )
            ranking = rows.all()
            await session.commit()
            lines = ["💰 主积分 | 发言总排行", ""]
            if not ranking:
                lines.append("暂无发言积分排行数据。")
            else:
                for idx, row in enumerate(ranking, start=1):
                    name = row.username or row.first_name or str(row.user_id)
                    lines.append(f"{idx}. {name}｜奖励次数 {row.message_count}｜累计积分 {int(row.message_points or 0)}")
            await safe_edit_func(update.callback_query, "\n".join(lines), reply_markup=back_button(chat_id))
            return True

        if feature == "personal_speech":
            user_id = update.effective_user.id if update.effective_user else 0
            stats = await session.execute(
                select(
                    func.count(PointsTransaction.id).label("message_count"),
                    func.coalesce(func.sum(PointsTransaction.amount), 0).label("message_points"),
                ).where(
                    PointsTransaction.chat_id == chat_id,
                    PointsTransaction.user_id == user_id,
                    PointsTransaction.txn_type == PointsTxnType.message.value,
                )
            )
            active_days = await session.execute(
                select(func.count(UserDailyStats.id)).where(
                    UserDailyStats.chat_id == chat_id,
                    UserDailyStats.user_id == user_id,
                    UserDailyStats.message_points_earned > 0,
                )
            )
            message_count, message_points = stats.one()
            active_day_count = int(active_days.scalar() or 0)
            await session.commit()
            text = (
                "💰 主积分 | 个人发言量\n\n"
                f"奖励计次：{int(message_count or 0)}\n"
                f"累计发言积分：{int(message_points or 0)}\n"
                f"活跃天数：{active_day_count}\n\n"
                "说明：当前统计基于已发放的发言积分记录。"
            )
            await safe_edit_func(update.callback_query, text, reply_markup=back_button(chat_id))
            return True

        if feature == "export_logs":
            rows = await session.execute(
                select(
                    PointsTransaction.created_at,
                    PointsTransaction.user_id,
                    PointsTransaction.txn_type,
                    PointsTransaction.amount,
                    PointsTransaction.reason,
                )
                .where(PointsTransaction.chat_id == chat_id)
                .order_by(PointsTransaction.created_at.desc())
                .limit(500)
            )
            entries = rows.all()
            await session.commit()

            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow(["created_at", "user_id", "txn_type", "amount", "reason"])
            for row in entries:
                writer.writerow([
                    row.created_at.isoformat() if row.created_at else "",
                    row.user_id,
                    row.txn_type,
                    row.amount,
                    row.reason or "",
                ])

            file_obj = io.BytesIO(buffer.getvalue().encode("utf-8-sig"))
            file_obj.name = f"points_logs_{chat_id}.csv"
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=file_obj,
                caption=f"已导出 {len(entries)} 条主积分流水。",
            )
            await show_points_home_func(
                update,
                context,
                chat_id,
                changed=False,
                get_chat_settings_func=get_chat_settings_func,
                safe_edit_func=safe_edit_func,
            )
            return True

        if feature == "extra_rules":
            await session.commit()
            text = (
                "💰 主积分 | 额外规则\n\n"
                "以下能力与主积分联动：\n"
                "• 自定义积分：管理员手动维护的积分类型\n"
                "• 积分等级：按主积分门槛控制权限\n"
                "• 积分商城：按主积分兑换商品\n"
                "• 抽奖：可按主积分参与活动"
            )
            keyboard = back_button(chat_id, callback_data=f"adm:menu:main:{chat_id}")
            await safe_edit_func(update.callback_query, text, reply_markup=keyboard)
            return True

        await session.commit()

    return False


async def handle_todo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    feature: str,
    edit_handler,
    *,
    safe_edit_func=safe_edit_message,
    get_chat_settings_func=get_chat_settings,
):
    legacy_to_action = {
        "display_rules": ("view", "display_rules"),
        "speech_rank": ("view", "speech_rank"),
        "personal_speech": ("view", "personal_speech"),
        "transfer": ("edit", "transfer"),
        "admin_add": ("edit", "admin_add"),
        "admin_deduct": ("edit", "admin_deduct"),
        "extra_rules": ("view", "extra_rules"),
        "export_logs": ("view", "export_logs"),
        "clear_points": ("edit", "clear_points"),
    }
    action = legacy_to_action.get(feature)
    if action is None:
        await safe_edit_func(
            update.callback_query,
            "该功能已迁移，请返回后重新进入。",
            reply_markup=back_button(chat_id),
        )
        return None
    if action[0] == "view":
        await handle_view(
            update,
            context,
            chat_id,
            action[1],
            get_chat_settings_func=get_chat_settings_func,
            safe_edit_func=safe_edit_func,
        )
        return None
    return await edit_handler(update, context, chat_id, action[1])
