from __future__ import annotations

import re

from telegram import Update
from telegram.ext import ContextTypes

from backend.features.points.services.points_extended_service import PointsExtendedService
from backend.shared.services.base import ValidationError
from backend.shared.services.permission_service import PermissionPolicyService
from backend.shared.services.user_service import ensure_user


def _admin_handler_instance():
    from backend.features.admin.admin_handler import _admin_handler

    return _admin_handler


def _admin_module():
    import backend.features.admin.admin_handler as admin_handler_module

    return admin_handler_module


async def handle_points_extended_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state,
    message_text: str,
) -> None:
    if update.effective_user is None or update.effective_message is None:
        return

    admin_module = _admin_module()
    target_chat_id = state.state_data.get("target_chat_id", state.chat_id)
    allowed, error_text = await admin_module.PermissionPolicyService.require_manage(
        context,
        target_chat_id,
        update.effective_user.id,
        capability="settings",
    )
    if not allowed:
        if error_text:
            await update.effective_message.reply_text(error_text)
        return

    state_type = state.state_type
    text_value = message_text.strip()

    async def _clear_points_state() -> None:
        await admin_module.clear_user_state(session, chat_id=target_chat_id, user_id=update.effective_user.id)
        await admin_module.clear_user_state(session, chat_id=update.effective_user.id, user_id=update.effective_user.id)

    def _parse_state_int(key: str) -> int | None:
        raw = state.state_data.get(key)
        if raw is None:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    if state_type in {"custom_points_name_input", "custom_points_rank_input", "custom_points_adjust_input"}:
        type_id = _parse_state_int("type_id")
        if type_id is None:
            await _clear_points_state()
            await session.commit()
            await update.effective_message.reply_text("自定义积分状态异常，已自动退出，请重新进入页面。")
            return
        item = await admin_module.PointsExtendedService.get_custom_point_type(session, target_chat_id, type_id)
        if item is None:
            await _clear_points_state()
            await session.commit()
            await update.effective_message.reply_text("自定义积分不存在，请重新进入页面。")
            return
        if state_type == "custom_points_name_input":
            if not text_value:
                await update.effective_message.reply_text("积分名字不能为空。")
                return
            try:
                await admin_module.PointsExtendedService.update_custom_point_type(session, item, name=text_value[:64])
            except ValidationError as exc:
                await update.effective_message.reply_text(str(exc))
                return
        elif state_type == "custom_points_rank_input":
            try:
                await admin_module.PointsExtendedService.update_custom_point_type(
                    session,
                    item,
                    rank_command=(None if text_value in {"", "清空"} else text_value[:32]),
                )
            except ValidationError as exc:
                await update.effective_message.reply_text(str(exc))
                return
        else:
            parts = message_text.strip().split(maxsplit=2)
            if len(parts) < 2 or not re.fullmatch(r"-?\d+", parts[0]) or not re.fullmatch(r"\d+", parts[1]):
                await update.effective_message.reply_text("格式错误，请输入：用户ID 数量 备注(可选)")
                return
            target_user_id = int(parts[0])
            amount = int(parts[1])
            if amount <= 0:
                await update.effective_message.reply_text("数量必须大于 0。")
                return
            mode = state.state_data.get("mode")
            if mode not in {"add", "deduct"}:
                await _clear_points_state()
                await session.commit()
                await update.effective_message.reply_text("自定义积分操作类型异常，已自动退出，请重新进入页面。")
                return
            delta = amount if mode == "add" else -amount
            reason_note = parts[2].strip() if len(parts) >= 3 else None
            await admin_module.ensure_user(
                session,
                user_id=target_user_id,
                username=None,
                first_name=None,
                last_name=None,
                language_code=None,
            )
            balance = await admin_module.PointsExtendedService.adjust_custom_points(
                session,
                chat_id=target_chat_id,
                type_id=item.id,
                user_id=target_user_id,
                delta=delta,
                operator_user_id=update.effective_user.id,
                reason_note=reason_note,
            )
            await _clear_points_state()
            await session.commit()
            action_text = "增加" if delta > 0 else "扣除"
            await update.effective_message.reply_text(
                f"已为用户 {target_user_id} {action_text} {abs(delta)} {item.name}，当前余额 {balance}。"
            )
            await _admin_handler_instance()._show_custom_point_detail(update, context, target_chat_id, item.id)
            return
        await _clear_points_state()
        await session.commit()
        await _admin_handler_instance()._show_custom_point_detail(update, context, target_chat_id, item.id)
        return

    if state_type in {"points_level_name_input", "points_level_threshold_input"}:
        level_id = _parse_state_int("level_id")
        if level_id is None:
            await _clear_points_state()
            await session.commit()
            await update.effective_message.reply_text("积分等级状态异常，已自动退出，请重新进入页面。")
            return
        level = await admin_module.PointsExtendedService.get_level(session, target_chat_id, level_id)
        if level is None:
            await _clear_points_state()
            await session.commit()
            await update.effective_message.reply_text("积分等级不存在，请重新进入页面。")
            return
        if state_type == "points_level_name_input":
            if not text_value:
                await update.effective_message.reply_text("等级名称不能为空。")
                return
            try:
                await admin_module.PointsExtendedService.update_level(session, level, level_name=text_value[:64])
            except ValidationError as exc:
                await update.effective_message.reply_text(str(exc))
                return
        else:
            if not re.fullmatch(r"\d+", text_value):
                await update.effective_message.reply_text("积分门槛必须是大于 0 的整数。")
                return
            threshold_value = int(text_value)
            if threshold_value <= 0:
                await update.effective_message.reply_text("积分门槛必须大于 0。")
                return
            try:
                await admin_module.PointsExtendedService.update_level(session, level, point_threshold=threshold_value)
            except ValidationError as exc:
                await update.effective_message.reply_text(str(exc))
                return
        await _clear_points_state()
        await session.commit()
        await _admin_handler_instance()._show_points_level_detail(update, context, target_chat_id, level.id)
        return

    if state_type == "points_mall_command_input":
        if not text_value:
            await update.effective_message.reply_text("商城指令不能为空。")
            return
        setting = await admin_module.PointsExtendedService.get_or_create_mall_setting(session, target_chat_id)
        await admin_module.PointsExtendedService.update_mall_setting(session, setting, entry_command=text_value[:32])
        await _clear_points_state()
        await session.commit()
        await _admin_handler_instance()._show_points_mall_menu(update, context, target_chat_id)
        return

    if state_type == "points_mall_cover_input":
        setting = await admin_module.PointsExtendedService.get_or_create_mall_setting(session, target_chat_id)
        if text_value == "清空":
            await admin_module.PointsExtendedService.update_mall_setting(
                session,
                setting,
                cover_media_type=None,
                cover_file_id=None,
            )
        else:
            message = update.effective_message
            if message.photo:
                await admin_module.PointsExtendedService.update_mall_setting(
                    session,
                    setting,
                    cover_media_type="photo",
                    cover_file_id=message.photo[-1].file_id,
                )
            elif message.video:
                await admin_module.PointsExtendedService.update_mall_setting(
                    session,
                    setting,
                    cover_media_type="video",
                    cover_file_id=message.video.file_id,
                )
            else:
                await update.effective_message.reply_text("请发送图片或视频，或输入 清空。")
                return
        await _clear_points_state()
        await session.commit()
        await _admin_handler_instance()._show_points_mall_cover_page(update, context, target_chat_id)
        return

    if state_type.startswith("points_mall_product_"):
        product_id = _parse_state_int("product_id")
        if product_id is None:
            await _clear_points_state()
            await session.commit()
            await update.effective_message.reply_text("商城商品状态异常，已自动退出，请重新进入页面。")
            return
        product = await admin_module.PointsExtendedService.get_product(session, target_chat_id, product_id)
        if product is None:
            await _clear_points_state()
            await session.commit()
            await update.effective_message.reply_text("商城商品不存在，请重新进入页面。")
            return

        if state_type == "points_mall_product_name_input":
            if not text_value:
                await update.effective_message.reply_text("商品名称不能为空。")
                return
            await admin_module.PointsExtendedService.update_product(session, product, name=text_value[:128])
        elif state_type == "points_mall_product_price_input":
            if not re.fullmatch(r"\d+", text_value):
                await update.effective_message.reply_text("所需积分必须是非负整数。")
                return
            price_value = int(text_value)
            if price_value <= 0:
                await update.effective_message.reply_text("所需积分必须大于 0。")
                return
            await admin_module.PointsExtendedService.update_product(session, product, price_points=price_value)
        elif state_type == "points_mall_product_limit_input":
            if not re.fullmatch(r"\d+", text_value):
                await update.effective_message.reply_text("限购次数必须是非负整数。")
                return
            limit_value = int(text_value)
            await admin_module.PointsExtendedService.update_product(
                session,
                product,
                limit_per_user=(None if limit_value == 0 else limit_value),
            )
        elif state_type == "points_mall_product_stock_input":
            if not re.fullmatch(r"\d+", text_value):
                await update.effective_message.reply_text("可售数量必须是非负整数。")
                return
            stock_value = int(text_value)
            await admin_module.PointsExtendedService.update_product_stock_total(
                session,
                product,
                stock_total=stock_value,
            )
        elif state_type == "points_mall_product_fulfiller_input":
            if text_value == "清空":
                await admin_module.PointsExtendedService.update_product(session, product, fulfiller_user_id=None)
            else:
                fulfiller_user_id = await admin_module.PointsExtendedService.resolve_user_id(session, text_value)
                if fulfiller_user_id is None:
                    await update.effective_message.reply_text("未找到该用户，请输入用户ID或已记录的用户名。")
                    return
                if not await admin_module.PointsExtendedService.is_chat_member(session, target_chat_id, fulfiller_user_id):
                    await update.effective_message.reply_text("发放人员必须是当前群组成员。")
                    return
                await admin_module.PointsExtendedService.update_product(session, product, fulfiller_user_id=fulfiller_user_id)
        elif state_type == "points_mall_product_description_input":
            await admin_module.PointsExtendedService.update_product(
                session,
                product,
                description=None if text_value == "清空" else message_text.strip(),
            )
        elif state_type == "points_mall_product_sort_input":
            if not re.fullmatch(r"-?\d+", text_value):
                await update.effective_message.reply_text("排序权重必须是整数。")
                return
            await admin_module.PointsExtendedService.update_product(session, product, sort_weight=int(text_value))
        elif state_type == "points_mall_product_cover_input":
            if text_value == "清空":
                await admin_module.PointsExtendedService.update_product(
                    session,
                    product,
                    cover_media_type=None,
                    cover_file_id=None,
                )
            else:
                message = update.effective_message
                if message.photo:
                    await admin_module.PointsExtendedService.update_product(
                        session,
                        product,
                        cover_media_type="photo",
                        cover_file_id=message.photo[-1].file_id,
                    )
                elif message.video:
                    await admin_module.PointsExtendedService.update_product(
                        session,
                        product,
                        cover_media_type="video",
                        cover_file_id=message.video.file_id,
                    )
                else:
                    await update.effective_message.reply_text("请发送图片或视频，或输入 清空。")
                    return

        await _clear_points_state()
        await session.commit()
        await _admin_handler_instance()._show_points_mall_product_detail(update, context, target_chat_id, product.product_id)
        return

    await update.effective_message.reply_text("当前积分扩展配置状态不支持该输入，请重新进入配置页面。")
