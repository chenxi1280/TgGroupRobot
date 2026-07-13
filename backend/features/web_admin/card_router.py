"""Web 管理端卡密路由。"""
from __future__ import annotations

from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.web_admin.api_common import bad_request, ok
from backend.features.web_admin.api_models import (
    CopyCardsRequest,
    GenerateBatchRequest,
    VoidCardsRequest,
)
from backend.features.web_admin.card_service import (
    COPY_CARD_LIMIT,
    KEY_SPECS,
    copy_cards,
    generate_card_batch,
    list_batches,
    list_cards,
    rows_for_export,
    void_cards,
)
from backend.features.web_admin.dependencies import admin_session as db_session
from backend.features.web_admin.dependencies import current_admin
from backend.platform.db.schema.models.core import AdminAccount

EXPORT_HEADERS = (
    "卡密", "规格天数", "状态", "激活群组",
    "激活用户", "群主", "激活时间", "创建时间",
)
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

router = APIRouter()


@router.get("/admin/api/key-specs")
async def api_key_specs(admin: AdminAccount = Depends(current_admin)):
    _ = admin
    return ok({"items": KEY_SPECS, "copy_limit": COPY_CARD_LIMIT})


@router.post("/admin/api/key-batches")
async def api_generate_batch(
    payload: GenerateBatchRequest,
    admin: AdminAccount = Depends(current_admin),
    session: AsyncSession = Depends(db_session),
):
    try:
        data = await generate_card_batch(
            session,
            admin=admin,
            spec_days=payload.spec_days,
            quantity=payload.quantity,
        )
    except ValueError as exc:
        raise bad_request(exc) from exc
    await session.commit()
    return ok(data, "卡密批次已生成")


@router.get("/admin/api/key-batches")
async def api_list_batches(
    spec_days: int | None = None,
    keyword: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    *,
    offset: int = Query(default=0, ge=0),
    admin: AdminAccount = Depends(current_admin),
    session: AsyncSession = Depends(db_session),
):
    _ = admin
    try:
        data = await list_batches(
            session,
            spec_days=spec_days,
            keyword=keyword,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise bad_request(exc) from exc
    return ok(data)


@router.get("/admin/api/keys")
async def api_list_keys(
    spec_days: int | None = None,
    batch_id: int | None = None,
    status: str | None = None,
    *,
    keyword: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    admin: AdminAccount = Depends(current_admin),
    session: AsyncSession = Depends(db_session),
):
    _ = admin
    try:
        data = await list_cards(
            session,
            spec_days=spec_days,
            batch_id=batch_id,
            status=status,
            keyword=keyword,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise bad_request(exc) from exc
    return ok(data)


@router.post("/admin/api/keys/copy")
async def api_copy_keys(
    payload: CopyCardsRequest,
    admin: AdminAccount = Depends(current_admin),
    session: AsyncSession = Depends(db_session),
):
    try:
        result = await copy_cards(
            session,
            admin=admin,
            card_ids=payload.card_ids,
            with_meta=payload.with_meta,
        )
    except ValueError as exc:
        raise bad_request(exc) from exc
    await session.commit()
    return ok({
        "count": result.count,
        "total": result.total,
        "copied_text": result.copied_text,
        "truncated": result.truncated,
    })


@router.post("/admin/api/keys/void")
async def api_void_keys(
    payload: VoidCardsRequest,
    admin: AdminAccount = Depends(current_admin),
    session: AsyncSession = Depends(db_session),
):
    try:
        result = await void_cards(session, admin=admin, card_ids=payload.card_ids)
    except ValueError as exc:
        raise bad_request(exc) from exc
    await session.commit()
    return ok(result, "卡密已作废")


def _export_status(row: dict) -> str:
    if row.get("voided"):
        return "已作废"
    return "已激活" if row.get("used") else "可用"


def _build_export_buffer(rows: list[dict]) -> BytesIO:
    try:
        from openpyxl import Workbook
    except ImportError as exc:
        raise HTTPException(status_code=500, detail="缺少 openpyxl 依赖，无法导出 XLSX") from exc
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "续费卡密"
    sheet.append(list(EXPORT_HEADERS))
    for row in rows:
        sheet.append([
            row.get("card_code") or "历史卡密无明文",
            row.get("spec_days") or "",
            _export_status(row),
            row.get("used_by_chat_title") or "",
            row.get("used_by_user_text") or "",
            row.get("owner_text") or "",
            row.get("used_at") or "",
            row.get("created_at") or "",
        ])
    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer


@router.get("/admin/api/keys/export")
async def api_export_keys(
    spec_days: int | None = None,
    batch_id: int | None = None,
    status: str | None = None,
    *,
    keyword: str | None = None,
    admin: AdminAccount = Depends(current_admin),
    session: AsyncSession = Depends(db_session),
):
    rows = await rows_for_export(
        session,
        admin=admin,
        spec_days=spec_days,
        batch_id=batch_id,
        status=status,
        keyword=keyword,
    )
    buffer = _build_export_buffer(rows)
    await session.commit()
    headers = {"Content-Disposition": "attachment; filename=renewal-keys.xlsx"}
    return StreamingResponse(buffer, media_type=XLSX_MEDIA_TYPE, headers=headers)
