"""积分扩展模块键盘。"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def _bool_label(enabled: bool, true_label: str, false_label: str) -> str:
    return f"✅ {true_label}" if enabled else f"❌ {false_label}"


def custom_points_list_keyboard(items, chat_id: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for item in items:
        rows.append(
            [
                InlineKeyboardButton(f"编号:{item.type_no}", callback_data=f"adm:cpt:{chat_id}:detail:{item.id}"),
                InlineKeyboardButton(
                    _bool_label(bool(item.enabled), "启用", "关闭"),
                    callback_data=f"adm:cpt:{chat_id}:toggle:{item.id}:{0 if item.enabled else 1}",
                ),
                InlineKeyboardButton("修改", callback_data=f"adm:cpt:{chat_id}:edit:name:{item.id}"),
                InlineKeyboardButton("删除", callback_data=f"adm:cpt:{chat_id}:delete_confirm:{item.id}"),
            ]
        )
    rows.append([InlineKeyboardButton("添加一条", callback_data=f"adm:cpt:{chat_id}:add")])
    rows.append([InlineKeyboardButton("返回", callback_data=f"adm:menu:points:{chat_id}")])
    return InlineKeyboardMarkup(rows)


def custom_point_detail_keyboard(item, chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("状态：", callback_data=f"adm:cpt:{chat_id}:noop:{item.id}"),
                InlineKeyboardButton("启动", callback_data=f"adm:cpt:{chat_id}:toggle:{item.id}:1"),
                InlineKeyboardButton("❌ 关闭", callback_data=f"adm:cpt:{chat_id}:toggle:{item.id}:0"),
            ],
            [
                InlineKeyboardButton("积分名字：", callback_data=f"adm:cpt:{chat_id}:noop:{item.id}"),
                InlineKeyboardButton(item.name, callback_data=f"adm:cpt:{chat_id}:edit:name:{item.id}"),
            ],
            [
                InlineKeyboardButton("排行指令：", callback_data=f"adm:cpt:{chat_id}:noop:{item.id}"),
                InlineKeyboardButton(item.rank_command or "待配置", callback_data=f"adm:cpt:{chat_id}:edit:rank:{item.id}"),
            ],
            [
                InlineKeyboardButton("增加积分", callback_data=f"adm:cpt:{chat_id}:adjust:add:{item.id}"),
                InlineKeyboardButton("扣除积分", callback_data=f"adm:cpt:{chat_id}:adjust:deduct:{item.id}"),
            ],
            [
                InlineKeyboardButton("导出操作日志", callback_data=f"adm:cpt:{chat_id}:export:{item.id}"),
                InlineKeyboardButton("清空此积分", callback_data=f"adm:cpt:{chat_id}:clear_confirm:{item.id}"),
            ],
            [InlineKeyboardButton("返回", callback_data=f"adm:menu:custom_points:{chat_id}")],
        ]
    )


def points_level_list_keyboard(setting, levels, chat_id: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton("状态：", callback_data=f"adm:lvl:{chat_id}:noop"),
            InlineKeyboardButton("启动", callback_data=f"adm:lvl:{chat_id}:toggle:enabled:1"),
            InlineKeyboardButton("❌ 关闭", callback_data=f"adm:lvl:{chat_id}:toggle:enabled:0"),
        ],
        [
            InlineKeyboardButton("排除老师：", callback_data=f"adm:lvl:{chat_id}:noop"),
            InlineKeyboardButton("启动", callback_data=f"adm:lvl:{chat_id}:toggle:exclude_teacher:1"),
            InlineKeyboardButton("❌ 关闭", callback_data=f"adm:lvl:{chat_id}:toggle:exclude_teacher:0"),
        ],
    ]
    if levels:
        for level in levels:
            rows.append(
                [InlineKeyboardButton(f"{level.level_name} / {level.point_threshold}", callback_data=f"adm:lvl:{chat_id}:detail:{level.id}")]
            )
    else:
        rows.append([InlineKeyboardButton("待配置", callback_data=f"adm:lvl:{chat_id}:noop")])
    rows.append([InlineKeyboardButton("添加一个等级", callback_data=f"adm:lvl:{chat_id}:add")])
    rows.append([InlineKeyboardButton("返回", callback_data=f"adm:menu:points:{chat_id}")])
    return InlineKeyboardMarkup(rows)


def points_level_detail_keyboard(level, chat_id: int) -> InlineKeyboardMarkup:
    perms = [
        ("发送文字：", "allow_text", level.allow_text),
        ("发送音频：", "allow_audio", level.allow_audio),
        ("发送图片：", "allow_photo", level.allow_photo),
        ("发送视频：", "allow_video", level.allow_video),
        ("发送贴纸：", "allow_sticker", level.allow_sticker),
        ("发送文件：", "allow_document", level.allow_document),
        ("发送@提到：", "allow_mention", level.allow_mention),
    ]
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton("等级名称：", callback_data=f"adm:lvl:{chat_id}:noop"),
            InlineKeyboardButton(level.level_name or "未配置", callback_data=f"adm:lvl:{chat_id}:edit:name:{level.id}"),
        ],
        [
            InlineKeyboardButton("积分门槛线：", callback_data=f"adm:lvl:{chat_id}:noop"),
            InlineKeyboardButton(str(level.point_threshold), callback_data=f"adm:lvl:{chat_id}:edit:threshold:{level.id}"),
        ],
    ]
    for label, perm, enabled in perms:
        rows.append(
            [
                InlineKeyboardButton(label, callback_data=f"adm:lvl:{chat_id}:noop"),
                InlineKeyboardButton("✅ 允许" if enabled else "允许", callback_data=f"adm:lvl:{chat_id}:perm:{level.id}:{perm}:1"),
                InlineKeyboardButton("不允许" if enabled else "❌ 不允许", callback_data=f"adm:lvl:{chat_id}:perm:{level.id}:{perm}:0"),
            ]
        )
    rows.append([InlineKeyboardButton("删除此等级", callback_data=f"adm:lvl:{chat_id}:delete_confirm:{level.id}")])
    rows.append([InlineKeyboardButton("返回", callback_data=f"adm:menu:points_level:{chat_id}")])
    return InlineKeyboardMarkup(rows)


def points_mall_home_keyboard(setting, chat_id: int) -> InlineKeyboardMarkup:
    enabled = bool(setting.enabled)
    auto_unlist = bool(setting.auto_unlist_when_out_of_stock)
    notice_text = "不删除" if setting.redeem_notice_delete_seconds <= 0 else f"{setting.redeem_notice_delete_seconds}秒后删除"
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("状态：", callback_data=f"adm:mall:{chat_id}:noop"),
                InlineKeyboardButton("✅ 启动" if enabled else "启动", callback_data=f"adm:mall:{chat_id}:toggle:enabled:1"),
                InlineKeyboardButton("关闭" if enabled else "❌ 关闭", callback_data=f"adm:mall:{chat_id}:toggle:enabled:0"),
            ],
            [
                InlineKeyboardButton("无货下架：", callback_data=f"adm:mall:{chat_id}:noop"),
                InlineKeyboardButton("启动" if auto_unlist else "✅ 启动", callback_data=f"adm:mall:{chat_id}:toggle:auto_unlist:1"),
                InlineKeyboardButton("❌ 关闭" if auto_unlist else "关闭", callback_data=f"adm:mall:{chat_id}:toggle:auto_unlist:0"),
            ],
            [
                InlineKeyboardButton("兑换通知：", callback_data=f"adm:mall:{chat_id}:noop"),
                InlineKeyboardButton(notice_text, callback_data=f"adm:mall:{chat_id}:edit:notice"),
            ],
            [
                InlineKeyboardButton("商城封面", callback_data=f"adm:menu:points_mall_cover:{chat_id}"),
                InlineKeyboardButton("⚙️ 修改指令", callback_data=f"adm:mall:{chat_id}:edit:command"),
            ],
            [InlineKeyboardButton("🛍️ 管理商品", callback_data=f"adm:menu:points_mall_products:{chat_id}")],
            [InlineKeyboardButton("🧼 管理订单", callback_data=f"adm:menu:points_mall_orders:{chat_id}")],
            [InlineKeyboardButton("返回", callback_data=f"adm:menu:points:{chat_id}")],
        ]
    )


def points_mall_products_keyboard(products, chat_id: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for product in products:
        rows.append(
            [
                InlineKeyboardButton(f"编号:{product.product_id}", callback_data=f"adm:mall:{chat_id}:product:detail:{product.product_id}"),
                InlineKeyboardButton("订单🧾", callback_data=f"adm:mall:{chat_id}:orders:{product.product_id}"),
                InlineKeyboardButton("修改🔧", callback_data=f"adm:mall:{chat_id}:product:detail:{product.product_id}"),
                InlineKeyboardButton("删除🗑", callback_data=f"adm:mall:{chat_id}:product:delete_confirm:{product.product_id}"),
            ]
        )
    rows.append([InlineKeyboardButton("➕ 添加一条", callback_data=f"adm:mall:{chat_id}:product:add")])
    rows.append([InlineKeyboardButton("返回", callback_data=f"adm:menu:points_mall:{chat_id}")])
    return InlineKeyboardMarkup(rows)


def points_mall_product_detail_keyboard(product, chat_id: int) -> InlineKeyboardMarkup:
    sale_toggle = "❎ 下架停售" if product.status == "on_sale" else "✅ 上架销售"
    sale_value = 0 if product.status == "on_sale" else 1
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("商品名称", callback_data=f"adm:mall:{chat_id}:product:edit:{product.product_id}:name"),
                InlineKeyboardButton("上传封面", callback_data=f"adm:mall:{chat_id}:product:edit:{product.product_id}:cover"),
                InlineKeyboardButton("所需积分", callback_data=f"adm:mall:{chat_id}:product:edit:{product.product_id}:price"),
            ],
            [
                InlineKeyboardButton("限购设置", callback_data=f"adm:mall:{chat_id}:product:edit:{product.product_id}:limit"),
                InlineKeyboardButton("可售数量", callback_data=f"adm:mall:{chat_id}:product:edit:{product.product_id}:stock"),
                InlineKeyboardButton("发放人员", callback_data=f"adm:mall:{chat_id}:product:edit:{product.product_id}:fulfiller"),
            ],
            [
                InlineKeyboardButton("兑换说明", callback_data=f"adm:mall:{chat_id}:product:edit:{product.product_id}:description"),
                InlineKeyboardButton("排序权重", callback_data=f"adm:mall:{chat_id}:product:edit:{product.product_id}:sort"),
            ],
            [
                InlineKeyboardButton(sale_toggle, callback_data=f"adm:mall:{chat_id}:product:toggle:{product.product_id}:{sale_value}"),
                InlineKeyboardButton("🏖 预览效果", callback_data=f"adm:mall:{chat_id}:product:preview:{product.product_id}"),
            ],
            [InlineKeyboardButton("返回上页", callback_data=f"adm:menu:points_mall_products:{chat_id}")],
        ]
    )


def points_mall_orders_keyboard(chat_id: int, orders=None, product_id: int | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for order in orders or []:
        rows.append(
            [
                InlineKeyboardButton(
                    f"订单#{order.order_id}",
                    callback_data=f"adm:mall:{chat_id}:order:detail:{order.order_id}",
                )
            ]
        )
    back_target = (
        f"adm:menu:points_mall_products:{chat_id}"
        if product_id is not None
        else f"adm:menu:points_mall:{chat_id}"
    )
    rows.append([InlineKeyboardButton("返回", callback_data=back_target)])
    return InlineKeyboardMarkup(rows)


def points_mall_order_detail_keyboard(chat_id: int, order) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("完成发货", callback_data=f"adm:mall:{chat_id}:order:fulfill:{order.order_id}"),
            InlineKeyboardButton("取消订单", callback_data=f"adm:mall:{chat_id}:order:cancel:{order.order_id}"),
        ],
        [
            InlineKeyboardButton("退款", callback_data=f"adm:mall:{chat_id}:order:refund:{order.order_id}"),
        ],
        [InlineKeyboardButton("返回", callback_data=f"adm:menu:points_mall_orders:{chat_id}")],
    ]
    return InlineKeyboardMarkup(rows)


def points_mall_cover_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("上传封面", callback_data=f"adm:mall:{chat_id}:edit:cover"),
                InlineKeyboardButton("清空封面", callback_data=f"adm:mall:{chat_id}:cover:clear"),
            ],
            [InlineKeyboardButton("返回", callback_data=f"adm:menu:points_mall:{chat_id}")],
        ]
    )


def points_mall_notice_keyboard(chat_id: int, current_seconds: int) -> InlineKeyboardMarkup:
    options = [
        ("不删除", 0),
        ("30秒后删除", 30),
        ("60秒后删除", 60),
        ("90秒后删除", 90),
        ("2分钟", 120),
        ("5分钟", 300),
    ]
    rows: list[list[InlineKeyboardButton]] = []
    current = max(int(current_seconds), 0)
    for label, seconds in options:
        prefix = "✅ " if current == seconds else ""
        rows.append([InlineKeyboardButton(f"{prefix}{label}", callback_data=f"adm:mall:{chat_id}:notice:{seconds}")])
    rows.append([InlineKeyboardButton("返回", callback_data=f"adm:menu:points_mall:{chat_id}")])
    return InlineKeyboardMarkup(rows)


def user_points_mall_keyboard(chat_id: int, products) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for product in products:
        rows.append(
            [
                InlineKeyboardButton(
                    f"{product.name} · {product.price_points}积分 · 余{product.stock_left}",
                    callback_data=f"mall:redeem:{chat_id}:{product.product_id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton("刷新商品", callback_data=f"mall:list:{chat_id}")])
    return InlineKeyboardMarkup(rows)
