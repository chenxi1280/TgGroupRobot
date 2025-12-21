from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = Field(default="dev", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    bot_token: str = Field(alias="BOT_TOKEN")
    database_url: str = Field(
        default="postgresql+psycopg://tg_bot:tg_bot@localhost:5432/tg_bot",
        alias="DATABASE_URL",
    )

    # 预留：未来 webhook 模式
    webhook_url: str | None = Field(default=None, alias="WEBHOOK_URL")


def get_settings() -> Settings:
    return Settings()



