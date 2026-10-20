"""Activity draft calendars: selection never invokes a publication operation."""
import datetime as dt
import hashlib
import json

from telegram import InlineKeyboardMarkup

from backend.shared.ui.datetime_picker import KEY, entry_button, new_picker
from backend.shared.time_helper import LOCAL_TIMEZONE
from backend.shared.time_ui import next_top_of_hour

STATES = {"lottery_create", "solitaire_create", "guess_wait_deadline", "auction_wait_end_at"}


def clean(data):
    return {key: value for key, value in data.items() if key != KEY}


def fingerprint(data):
    payload = {key: value for key, value in clean(data).items() if key != "updated_at"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def attach(data, *, back, initial=None):
    data = clean(data)
    sample = next_top_of_hour(days_offset=1).astimezone(LOCAL_TIMEZONE).strftime("%Y-%m-%d %H:%M")
    if initial:
        parsed = dt.datetime.fromisoformat(initial)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=LOCAL_TIMEZONE)
        sample = parsed.astimezone(LOCAL_TIMEZONE).strftime("%Y-%m-%d %H:%M")
    picker = {**new_picker(back, sample), "prefix": "acal", "base": fingerprint(data)}
    return {**data, KEY: picker}


def with_calendar(keyboard, data):
    picker = data.get(KEY)
    if not picker:
        return keyboard
    return InlineKeyboardMarkup([[entry_button(picker)], *keyboard.inline_keyboard])


async def block_text(update, state):
    picker = (state.state_data or {}).get(KEY)
    if picker and picker.get("step") != "input":
        await update.effective_message.reply_text("正在选择日期，请使用最新日历确认，或点击手动输入/取消；本条消息未保存。")
        return True
    return False
