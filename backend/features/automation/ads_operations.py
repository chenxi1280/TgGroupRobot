from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from backend.features.automation.ad_delivery_admin_service import (
    cancel_delivery,
    list_delivery_history,
    replay_uncertain_delivery,
    retry_delivery,
    toggle_pool_membership,
)
from backend.features.automation.ads_handler import _resolve_ads_target_chat_id
from backend.features.automation.services.ad_rotation_service import get_or_create_rotation_rule, list_rotation_items
from backend.platform.db.runtime.session import Database
from backend.platform.delivery import DeliveryStatus
from backend.platform.telegram.errors import answer_callback_query_safely, build_public_error_text

STATUS_LABELS = {
    DeliveryStatus.pending.value: "待执行",
    DeliveryStatus.processing.value: "执行中",
    DeliveryStatus.retryable_failed.value: "等待重试",
    DeliveryStatus.succeeded.value: "成功",
    DeliveryStatus.permanent_failed.value: "永久失败",
    DeliveryStatus.uncertain.value: "结果不确定",
    DeliveryStatus.cancelled.value: "已取消",
}


async def ads_history_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = await _resolve_ads_target_chat_id(update, context)
    if chat_id is None:
        return
    parts = str(update.callback_query.data).split(":")
    status = parts[3] if len(parts) > 3 and parts[3] != "all" else None
    await _show_history(update, context, chat_id, status=status)


async def _show_history(update, context, chat_id: int, *, status: str | None) -> None:
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        histories = await list_delivery_history(session, chat_id, status=status)
        await session.commit()
    await _edit(update, _format_history(histories), _history_keyboard(chat_id, histories))


async def ads_delivery_operation_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = await _resolve_ads_target_chat_id(update, context)
    if chat_id is None:
        return
    parts = str(update.callback_query.data).split(":")
    action, history_id = parts[2], int(parts[-1])
    if action == "replay_confirm":
        await _show_replay_confirmation(update, chat_id, history_id)
        return
    try:
        await _apply_delivery_action(
            context,
            chat_id=chat_id,
            history_id=history_id,
            action=action,
            admin_id=update.effective_user.id,
        )
    except Exception as exc:
        await answer_callback_query_safely(update, build_public_error_text(exc), show_alert=True)
        return
    await _show_history(update, context, chat_id, status=None)


async def ads_pool_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = await _resolve_ads_target_chat_id(update, context)
    if chat_id is None:
        return
    parts = str(update.callback_query.data).split(":")
    pool = parts[2]
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        if parts[1] == "pool_toggle":
            await toggle_pool_membership(session, chat_id, int(parts[-1]), pool=pool)
        rule = await get_or_create_rotation_rule(session, chat_id)
        items = await list_rotation_items(session, chat_id)
        await session.commit()
    await _edit(
        update,
        _format_pool(pool, rule, items),
        _pool_keyboard(chat_id, pool, rule, items=items),
    )


async def _apply_delivery_action(
    context,
    *,
    chat_id: int,
    history_id: int,
    action: str,
    admin_id: int,
) -> None:
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        if action == "retry":
            await retry_delivery(session, history_id, chat_id)
        elif action == "cancel":
            await cancel_delivery(session, history_id, chat_id)
        elif action == "replay_do":
            await replay_uncertain_delivery(
                session,
                history_id,
                chat_id,
                admin_id=admin_id,
                reason="telegram_admin_confirmed_replay",
            )
        else:
            raise ValueError(f"unknown ad operation: {action}")
        await session.commit()


async def _show_replay_confirmation(update: Update, chat_id: int, history_id: int) -> None:
    text = "⚠️ 发送结果未知，重放可能产生重复广告。确认仍要人工重放吗？"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("确认重放", callback_data=f"ads:delivery:replay_do:{chat_id}:{history_id}")],
        [InlineKeyboardButton("返回历史", callback_data=f"ads:history:{chat_id}:uncertain")],
    ])
    await _edit(update, text, keyboard)


async def _edit(update: Update, text: str, keyboard: InlineKeyboardMarkup) -> None:
    if update.callback_query and update.callback_query.message:
        await update.callback_query.message.edit_text(text, reply_markup=keyboard)
    await answer_callback_query_safely(update)


def _format_history(histories) -> str:
    lines = ["📜 轮播广告派发历史"]
    for item in histories:
        status = STATUS_LABELS.get(item.status, item.status)
        detail = item.error_code or item.error_message or "-"
        lines.append(f"\n#{item.id} {status} | 尝试 {item.attempt_count}\n{item.title_snapshot} | {detail}")
    if not histories:
        lines.append("\n暂无记录")
    return "\n".join(lines)


def _history_keyboard(chat_id: int, histories) -> InlineKeyboardMarkup:
    rows = [[
        InlineKeyboardButton("全部", callback_data=f"ads:history:{chat_id}:all"),
        InlineKeyboardButton("失败", callback_data=f"ads:history:{chat_id}:permanent_failed"),
        InlineKeyboardButton("不确定", callback_data=f"ads:history:{chat_id}:uncertain"),
    ]]
    for item in histories:
        if item.status in {DeliveryStatus.retryable_failed.value, DeliveryStatus.permanent_failed.value}:
            rows.append([
                _operation_button("重试", "retry", chat_id=chat_id, history_id=item.id),
                _operation_button("取消", "cancel", chat_id=chat_id, history_id=item.id),
            ])
        elif item.status == DeliveryStatus.uncertain.value:
            rows.append([
                _operation_button("确认重放", "replay_confirm", chat_id=chat_id, history_id=item.id),
                _operation_button("取消", "cancel", chat_id=chat_id, history_id=item.id),
            ])
    rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"ads:menu:{chat_id}")])
    return InlineKeyboardMarkup(rows)


def _operation_button(label: str, action: str, *, chat_id: int, history_id: int):
    return InlineKeyboardButton(label, callback_data=f"ads:delivery:{action}:{chat_id}:{history_id}")


def _format_pool(pool: str, rule, items) -> str:
    label = "置顶池" if pool == "top" else "排除池"
    selected = {int(value) for value in getattr(rule, "top_campaign_ids" if pool == "top" else "exclude_campaign_ids", []) or []}
    lines = [f"🎯 轮播广告{label}", f"\n已选择 {len(selected)} 条"]
    lines.extend(f"\n{'✅' if item.id in selected else '▫️'} #{item.id} {item.title}" for item in items)
    return "".join(lines)


def _pool_keyboard(chat_id: int, pool: str, rule, *, items) -> InlineKeyboardMarkup:
    selected = {int(value) for value in getattr(rule, "top_campaign_ids" if pool == "top" else "exclude_campaign_ids", []) or []}
    rows = [[InlineKeyboardButton(
        f"{'✅' if item.id in selected else '▫️'} #{item.id} {item.title}"[:60],
        callback_data=f"ads:pool_toggle:{pool}:{chat_id}:{item.id}",
    )] for item in items]
    rows.append([InlineKeyboardButton("🔙 返回规则", callback_data=f"ads:rules:{chat_id}")])
    return InlineKeyboardMarkup(rows)
