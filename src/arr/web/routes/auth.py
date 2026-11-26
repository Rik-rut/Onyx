"""Web UI auth endpoints: status, login, change-credentials, logout.

Sessions are in-memory (a process-lifetime dict of token -> expiry) backed by
an httpOnly cookie; a restart logs everyone out, which is fine for one LAN
account. The forced credential change is a frontend gate (see design): the
backend only records ``must_change_credentials``.
"""

from __future__ import annotations

import secrets
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from arr.log import get_logger

logger = get_logger("web.auth")

COOKIE_NAME = "onyx_session"
SESSION_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days

# token -> expiry (epoch seconds). Process-lifetime: restarts clear sessions.
_SESSIONS: dict[str, float] = {}


class Credentials(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


def _expiry(token: str | None) -> float | None:
    if not token:
        return None
    return _SESSIONS.get(token)


def has_valid_session(cookies: dict[str, str]) -> bool:
    expiry = _expiry(cookies.get(COOKIE_NAME))
    return expiry is not None and expiry > time.time()


def _status_payload(cookies: dict[str, str], username: str, must_change: bool) -> dict:
    valid = has_valid_session(cookies)
    return {
        "authenticated": valid,
        "username": username if valid else None,
        "must_change_credentials": must_change,
    }


router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/status")
async def auth_status(request: Request) -> JSONResponse:
    store = request.app.state.auth
    store.ensure_loaded()
    payload = _status_payload(request.cookies, store.username, store.must_change_credentials)
    return JSONResponse(payload)


@router.post("/login")
async def auth_login(body: Credentials, request: Request) -> JSONResponse:
    store = request.app.state.auth
    store.ensure_loaded()
    if not store.verify(body.username, body.password):
        return JSONResponse({"detail": "invalid username or password"}, status_code=401)
    if store.must_change_credentials:
        # Never log the password or the hash; name the defaults only.
        logger.warning(
            "Login used the default credentials admin / 1234 - change them after login"
        )
    token = secrets.token_urlsafe(32)
    _SESSIONS[token] = time.time() + SESSION_TTL_SECONDS
    response = JSONResponse(
        _status_payload({COOKIE_NAME: token}, store.username, store.must_change_credentials)
    )
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=SESSION_TTL_SECONDS,
    )
    return response


@router.post("/change-credentials")
async def change_credentials(body: Credentials, request: Request) -> JSONResponse:
    store = request.app.state.auth
    store.change_credentials(body.username, body.password)
    return JSONResponse(
        {
            "authenticated": True,
            "username": store.username,
            "must_change_credentials": store.must_change_credentials,
        }
    )


@router.post("/logout")
async def auth_logout(request: Request) -> JSONResponse:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        _SESSIONS.pop(token, None)
    payload = {"authenticated": False, "username": None, "must_change_credentials": False}
    response = JSONResponse(payload)
    response.delete_cookie(COOKIE_NAME)
    return response
