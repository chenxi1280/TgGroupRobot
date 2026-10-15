"""Validated plaintext notices, with independent media/buttons/retention."""
import datetime as dt
import string
from telegram import InlineKeyboardMarkup
from telegram.error import BadRequest
from backend.shared.ui.button_input import parse_button_rows

MAX_TEXT = 1000
MAX_RETENTION = 86400
MAX_ADVANCE = 30
MAX_CAPTION = 1024
MAX_MESSAGE = 4096
MAX_BUTTON_ROWS = 6


def template(value: str, *, fields: set[str]) -> str:
    if not value.strip() or len(value) > MAX_TEXT:
        raise ValueError('请输入1—1000字纯文本。')
    for _, field, spec, conversion in string.Formatter().parse(value):
        if field is not None and (field not in fields or spec or conversion):
            raise ValueError('文案占位符无效，请使用页面列出的字段。')
    return value


def parse_value(key: str, text: str, *, fields: set[str], message=None):
    if key == 'text':
        return template(text, fields=fields)
    if key == 'buttons':
        if text.strip() == '清空':
            return []
        return _parse_buttons(text)
    if key == 'cover':
        if text.strip() == '清空':
            return None
        if message is not None and message.photo:
            return message.photo[-1].file_id
        raise ValueError('请发送图片，或输入 清空。')
    return _parse_scalar(key, text)


def _parse_scalar(key, text):
    if key in {'delete_seconds', 'advance_days'}:
        maximum = MAX_RETENTION if key == 'delete_seconds' else MAX_ADVANCE
        if text.isascii() and text.isdigit() and 0 <= int(text) <= maximum:
            return int(text)
        raise ValueError(f'请输入0—{maximum}的整数。')
    if key == 'time':
        hour, minute = text.split(':')
        dt.time(int(hour), int(minute))
        return f'{int(hour):02}:{int(minute):02}'
    raise ValueError('无效配置字段。')


async def send_notice(bot, chat_id: int, config: dict, *, values: dict):
    fields = set(values)
    text = template(config['text'], fields=fields).format_map(values)
    limit = MAX_CAPTION if config.get('cover') else MAX_MESSAGE
    if len(text) > limit:
        raise BadRequest(f'展开后的通知超过{limit}字，请缩短文案。')
    markup = InlineKeyboardMarkup.de_json({'inline_keyboard': config.get('buttons', [])}, bot)
    if config.get('cover'):
        return await bot.send_photo(chat_id=chat_id, photo=config['cover'], caption=text, reply_markup=markup, parse_mode=None)
    return await bot.send_message(chat_id=chat_id, text=text, reply_markup=markup, parse_mode=None)


def _parse_buttons(text):
    rows = parse_button_rows(text)
    if len(rows) > MAX_BUTTON_ROWS:
        raise ValueError('按钮最多6行，每行最多4个。')
    return rows
