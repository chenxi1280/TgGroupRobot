from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_env_file() -> Path | None:
    """查找 env 文件，优先级：项目根目录的 .env > 项目根目录的 env"""
    # backend/platform/config/core/settings.py -> 项目根目录
    config_dir = Path(__file__).parent
    project_root = config_dir.parents[3]
    
    # 按优先级查找
    for filename in [".env", "env"]:
        env_path = project_root / filename
        if env_path.exists():
            return env_path
    
    return None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",  # 默认值，会在 get_settings() 中动态覆盖
        env_file_encoding="utf-8",
        extra="ignore"
    )

    app_env: str = Field(default="dev", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_format: str = Field(default="console", alias="LOG_FORMAT")

    bot_token: str = Field(alias="BOT_TOKEN")
    database_url: str = Field(
        default="postgresql+psycopg://tg_bot:tg_bot@db:5432/tg_bot",
        alias="DATABASE_URL",
    )
    database_connect_timeout_seconds: int = Field(default=10, alias="DATABASE_CONNECT_TIMEOUT_SECONDS")
    startup_schema_migrations_enabled: bool = Field(default=True, alias="STARTUP_SCHEMA_MIGRATIONS_ENABLED")

    # 代理设置（用于连接 Telegram API）
    proxy_url: str | None = Field(default=None, alias="PROXY_URL")

    # Telegram Bot API 请求池配置
    telegram_connection_pool_size: int = Field(default=32, alias="TELEGRAM_CONNECTION_POOL_SIZE")
    telegram_pool_timeout_seconds: float = Field(default=15.0, alias="TELEGRAM_POOL_TIMEOUT_SECONDS")
    telegram_connect_timeout_seconds: float = Field(default=10.0, alias="TELEGRAM_CONNECT_TIMEOUT_SECONDS")
    telegram_read_timeout_seconds: float = Field(default=20.0, alias="TELEGRAM_READ_TIMEOUT_SECONDS")
    telegram_write_timeout_seconds: float = Field(default=20.0, alias="TELEGRAM_WRITE_TIMEOUT_SECONDS")

    # 启动期调度器控制：默认不在启动瞬间立刻跑所有后台任务，避免抢占 bot 初始化。
    scheduler_run_immediately: bool = Field(default=False, alias="SCHEDULER_RUN_IMMEDIATELY")
    scheduler_initial_stagger_seconds: float = Field(default=0.25, alias="SCHEDULER_INITIAL_STAGGER_SECONDS")

    # 预留：未来 webhook 模式
    webhook_url: str | None = Field(default=None, alias="WEBHOOK_URL")

    # 群聊中 /start 和 /cancel 指令回复消息的自动删除时间（秒）
    group_guide_message_delete_seconds: int = Field(default=30, alias="GROUP_GUIDE_MESSAGE_DELETE_SECONDS")

    # Bot 全局管理员（用于风控豁免等逻辑），逗号分隔 user_id，如：123,456
    bot_admin_ids: str = Field(default="", alias="BOT_ADMIN_IDS")

    # 续费入口：联系购买账号（可选，不带 @）
    renew_contact_username: str | None = Field(default=None, alias="RENEW_CONTACT_USERNAME")
    renew_contact_label: str = Field(default="一键联系", alias="RENEW_CONTACT_LABEL")

    # 续费入口：人工联系链接与展示文案
    renewal_contact_url: str | None = Field(default=None, alias="RENEWAL_CONTACT_URL")
    renewal_contact_label: str = Field(default="一键联系", alias="RENEWAL_CONTACT_LABEL")

    # 内置后台管理
    admin_web_enabled: bool = Field(default=True, alias="ADMIN_WEB_ENABLED")
    admin_web_host: str = Field(default="127.0.0.1", alias="ADMIN_WEB_HOST")
    admin_web_port: int = Field(default=8088, alias="ADMIN_WEB_PORT")
    admin_session_days: int = Field(default=7, alias="ADMIN_SESSION_DAYS")
    admin_bootstrap_username: str | None = Field(default=None, alias="ADMIN_BOOTSTRAP_USERNAME")
    admin_bootstrap_password: str | None = Field(default=None, alias="ADMIN_BOOTSTRAP_PASSWORD")
    admin_bootstrap_display_name: str = Field(default="超级管理员", alias="ADMIN_BOOTSTRAP_DISPLAY_NAME")


def get_settings() -> Settings:
    # 查找 env 文件
    env_file = _find_env_file()
    
    # 如果找到 env 文件，使用 load_dotenv 加载它到环境变量
    if env_file:
        # 加载 env 文件到环境变量，这样 Settings 就可以从环境变量读取
        load_dotenv(env_file, override=True)
    
    # 尝试创建 Settings 实例（会从环境变量读取）
    try:
        return Settings()
    except ValidationError as e:
        # 检查是否缺少 BOT_TOKEN
        for error in e.errors():
            error_loc = error.get("loc", ())
            error_type = error.get("type", "")
            
            # 兼容不同的 loc 格式（元组或列表）
            loc_tuple = tuple(error_loc) if error_loc else ()
            
            if loc_tuple == ("bot_token",) and error_type == "missing":
                config_dir = Path(__file__).parent
                project_root = config_dir.parent.parent.parent
                env_file = _find_env_file()
                example_file = project_root / "config" / "env.example"
                
                error_msg = "\n" + "=" * 60 + "\n"
                error_msg += "配置错误：缺少必需的 BOT_TOKEN\n"
                error_msg += "=" * 60 + "\n\n"
                
                if env_file is None:
                    error_msg += f"未找到环境配置文件（.env 或 env）。\n"
                    error_msg += f"请参考示例文件创建：{example_file}\n\n"
                    error_msg += "创建步骤：\n"
                    error_msg += "1. 复制示例文件：cp config/env.example .env\n"
                    error_msg += "   或者：cp config/env.example env\n"
                    error_msg += "2. 编辑文件，设置你的 BOT_TOKEN\n"
                    error_msg += "   例如：BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz\n\n"
                else:
                    error_msg += f"环境配置文件存在：{env_file}\n"
                    error_msg += f"但缺少 BOT_TOKEN 配置。\n"
                    error_msg += f"请在文件中添加：BOT_TOKEN=你的机器人令牌\n\n"
                
                error_msg += "如何获取 BOT_TOKEN：\n"
                error_msg += "1. 在 Telegram 中搜索 @BotFather\n"
                error_msg += "2. 发送 /newbot 命令创建新机器人\n"
                error_msg += "3. 按照提示完成创建后，BotFather 会提供 BOT_TOKEN\n"
                error_msg += "=" * 60 + "\n"
                
                raise ValueError(error_msg) from e
        
        # 其他错误直接抛出
        raise
