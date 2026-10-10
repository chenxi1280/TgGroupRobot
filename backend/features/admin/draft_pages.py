from __future__ import annotations

import datetime as dt
from sqlalchemy import select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from backend.platform.db.schema.models.chat import EditDraft
from backend.platform.state.edit_drafts import list_drafts, suspend_inputs
from backend.platform.state.conversation_state_service import ConversationStateService, SELECTED_CHAT_STATE
from backend.shared.services.permission_service import PermissionPolicyService
from backend.platform.telegram.errors import answer_callback_query_safely


DRAFT_CALLBACK_PARTS = 4


async def draft_callback(update, context):
    query, user = update.callback_query, update.effective_user
    if query is None or user is None or update.effective_chat.type != "private":
        return
    parts = (query.data or "").split(":")
    if len(parts) != DRAFT_CALLBACK_PARTS:
        return
    _, action, raw_chat, token = parts
    try:
        chat_id = int(raw_chat)
    except ValueError:
        return
    allowed, reason = await PermissionPolicyService.require_manage(context, chat_id, user.id, capability="manage")
    if action == "resume" and not allowed:
        await answer_callback_query_safely(update, reason or "管理权限已失效", show_alert=True)
        return
    db = context.application.bot_data["db"]
    back = [InlineKeyboardButton("返回管理首页", callback_data=f"adm:menu:main:{chat_id}")]
    async with db.session_factory() as session:
        text, rows = await _draft_page(session, update, action=action, token=token, chat_id=chat_id, allowed=allowed, back=back)
        await session.commit()
    await query.answer()
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))


def _draft_title(draft):
    labels = {"command": "命令配置", "points": "积分配置", "guess": "竞猜", "auction": "拍卖",
              "ads": "轮播消息", "auto": "自动回复", "welcome": "欢迎消息", "invite": "邀请链接",
              "teacher": "老师资料", "garage": "车库配置", "verification": "进群验证"}
    title = labels.get(draft.state_type.split("_")[0], "功能编辑")
    data = draft.state_data or {}
    identity = next((data[key] for key in ("product_id", "item_id", "rule_id", "welcome_id", "command_key") if data.get(key)), None)
    return f"{title} · {identity}" if identity is not None else title


async def _draft_page(session, update, *, action, token, chat_id, allowed, back):
    user = update.effective_user
    if action == "list":
        return await _draft_list(session, user.id, chat_id, token=token, allowed=allowed, back=back)
    draft = (await session.execute(select(EditDraft).where(
        EditDraft.token == token, EditDraft.user_id == user.id, EditDraft.chat_id == chat_id,
        EditDraft.state_type.not_in(["mall_fulfillment_confirmation", "button_layout_draft"]),
    ).with_for_update())).scalar_one_or_none()
    if draft is None or draft.expires_at <= dt.datetime.now(dt.UTC):
        return "草稿不存在或已过期", [back]
    if action == "resume":
        return await _resume_draft(session, draft, user_id=user.id, chat_id=chat_id, back=back)
    if action == "discard_confirm":
        await session.delete(draft)
        return "已放弃本次修改，正式配置未改变。", [back]
    if action == "discard":
        return "确认放弃此草稿？此操作只删除未保存的编辑内容。", [[InlineKeyboardButton("确认放弃", callback_data=f"draft:discard_confirm:{chat_id}:{token}")], back]
    text = f"所属群：{chat_id}\n编辑对象：{_draft_title(draft)}\n编辑草稿已保留；继续编辑后才接收输入。"
    rows = [[InlineKeyboardButton("继续编辑", callback_data=f"draft:resume:{chat_id}:{token}")]] if allowed else []
    rows.extend([[InlineKeyboardButton("放弃修改", callback_data=f"draft:discard:{chat_id}:{token}")], back])
    return text, rows


async def _draft_list(session, user_id, chat_id, *, token, allowed, back):
    drafts = await list_drafts(session, user_id, chat_id)
    page = max(0, min(int(token) if token.isdigit() else 0, max(0, (len(drafts)-1)//8)))
    rows = [[InlineKeyboardButton(f"{_draft_title(d)} · {d.created_at:%m-%d %H:%M}", callback_data=f"draft:view:{chat_id}:{d.token}")]
            for d in drafts[page*8:(page+1)*8]]
    nav = []
    if page:
        nav.append(InlineKeyboardButton("上一页", callback_data=f"draft:list:{chat_id}:{page-1}"))
    if (page+1)*8 < len(drafts):
        nav.append(InlineKeyboardButton("下一页", callback_data=f"draft:list:{chat_id}:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("刷新草稿", callback_data=f"draft:list:{chat_id}:{page}")])
    rows.append(back)
    text = f"群 {chat_id} 编辑草稿：{len(drafts)} 份（保留 7 天）\n第 {page+1}/{max(1,(len(drafts)+7)//8)} 页"
    if not allowed:
        text += "\n管理权限当前不可用，可以查看或放弃自己的草稿；不能恢复提交。"
    return text, rows


async def _resume_draft(session, draft, *, user_id, chat_id, back):
    from backend.platform.state.draft_versions import resumed_version_matches
    if not await resumed_version_matches(session, draft, lock=True):
        return "正式配置已变化或对象已删除，草稿已保留。请返回功能页重新载入后编辑，不能直接覆盖。", [back]
    await suspend_inputs(session, user_id)
    if draft.state_chat_id != user_id:
        await ConversationStateService.start(session, user_id, user_id,
            state_type=SELECTED_CHAT_STATE, state_data={"managed_chat_id": chat_id})
    await ConversationStateService.start(session, draft.state_chat_id, user_id,
        state_type=draft.state_type, state_data=dict(draft.state_data))
    await session.delete(draft)
    text, rows = f"已继续编辑群 {chat_id} 的草稿。请发送下一项内容；/cancel 可退出并保留草稿。", [back]
    return text, rows
