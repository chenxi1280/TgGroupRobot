"""Native clipboard buttons; never silently truncate values such as URLs."""
from telegram import InlineKeyboardButton

COPY_TEXT_LIMIT = 256


def copy_button(label: str, value: str) -> InlineKeyboardButton:
    if not isinstance(value, str) or not 1 <= len(value) <= COPY_TEXT_LIMIT:
        raise ValueError("复制内容须为 1—256 个字符；较长内容请导出文件。")
    return InlineKeyboardButton(label, api_kwargs={"copy_text": {"text": value}})


def copy_value_rows(values: list[tuple[str, str]]) -> list[list[InlineKeyboardButton]]:
    buttons = [copy_button(label, value) for label, value in values
               if isinstance(value, str) and 1 <= len(value) <= COPY_TEXT_LIMIT]
    return [buttons[index:index + 2] for index in range(0, len(buttons), 2)]
