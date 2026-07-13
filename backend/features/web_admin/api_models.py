"""Web 管理端请求模型。"""
from __future__ import annotations

from pydantic import BaseModel, Field

from backend.features.web_admin.card_service import COPY_CARD_LIMIT


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class GenerateBatchRequest(BaseModel):
    spec_days: int
    quantity: int = Field(..., ge=1, le=500)


class CopyCardsRequest(BaseModel):
    card_ids: list[int] = Field(..., min_length=1, max_length=COPY_CARD_LIMIT)
    with_meta: bool = False


class VoidCardsRequest(BaseModel):
    card_ids: list[int] = Field(..., min_length=1, max_length=500)


class AnnouncementRequest(BaseModel):
    enabled: bool = True
    entry_text: str = Field(default="", max_length=500)
    target_url: str = Field(default="", max_length=500)
    message_text: str = Field(default="", max_length=2000)


class PlatformConfigRequest(BaseModel):
    platform_name: str = Field(default="", max_length=80)
    bot_display_name: str = Field(default="", max_length=80)
    web_admin_title: str = Field(default="", max_length=80)
    maintenance_notice: str = Field(default="", max_length=500)
    contact_text: str = Field(default="", max_length=200)
    help_text: str = Field(default="", max_length=1000)


class AdminAccountRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=6, max_length=128)
    display_name: str = Field(default="", max_length=64)


class AdminPasswordRequest(BaseModel):
    password: str = Field(..., min_length=6, max_length=128)


class CurrentPasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=6, max_length=128)
