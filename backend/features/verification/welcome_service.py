from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, User
from telegram.ext import ContextTypes

from backend.platform.db.schema.models.core import TgChat, TgUser
from backend.platform.db.schema.models.enums import WelcomeDeleteMode, WelcomeMode
from backend.platform.db.schema.models.welcome import WelcomeMessage
from backend.shared.services.base import NotFoundError, ValidationError
from backend.features.automation.services.scheduled_message_service import ScheduledMessageService
from backend.features.verification.welcome_delivery import (
    apply_welcome_delete_strategy,
    delete_welcome_later,
    send_rendered_payload,
)
from backend.features.verification.welcome_templates import render_welcome_template
_NORMALIZE_BUTTONS_THRESHOLD_3 = 3



@dataclass(slots=True)
class WelcomePayload:
    text: str
    reply_markup: InlineKeyboardMarkup | None
    parse_mode: str | None
    media_type: str | None
    media_file_id: str | None


class WelcomeService:
    DEFAULT_TEXT = "{member}，欢迎加入{group}。"

    @staticmethod
    async def list_messages(session: AsyncSession, chat_id: int) -> list[WelcomeMessage]:
        result = await session.execute(
            select(WelcomeMessage)
            .where(WelcomeMessage.chat_id == chat_id)
            .order_by(WelcomeMessage.id.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_message(session: AsyncSession, chat_id: int, welcome_id: int) -> WelcomeMessage:
        result = await session.execute(
            select(WelcomeMessage).where(
                WelcomeMessage.chat_id == chat_id,
                WelcomeMessage.id == welcome_id,
            )
        )
        welcome = result.scalar_one_or_none()
        if welcome is None:
            raise NotFoundError("欢迎配置不存在")
        return welcome

    @staticmethod
    async def create_message(session: AsyncSession, chat_id: int) -> WelcomeMessage:
        welcome = WelcomeMessage(
            chat_id=chat_id,
            title="待配置",
            enabled=False,
            welcome_mode=WelcomeMode.after_verify.value,
            text_content=WelcomeService.DEFAULT_TEXT,
            buttons=[],
            delete_mode=WelcomeDeleteMode.seconds.value,
            delete_delay_seconds=15,
        )
        session.add(welcome)
        await session.flush()
        return welcome

    @staticmethod
    async def delete_message(session: AsyncSession, chat_id: int, welcome_id: int) -> None:
        welcome = await WelcomeService.get_message(session, chat_id, welcome_id)
        await session.delete(welcome)
        await session.flush()

    @staticmethod
    def normalize_buttons(buttons: list) -> list[list[dict[str, str]]]:
        normalized = ScheduledMessageService.normalize_buttons_config(buttons)
        for row in normalized:
            if len(row) > _NORMALIZE_BUTTONS_THRESHOLD_3:
                raise ValidationError("每行最多 3 个按钮")
        return normalized

    @staticmethod
    def build_markup(buttons: list | None) -> InlineKeyboardMarkup | None:
        if not buttons:
            return None
        rows = WelcomeService.normalize_buttons(buttons)
        keyboard = [
            [InlineKeyboardButton(btn["text"], url=btn["url"]) for btn in row]
            for row in rows
        ]
        return InlineKeyboardMarkup(keyboard) if keyboard else None

    @staticmethod
    async def update_field(
        session: AsyncSession,
        chat_id: int,
        welcome_id: int,
        *,
        title: str | None = None,
        enabled: bool | None = None,
        welcome_mode: str | None = None,
        cover_media_type: str | None | object = ...,
        cover_media_file_id: str | None | object = ...,
        text_content: str | None = None,
        buttons: list | None = None,
        delete_mode: str | None = None,
        delete_delay_seconds: int | None | object = ...,
        last_sent_message_id: int | None | object = ...,
    ) -> WelcomeMessage:
        welcome = await WelcomeService.get_message(session, chat_id, welcome_id)
        WelcomeService._apply_core_fields(
            welcome,
            title=title,
            enabled=enabled,
            welcome_mode=welcome_mode,
            text_content=text_content,
            buttons=buttons,
        )
        WelcomeService._apply_delivery_fields(
            welcome,
            cover_media_type=cover_media_type,
            cover_media_file_id=cover_media_file_id,
            delete_mode=delete_mode,
            delete_delay_seconds=delete_delay_seconds,
            last_sent_message_id=last_sent_message_id,
        )
        await session.flush()
        return welcome

    @staticmethod
    def _apply_core_fields(
        welcome: WelcomeMessage,
        *,
        title: str | None,
        enabled: bool | None,
        welcome_mode: str | None,
        text_content: str | None,
        buttons: list | None,
    ) -> None:
        if title is not None:
            welcome.title = title.strip() or "待配置"
        if enabled is not None:
            welcome.enabled = enabled
        if welcome_mode is not None:
            if welcome_mode not in {item.value for item in WelcomeMode}:
                raise ValidationError("欢迎模式无效")
            welcome.welcome_mode = welcome_mode
        if text_content is not None:
            welcome.text_content = text_content.strip() or WelcomeService.DEFAULT_TEXT
        if buttons is not None:
            welcome.buttons = WelcomeService.normalize_buttons(buttons)

    @staticmethod
    def _apply_delivery_fields(
        welcome: WelcomeMessage,
        *,
        cover_media_type: str | None | object,
        cover_media_file_id: str | None | object,
        delete_mode: str | None,
        delete_delay_seconds: int | None | object,
        last_sent_message_id: int | None | object,
    ) -> None:
        if cover_media_type is not ...:
            welcome.cover_media_type = cover_media_type
        if cover_media_file_id is not ...:
            welcome.cover_media_file_id = cover_media_file_id
        if delete_mode is not None:
            if delete_mode not in {item.value for item in WelcomeDeleteMode}:
                raise ValidationError("删除模式无效")
            welcome.delete_mode = delete_mode
        if delete_delay_seconds is not ...:
            welcome.delete_delay_seconds = delete_delay_seconds
        if last_sent_message_id is not ...:
            welcome.last_sent_message_id = last_sent_message_id

    @staticmethod
    def _render_template(template: str, *, member: User | TgUser | None, group_name: str, user_id: int) -> str:
        return render_welcome_template(
            template,
            default_text=WelcomeService.DEFAULT_TEXT,
            member=member,
            group_name=group_name,
            user_id=user_id,
        )

    @staticmethod
    async def build_payload(
        session: AsyncSession,
        chat_id: int,
        welcome_id: int,
        *,
        member: User | TgUser | None,
        user_id: int,
    ) -> WelcomePayload:
        welcome = await WelcomeService.get_message(session, chat_id, welcome_id)
        chat = await session.get(TgChat, chat_id)
        text = WelcomeService._render_template(
            welcome.text_content,
            member=member,
            group_name=chat.title if chat else "本群",
            user_id=user_id,
        )
        return WelcomePayload(
            text=text,
            reply_markup=WelcomeService.build_markup(welcome.buttons),
            parse_mode="HTML",
            media_type=welcome.cover_media_type,
            media_file_id=welcome.cover_media_file_id,
        )

    @staticmethod
    async def preview(
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        *,
        preview_chat_id: int,
        chat_id: int,
        welcome_id: int,
        member: User | TgUser | None,
        user_id: int,
    ) -> None:
        payload = await WelcomeService.build_payload(
            session,
            chat_id,
            welcome_id,
            member=member,
            user_id=user_id,
        )
        preview_text = f"{payload.text}\n\n(本消息为预览)"
        await WelcomeService._send_rendered_payload(
            context,
            preview_chat_id,
            payload=WelcomePayload(
                text=preview_text,
                reply_markup=payload.reply_markup,
                parse_mode=payload.parse_mode,
                media_type=payload.media_type,
                media_file_id=payload.media_file_id,
            ),
        )

    @staticmethod
    async def send_for_mode(
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        *,
        chat_id: int,
        mode: str,
        members: list[User] | None = None,
        user_ids: list[int] | None = None,
    ) -> bool:
        result = await session.execute(
            select(WelcomeMessage)
            .where(
                WelcomeMessage.chat_id == chat_id,
                WelcomeMessage.enabled.is_(True),
                WelcomeMessage.welcome_mode == mode,
            )
            .order_by(WelcomeMessage.id.asc())
        )
        welcomes = list(result.scalars().all())
        if not welcomes:
            return False

        member_map = {member.id: member for member in (members or [])}
        resolved_ids = user_ids or list(member_map.keys())
        if not resolved_ids:
            return False

        chat = await session.get(TgChat, chat_id)
        group_name = chat.title if chat else "本群"
        sent_any = False
        for welcome in welcomes:
            sent = await WelcomeService._send_to_members(
                context,
                session,
                chat_id=chat_id,
                welcome=welcome,
                member_map=member_map,
                member_ids=resolved_ids,
                group_name=group_name,
            )
            sent_any = sent_any or sent
        return sent_any

    @staticmethod
    async def _send_to_members(
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        *,
        chat_id: int,
        welcome: WelcomeMessage,
        member_map: dict[int, User],
        member_ids: list[int],
        group_name: str,
    ) -> bool:
        sent_any = False
        for member_id in member_ids:
            member = member_map.get(member_id) or await session.get(TgUser, member_id)
            sent = await WelcomeService._send_mode_message(
                context,
                session,
                chat_id=chat_id,
                welcome=welcome,
                member=member,
                member_id=member_id,
                group_name=group_name,
            )
            sent_any = sent_any or sent
        return sent_any

    @staticmethod
    async def _send_mode_message(
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        *,
        chat_id: int,
        welcome: WelcomeMessage,
        member: TgUser | User | None,
        member_id: int,
        group_name: str,
    ) -> bool:
        payload = WelcomePayload(
            text=WelcomeService._render_template(
                welcome.text_content,
                member=member,
                group_name=group_name,
                user_id=member_id,
            ),
            reply_markup=WelcomeService.build_markup(welcome.buttons),
            parse_mode="HTML",
            media_type=welcome.cover_media_type,
            media_file_id=welcome.cover_media_file_id,
        )
        message = await WelcomeService._send_rendered_payload(context, chat_id, payload=payload)
        if message is None:
            return False
        await WelcomeService._apply_delete_strategy(
            session,
            welcome,
            message.message_id,
            context=context,
            chat_id=chat_id,
        )
        return True

    @staticmethod
    async def _send_rendered_payload(
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *,
        payload: WelcomePayload,
    ):
        return await send_rendered_payload(context, chat_id, payload=payload)

    @staticmethod
    async def _apply_delete_strategy(
        session: AsyncSession,
        welcome: WelcomeMessage,
        message_id: int,
        *, context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        await apply_welcome_delete_strategy(session, welcome, message_id, context=context, chat_id=chat_id)

    @staticmethod
    async def _delete_later(
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        message_id: int,
        *, delay: int,
    ) -> None:
        await delete_welcome_later(context, chat_id, message_id, delay=delay)
