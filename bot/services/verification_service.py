from __future__ import annotations

import datetime as dt
import random
import secrets
import string

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.core import VerificationChallenge
from bot.models.enums import VerificationMode


def new_token() -> str:
    return secrets.token_urlsafe(24)


def generate_captcha(length: int = 4) -> tuple[str, str]:
    """生成验证码 (code, image_text)"""
    # 生成数字验证码
    code = "".join(random.choices(string.digits, k=length))
    return code, code


def generate_math_question() -> tuple[str, str]:
    """生成数学题 (question, answer)"""
    ops = ["+", "-", "*"]
    op = random.choice(ops)

    if op == "+":
        a = random.randint(1, 50)
        b = random.randint(1, 50)
        question = f"{a} + {b} = ?"
        answer = str(a + b)
    elif op == "-":
        a = random.randint(10, 50)
        b = random.randint(1, a)
        question = f"{a} - {b} = ?"
        answer = str(a - b)
    else:  # *
        a = random.randint(2, 10)
        b = random.randint(2, 10)
        question = f"{a} × {b} = ?"
        answer = str(a * b)

    return question, answer


async def create_or_replace_challenge(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    ttl_seconds: int,
    verification_type: str = VerificationMode.button.value,
) -> VerificationChallenge:
    """创建或替换验证挑战"""
    res = await session.execute(
        select(VerificationChallenge).where(
            and_(
                VerificationChallenge.chat_id == chat_id,
                VerificationChallenge.user_id == user_id,
            )
        )
    )
    existing = res.scalar_one_or_none()
    if existing is not None:
        await session.delete(existing)
        await session.flush()

    token = new_token()
    question = None
    answer = None

    # 根据验证类型生成问题
    if verification_type == VerificationMode.math.value:
        question, answer = generate_math_question()
    elif verification_type == VerificationMode.captcha.value:
        code, answer = generate_captcha()
        question = f"请输入验证码: {code}"

    ch = VerificationChallenge(
        chat_id=chat_id,
        user_id=user_id,
        token=token,
        expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(seconds=ttl_seconds),
        solved=False,
        verification_type=verification_type,
        question=question,
        answer=answer,
    )
    session.add(ch)
    await session.flush()
    return ch


async def solve_by_token(session: AsyncSession, token: str) -> VerificationChallenge | None:
    """通过token验证（按钮模式）"""
    res = await session.execute(select(VerificationChallenge).where(VerificationChallenge.token == token))
    ch = res.scalar_one_or_none()
    if ch is None:
        return None
    if ch.solved:
        return ch
    if dt.datetime.now(dt.UTC) > ch.expires_at:
        return ch
    ch.solved = True
    await session.flush()
    return ch


async def solve_by_answer(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    answer: str,
) -> VerificationChallenge | None:
    """通过答案验证（数学题/验证码模式）"""
    res = await session.execute(
        select(VerificationChallenge).where(
            and_(
                VerificationChallenge.chat_id == chat_id,
                VerificationChallenge.user_id == user_id,
            )
        )
    )
    ch = res.scalar_one_or_none()
    if ch is None:
        return None
    if ch.solved:
        return ch
    if dt.datetime.now(dt.UTC) > ch.expires_at:
        return ch

    # 验证答案
    if ch.answer and ch.answer.lower() == answer.lower().strip():
        ch.solved = True
        await session.flush()
        return ch

    return None


async def get_challenge(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
) -> VerificationChallenge | None:
    """获取用户的验证挑战"""
    res = await session.execute(
        select(VerificationChallenge).where(
            and_(
                VerificationChallenge.chat_id == chat_id,
                VerificationChallenge.user_id == user_id,
            )
        )
    )
    return res.scalar_one_or_none()


async def is_verified(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
) -> bool:
    """检查用户是否已验证"""
    ch = await get_challenge(session, chat_id, user_id)
    return ch is not None and ch.solved
