from __future__ import annotations

import importlib
from pathlib import Path

import pytest

router_module = importlib.import_module("backend.features.web_admin.ad_delivery_router")
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_ad_delivery_router_exposes_authenticated_endpoints() -> None:
    routes = {
        (route.path, method)
        for route in router_module.router.routes
        for method in route.methods
    }
    assert ("/admin/api/ad-deliveries", "GET") in routes
    assert ("/admin/api/ad-deliveries/{history_id}/retry", "POST") in routes
    assert ("/admin/api/ad-deliveries/{history_id}/cancel", "POST") in routes
    assert ("/admin/api/ad-deliveries/{history_id}/replay", "POST") in routes
    for route in router_module.router.routes:
        dependencies = {dependency.call.__name__ for dependency in route.dependant.dependencies}
        assert {"current_admin", "admin_session"} <= dependencies


def test_ad_replay_requires_confirmation_and_reason() -> None:
    assert router_module.AdReplayRequest(confirm=True, reason="人工核对后重放").confirm is True
    with pytest.raises(ValueError):
        router_module.AdReplayRequest(confirm=False, reason="x")
    with pytest.raises(ValueError):
        router_module.AdReplayRequest(confirm=True, reason="")


def test_web_admin_static_ui_exposes_ad_history_and_explicit_replay() -> None:
    html = (PROJECT_ROOT / "backend/features/web_admin/static/admin.html").read_text()
    javascript = (PROJECT_ROOT / "backend/features/web_admin/static/ad_deliveries.js").read_text()

    assert 'data-tab="adDeliveries"' in html
    assert 'id="adDeliveryChatId"' in html
    assert 'id="adDeliveryStatus"' in html
    assert 'id="adDeliveriesBody"' in html
    assert "/admin/api/ad-deliveries" in javascript
    assert "window.confirm" in javascript
    assert "window.prompt" in javascript
