from __future__ import annotations

import importlib
from pathlib import Path


router_module = importlib.import_module("backend.features.web_admin.verification_timeout_router")
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_verification_timeout_router_exposes_authenticated_operation_endpoints() -> None:
    router = getattr(router_module, "router", None)

    assert router is not None
    routes = {
        (route.path, method)
        for route in router.routes
        for method in route.methods
    }
    assert ("/admin/api/verification-timeouts", "GET") in routes
    assert ("/admin/api/verification-timeouts/{challenge_id}/retry", "POST") in routes
    assert ("/admin/api/verification-timeouts/{challenge_id}/cancel", "POST") in routes
    assert ("/admin/api/verification-timeouts/{challenge_id}/replay", "POST") in routes
    for route in router.routes:
        dependencies = {
            dependency.call.__name__
            for dependency in route.dependant.dependencies
        }
        assert {"current_admin", "admin_session"} <= dependencies


def test_uncertain_replay_request_requires_explicit_confirmation() -> None:
    request_type = getattr(router_module, "UncertainReplayRequest", None)

    assert request_type is not None
    assert request_type(confirm=True).confirm is True
    try:
        request_type(confirm=False)
    except ValueError:
        pass
    else:
        raise AssertionError("confirm=false must be rejected")


def test_web_admin_static_ui_exposes_timeout_filter_and_operations() -> None:
    html = (PROJECT_ROOT / "backend/features/web_admin/static/admin.html").read_text()
    javascript = "\n".join([
        (PROJECT_ROOT / "backend/features/web_admin/static/admin.js").read_text(),
        (PROJECT_ROOT / "backend/features/web_admin/static/verification_timeouts.js").read_text(),
    ])

    assert 'data-tab="verificationTimeouts"' in html
    assert 'id="verificationTimeoutChatId"' in html
    assert 'id="verificationTimeoutStatus"' in html
    assert 'id="verificationTimeoutBody"' in html
    assert "loadVerificationTimeouts" in javascript
    assert "confirmVerificationTimeoutReplay" in javascript
    assert "/admin/api/verification-timeouts" in javascript
