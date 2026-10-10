"""Opt-in real transaction tests. Only use a disposable database."""
import asyncio
import datetime as dt
import os
import secrets

import pytest
from sqlalchemy import func, select

from backend.features.points.services.points_extended_service import PointsExtendedService as Mall
from backend.platform.db.runtime.session import create_database
from backend.platform.db.schema.models.core import (
    TgChat, TgUser, PointsAccount, PointsMallSetting, PointsMallProduct,
    PointsMallOrder, PointsTransaction,
)

URL = os.environ.get("TGR_REPAIR_TEST_DATABASE_URL")
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not URL, reason="disposable Postgres URL required")]


async def seed(db, *, stock=2, balance=100):
    identity = secrets.randbelow(1_000_000_000) + 1_000_000_000
    chat_id, user_id = -identity, identity
    async with db.session_factory() as s:
        s.add_all([TgChat(id=chat_id, type="supergroup", title="repair test"), TgUser(id=user_id)])
        await s.flush()
        product = PointsMallProduct(chat_id=chat_id, name="test", price_points=20,
                                    stock_total=stock, stock_left=stock, status="on_sale")
        s.add_all([PointsMallSetting(chat_id=chat_id, enabled=True), product,
                   PointsAccount(chat_id=chat_id, user_id=user_id, balance=balance)])
        await s.commit()
        return chat_id, user_id, product.product_id


async def intent(db, scope):
    chat, user, product = scope
    async with db.session_factory() as s:
        value, error = await Mall.create_redeem_intent(s, chat_id=chat, product_id=product, buyer_user_id=user)
        assert error is None
        await s.commit()
        return value.token


async def confirm(db, scope, token):
    chat, user, _ = scope
    async with db.session_factory() as s:
        ok, reason, order = await Mall.confirm_redeem_intent(s, chat_id=chat, token=token, buyer_user_id=user)
        await s.commit()
        return ok, reason, order.order_id if order else None


async def test_duplicate_confirmation_concurrency_and_restart():
    db = create_database(URL)
    try:
        scope = await seed(db)
        token = await intent(db, scope)
        results = await asyncio.gather(*(confirm(db, scope, token) for _ in range(3)))
        assert all(row[0] for row in results)
        assert len({row[2] for row in results}) == 1
        await db.engine.dispose()
        assert (await confirm(db, scope, token))[2] == results[0][2]
        async with db.session_factory() as s:
            account = (await s.execute(select(PointsAccount).where(PointsAccount.chat_id == scope[0]))).scalar_one()
            product = await s.get(PointsMallProduct, scope[2])
            count = await s.scalar(select(func.count()).select_from(PointsTransaction).where(PointsTransaction.chat_id == scope[0]))
            assert account.balance == 80 and product.stock_left == 1 and count == 1
    finally:
        await db.engine.dispose()


async def test_distinct_intents_compete_for_last_stock():
    db = create_database(URL)
    try:
        scope = await seed(db, stock=1)
        tokens = [await intent(db, scope), await intent(db, scope)]
        results = await asyncio.gather(*(confirm(db, scope, token) for token in tokens))
        assert sum(row[0] for row in results) == 1
    finally:
        await db.engine.dispose()


async def test_changed_terms_and_closed_mall_do_not_charge():
    db = create_database(URL)
    try:
        scope = await seed(db)
        token = await intent(db, scope)
        async with db.session_factory() as s:
            product = await s.get(PointsMallProduct, scope[2])
            product.price_points = 30
            await s.commit()
        assert "条款已变化" in (await confirm(db, scope, token))[1]
        token = await intent(db, scope)
        async with db.session_factory() as s:
            setting = await s.get(PointsMallSetting, scope[0])
            setting.enabled = False
            await s.commit()
        assert (await confirm(db, scope, token))[1] == "商城已关闭"
        async with db.session_factory() as s:
            assert await s.scalar(select(func.count()).select_from(PointsMallOrder).where(PointsMallOrder.chat_id == scope[0])) == 0
    finally:
        await db.engine.dispose()


@pytest.mark.parametrize("constraint", ["balance", "limit"])
async def test_distinct_intents_share_one_balance_and_limit(constraint):
    db = create_database(URL)
    try:
        scope = await seed(db, stock=3, balance=20 if constraint == "balance" else 100)
        if constraint == "limit":
            async with db.session_factory() as s:
                (await s.get(PointsMallProduct, scope[2])).limit_per_user = 1
                await s.commit()
        tokens = [await intent(db, scope), await intent(db, scope)]
        results = await asyncio.gather(*(confirm(db, scope, token) for token in tokens))
        assert sum(row[0] for row in results) == 1
        async with db.session_factory() as s:
            assert (await s.get(PointsMallProduct, scope[2])).stock_left == 2
            assert await s.scalar(select(func.count()).select_from(PointsTransaction).where(PointsTransaction.chat_id == scope[0])) == 1
    finally:
        await db.engine.dispose()


@pytest.mark.parametrize("failure", ["expired", "other_user", "other_chat", "off_sale", "no_balance"])
async def test_invalid_confirmation_leaves_financial_state_unchanged(failure):
    from backend.platform.db.schema.models.core import PointsMallIntent
    db = create_database(URL)
    try:
        scope = await seed(db, balance=0 if failure == "no_balance" else 100)
        token = await intent(db, scope)
        async with db.session_factory() as s:
            if failure == "expired":
                (await s.get(PointsMallIntent, token)).expires_at = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1)
            elif failure == "off_sale":
                (await s.get(PointsMallProduct, scope[2])).status = "off_sale"
            await s.commit()
        attempted = (scope[0]-1, scope[1], scope[2]) if failure == "other_chat" else (
            (scope[0], scope[1]+1, scope[2]) if failure == "other_user" else scope)
        assert not (await confirm(db, attempted, token))[0]
        async with db.session_factory() as s:
            assert (await s.get(PointsMallProduct, scope[2])).stock_left == 2
            assert await s.scalar(select(func.count()).select_from(PointsMallOrder).where(PointsMallOrder.chat_id == scope[0])) == 0
            assert await s.scalar(select(func.count()).select_from(PointsTransaction).where(PointsTransaction.chat_id == scope[0])) == 0
    finally:
        await db.engine.dispose()


async def test_close_holding_setting_lock_prevents_inflight_confirmation():
    db = create_database(URL)
    try:
        scope = await seed(db)
        token = await intent(db, scope)
        async with db.session_factory() as s:
            setting = (await s.execute(select(PointsMallSetting).where(PointsMallSetting.chat_id == scope[0]).with_for_update())).scalar_one()
            competing = asyncio.create_task(confirm(db, scope, token))
            await asyncio.sleep(0.03)
            assert not competing.done()
            setting.enabled = False
            await s.commit()
        result = await competing
        assert not result[0] and result[1] == "商城已关闭"
    finally:
        await db.engine.dispose()


async def test_cancelled_confirmation_cannot_be_consumed_later():
    db = create_database(URL)
    try:
        scope = await seed(db)
        token = await intent(db, scope)
        async with db.session_factory() as s:
            message, product = await Mall.cancel_redeem_intent(s, chat_id=scope[0], token=token, buyer_user_id=scope[1])
            assert product == scope[2] and "没有扣分" in message
            await s.commit()
        await db.engine.dispose()
        assert "已取消" in (await confirm(db, scope, token))[1]
        async with db.session_factory() as s:
            assert await s.scalar(select(func.count()).select_from(PointsMallOrder).where(PointsMallOrder.chat_id == scope[0])) == 0
    finally:
        await db.engine.dispose()
