from __future__ import annotations

import datetime as dt
import random
import secrets
import string

from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.core import VerificationChallenge
from backend.platform.db.schema.models.enums import VerificationMode
from backend.shared.services.base import ServiceBase

SELF_REVIEW_CHALLENGE_PREFIX = "[SELF_REVIEW]"
SELF_REVIEW_EXPECTED_ANSWER = "我已阅读群规"


def new_token() -> str:
    """生成新的验证 token"""
    return secrets.token_urlsafe(24)


def generate_captcha(length: int = 4) -> tuple[str, str]:
    """
    生成验证码

    Args:
        length: 验证码长度

    Returns:
        (code, image_text) - 验证码和显示文本
    """
    code = "".join(random.choices(string.digits, k=length))
    return code, code


def generate_math_question() -> tuple[str, str]:
    """
    生成数学题

    Returns:
        (question, answer) - 问题和答案
    """
    ops = ["+", "-"]
    op = random.choice(ops)

    if op == "+":
        a = random.randint(1, 50)
        b = random.randint(1, 50)
        question = f"{a} + {b} = ?"
        answer = str(a + b)
        return question, answer

    a = random.randint(10, 50)
    b = random.randint(1, a)
    question = f"{a} - {b} = ?"
    answer = str(a - b)
    return question, answer


def build_self_review_question() -> str:
    return f"{SELF_REVIEW_CHALLENGE_PREFIX} 请发送：{SELF_REVIEW_EXPECTED_ANSWER}"


def is_self_review_question(question: str | None) -> bool:
    return bool(question and question.startswith(SELF_REVIEW_CHALLENGE_PREFIX))


def render_self_review_question(question: str | None) -> str:
    if not question:
        return SELF_REVIEW_EXPECTED_ANSWER
    if not is_self_review_question(question):
        return question
    return question.split("]", 1)[-1].strip()


async def create_or_replace_challenge(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    ttl_seconds: int,
    verification_type: str = VerificationMode.button.value,
) -> VerificationChallenge:
    """
    创建或替换验证挑战

    Args:
        session: 数据库会话
        chat_id: 群组 ID
        user_id: 用户 ID
        ttl_seconds: 过期时间（秒）
        verification_type: 验证类型

    Returns:
        VerificationChallenge: 验证挑战对象
    """
    # 删除现有挑战
    existing = await ServiceBase._get_by_filters(
        session,
        VerificationChallenge,
        {"chat_id": chat_id, "user_id": user_id},
    )
    if existing is not None:
        await ServiceBase._delete_entity(session, existing)

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
    """
    通过 token 验证（按钮模式）

    Args:
        session: 数据库会话
        token: 验证 token

    Returns:
        VerificationChallenge: 验证挑战对象，验证失败则返回 None
    """
    ch = await ServiceBase._get_by_filters(
        session,
        VerificationChallenge,
        {"token": token},
    )
    if ch is None:
        return None
    if ch.solved:
        return ch

    # 管理员审核模式允许超时后仍可人工通过，其他模式仍遵循超时限制
    if (
        dt.datetime.now(dt.UTC) > ch.expires_at
        and ch.verification_type != VerificationMode.admin.value
    ):
        return ch

    await ServiceBase._update_entity(session, ch, {"solved": True})
    return ch


async def solve_by_token_scoped(
    session: AsyncSession,
    token: str,
    expected_chat_id: int | None = None,
    expected_user_id: int | None = None,
) -> VerificationChallenge | None:
    """
    通过 token 验证（带 chat/user 归属校验）

    仅当 token 属于指定 chat/user 时才会标记 solved，避免跨群或他人代点导致误通过。
    """
    ch = await ServiceBase._get_by_filters(
        session,
        VerificationChallenge,
        {"token": token},
    )
    if ch is None:
        return None
    if expected_chat_id is not None and ch.chat_id != expected_chat_id:
        return None
    if expected_user_id is not None and ch.user_id != expected_user_id:
        return None
    if ch.solved:
        return ch

    if (
        dt.datetime.now(dt.UTC) > ch.expires_at
        and ch.verification_type != VerificationMode.admin.value
    ):
        return ch

    await ServiceBase._update_entity(session, ch, {"solved": True})
    return ch


async def get_challenge_by_token(
    session: AsyncSession,
    token: str,
) -> VerificationChallenge | None:
    """按 token 获取验证挑战，不修改状态。"""
    return await ServiceBase._get_by_filters(
        session,
        VerificationChallenge,
        {"token": token},
    )


async def solve_by_answer(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    answer: str,
) -> VerificationChallenge | None:
    """
    通过答案验证（数学题/验证码模式）

    Args:
        session: 数据库会话
        chat_id: 群组 ID
        user_id: 用户 ID
        answer: 用户答案

    Returns:
        VerificationChallenge: 验证挑战对象，验证失败则返回 None
    """
    ch = await ServiceBase._get_by_filters(
        session,
        VerificationChallenge,
        {"chat_id": chat_id, "user_id": user_id},
    )
    if ch is None:
        return None
    if ch.solved:
        return ch
    if dt.datetime.now(dt.UTC) > ch.expires_at:
        return ch

    # 验证答案
    if ch.answer and ch.answer.lower() == answer.lower().strip():
        await ServiceBase._update_entity(session, ch, {"solved": True})
        return ch

    return None


async def get_challenge(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
) -> VerificationChallenge | None:
    """
    获取用户的验证挑战

    Args:
        session: 数据库会话
        chat_id: 群组 ID
        user_id: 用户 ID

    Returns:
        VerificationChallenge: 验证挑战对象，如果不存在则返回 None
    """
    return await ServiceBase._get_by_filters(
        session,
        VerificationChallenge,
        {"chat_id": chat_id, "user_id": user_id},
    )
