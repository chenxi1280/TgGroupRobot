from __future__ import annotations

import datetime as dt
import hashlib
import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.core import CustomPointAccount, CustomPointLedger, PointsAccount, PointsTransaction
from backend.platform.db.schema.models.enums import PointsTxnType
from backend.platform.db.schema.models.expansion import AccountInheritAudit, AccountInheritSetting, AccountInheritToken
from backend.shared.services.base import ValidationError
from backend.shared.services.module_settings_service import ModuleSettingsService
from backend.shared.services.user_service import ensure_user


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_inherit_token() -> str:
    return secrets.token_urlsafe(18)


async def get_or_create_setting(session: AsyncSession, chat_id: int) -> AccountInheritSetting:
    await ModuleSettingsService.ensure(session, chat_id=chat_id)
    setting = await session.get(AccountInheritSetting, chat_id)
    if setting is None:
        setting = AccountInheritSetting(chat_id=chat_id)
        session.add(setting)
        await session.flush()
    return setting


async def update_setting(session: AsyncSession, chat_id: int, **updates) -> AccountInheritSetting:
    setting = await get_or_create_setting(session, chat_id)
    for key, value in updates.items():
        if hasattr(setting, key):
            setattr(setting, key, value)
    setting.updated_at = _now()
    await session.flush()
    return setting


async def _audit(
    session: AsyncSession,
    *,
    chat_id: int,
    old_user_id: int | None,
    new_user_id: int | None,
    asset_snapshot: dict,
    result: str,
    reason: str | None = None,
) -> None:
    session.add(
        AccountInheritAudit(
            chat_id=chat_id,
            old_user_id=old_user_id,
            new_user_id=new_user_id,
            asset_snapshot=asset_snapshot,
            result=result,
            reason=reason,
        )
    )
    await session.flush()


async def generate_token(session: AsyncSession, chat_id: int, old_user_id: int) -> tuple[str, dt.datetime]:
    setting = await get_or_create_setting(session, chat_id)
    if not setting.enabled:
        raise ValidationError("当前群未开启炸号继承。")

    account_result = await session.execute(
        select(PointsAccount).where(
            PointsAccount.chat_id == chat_id,
            PointsAccount.user_id == old_user_id,
        ).with_for_update()
    )
    points_account = account_result.scalar_one_or_none()
    custom_result = await session.execute(
        select(CustomPointAccount).where(
            CustomPointAccount.chat_id == chat_id,
            CustomPointAccount.user_id == old_user_id,
        ).with_for_update()
    )
    custom_accounts = list(custom_result.scalars().all())
    if (points_account is None or int(points_account.balance) == 0) and not any(int(item.balance) != 0 for item in custom_accounts):
        raise ValidationError("旧账号当前没有可继承资产。")

    plain_token = new_inherit_token()
    expires_at = _now() + dt.timedelta(minutes=max(int(setting.token_expire_minutes), 1))
    session.add(
        AccountInheritToken(
            chat_id=chat_id,
            old_user_id=old_user_id,
            token_hash=_hash_token(plain_token),
            expires_at=expires_at,
            used=False,
        )
    )
    await _audit(
        session,
        chat_id=chat_id,
        old_user_id=old_user_id,
        new_user_id=None,
        asset_snapshot={"action": "generate_token"},
        result="success",
        reason="token_generated",
    )
    await session.flush()
    return plain_token, expires_at


async def _get_token_by_hash(session: AsyncSession, chat_id: int, token_hash: str) -> AccountInheritToken | None:
    result = await session.execute(
        select(AccountInheritToken).where(
            AccountInheritToken.chat_id == chat_id,
            AccountInheritToken.token_hash == token_hash,
        ).with_for_update()
    )
    return result.scalar_one_or_none()


async def consume_token(session: AsyncSession, chat_id: int, new_user_id: int, plain_token: str) -> dict:
    setting = await get_or_create_setting(session, chat_id)
    if not setting.enabled:
        raise ValidationError("当前群未开启炸号继承。")

    token = await _get_token_by_hash(session, chat_id, _hash_token(plain_token))
    if token is None:
        await _audit(
            session,
            chat_id=chat_id,
            old_user_id=None,
            new_user_id=new_user_id,
            asset_snapshot={"token": "unknown"},
            result="failed",
            reason="token_not_found",
        )
        raise ValidationError("继承 token 无效。")
    if token.used:
        await _audit(
            session,
            chat_id=chat_id,
            old_user_id=token.old_user_id,
            new_user_id=new_user_id,
            asset_snapshot={"token_id": token.id},
            result="failed",
            reason="token_used",
        )
        raise ValidationError("该 token 已使用。")
    if token.expires_at <= _now():
        await _audit(
            session,
            chat_id=chat_id,
            old_user_id=token.old_user_id,
            new_user_id=new_user_id,
            asset_snapshot={"token_id": token.id},
            result="failed",
            reason="token_expired",
        )
        raise ValidationError("该 token 已过期。")
    if token.old_user_id == new_user_id:
        raise ValidationError("不能给同一个账号重复继承。")

    await ensure_user(session, user_id=new_user_id, username=None, first_name=None, last_name=None, language_code=None)

    old_points_result = await session.execute(
        select(PointsAccount).where(
            PointsAccount.chat_id == chat_id,
            PointsAccount.user_id == token.old_user_id,
        ).with_for_update()
    )
    old_points = old_points_result.scalar_one_or_none()
    new_points_result = await session.execute(
        select(PointsAccount).where(
            PointsAccount.chat_id == chat_id,
            PointsAccount.user_id == new_user_id,
        ).with_for_update()
    )
    new_points = new_points_result.scalar_one_or_none()
    if new_points is None:
        new_points = PointsAccount(chat_id=chat_id, user_id=new_user_id, balance=0)
        session.add(new_points)
        await session.flush()

    old_custom_result = await session.execute(
        select(CustomPointAccount).where(
            CustomPointAccount.chat_id == chat_id,
            CustomPointAccount.user_id == token.old_user_id,
        ).with_for_update()
    )
    old_custom_accounts = list(old_custom_result.scalars().all())

    snapshot = {
        "main_points": int(old_points.balance) if old_points else 0,
        "custom_points": [
            {"type_id": account.type_id, "balance": int(account.balance)}
            for account in old_custom_accounts
            if int(account.balance) != 0
        ],
    }

    if snapshot["main_points"] == 0 and not snapshot["custom_points"]:
        await _audit(
            session,
            chat_id=chat_id,
            old_user_id=token.old_user_id,
            new_user_id=new_user_id,
            asset_snapshot=snapshot,
            result="failed",
            reason="empty_assets",
        )
        raise ValidationError("旧账号已经没有可继承资产。")

    if old_points and int(old_points.balance) != 0:
        moved = int(old_points.balance)
        old_points.balance = 0
        new_points.balance = int(new_points.balance) + moved
        session.add(
            PointsTransaction(
                chat_id=chat_id,
                user_id=token.old_user_id,
                txn_type=PointsTxnType.admin_adjust.value,
                amount=-moved,
                reason=f"炸号继承迁出至 {new_user_id}",
            )
        )
        session.add(
            PointsTransaction(
                chat_id=chat_id,
                user_id=new_user_id,
                txn_type=PointsTxnType.admin_adjust.value,
                amount=moved,
                reason=f"炸号继承迁入自 {token.old_user_id}",
            )
        )

    for old_account in old_custom_accounts:
        balance = int(old_account.balance)
        if balance == 0:
            continue
        new_custom_result = await session.execute(
            select(CustomPointAccount).where(
                CustomPointAccount.chat_id == chat_id,
                CustomPointAccount.type_id == old_account.type_id,
                CustomPointAccount.user_id == new_user_id,
            ).with_for_update()
        )
        new_custom = new_custom_result.scalar_one_or_none()
        if new_custom is None:
            new_custom = CustomPointAccount(
                chat_id=chat_id,
                type_id=old_account.type_id,
                user_id=new_user_id,
                balance=0,
            )
            session.add(new_custom)
            await session.flush()
        old_account.balance = 0
        new_custom.balance = int(new_custom.balance) + balance
        session.add(
            CustomPointLedger(
                chat_id=chat_id,
                type_id=old_account.type_id,
                user_id=token.old_user_id,
                delta=-balance,
                reason_note=f"炸号继承迁出至 {new_user_id}",
                operator_user_id=new_user_id,
            )
        )
        session.add(
            CustomPointLedger(
                chat_id=chat_id,
                type_id=old_account.type_id,
                user_id=new_user_id,
                delta=balance,
                reason_note=f"炸号继承迁入自 {token.old_user_id}",
                operator_user_id=new_user_id,
            )
        )

    token.used = True
    token.used_by_user_id = new_user_id
    token.used_at = _now()
    await _audit(
        session,
        chat_id=chat_id,
        old_user_id=token.old_user_id,
        new_user_id=new_user_id,
        asset_snapshot=snapshot,
        result="success",
        reason="inherit_success",
    )
    await session.flush()
    return snapshot


async def build_summary(session: AsyncSession, chat_id: int) -> dict:
    setting = await get_or_create_setting(session, chat_id)
    token_count_result = await session.execute(
        select(AccountInheritToken).where(AccountInheritToken.chat_id == chat_id)
    )
    tokens = list(token_count_result.scalars().all())
    return {
        "enabled": setting.enabled,
        "token_expire_minutes": setting.token_expire_minutes,
        "active_tokens": sum(1 for item in tokens if not item.used and item.expires_at > _now()),
        "used_tokens": sum(1 for item in tokens if item.used),
    }
