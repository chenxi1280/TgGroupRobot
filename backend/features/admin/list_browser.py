"""Private list navigation and search input with explicit group and permission scope."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.exc import SQLAlchemyError
import structlog

from backend.features.admin.list_queries import FILTERS, PAGE_SIZE, SPECS, normalize_query, search_page
from backend.platform.state.state_service import clear_user_state, set_user_state
from backend.platform.state.edit_drafts import suspend_inputs
from backend.shared.handlers.base.message_helper import MessageHelper
from backend.shared.services.permission_service import PermissionPolicyService
from backend.shared.callback_parser import CallbackParser

SEARCH_STATE = "admin_list_search_input"
log = structlog.get_logger(__name__)


def list_options(context, feature: str, chat_id: int) -> dict:
    key = f"{chat_id}:{feature}"
    user_data = getattr(context, "user_data", None)
    if user_data is None:
        return {"query": "", "status": "all", "page": 0}
    return user_data.setdefault("admin_list_queries", {}).setdefault(
        key, {"query": "", "status": "all", "page": 0},
    )


def list_callback(feature: str, chat_id: int, *, action: str = "list", value=0) -> str:
    return f"mlist:{feature}:{chat_id}:{action}:{value}"


async def _authorized(update, context, chat_id: int) -> bool:
    if chat_id >= 0:
        return False
    if update.effective_user is None or update.effective_chat is None or update.effective_chat.type != "private":
        return False
    return await PermissionPolicyService.can_manage(context, chat_id, update.effective_user.id)


def with_list_return(markup, context, *, chat_id: int, feature: str):
    page = list_options(context, feature, chat_id)["page"]
    prefix = {"autoreply": "auto_reply:list:", "scheduled": "sm:list:", "ads": "ads:list:"}[feature]
    rows = [[InlineKeyboardButton("返回列表", callback_data=list_callback(feature, chat_id, value=page))
        if (button.callback_data or "").startswith(prefix) else button for button in row]
        for row in markup.inline_keyboard]
    return InlineKeyboardMarkup(rows)


def _item_label(item, feature: str) -> tuple[str, str]:
    if feature == "autoreply":
        return str(item.id), "、".join(item.keywords or []) or "待配置"
    key = item.short_id if feature == "scheduled" else item.id
    return str(key), item.title or "待配置"


def _detail_callback(feature: str, chat_id: int, key) -> str:
    return {"autoreply": f"auto_reply:detail:{chat_id}:{key}",
        "scheduled": f"sm:open:{chat_id}:{key}", "ads": f"ads:detail:{chat_id}:{key}"}[feature]


def _create_callback(feature: str, chat_id: int) -> str:
    return {"autoreply": f"auto_reply:create:{chat_id}", "scheduled": f"sm:add:{chat_id}",
        "ads": f"ads:create:{chat_id}"}[feature]


def _list_keyboard(items, feature: str, *, context, chat_id: int, total: int, options: dict):
    rows = []
    for item in items:
        key, title = _item_label(item, feature)
        rows.append([InlineKeyboardButton(f"#{key} {title}"[:60], callback_data=_detail_callback(feature, chat_id, key))])
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = options["page"]
    nav = [InlineKeyboardButton("上一页", callback_data=list_callback(feature, chat_id, value=page-1))] if page else []
    if page + 1 < pages:
        nav.append(InlineKeyboardButton("下一页", callback_data=list_callback(feature, chat_id, value=page+1)))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("修改搜索", callback_data=list_callback(feature, chat_id, action="search")),
        InlineKeyboardButton("清除搜索", callback_data=list_callback(feature, chat_id, action="clear"))])
    rows.append([InlineKeyboardButton(("✅ " if options["status"] == key else "") + title,
        callback_data=list_callback(feature, chat_id, action="filter", value=key)) for key, title in FILTERS.items()])
    rows.extend([[InlineKeyboardButton("➕ 添加一条", callback_data=_create_callback(feature, chat_id))],
        [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:category_messages:{chat_id}")]])
    if feature in {'ads','scheduled'}:
        rows.insert(-1,[InlineKeyboardButton('附加动作/清理恢复',callback_data=f'eff:{chat_id}:delivery_action:list')])
    from backend.features.admin.menu_origins import with_menu_origin
    return with_menu_origin(InlineKeyboardMarkup(rows), context, chat_id=chat_id, feature=feature)


async def render_list(update, context, *, feature: str, chat_id: int, page: int | None = None):
    if not await _authorized(update, context, chat_id):
        await MessageHelper.safe_edit(update, "无权查看该群列表，请返回重新选择。")
        return
    options = list_options(context, feature, chat_id)
    db = context.application.bot_data["db"]
    try:
        async with db.session_factory() as session:
            await suspend_inputs(session, update.effective_user.id)
            items, total, actual_page = await search_page(session, feature, chat_id=chat_id,
                query=options["query"], status=options["status"], page=options["page"] if page is None else page)
            from backend.features.admin.delivery_summary import delivery_summaries
            summaries = await delivery_summaries(session, feature, chat_id=chat_id, items=items)
            await session.commit()
    except SQLAlchemyError:
        log.exception("admin_list_query_failed", feature=feature, chat_id=chat_id)
        await _show_query_failure(update, context, feature=feature, chat_id=chat_id)
        return
    options["page"] = actual_page
    text = f"{SPECS[feature].title}\n群：{chat_id}\n搜索：{options['query'] or '未设置'} · {FILTERS[options['status']]}\n"
    text += f"{total} 条数据，第 {actual_page + 1} 页/共 {max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)} 页\n"
    text += _item_lines(items, feature, summaries=summaries)
    if not items:
        text += "\n暂无匹配，可修改条件或清除搜索。"
    keyboard = _list_keyboard(items, feature, context=context, chat_id=chat_id, total=total, options=options)
    await MessageHelper.safe_edit(update, text, reply_markup=keyboard)


async def _show_query_failure(update, context, *, feature: str, chat_id: int):
    from backend.features.admin.menu_origins import with_menu_origin
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("重新查询", callback_data=list_callback(feature, chat_id))],
        [InlineKeyboardButton("清除搜索", callback_data=list_callback(feature, chat_id, action="clear"))],
        [InlineKeyboardButton("返回", callback_data=f"adm:menu:category_messages:{chat_id}")],
    ])
    await MessageHelper.safe_edit(update, "查询暂时失败，原搜索条件已保留，请重试或返回。",
        reply_markup=with_menu_origin(keyboard, context, chat_id=chat_id, feature=feature))


def _item_lines(items, feature: str, *, summaries: dict) -> str:
    text = ""
    for item in items:
        key, title = _item_label(item, feature)
        enabled = item.is_active if feature == "autoreply" else item.enabled
        text += f"\n#{key} {_utf16_preview(title,limit=60)} · {'启用' if enabled else '关闭'}\n"
        identity = item.task_id if feature == "scheduled" else getattr(item, "id", None)
        if identity in summaries:
            text += _summary_preview(summaries[identity]) + "\n"
        if feature == "scheduled":
            from backend.shared.time_helper import format_timestamp
            text += f"下次计划：{format_timestamp(item.next_run_at) if item.next_run_at else '未设置'}\n"
    return text


def _utf16_preview(text,*,limit):
    return text.encode('utf-16-le')[:limit*2].decode('utf-16-le',errors='ignore')


def _summary_preview(summary):
    lines=summary.splitlines()
    links=[line for line in lines if line.startswith('最近成功消息：')]
    reserved=len('\n'.join(links).encode('utf-16-le'))//2
    budget=300-reserved
    kept=[]
    for line in lines:
        if line in links:
            continue
        size=len(line.encode('utf-16-le'))//2+1
        if size<=budget:
            kept.append(line)
            budget-=size
    return '\n'.join(kept+links)


async def list_browser_callback(update, context):
    cb = CallbackParser.parse(update.callback_query.data or "")
    feature, chat_id, action = cb.get(1), cb.get_int_optional(2), cb.get(3)
    if feature not in SPECS or chat_id is None:
        await update.callback_query.answer("群组或权限无效", show_alert=True)
        return
    if not await _authorized(update, context, chat_id):
        await update.callback_query.answer("无权查看该群列表", show_alert=True)
        return
    options = list_options(context, feature, chat_id)
    if action == "search":
        await _start_search(update, context, feature=feature, chat_id=chat_id)
        return
    if not _change_list_options(options, cb, action=action):
        await update.callback_query.answer("无效列表操作", show_alert=True)
        return
    await render_list(update, context, feature=feature, chat_id=chat_id)


def _change_list_options(options, cb, *, action: str) -> bool:
    if action == "clear":
        options.update(query="", page=0)
    elif action == "filter" and cb.get(4) in FILTERS:
        options.update(status=cb.get(4), page=0)
    elif action == "list":
        options["page"] = cb.get_int_optional(4) or 0
    else:
        return False
    return True


async def _start_search(update, context, *, feature: str, chat_id: int):
    async with context.application.bot_data["db"].session_factory() as session:
        await set_user_state(session, update.effective_user.id, update.effective_user.id,
            state_type=SEARCH_STATE, state_data={"target_chat_id": chat_id, "feature": feature})
        await session.commit()
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("取消搜索", callback_data=list_callback(feature, chat_id))]])
    await MessageHelper.safe_edit(update, "请输入关键词、标题或编号（1—100 字）；取消后不再接收搜索文本。", reply_markup=keyboard)


async def handle_list_search_input(update, context, session, *, state, message_text):
    data = state.state_data or {}
    feature, chat_id = data.get("feature"), data.get("target_chat_id")
    if feature not in SPECS or not isinstance(chat_id, int) or not await _authorized(update, context, chat_id):
        await clear_user_state(session, state.chat_id, update.effective_user.id)
        await session.commit()
        await update.effective_message.reply_text("搜索权限已失效，已退出。")
        return
    try:
        query = normalize_query(message_text)
    except ValueError as exc:
        await update.effective_message.reply_text(str(exc))
        return
    list_options(context, feature, chat_id).update(query=query, page=0)
    await clear_user_state(session, state.chat_id, update.effective_user.id)
    await session.commit()
    await render_list(update, context, feature=feature, chat_id=chat_id)
