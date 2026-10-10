"""One product snapshot renderer for customer detail and administrator preview."""
from telegram import InlineKeyboardMarkup


def product_detail_text(product):
    return (f"{product.name}\n所需积分：{product.price_points}\n可用库存：{product.stock_left}\n"
            f"个人限购：{product.limit_per_user or '不限'}\n发放方式：人工发放\n\n"
            f"{product.description or '暂无兑换说明'}")


def split_telegram_text(text, limit):
    parts, current, units = [], [], 0
    for char in text:
        width = len(char.encode("utf-16-le")) // 2
        if units + width > limit:
            parts.append("".join(current))
            current, units = [], 0
        current.append(char)
        units += width
    if current:
        parts.append("".join(current))
    return parts or [""]


async def send_mall_page(update, text, rows, *, media=None, media_type=None):
    markup = InlineKeyboardMarkup(rows)
    message = update.effective_message
    if media:
        chunks = split_telegram_text(text, 1024)
        caption = chunks.pop(0)
        if media_type == "video":
            await message.reply_video(video=media, caption=caption, reply_markup=markup)
        elif media_type == "document":
            await message.reply_document(document=media, caption=caption, reply_markup=markup)
        else:
            await message.reply_photo(photo=media, caption=caption, reply_markup=markup)
        remainder = "".join(chunks)
        if remainder:
            for chunk in split_telegram_text(remainder, 4096):
                await message.reply_text(chunk)
    else:
        chunks = split_telegram_text(text, 4096)
        for index, chunk in enumerate(chunks):
            await message.reply_text(chunk, reply_markup=markup if index == len(chunks)-1 else None)
