from __future__ import annotations

import datetime as dt
import hashlib
import secrets
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.core import CustomPointAccount, CustomPointLedger, PointsAccount, PointsTransaction
from backend.platform.db.schema.models.enums import PointsTxnType
from backend.platform.db.schema.models.expansion import AccountInheritAudit, AccountInheritSetting, AccountInheritToken
from backend.shared.services.base import ValidationError
from backend.shared.services.module_settings_service import ModuleSettingsService
from backend.shared.services.user_service import ensure_user


@dataclass(frozen=True)
class InheritTransfer:
    chat_id: int
    old_user_id: int
    new_user_id: int


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


async def _audit_token_failure(
    session: AsyncSession,
    *,
    chat_id: int,
    new_user_id: int,
    token: AccountInheritToken | None,
    reason: str,
) -> None:
    await _audit(
        session,
        chat_id=chat_id,
        old_user_id=token.old_user_id if token is not None else None,
        new_user_id=new_user_id,
        asset_snapshot={"token_id": token.id} if token is not None else {"token": "unknown"},
        result="failed",
        reason=reason,
    )


def _token_validation_error(
    token: AccountInheritToken,
    new_user_id: int,
) -> tuple[str, str] | None:
    if token.used:
        return "token_used", "该 token 已使用。"
    if token.expires_at <= _now():
        return "token_expired", "该 token 已过期。"
    if token.old_user_id == new_user_id:
        return "same_account", "不能给同一个账号重复继承。"
    return None


async def _load_valid_token(
    session: AsyncSession,
    chat_id: int,
    new_user_id: int,
    *,
    plain_token: str,
) -> AccountInheritToken:
    token = await _get_token_by_hash(session, chat_id, _hash_token(plain_token))
    if token is None:
        await _audit_token_failure(
            session, chat_id=chat_id, new_user_id=new_user_id, token=None, reason="token_not_found"
        )
        raise ValidationError("继承 token 无效。")
    failure = _token_validation_error(token, new_user_id)
    if failure is not None:
        reason, message = failure
        await _audit_token_failure(
            session, chat_id=chat_id, new_user_id=new_user_id, token=token, reason=reason
        )
        raise ValidationError(message)
    return token


async def _load_points_account(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
) -> PointsAccount | None:
    result = await session.execute(
        select(PointsAccount).where(
            PointsAccount.chat_id == chat_id,
            PointsAccount.user_id == user_id,
        ).with_for_update()
    )
    return result.scalar_one_or_none()


async def _load_transfer_assets(
    session: AsyncSession,
    transfer: InheritTransfer,
) -> tuple[PointsAccount | None, PointsAccount, list[CustomPointAccount]]:
    old_points = await _load_points_account(session, transfer.chat_id, transfer.old_user_id)
    new_points = await _load_points_account(session, transfer.chat_id, transfer.new_user_id)
    if new_points is None:
        new_points = PointsAccount(chat_id=transfer.chat_id, user_id=transfer.new_user_id, balance=0)
        session.add(new_points)
        await session.flush()
    custom_result = await session.execute(
        select(CustomPointAccount).where(
            CustomPointAccount.chat_id == transfer.chat_id,
            CustomPointAccount.user_id == transfer.old_user_id,
        ).with_for_update()
    )
    return old_points, new_points, list(custom_result.scalars().all())


def _build_asset_snapshot(
    old_points: PointsAccount | None,
    old_custom_accounts: list[CustomPointAccount],
) -> dict:
    return {
        "main_points": int(old_points.balance) if old_points else 0,
        "custom_points": [
            {"type_id": account.type_id, "balance": int(account.balance)}
            for account in old_custom_accounts
            if int(account.balance) != 0
        ],
    }


async def _reject_empty_assets(
    session: AsyncSession,
    transfer: InheritTransfer,
    snapshot: dict,
) -> None:
    if snapshot["main_points"] != 0 or snapshot["custom_points"]:
        return
    await _audit(
        session,
        chat_id=transfer.chat_id,
        old_user_id=transfer.old_user_id,
        new_user_id=transfer.new_user_id,
        asset_snapshot=snapshot,
        result="failed",
        reason="empty_assets",
    )
    raise ValidationError("旧账号已经没有可继承资产。")


def _add_main_points_ledgers(session: AsyncSession, transfer: InheritTransfer, moved: int) -> None:
    session.add(
        PointsTransaction(
            chat_id=transfer.chat_id,
            user_id=transfer.old_user_id,
            txn_type=PointsTxnType.admin_adjust.value,
            amount=-moved,
            reason=f"炸号继承迁出至 {transfer.new_user_id}",
        )
    )
    session.add(
        PointsTransaction(
            chat_id=transfer.chat_id,
            user_id=transfer.new_user_id,
            txn_type=PointsTxnType.admin_adjust.value,
            amount=moved,
            reason=f"炸号继承迁入自 {transfer.old_user_id}",
        )
    )


def _move_main_points(
    session: AsyncSession,
    transfer: InheritTransfer,
    *,
    old_points: PointsAccount | None,
    new_points: PointsAccount,
) -> None:
    if old_points is None or int(old_points.balance) == 0:
        return
    moved = int(old_points.balance)
    old_points.balance = 0
    new_points.balance = int(new_points.balance) + moved
    _add_main_points_ledgers(session, transfer, moved)


async def _get_or_create_custom_account(
    session: AsyncSession,
    transfer: InheritTransfer,
    type_id: int,
) -> CustomPointAccount:
    result = await session.execute(
        select(CustomPointAccount).where(
            CustomPointAccount.chat_id == transfer.chat_id,
            CustomPointAccount.type_id == type_id,
            CustomPointAccount.user_id == transfer.new_user_id,
        ).with_for_update()
    )
    account = result.scalar_one_or_none()
    if account is None:
        account = CustomPointAccount(
            chat_id=transfer.chat_id,
            type_id=type_id,
            user_id=transfer.new_user_id,
            balance=0,
        )
        session.add(account)
        await session.flush()
    return account


def _add_custom_points_ledgers(
    session: AsyncSession,
    transfer: InheritTransfer,
    *,
    type_id: int,
    balance: int,
) -> None:
    session.add(
        CustomPointLedger(
            chat_id=transfer.chat_id,
            type_id=type_id,
            user_id=transfer.old_user_id,
            delta=-balance,
            reason_note=f"炸号继承迁出至 {transfer.new_user_id}",
            operator_user_id=transfer.new_user_id,
        )
    )
    session.add(
        CustomPointLedger(
            chat_id=transfer.chat_id,
            type_id=type_id,
            user_id=transfer.new_user_id,
            delta=balance,
            reason_note=f"炸号继承迁入自 {transfer.old_user_id}",
            operator_user_id=transfer.new_user_id,
        )
    )


async def _move_custom_points(
    session: AsyncSession,
    transfer: InheritTransfer,
    old_accounts: list[CustomPointAccount],
) -> None:
    for old_account in old_accounts:
        balance = int(old_account.balance)
        if balance == 0:
            continue
        new_account = await _get_or_create_custom_account(session, transfer, old_account.type_id)
        old_account.balance = 0
        new_account.balance = int(new_account.balance) + balance
        _add_custom_points_ledgers(
            session, transfer, type_id=old_account.type_id, balance=balance
        )


async def consume_token(session: AsyncSession, chat_id: int, new_user_id: int, *, plain_token: str) -> dict:
    setting = await get_or_create_setting(session, chat_id)
    if not setting.enabled:
        raise ValidationError("当前群未开启炸号继承。")
    token = await _load_valid_token(session, chat_id, new_user_id, plain_token=plain_token)
    await ensure_user(
        session,
        user_id=new_user_id,
        username=None,
        first_name=None,
        last_name=None,
        language_code=None,
    )
    transfer = InheritTransfer(chat_id, token.old_user_id, new_user_id)
    old_points, new_points, old_custom_accounts = await _load_transfer_assets(session, transfer)
    snapshot = _build_asset_snapshot(old_points, old_custom_accounts)
    await _reject_empty_assets(session, transfer, snapshot)
    _move_main_points(
        session, transfer, old_points=old_points, new_points=new_points
    )
    await _move_custom_points(session, transfer, old_custom_accounts)

    token.used = True
    token.used_by_user_id = new_user_id
    token.used_at = _now()
    await _audit(
        session,
        chat_id=transfer.chat_id,
        old_user_id=transfer.old_user_id,
        new_user_id=transfer.new_user_id,
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
