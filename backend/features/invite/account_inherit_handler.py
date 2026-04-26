from __future__ import annotations

import datetime as dt

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.shared.handlers.base.chat_resolver import ChatResolver
from backend.shared.services.base import ValidationError
from backend.shared.services.permission_service import PermissionPolicyService
from backend.shared.services.command_config_service import ensure_command_enabled
from backend.features.invite.services.account_inherit_service import (
    build_summary,
    consume_token,
    generate_token,
    update_setting,
)
from backend.features.group_ops.services.chat_group_service import set_user_current_chat
from backend.platform.state.state_service import clear_user_state, set_user_state
from backend.shared.callback_parser import CallbackParser
from backend.platform.telegram.errors import answer_callback_query_safely, mark_callback_query_answered


def _user_home_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎟️ 旧号生成令牌", callback_data=f"inh:token:gen:{chat_id}"),
            InlineKeyboardButton("🔓 新号使用令牌", callback_data=f"inh:token:use:{chat_id}"),
        ],
        [InlineKeyboardButton("🔙 返回", callback_data=f"inh:user:{chat_id}")],
    ])


def _extract_inherit_chat_id(cb: CallbackParser) -> int | None:
    action = cb.get(1)
    if action == "token":
        return cb.get_int_optional(3)
    return cb.get_int_optional(2)


async def _render_text(update: Update, text: str, reply_markup: InlineKeyboardMarkup) -> None:
    if update.callback_query is not None and update.callback_query.message is not None:
        try:
            await update.callback_query.edit_message_text(text=text, reply_markup=reply_markup)
        except BadRequest as exc:
            if "Message is not modified" not in str(exc):
                raise
            await update.callback_query.answer(text="已是当前页面", show_alert=False)
            mark_callback_query_answered(update)
            return
        await update.callback_query.answer()
        mark_callback_query_answered(update)
        return
    if update.effective_message is not None:
        await update.effective_message.reply_text(text=text, reply_markup=reply_markup)


async def show_user_inherit_home(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        summary = await build_summary(session, chat_id)
        await session.commit()
    text = "\n".join(
        [
            "💥 炸号继承 | 用户自助",
            "",
            f"📌 当前群组：{chat_id}",
            f"🛡️ 状态：{'✅ 已开启' if summary['enabled'] else '❌ 未开启'}",
            f"⏱️ Token 有效期：{summary['token_expire_minutes']} 分钟",
            "",
            "旧号先生成一次性 token，新号再使用 token 完成资产继承。",
            "Token 只展示一次，请立即保存。",
        ]
    )
    await _render_text(update, text, _user_home_keyboard(chat_id))


async def account_inherit_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return
    db: Database = context.application.bot_data["db"]
    if update.effective_chat.type != "private":
        allowed = await ensure_command_enabled(context, update, command_key="inherit")
        if not allowed:
            return
        await set_user_current_chat(db, update.effective_user.id, update.effective_chat.id)
        await update.effective_message.reply_text("已关联当前群，请到私聊中发送 /inherit 继续。")
        return

    chat_id = await ChatResolver.get_current_chat(db, update.effective_user.id)
    if chat_id in (None, 0):
        await update.effective_message.reply_text("请先使用 /start 选择一个群组，或先在目标群发送一次 /inherit。")
        return
    await show_user_inherit_home(update, context, chat_id)


async def account_inherit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None:
        return
    cb = CallbackParser.parse(update.callback_query.data or "")
    action = cb.get(1)
    chat_id = _extract_inherit_chat_id(cb)
    if chat_id is None:
        await answer_callback_query_safely(update, "❌ 群组参数无效", show_alert=True)
        return

    db: Database = context.application.bot_data["db"]

    if action in {"manage", "toggle"}:
        allowed, reason = await PermissionPolicyService.require_manage(context, chat_id, update.effective_user.id)
        if not allowed:
            await answer_callback_query_safely(update, f"❌ {reason or '没有权限'}", show_alert=True)
            return

    if action == "manage":
        from backend.features.admin.admin_handler import _admin_handler

        await _admin_handler._show_account_inherit_menu(update, context, chat_id)
        return

    async with db.session_factory() as session:
        if action == "toggle":
            await update_setting(session, chat_id, enabled=cb.get(3) == "1")
            await session.commit()
            from backend.features.admin.admin_handler import _admin_handler

            await _admin_handler._show_account_inherit_menu(update, context, chat_id)
            return

        if action == "user":
            await session.commit()
            await show_user_inherit_home(update, context, chat_id)
            return

        if action == "token" and cb.get(2) == "gen":
            target_chat_id = chat_id
            if target_chat_id is None:
                await answer_callback_query_safely(update, "❌ 群组参数无效", show_alert=True)
                return
            try:
                token, expires_at = await generate_token(session, target_chat_id, update.effective_user.id)
                await session.commit()
            except ValidationError as exc:
                await session.rollback()
                await _render_text(
                    update,
                    "\n".join(
                        [
                            "❌ 继承令牌生成失败",
                            "",
                            str(exc),
                            "",
                            "旧号需要在当前群有可继承的主积分或自定义积分。",
                        ]
                    ),
                    InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"inh:user:{target_chat_id}")]]),
                )
                return
            text = "\n".join(
                [
                    "🎟️ 继承令牌已生成",
                    "",
                    f"`{token}`",
                    "",
                    f"⏰ 过期时间：{expires_at.astimezone().strftime('%Y-%m-%d %H:%M:%S')}",
                    "请在新号私聊里立即使用，令牌仅展示这一次。",
                ]
            )
            await _render_text(update, text, InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"inh:user:{target_chat_id}")]]))
            return

        if action == "token" and cb.get(2) == "use":
            target_chat_id = chat_id
            if target_chat_id is None:
                await answer_callback_query_safely(update, "❌ 群组参数无效", show_alert=True)
                return
            await clear_user_state(session, chat_id=update.effective_user.id, user_id=update.effective_user.id)
            await set_user_state(
                session,
                chat_id=update.effective_user.id,
                user_id=update.effective_user.id,
                state_type="inherit_wait_token_input",
                state_data={"target_chat_id": target_chat_id},
            )
            await session.commit()
            await _render_text(
                update,
                "🔓 炸号继承 | 使用令牌\n\n请发送旧号生成的一次性 token：",
                InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"inh:user:{target_chat_id}")]]),
            )
            return


async def handle_account_inherit_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state,
    message_text: str,
) -> None:
    if update.effective_user is None or update.effective_message is None:
        return
    target_chat_id = state.state_data.get("target_chat_id")
    if not isinstance(target_chat_id, int):
        await update.effective_message.reply_text("炸号继承状态异常，请重新发送 /inherit。")
        return
    token = message_text.strip()
    if not token:
        await update.effective_message.reply_text("token 不能为空。")
        return
    try:
        snapshot = await consume_token(session, target_chat_id, update.effective_user.id, token)
    except ValidationError as exc:
        await update.effective_message.reply_text(f"❌ {exc}")
        return
    await clear_user_state(session, chat_id=update.effective_user.id, user_id=update.effective_user.id)
    await session.commit()
    custom_lines = [f"type#{item['type_id']}={item['balance']}" for item in snapshot["custom_points"]] or ["无"]
    await update.effective_message.reply_text(
        "\n".join(
            [
                "✅ 继承成功",
                f"🌑 主积分：{snapshot['main_points']}",
                f"🌐 自定义积分：{' / '.join(custom_lines)}",
            ]
        )
    )
    await show_user_inherit_home(update, context, target_chat_id)
