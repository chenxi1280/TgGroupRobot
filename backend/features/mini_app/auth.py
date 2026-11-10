from __future__ import annotations

import hashlib
import hmac
import json
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass
from urllib.parse import parse_qsl

from fastapi import HTTPException, Request, Response
from telegram import User

VERIFICATION_AUTH_SECONDS = 3600


@dataclass(frozen=True)
class MiniAppIdentity:
    user: User
    start_param: str


def validate_init_data(raw: str, token: str, *, max_age: int, now: int | None = None) -> MiniAppIdentity:
    pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise ValueError("重复的身份字段")
    received = fields.pop("hash")
    check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.digest(b"WebAppData", token.encode(), hashlib.sha256)
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(received, expected):
        raise ValueError("身份签名无效")
    age = (int(time.time()) if now is None else now) - int(fields["auth_date"])
    if age < 0 or age > max_age:
        raise ValueError("身份已过期，请重新打开小程序")
    payload = json.loads(fields["user"])
    user = User.de_json({"is_bot": False, **payload}, None)
    if user is None or user.id <= 0 or user.is_bot:
        raise ValueError("请使用 Telegram 个人账号打开")
    return MiniAppIdentity(user=user, start_param=fields.get("start_param", ""))


def request_identity(request: Request, *, max_age: int) -> MiniAppIdentity:
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("tma "):
        raise HTTPException(status_code=401, detail="请从 Telegram 机器人入口打开")
    try:
        return validate_init_data(
            authorization.removeprefix("tma "), request.app.state.settings.bot_token,
            max_age=max_age,
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=401, detail="身份无效或已过期，请重新打开小程序") from exc


def verification_identity(request: Request) -> MiniAppIdentity:
    return request_identity(request, max_age=VERIFICATION_AUTH_SECONDS)


ROOM_SESSION_SECONDS = 7200
ROOM_SESSION_MAX_SECONDS = 86400
ROOM_SESSION_HEADER = "X-Room-Session"


def room_session_identity(request: Request) -> tuple[MiniAppIdentity, int, int]:
    current = int(time.time())
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("room "):
        return request_identity(request, max_age=VERIFICATION_AUTH_SECONDS), current, 0
    try:
        encoded, signature = authorization.removeprefix("room ").split(".", 1)
        secret = request.app.state.settings.bot_token
        if not hmac.compare_digest(signature, _sign_room_session(encoded, secret)):
            raise ValueError("invalid room session signature")
        user_data, scene, issued, expires = json.loads(urlsafe_b64decode(encoded))
        if not issued <= current < expires <= issued + ROOM_SESSION_MAX_SECONDS:
            raise ValueError("expired room session")
        return MiniAppIdentity(User.de_json(user_data, None), scene), issued, expires
    except (ValueError, TypeError) as exc:
        raise HTTPException(401, "房间登录已过期，请重新打开小程序") from exc


def renew_room_session(request: Request, response: Response, actor: MiniAppIdentity, *, issued: int, expires: int) -> None:
    current = int(time.time())
    if expires - current > ROOM_SESSION_SECONDS // 2:
        return
    renewed = min(current + ROOM_SESSION_SECONDS, issued + ROOM_SESSION_MAX_SECONDS)
    payload = json.dumps([actor.user.to_dict(), actor.start_param, issued, renewed], separators=(",", ":"))
    encoded = urlsafe_b64encode(payload.encode()).decode()
    signature = _sign_room_session(encoded, request.app.state.settings.bot_token)
    response.headers[ROOM_SESSION_HEADER] = f"{encoded}.{signature}"
    response.headers["Cache-Control"] = "no-store"


def _sign_room_session(encoded: str, token: str) -> str:
    return hmac.digest(token.encode(), b"room-session:" + encoded.encode(), hashlib.sha256).hex()
