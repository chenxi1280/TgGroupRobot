from __future__ import annotations

import re

from telegram import Update
from telegram.ext import ContextTypes

from backend.shared.services.base import ValidationError
from backend.shared.services.permission_service import PermissionPolicyService


def _admin_handler_instance():
    from backend.features.admin.admin_handler import _admin_handler

    return _admin_handler


def _admin_module():
    import backend.features.admin.admin_handler as admin_handler_module

    return admin_handler_module


async def handle_alliance_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state,
    message_text: str,
) -> None:
    from backend.features.garage.services.alliance_service import AllianceService
    from backend.platform.state.state_service import clear_user_state

    if update.effective_user is None or update.effective_message is None:
        return

    target_chat_id = state.state_data.get("target_chat_id", state.chat_id)
    admin_module = _admin_module()
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

    try:
        if state.state_type == "alliance_create_name_input":
            alliance, invite_code = await AllianceService.create_alliance(
                session,
                chat_id=target_chat_id,
                operator_user_id=update.effective_user.id,
                name=message_text,
            )
            notice = f"联盟创建成功，邀请码：{invite_code}"
        elif state.state_type == "alliance_join_code_input":
            alliance = await AllianceService.join_alliance(
                session,
                chat_id=target_chat_id,
                operator_user_id=update.effective_user.id,
                invite_code=message_text,
            )
            notice = f"已加入联盟：{alliance.name}"
        else:
            await update.effective_message.reply_text("联盟输入状态异常，请重新进入页面。")
            return
    except ValidationError as exc:
        await update.effective_message.reply_text(str(exc))
        return

    await clear_user_state(session, chat_id=target_chat_id, user_id=update.effective_user.id)
    await clear_user_state(session, chat_id=update.effective_user.id, user_id=update.effective_user.id)
    await session.commit()
    await update.effective_message.reply_text(notice)
    await _admin_handler_instance()._show_alliance_menu(update, context, target_chat_id)


async def handle_garage_forward_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state,
    message_text: str,
) -> None:
    from backend.features.garage.services.garage_forward_service import GarageForwardService
    from backend.platform.state.state_service import clear_user_state

    if update.effective_user is None or update.effective_message is None:
        return

    target_chat_id = state.state_data.get("target_chat_id", state.chat_id)
    admin_module = _admin_module()
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

    if state.state_type not in {
        "garage_forward_source_input",
        "garage_forward_keyword_input",
        "garage_forward_buttons_input",
    }:
        await update.effective_message.reply_text("频道同步状态异常，请重新进入页面。")
        return

    if state.state_type == "garage_forward_keyword_input":
        keywords = [
            item.strip()
            for chunk in message_text.replace("，", ",").splitlines()
            for item in chunk.replace(",", " ").split()
            if item.strip()
        ]
        normalized_keywords: list[str] = []
        for item in keywords:
            if item not in normalized_keywords:
                normalized_keywords.append(item[:64])

        await GarageForwardService.update_setting(
            session,
            target_chat_id,
            keyword_rules=normalized_keywords,
        )
        await clear_user_state(session, chat_id=target_chat_id, user_id=update.effective_user.id)
        await clear_user_state(session, chat_id=update.effective_user.id, user_id=update.effective_user.id)
        await session.commit()
        await update.effective_message.reply_text(
            f"已更新关键词规则，共 {len(normalized_keywords)} 条。"
            if normalized_keywords
            else "已清空关键词规则。"
        )
        await _admin_handler_instance()._show_garage_forward_prompt(update, context, target_chat_id)
        return

    if state.state_type == "garage_forward_buttons_input":
        from backend.features.automation.scheduled_message_handler import _parse_buttons_text

        raw_value = (message_text or "").strip()
        if raw_value.lower().startswith("/clear"):
            await GarageForwardService.update_setting(
                session,
                target_chat_id,
                button_template=[],
                button_template_enabled=False,
            )
            await clear_user_state(session, chat_id=target_chat_id, user_id=update.effective_user.id)
            await clear_user_state(session, chat_id=update.effective_user.id, user_id=update.effective_user.id)
            await session.commit()
            await update.effective_message.reply_text("已清空按钮模板并关闭自动按钮。")
            await _admin_handler_instance()._show_garage_forward_prompt(update, context, target_chat_id)
            return

        try:
            buttons = _parse_buttons_text(raw_value)
        except ValidationError as exc:
            await update.effective_message.reply_text(str(exc))
            return

        await GarageForwardService.update_setting(
            session,
            target_chat_id,
            button_template=buttons,
            button_template_enabled=bool(buttons),
        )
        await clear_user_state(session, chat_id=target_chat_id, user_id=update.effective_user.id)
        await clear_user_state(session, chat_id=update.effective_user.id, user_id=update.effective_user.id)
        await session.commit()
        await update.effective_message.reply_text("已更新按钮模板，并自动启用。")
        await _admin_handler_instance()._show_garage_forward_prompt(update, context, target_chat_id)
        return

    raw_value = message_text.strip()
    if not raw_value:
        await update.effective_message.reply_text("来源频道不能为空。")
        return

    source_channel_id: int | None = None
    source_name: str | None = None
    remote_chat = None
    if raw_value.lstrip("-").isdigit():
        source_channel_id = int(raw_value)
        try:
            remote_chat = await context.bot.get_chat(source_channel_id)
        except Exception:
            remote_chat = None
    else:
        try:
            remote_chat = await context.bot.get_chat(raw_value)
        except Exception:
            remote_chat = None
        if remote_chat is not None:
            source_channel_id = int(remote_chat.id)
            source_name = getattr(remote_chat, "title", None) or getattr(remote_chat, "username", None)

    if source_channel_id is None:
        await update.effective_message.reply_text("无法识别该频道，请输入频道 ID、用户名或可解析链接。")
        return
    if remote_chat is None or getattr(remote_chat, "type", None) != "channel":
        await update.effective_message.reply_text("来源必须是频道，群组或私聊不能作为车库转发来源。")
        return

    source_name = source_name or getattr(remote_chat, "title", None) or getattr(remote_chat, "username", None)

    await GarageForwardService.add_source(
        session,
        chat_id=target_chat_id,
        source_channel_id=source_channel_id,
        source_name=source_name,
    )
    await clear_user_state(session, chat_id=target_chat_id, user_id=update.effective_user.id)
    await clear_user_state(session, chat_id=update.effective_user.id, user_id=update.effective_user.id)
    await session.commit()
    await update.effective_message.reply_text("已添加来源频道。")
    await _admin_handler_instance()._show_garage_forward_prompt(update, context, target_chat_id)


async def handle_garage_features_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state,
    message_text: str,
) -> None:
    from backend.features.garage.services.garage_features_service import (
        CarReviewService,
        GarageAuthService,
        TeacherSearchService,
    )
    from backend.platform.state.state_service import clear_user_state, set_user_state

    if update.effective_user is None or update.effective_message is None:
        return

    target_chat_id = state.state_data.get("target_chat_id", state.chat_id)
    admin_module = _admin_module()
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

    async def _clear_state() -> None:
        await clear_user_state(session, chat_id=target_chat_id, user_id=update.effective_user.id)
        await clear_user_state(session, chat_id=update.effective_user.id, user_id=update.effective_user.id)

    state_type = state.state_type
    text_value = message_text.strip()

    if state_type == "garage_badge_input":
        if not text_value:
            await update.effective_message.reply_text("认证图标不能为空。")
            return
        await GarageAuthService.update_settings(session, target_chat_id, garage_auth_badge=text_value[:16])
        await _clear_state()
        await session.commit()
        await _admin_handler_instance()._show_garage_auth_menu(update, context, target_chat_id)
        return

    if state_type == "garage_teacher_input":
        try:
            await GarageAuthService.add_teacher(session, target_chat_id, update.effective_user.id, text_value)
        except ValidationError as exc:
            await update.effective_message.reply_text(str(exc))
            return
        await _clear_state()
        await session.commit()
        await _admin_handler_instance()._show_garage_teacher_list_menu(update, context, target_chat_id, 0)
        return

    if state_type == "garage_whitelist_input":
        try:
            await GarageAuthService.add_whitelist(session, target_chat_id, update.effective_user.id, text_value)
        except ValidationError as exc:
            await update.effective_message.reply_text(str(exc))
            return
        await _clear_state()
        await session.commit()
        await _admin_handler_instance()._show_garage_whitelist_menu(update, context, target_chat_id, 0)
        return

    if state_type in {"garage_limit_interval_input", "garage_limit_max_count_input", "car_review_reward_points_input"}:
        if not re.fullmatch(r"\d+", text_value):
            await update.effective_message.reply_text("请输入正整数。")
            return
        number = int(text_value)
        if state_type == "garage_limit_interval_input":
            await GarageAuthService.update_settings(session, target_chat_id, garage_limit_interval_sec=number)
            await _clear_state()
            await session.commit()
            await _admin_handler_instance()._show_garage_auth_menu(update, context, target_chat_id)
            return
        if state_type == "garage_limit_max_count_input":
            await GarageAuthService.update_settings(session, target_chat_id, garage_limit_max_count=number)
            await _clear_state()
            await session.commit()
            await _admin_handler_instance()._show_garage_auth_menu(update, context, target_chat_id)
            return
        await CarReviewService.update_setting(session, target_chat_id, reward_points=number)
        await _clear_state()
        await session.commit()
        await _admin_handler_instance()._show_car_review_menu(update, context, target_chat_id)
        return

    if state_type == "teacher_search_delegate_target_input":
        try:
            user = await TeacherSearchService.resolve_delegate_user(session, text_value)
        except ValidationError as exc:
            await update.effective_message.reply_text(str(exc))
            return
        await clear_user_state(session, chat_id=target_chat_id, user_id=update.effective_user.id)
        await clear_user_state(session, chat_id=update.effective_user.id, user_id=update.effective_user.id)
        await set_user_state(
            session,
            chat_id=target_chat_id,
            user_id=update.effective_user.id,
            state_type="teacher_search_delegate_location_input",
            state_data={"target_chat_id": target_chat_id, "delegate_user_id": user.id},
        )
        await session.commit()
        await update.effective_message.reply_text("👉 请输入经纬度，格式：纬度,经度")
        return

    if state_type == "teacher_search_delegate_location_input":
        parts = [item for item in re.split(r"[\s,，]+", text_value) if item]
        if len(parts) != 2:
            await update.effective_message.reply_text("格式错误，请输入：纬度,经度")
            return
        try:
            latitude = float(parts[0])
            longitude = float(parts[1])
        except ValueError:
            await update.effective_message.reply_text("经纬度格式错误，请重新输入。")
            return
        delegate_user_id = state.state_data.get("delegate_user_id")
        if not isinstance(delegate_user_id, int):
            await _clear_state()
            await session.commit()
            await update.effective_message.reply_text("代录状态异常，请重新进入。")
            return
        await TeacherSearchService.upsert_member_location(
            session,
            chat_id=target_chat_id,
            user_id=delegate_user_id,
            latitude=latitude,
            longitude=longitude,
            operator_user_id=update.effective_user.id,
        )
        await TeacherSearchService.upsert_teacher_profile_from_location(
            session,
            chat_id=target_chat_id,
            user_id=delegate_user_id,
            latitude=latitude,
            longitude=longitude,
        )
        await _clear_state()
        await session.commit()
        await _admin_handler_instance()._show_teacher_search_menu(update, context, target_chat_id)
        return

    if state_type == "car_review_submit_command_input":
        if not text_value:
            await update.effective_message.reply_text("指令不能为空。")
            return
        await CarReviewService.update_setting(session, target_chat_id, submit_command=text_value[:64])
        await _clear_state()
        await session.commit()
        await _admin_handler_instance()._show_car_review_menu(update, context, target_chat_id)
        return

    if state_type == "car_review_rank_command_input":
        if not text_value:
            await update.effective_message.reply_text("指令不能为空。")
            return
        await CarReviewService.update_setting(session, target_chat_id, rank_command=text_value[:64])
        await _clear_state()
        await session.commit()
        await _admin_handler_instance()._show_car_review_menu(update, context, target_chat_id)
        return

    if state_type == "car_review_approver_input":
        approver_id = None
        if text_value != "清空":
            try:
                user = await CarReviewService.resolve_approver(session, text_value)
            except ValidationError as exc:
                await update.effective_message.reply_text(str(exc))
                return
            approver_id = user.id
        await CarReviewService.update_setting(session, target_chat_id, approver_user_id=approver_id)
        await _clear_state()
        await session.commit()
        await _admin_handler_instance()._show_car_review_menu(update, context, target_chat_id)
        return

    if state_type == "car_review_template_input":
        if not text_value:
            await update.effective_message.reply_text("模板不能为空。")
            return
        await CarReviewService.update_setting(session, target_chat_id, template_text=message_text)
        await _clear_state()
        await session.commit()
        await _admin_handler_instance()._show_car_review_menu(update, context, target_chat_id)
        return

    await update.effective_message.reply_text("配置状态异常，请重新进入页面。")
