from __future__ import annotations

from backend.features.admin.support import *


class AccountInheritAdminMixin:
    async def _show_account_inherit_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        await self._set_current_chat(db, update.effective_user.id, chat_id)
        async with db.session_factory() as session:
            summary = await build_inherit_summary(session, chat_id)
            await session.commit()
        enabled = bool(summary["enabled"])
        text = "\n".join(
            [
                "💥 炸号继承",
                "",
                f"📌 允许继承：{'✅ 允许' if enabled else '❌ 不允许'}",
                f"⏱️ Token 有效期：{summary['token_expire_minutes']} 分钟",
                f"🎟️ 活跃令牌：{summary['active_tokens']}",
                f"🧾 已使用令牌：{summary['used_tokens']}",
                "",
                "旧号生成一次性 token，新号在私聊里使用 token 继承主积分和自定义积分。",
            ]
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("允许继承：", callback_data=f"inh:manage:{chat_id}"),
                InlineKeyboardButton("允许" + (" ✅" if enabled else ""), callback_data=f"inh:toggle:{chat_id}:1"),
                InlineKeyboardButton("不允许" + (" ✅" if not enabled else ""), callback_data=f"inh:toggle:{chat_id}:0"),
            ],
            [
                InlineKeyboardButton("🎟️ 旧号生成令牌", callback_data=f"inh:token:gen:{chat_id}"),
                InlineKeyboardButton("🔓 新号使用令牌", callback_data=f"inh:token:use:{chat_id}"),
            ],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
        ])
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)
