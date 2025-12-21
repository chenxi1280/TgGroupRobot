from __future__ import annotations

from pathlib import Path

from pydantic import Field, ValidationError
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
    try:
        return Settings()
    except ValidationError as e:
        # 检查是否缺少 BOT_TOKEN
        for error in e.errors():
            if error.get("loc") == ("bot_token",) and error.get("type") == "missing":
                env_file = Path(".env")
                example_file = Path("config/env.example")
                
                error_msg = "\n" + "=" * 60 + "\n"
                error_msg += "配置错误：缺少必需的 BOT_TOKEN\n"
                error_msg += "=" * 60 + "\n\n"
                
                if not env_file.exists():
                    error_msg += f"未找到 .env 文件。\n"
                    error_msg += f"请参考示例文件创建：{example_file}\n\n"
                    error_msg += "创建步骤：\n"
                    error_msg += "1. 复制示例文件：cp config/env.example .env\n"
                    error_msg += "2. 编辑 .env 文件，设置你的 BOT_TOKEN\n"
                    error_msg += "   例如：BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz\n\n"
                else:
                    error_msg += f".env 文件存在，但缺少 BOT_TOKEN 配置。\n"
                    error_msg += f"请在 .env 文件中添加：BOT_TOKEN=你的机器人令牌\n\n"
                
                error_msg += "如何获取 BOT_TOKEN：\n"
                error_msg += "1. 在 Telegram 中搜索 @BotFather\n"
                error_msg += "2. 发送 /newbot 命令创建新机器人\n"
                error_msg += "3. 按照提示完成创建后，BotFather 会提供 BOT_TOKEN\n"
                error_msg += "=" * 60 + "\n"
                
                raise ValueError(error_msg) from e
        
        # 其他错误直接抛出
        raise



