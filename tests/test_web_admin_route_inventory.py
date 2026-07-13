from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from backend.features.web_admin.app import create_admin_web_app
from backend.features.web_admin.card_serialization import serialize_card


def test_admin_web_app_registers_all_operational_routes() -> None:
    app = create_admin_web_app(object(), SimpleNamespace())  # type: ignore[arg-type]
    routes = {
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", set())
    }

    expected = {
        ("GET", "/admin"),
        ("GET", "/admin/"),
        ("POST", "/admin/api/auth/login"),
        ("GET", "/admin/api/auth/me"),
        ("POST", "/admin/api/auth/logout"),
        ("POST", "/admin/api/auth/change-password"),
        ("GET", "/admin/api/key-specs"),
        ("POST", "/admin/api/key-batches"),
        ("GET", "/admin/api/key-batches"),
        ("GET", "/admin/api/keys"),
        ("POST", "/admin/api/keys/copy"),
        ("POST", "/admin/api/keys/void"),
        ("GET", "/admin/api/keys/export"),
        ("GET", "/admin/api/announcement"),
        ("PUT", "/admin/api/announcement"),
        ("GET", "/admin/api/platform-config"),
        ("PUT", "/admin/api/platform-config"),
        ("GET", "/admin/api/accounts"),
        ("POST", "/admin/api/accounts"),
        ("POST", "/admin/api/accounts/{account_id}/status"),
        ("POST", "/admin/api/accounts/{account_id}/password"),
        ("GET", "/admin/api/audit-logs"),
    }
    assert expected <= routes


def test_card_serialization_preserves_voided_status() -> None:
    created_at = dt.datetime(2026, 7, 13, tzinfo=dt.UTC)
    card = SimpleNamespace(
        id=1,
        batch_id=2,
        card_code_plain="TGR-TEST",
        spec_days=30,
        duration_seconds=2_592_000,
        used=False,
        copy_status="voided",
        export_status="voided",
        used_by_chat_id=None,
        used_by_user_id=None,
        used_at=None,
        created_at=created_at,
    )

    result = serialize_card(card)  # type: ignore[arg-type]

    assert result["voided"] is True
    assert result["status"] == "voided"
    assert result["created_at"] == created_at.isoformat()
