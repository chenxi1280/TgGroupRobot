from __future__ import annotations

from collections import deque

from telegram import Update

_ANSWERED_CACHE_LIMIT = 2048
_ANSWERED_CALLBACK_IDS: set[str] = set()
_ANSWERED_CALLBACK_QUEUE: deque[str] = deque()


def _get_callback_query_token(update: Update) -> str | None:
    callback_query = update.callback_query
    if callback_query is None:
        return None

    callback_id = getattr(callback_query, "id", None)
    if callback_id:
        return f"id:{callback_id}"
    return f"obj:{id(callback_query)}"


def _is_callback_query_answered(update: Update) -> bool:
    token = _get_callback_query_token(update)
    if token is None:
        return False
    return token in _ANSWERED_CALLBACK_IDS


def _remember_callback_query_answered(update: Update) -> None:
    token = _get_callback_query_token(update)
    if token is None or token in _ANSWERED_CALLBACK_IDS:
        return

    _ANSWERED_CALLBACK_IDS.add(token)
    _ANSWERED_CALLBACK_QUEUE.append(token)
    while len(_ANSWERED_CALLBACK_QUEUE) > _ANSWERED_CACHE_LIMIT:
        expired = _ANSWERED_CALLBACK_QUEUE.popleft()
        _ANSWERED_CALLBACK_IDS.discard(expired)


def build_public_error_text(error: Exception | None, fallback: str = "操作失败，请重试") -> str:
    """将内部异常压缩为适合 Telegram 展示的短文本。"""
    if error is None:
        return fallback

    text = str(error).strip()
    if not text:
        return fallback

    first_line = text.splitlines()[0].strip()
    if not first_line:
        return fallback

    if len(first_line) > 120:
        return fallback
    return first_line


async def answer_callback_query_safely(
    update: Update,
    text: str,
    *,
    show_alert: bool = True,
    fallback_text: str = "操作失败，请重试",
) -> None:
    """安全回复 callback query，避免因文本过长再次触发 Telegram 异常。"""
    if update.callback_query is None:
        return
    if _is_callback_query_answered(update):
        return

    safe_text = text.strip() or fallback_text
    if len(safe_text) > 180:
        safe_text = fallback_text

    try:
        await update.callback_query.answer(text=safe_text, show_alert=show_alert)
        _remember_callback_query_answered(update)
    except Exception:
        try:
            await update.callback_query.answer(text=fallback_text, show_alert=show_alert)
            _remember_callback_query_answered(update)
        except Exception:
            return


def mark_callback_query_answered(update: Update) -> None:
    if update.callback_query is None:
        return
    _remember_callback_query_answered(update)
