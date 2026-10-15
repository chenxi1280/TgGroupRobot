from __future__ import annotations

from backend.shared.ui.admin_keyboard import admin_keyboard

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def points_mall_home_keyboard(setting, chat_id: int) -> InlineKeyboardMarkup:
    enabled = bool(setting.enabled)
    auto_unlist = bool(setting.auto_unlist_when_out_of_stock)
    notice_text = "不删除" if setting.redeem_notice_delete_seconds <= 0 else f"{setting.redeem_notice_delete_seconds}秒后删除"
    return admin_keyboard(
        [
            [
                InlineKeyboardButton("⚙️ 状态：", callback_data=f"adm:mall:{chat_id}:noop"),
                InlineKeyboardButton("✅ 启动" if enabled else "启动", callback_data=f"adm:mall:{chat_id}:toggle:enabled:1"),
                InlineKeyboardButton("关闭" if enabled else "❌ 关闭", callback_data=f"adm:mall:{chat_id}:toggle:enabled:0"),
            ],
            [
                InlineKeyboardButton("📦 无货下架：", callback_data=f"adm:mall:{chat_id}:noop"),
                InlineKeyboardButton("✅ 启动" if auto_unlist else "启动", callback_data=f"adm:mall:{chat_id}:toggle:auto_unlist:1"),
                InlineKeyboardButton("关闭" if auto_unlist else "❌ 关闭", callback_data=f"adm:mall:{chat_id}:toggle:auto_unlist:0"),
            ],
            [
                InlineKeyboardButton("🔔 兑换通知：", callback_data=f"adm:mall:{chat_id}:noop"),
                InlineKeyboardButton(notice_text, callback_data=f"adm:mall:{chat_id}:edit:notice"),
            ],
            [
                InlineKeyboardButton("🖼️ 商城封面", callback_data=f"adm:menu:points_mall_cover:{chat_id}"),
                InlineKeyboardButton("⚙️ 修改指令", callback_data=f"adm:mall:{chat_id}:edit:command"),
            ],
            [InlineKeyboardButton("打开用户商城", callback_data=f"mall:list:{chat_id}")],
            [InlineKeyboardButton("🛍️ 管理商品", callback_data=f"adm:menu:points_mall_products:{chat_id}")],
            [InlineKeyboardButton("🧼 管理订单", callback_data=f"adm:menu:points_mall_orders:{chat_id}")],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:category_growth:{chat_id}")],
        ]
    )


def points_mall_products_keyboard(products, chat_id: int, *, page: int = 0, total: int | None = None) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(f"🔢 编号:{product.product_id}", callback_data=f"adm:mall:{chat_id}:product:detail:{product.product_id}"),
            InlineKeyboardButton("🧾 订单", callback_data=f"adm:mall:{chat_id}:orders:{product.product_id}"),
            InlineKeyboardButton("🔧 修改", callback_data=f"adm:mall:{chat_id}:product:detail:{product.product_id}"),
            InlineKeyboardButton("🗑 删除", callback_data=f"adm:mall:{chat_id}:product:delete_confirm:{product.product_id}"),
        ]
        for product in products
    ]
    total = len(products) if total is None else total
    nav = []
    if page:
        nav.append(InlineKeyboardButton("上一页", callback_data=f"adm:mall:{chat_id}:products:{page-1}"))
    if (page+1)*8 < total:
        nav.append(InlineKeyboardButton("下一页", callback_data=f"adm:mall:{chat_id}:products:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("刷新", callback_data=f"adm:mall:{chat_id}:products:{page}")])
    rows.append([InlineKeyboardButton("➕ 添加一条", callback_data=f"adm:mall:{chat_id}:product:add")])
    rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:points_mall:{chat_id}")])
    return InlineKeyboardMarkup(rows)


def points_mall_product_detail_keyboard(product, chat_id: int) -> InlineKeyboardMarkup:
    sale_toggle = "❎ 下架停售" if product.status == "on_sale" else "✅ 上架销售"
    sale_value = 0 if product.status == "on_sale" else 1
    return admin_keyboard(
        [
            [
                InlineKeyboardButton("🏷️ 商品名称", callback_data=f"adm:mall:{chat_id}:product:edit:{product.product_id}:name"),
                InlineKeyboardButton("🖼️ 上传封面", callback_data=f"adm:mall:{chat_id}:product:edit:{product.product_id}:cover"),
                InlineKeyboardButton("🪙 所需积分", callback_data=f"adm:mall:{chat_id}:product:edit:{product.product_id}:price"),
            ],
            [
                InlineKeyboardButton("📮 限购设置", callback_data=f"adm:mall:{chat_id}:product:edit:{product.product_id}:limit"),
                InlineKeyboardButton("🛒 可售数量", callback_data=f"adm:mall:{chat_id}:product:edit:{product.product_id}:stock"),
                InlineKeyboardButton("👤 发放人员", callback_data=f"adm:mall:{chat_id}:product:edit:{product.product_id}:fulfiller"),
            ],
            [
                InlineKeyboardButton("⚠️ 兑换说明", callback_data=f"adm:mall:{chat_id}:product:edit:{product.product_id}:description"),
                InlineKeyboardButton("↕️ 排序权重", callback_data=f"adm:mall:{chat_id}:product:edit:{product.product_id}:sort"),
            ],
            [
                InlineKeyboardButton(sale_toggle, callback_data=f"adm:mall:{chat_id}:product:toggle:{product.product_id}:{sale_value}"),
                InlineKeyboardButton("👀 预览效果", callback_data=f"adm:mall:{chat_id}:product:preview:{product.product_id}"),
            ],
            [InlineKeyboardButton("🔙 返回上页", callback_data=f"adm:menu:points_mall_products:{chat_id}")],
        ]
    )


def points_mall_orders_keyboard(chat_id: int, orders=None, product_id: int | None = None, *, status: str = "all", status_counts: dict[str, int] | None = None, page: int = 0, total: int | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    counts = status_counts or {}
    normalized_status = _mall_order_status(status)
    status_to_code = {"all": "a", "created": "c", "fulfilled": "f", "canceled": "x", "refunded": "r"}
    rows.append(_mall_order_status_buttons(chat_id, product_id, counts=counts, normalized_status=normalized_status, status_to_code=status_to_code))
    product_token = product_id if product_id is not None else 0
    selected_code = status_to_code[normalized_status]
    for order in orders or []:
        rows.append([InlineKeyboardButton(f"🧾 订单#{order.order_id}", callback_data=f"adm:mall:{chat_id}:order:detail:{order.order_id}:{selected_code}:{product_token}:{page}")])
    total = int(counts.get(normalized_status, 0)) if total is None else total
    pagination = []
    for label, target in (("上一页", page - 1), ("下一页", page + 1)):
        if 0 <= target < max(1, (total + 7) // 8):
            pagination.append(InlineKeyboardButton(label, callback_data=f"adm:mall:{chat_id}:orders_status:{selected_code}:{product_token}:{target}"))
    if pagination:
        rows.append(pagination)
    rows.append([InlineKeyboardButton("刷新", callback_data=f"adm:mall:{chat_id}:orders_status:{selected_code}:{product_token}:{page}")])
    rows.append([InlineKeyboardButton("按订单编号查找", callback_data=f"morder:search:{chat_id}:0")])
    back_target = f"adm:menu:points_mall_products:{chat_id}" if product_id is not None else f"adm:menu:points_mall:{chat_id}"
    rows.append([InlineKeyboardButton("🔙 返回", callback_data=back_target)])
    return InlineKeyboardMarkup(rows)


def points_mall_order_detail_keyboard(chat_id: int, order, *, status: str = "all", product_id: int | None = None, page: int = 0) -> InlineKeyboardMarkup:
    normalized_status = _mall_order_status(status)
    status_code = {"all": "a", "created": "c", "fulfilled": "f", "canceled": "x", "refunded": "r"}[normalized_status]
    product_token = product_id if product_id is not None else 0
    back_target = f"adm:mall:{chat_id}:orders_status:{status_code}:{product_token}:{page}"
    return admin_keyboard(
        [
            [
                InlineKeyboardButton("📦 完成发货", callback_data=f"adm:mall:{chat_id}:order:fulfill:{order.order_id}:{status_code}:{product_token}:{page}"),
                InlineKeyboardButton("❌ 取消订单", callback_data=f"adm:mall:{chat_id}:order:cancel:{order.order_id}:{status_code}:{product_token}:{page}"),
            ],
            [InlineKeyboardButton("💸 退款", callback_data=f"adm:mall:{chat_id}:order:refund:{order.order_id}:{status_code}:{product_token}:{page}")],
            [InlineKeyboardButton("🔙 返回", callback_data=back_target)],
        ]
    )


def points_mall_cover_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return admin_keyboard(
        [
            [
                InlineKeyboardButton("🖼️ 上传封面", callback_data=f"adm:mall:{chat_id}:edit:cover"),
                InlineKeyboardButton("🧹 清空封面", callback_data=f"adm:mall:{chat_id}:cover:clear"),
            ],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:points_mall:{chat_id}")],
        ]
    )


def points_mall_notice_keyboard(chat_id: int, current_seconds: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    current = max(int(current_seconds), 0)
    for label, seconds in [("不删除", 0), ("30秒后删除", 30), ("60秒后删除", 60), ("90秒后删除", 90), ("2分钟", 120), ("5分钟", 300)]:
        prefix = "✅ " if current == seconds else ""
        rows.append([InlineKeyboardButton(f"{prefix}{label}", callback_data=f"adm:mall:{chat_id}:notice:{seconds}")])
    rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:points_mall:{chat_id}")])
    return admin_keyboard(rows)


def points_mall_command_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return admin_keyboard([[InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:points_mall:{chat_id}")]])


def user_points_mall_keyboard(chat_id: int, products) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(f"{product.name} · {product.price_points}积分 · 余{product.stock_left}", callback_data=f"mall:detail:{chat_id}:{product.product_id}")] for product in products]
    rows.append([InlineKeyboardButton("我的订单", callback_data="morder:mine:0:0")])
    rows.append([InlineKeyboardButton("刷新商品", callback_data=f"mall:list:{chat_id}")])
    return InlineKeyboardMarkup(rows)


def _mall_order_status_buttons(chat_id, product_id, *, counts, normalized_status, status_to_code):
    status_items = [("all", "📋 全部"), ("created", "🟡 待处理"), ("fulfilled", "✅ 已发放"), ("canceled", "❌ 已取消"), ("refunded", "💸 已退款")]
    status_row: list[InlineKeyboardButton] = []
    for key, title in status_items:
        label = f"{title}({int(counts.get(key, 0))})"
        if normalized_status == key:
            label = f"✅ {label}"
        code = status_to_code[key]
        callback = f"adm:mall:{chat_id}:orders_status:{code}:{product_id}" if product_id is not None else f"adm:mall:{chat_id}:orders_status:{code}"
        status_row.append(InlineKeyboardButton(label, callback_data=callback))
    return status_row


def _mall_order_status(status):
    return status if status in {"all", "created", "fulfilled", "canceled", "refunded"} else "all"
