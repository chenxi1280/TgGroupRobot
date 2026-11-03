import hashlib
import hmac
import json
from urllib.parse import urlencode

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from types import SimpleNamespace

from backend.features.mini_app.auth import validate_init_data, verification_identity

TOKEN = "999000:MINI_APP_TEST_TOKEN"
NOW = 1793750400


def signed_data(*, user_id=42, issued_at=NOW, scene="verify_test", **extra):
    fields = {"auth_date": str(issued_at), "user": json.dumps({
        "id": user_id, "first_name": "测试", "is_bot": False,
    }, separators=(",", ":")), "start_param": scene, **extra}
    secret = hmac.digest(b"WebAppData", TOKEN.encode(), hashlib.sha256)
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def test_valid_signed_identity_preserves_unicode_and_scene():
    identity = validate_init_data(signed_data(), TOKEN, max_age=3600, now=NOW)
    assert identity.user.id == 42
    assert identity.user.first_name == "测试"
    assert identity.start_param == "verify_test"


@pytest.mark.parametrize("change", ["tamper", "duplicate", "expired", "future", "wrong_bot"])
def test_identity_rejects_tampering_duplicates_expiry_and_wrong_bot(change):
    raw, token = signed_data(), TOKEN
    if change == "tamper":
        raw = raw.replace("verify_test", "verify_another")
    if change == "duplicate":
        raw += "&auth_date=" + str(NOW)
    if change == "expired":
        raw = signed_data(issued_at=NOW - 3601)
    if change == "future":
        raw = signed_data(issued_at=NOW + 1)
    if change == "wrong_bot":
        token = "888000:OTHER_BOT"
    with pytest.raises(ValueError):
        validate_init_data(raw, token, max_age=3600, now=NOW)


def test_signed_extra_fields_are_included_in_hmac():
    identity = validate_init_data(signed_data(signature="test-signature"), TOKEN, max_age=3600, now=NOW)
    assert identity.user.id == 42


@pytest.mark.parametrize("dependency", [verification_identity])
def test_http_dependency_rejects_missing_or_malformed_identity(dependency):
    app = FastAPI()
    app.state.settings = SimpleNamespace(bot_token=TOKEN)
    from fastapi import Depends

    @app.get("/identity")
    def identity(actor=Depends(verification_identity)):
        return {"id": actor.user.id}

    with TestClient(app) as client:
        for value in ["", "Bearer anything", "tma invalid", "tma hash=bad"]:
            response = client.get("/identity", headers={"authorization": value})
            assert response.status_code == 401
            assert "bad" not in response.text
