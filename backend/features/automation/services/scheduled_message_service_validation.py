from __future__ import annotations

import datetime as dt
from urllib.parse import urlparse

from backend.shared.services.base import ValidationError
from backend.shared.time_helper import parse_date_time_string
_VALIDATE_DAY_PERIOD_THRESHOLD_23 = 23


def _expand_button_url(url: str) -> str:
    if url.startswith("@"):
        return f"https://t.me/{url[1:]}"
    if url.startswith("t.me/") or url.startswith("www."):
        return f"https://{url}"
    if "://" not in url and not url.startswith("tg://"):
        return f"https://{url}"
    return url


def _validate_web_button_url(parsed) -> None:
    if not parsed.netloc:
        raise ValidationError("按钮 URL 格式无效")
    if not parsed.hostname:
        raise ValidationError("按钮 URL 主机名无效")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValidationError("按钮 URL 端口格式无效") from exc


def _button_rows(buttons: list) -> list:
    if all(isinstance(item, dict) for item in buttons):
        return [buttons]
    if all(isinstance(item, list) for item in buttons):
        return buttons
    raise ValidationError("按钮格式必须是 [{text,url}] 或 [[{text,url}]]")


class ScheduledMessageValidationMixin:
    """定时消息服务的输入校验与格式标准化。"""

    _NULLABLE_UPDATE_FIELDS = {
        "text",
        "start_at",
        "end_at",
        "media_file_id",
        "created_by_user_id",
        "last_sent_message_id",
        "next_run_at",
    }
    _VALID_REPEAT_INTERVALS = [10, 15, 20, 30, 60, 120, 180, 240, 360, 480, 720, 1440]
    _VALID_MEDIA_TYPES = ["none", "photo", "video", "sticker", "animation", "document"]
    _VALID_TOGGLE_OPTIONS = ["enabled", "delete_previous", "pin_message"]

    @staticmethod
    def has_sendable_payload(
        *,
        text: str | None,
        media_type: str | None,
        media_file_id: str | None,
    ) -> bool:
        has_text = bool(str(text or "").strip())
        has_media = bool(media_type and media_type != "none" and media_file_id)
        return has_text or has_media

    @classmethod
    def has_sendable_content(cls, task) -> bool:
        return cls.has_sendable_payload(
            text=getattr(task, "text", None),
            media_type=getattr(task, "media_type", "none"),
            media_file_id=getattr(task, "media_file_id", None),
        )

    @staticmethod
    def _normalize_button_url(url: str) -> str:
        """规范化按钮 URL，支持常见简写。"""
        normalized = url.strip()
        if not normalized:
            raise ValidationError("按钮 URL 不能为空")

        lowered = normalized.lower()
        blocked_schemes = ("javascript:", "data:", "file:", "vbscript:")
        if lowered.startswith(blocked_schemes):
            raise ValidationError("按钮 URL 协议不安全")

        normalized = _expand_button_url(normalized)
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https", "tg"}:
            raise ValidationError("按钮 URL 协议仅支持 http/https/tg")
        if parsed.scheme in {"http", "https"}:
            _validate_web_button_url(parsed)
        if parsed.scheme == "tg" and not (parsed.netloc or parsed.path):
            raise ValidationError("按钮 tg:// 链接格式无效")

        return normalized

    @classmethod
    def normalize_buttons_config(cls, buttons: list) -> list[list[dict[str, str]]]:
        """规范化按钮配置，兼容单层和双层数组。"""
        if not isinstance(buttons, list):
            raise ValidationError("按钮配置必须是 JSON 数组")

        if not buttons:
            return []

        rows = _button_rows(buttons)
        normalized_rows: list[list[dict[str, str]]] = []
        for row_index, row in enumerate(rows, start=1):
            normalized_row = cls._normalize_button_row(row, row_index=row_index)
            if normalized_row:
                normalized_rows.append(normalized_row)
        return normalized_rows

    @classmethod
    def _normalize_button_row(cls, row, *, row_index: int) -> list[dict[str, str]]:
        if not isinstance(row, list):
            raise ValidationError(f"第 {row_index} 行按钮格式错误")
        normalized: list[dict[str, str]] = []
        for col_index, button in enumerate(row, start=1):
            if not isinstance(button, dict):
                raise ValidationError(f"第 {row_index} 行第 {col_index} 个按钮必须是对象")
            text = str(button.get("text", "")).strip()
            url = str(button.get("url", button.get("link", ""))).strip()
            if not text:
                raise ValidationError(f"第 {row_index} 行第 {col_index} 个按钮 text 不能为空")
            if not url:
                raise ValidationError(f"第 {row_index} 行第 {col_index} 个按钮 url 不能为空")
            normalized.append({"text": text, "url": cls._normalize_button_url(url)})
        return normalized

    @classmethod
    def validate_repeat_interval(cls, repeat_interval_min: int) -> None:
        if repeat_interval_min not in cls._VALID_REPEAT_INTERVALS:
            raise ValidationError(
                f"无效的重复间隔，必须是以下值之一: {cls._VALID_REPEAT_INTERVALS}"
            )

    @staticmethod
    def validate_day_period(day_start_hour: int, day_end_hour: int) -> None:
        if not (0 <= day_start_hour <= _VALIDATE_DAY_PERIOD_THRESHOLD_23 and 0 <= day_end_hour <= _VALIDATE_DAY_PERIOD_THRESHOLD_23):
            raise ValidationError("时段小时必须在 0-23 之间")

    @staticmethod
    def validate_time_range(start_at, end_at) -> None:
        if start_at is not None and end_at is not None and start_at >= end_at:
            raise ValidationError("开始时间必须早于终止时间")

    @staticmethod
    def validate_future_end_at(end_at) -> None:
        if end_at is not None and end_at <= int(dt.datetime.now(dt.UTC).timestamp()):
            raise ValidationError("终止时间必须晚于当前时间")

    @classmethod
    def validate_media_type(cls, media_type: str) -> None:
        if media_type not in cls._VALID_MEDIA_TYPES:
            raise ValidationError(f"无效的媒体类型，必须是: {cls._VALID_MEDIA_TYPES}")

    @classmethod
    def validate_toggle_option(cls, option: str) -> None:
        if option not in cls._VALID_TOGGLE_OPTIONS:
            raise ValidationError(f"无效的选项，必须是: {cls._VALID_TOGGLE_OPTIONS}")

    @staticmethod
    def parse_optional_datetime(date_time_str: str | None):
        if date_time_str is None:
            return None

        parsed = parse_date_time_string(date_time_str)
        if parsed is None:
            raise ValidationError("无效的日期时间格式，应为: YYYY-MM-DD HH:MM")
        return parsed
