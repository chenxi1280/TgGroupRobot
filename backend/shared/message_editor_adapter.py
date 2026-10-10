"""Explicit field adapters for the existing message/button editor.

Only detached snapshots cross the editor boundary. Saves lock the target and
compare the complete editable snapshot before changing formal configuration.
"""
from __future__ import annotations

from dataclasses import dataclass
from sqlalchemy import select
from backend.platform.db.schema.models.core import AdCampaign, AutoReplyRule, ChatSettings
from backend.platform.db.schema.models.welcome import WelcomeMessage
from backend.shared.services.base import ValidationError


@dataclass(frozen=True)
class MessageEditorAdapter:
    model: type
    text_field: str
    media_field: str
    media_type_field: str | None
    button_field: str
    media_types: tuple[str, ...]

    async def load(self, session, editor_ctx):
        predicate = self.model.chat_id == editor_ctx.target_chat_id
        if self.model is not ChatSettings:
            predicate &= self.model.id == editor_ctx.entity_id
        item = (await session.execute(select(self.model).where(predicate).with_for_update()
                    .execution_options(populate_existing=True))).scalar_one_or_none()
        if item is None:
            raise ValidationError("编辑对象已删除，请返回列表。")
        return item

    def snapshot(self, item):
        media = getattr(item, self.media_field, None)
        return {"text": getattr(item, self.text_field, "") or "",
                "media": media,
                "media_type": getattr(item, self.media_type_field, None) if self.media_type_field else ("photo" if media else None)}

    def apply(self, item, snapshot):
        validate_message_snapshot(snapshot, self)
        setattr(item, self.text_field, snapshot["text"])
        setattr(item, self.media_field, snapshot["media"])
        if self.media_type_field:
            setattr(item, self.media_type_field, snapshot["media_type"])
        if self.model is AdCampaign:
            item.has_image = bool(snapshot["media"])


MESSAGE_EDITOR_ADAPTERS = {
    "ads": MessageEditorAdapter(AdCampaign, "content", "image_file_id", None, "buttons", ("photo",)),
    "auto_reply": MessageEditorAdapter(AutoReplyRule, "reply_content", "cover_media_file_id", "cover_media_type", "buttons", ("photo", "video")),
    "welcome": MessageEditorAdapter(WelcomeMessage, "text_content", "cover_media_file_id", "cover_media_type", "buttons", ("photo", "video")),
    "invite": MessageEditorAdapter(ChatSettings, "invite_link_text_template", "invite_link_cover_file_id", "invite_link_cover_media_type", "invite_link_buttons", ("photo", "video")),
}


def message_adapter(editor_ctx):
    try:
        return MESSAGE_EDITOR_ADAPTERS[editor_ctx.module_type]
    except KeyError as exc:
        raise ValidationError("此模块不支持消息编辑。") from exc


def validate_message_snapshot(snapshot, adapter):
    text = snapshot["text"]
    if not text.strip():
        raise ValidationError("正文不能为空。")
    maximum = 1024 if snapshot.get("media") else 4096
    if len(text.encode("utf-16-le")) // 2 > maximum:
        raise ValidationError(f"正文过长，当前消息最多支持 {maximum} 字符。")
    if snapshot.get("media") and snapshot.get("media_type") not in adapter.media_types:
        raise ValidationError("此功能不支持该媒体类型，请使用图片" + ("或视频。" if "video" in adapter.media_types else "。"))


async def apply_message_input(update, context, session, *, editor_ctx, state, message_text):
    from backend.shared.button_layout_persistence import ensure_message_draft
    field = (state.state_data or {}).get("message_field")
    record = await ensure_message_draft(session, context, editor_ctx)
    snapshot = dict(record.state_data["message"])
    _update_message_field(snapshot, update.effective_message, field=field, message_text=message_text)
    validate_message_snapshot(snapshot, message_adapter(editor_ctx))
    record.state_data = {**record.state_data, "message": snapshot}
    return


def _update_message_field(snapshot, message, *, field, message_text):
    from backend.shared.ui.button_input import is_clear_button_input
    if field == "body":
        snapshot["text"] = message_text
        return
    if is_clear_button_input(message_text.strip()):
        snapshot.update(media=None, media_type=None)
        return
    if message.photo:
        snapshot.update(media=message.photo[-1].file_id, media_type="photo")
        return
    if message.video:
        snapshot.update(media=message.video.file_id, media_type="video")
        return
    raise ValidationError("请发送本功能支持的图片/视频，或发送 清除 移除封面。")
