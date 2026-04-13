from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


@dataclass(frozen=True)
class Database:
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]


def create_database(database_url: str) -> Database:
    # 如果数据在 bot schema 下，设置 search_path
    # 注意：DATABASE_URL 保持标准格式，schema 通过 connect_args 设置
    engine = create_async_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        connect_args={
            "options": "-csearch_path=bot"
        },
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    return Database(engine=engine, session_factory=session_factory)




