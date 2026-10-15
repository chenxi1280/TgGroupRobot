"""Separate open/closed member permissions using the existing module configuration."""
from __future__ import annotations

import json
from telegram import ChatPermissions

from backend.shared.services.module_config_service import get_module_config

PERMISSION_FIELDS = {
    "text": ("文本", "can_send_messages"), "photo": ("图片", "can_send_photos"),
    "video": ("视频", "can_send_videos"), "audio": ("音乐", "can_send_audios"),
    "voice": ("语音", "can_send_voice_notes"), "video_note": ("视频消息", "can_send_video_notes"),
    "file": ("文件", "can_send_documents"), "other": ("贴纸与 GIF", "can_send_other_messages"),
    "preview": ("链接预览", "can_add_web_page_previews"), "poll": ("投票", "can_send_polls"),
    "invite": ("邀请成员", "can_invite_users"), "info": ("修改群信息", "can_change_info"),
    "pin": ("置顶消息", "can_pin_messages"), "topic": ("管理话题", "can_manage_topics"),
    "react": ("消息表情回应", "can_react_to_messages"), "tag": ("修改自己的标签", "can_edit_tag"),
}


def profile_values(settings, *, closed: bool) -> dict | None:
    key = "closed" if closed else "open"
    value = get_module_config(settings, "group_lock").get("profiles", {}).get(key)
    return value if isinstance(value, dict) else None


def profile_permissions(settings, *, closed: bool):
    values = profile_values(settings, closed=closed)
    if values is None:
        return ChatPermissions(can_send_messages=not closed)
    return ChatPermissions.de_json(effective_permissions(values), bot=None)


def effective_permissions(values: dict) -> dict[str, bool]:
    result = {field: bool(values.get(field, False)) for _, field in PERMISSION_FIELDS.values()}
    # New Bot API defaults also apply to existing profiles that lack these keys.
    result['can_react_to_messages'] = bool(values.get('can_react_to_messages', result['can_send_messages']))
    result['can_edit_tag'] = bool(values.get('can_edit_tag', result['can_pin_messages']))
    return result


def profile_fingerprint(settings):
    config = get_module_config(settings, "group_lock").get("profiles")
    return json.dumps(config, sort_keys=True) if config else None
