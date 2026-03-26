from __future__ import annotations

from telegram import Update

_CALLBACK_ANSWERED_ATTR = "_safe_answered"


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
    if getattr(update.callback_query, _CALLBACK_ANSWERED_ATTR, False):
        return

    safe_text = text.strip() or fallback_text
    if len(safe_text) > 180:
        safe_text = fallback_text

    try:
        await update.callback_query.answer(text=safe_text, show_alert=show_alert)
        setattr(update.callback_query, _CALLBACK_ANSWERED_ATTR, True)
    except Exception:
        try:
            await update.callback_query.answer(text=fallback_text, show_alert=show_alert)
            setattr(update.callback_query, _CALLBACK_ANSWERED_ATTR, True)
        except Exception:
            return


def mark_callback_query_answered(update: Update) -> None:
    if update.callback_query is None:
        return
    setattr(update.callback_query, _CALLBACK_ANSWERED_ATTR, True)
