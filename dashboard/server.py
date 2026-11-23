"""Serves the Spending page at / and the Net Worth page at /net-worth behind one password.

    DASHBOARD_PASSWORD=<password> uvicorn --factory dashboard.server:create_app --port 2718

The login gate is adapted from RobinhoodToSheets' dashboard_server.py: a signed
cookie (key derived from the password, so changing the password logs everyone
out) is required for every HTTP request and websocket except the login page.
"""

import asyncio
import hashlib
import hmac
import html
import os
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, quote

import marimo
from itsdangerous import BadSignature, TimestampSigner

_HERE = Path(__file__).parent
PASSWORD_ENV_VAR = "DASHBOARD_PASSWORD"
COOKIE_NAME = "dashboard_session"
COOKIE_MAX_AGE = 24 * 60 * 60  # log in again daily
LOGIN_PATH = "/login"
FAILED_LOGIN_DELAY_SECONDS = 1.0

_LOGIN_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Finance dashboard</title>
<style>
  body {{ margin:0; min-height:100vh; display:grid; place-items:center; background:#f6f7f9;
         font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; color:#111827; }}
  form {{ display:grid; gap:.8rem; width:min(22rem, 100% - 2rem); background:#fff; padding:1.6rem;
         border:1px solid #e3e6ec; border-radius:10px; }}
  h1 {{ font-size:1.05rem; margin:0; }}
  input, button {{ font:inherit; padding:.6rem .8rem; border-radius:6px; }}
  input {{ border:1px solid #d1d5db; }}
  button {{ background:#2563eb; color:#fff; border:0; cursor:pointer; }}
  .error {{ color:#b91c1c; font-size:.85rem; }}
</style></head>
<body><form method="post" action="{action}">
  <h1>Finance dashboard</h1>
  <input type="password" name="password" placeholder="Password" autofocus autocomplete="current-password">
  {error}
  <button type="submit">Log in</button>
</form></body></html>"""


def _safe_next(target: str) -> str:
    """Only same-site paths, so the login page can't redirect to another site."""
    if not target.startswith("/") or target.startswith("//") or "\\" in target:
        return "/"
    return target


def _header(scope, name: bytes) -> str:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return value.decode("latin-1")
    return ""


class PasswordGate:
    """ASGI middleware requiring a signed session cookie on every request."""

    def __init__(self, app, password: str):
        self.app = app
        self.password = password.encode()
        self.signer = TimestampSigner(hashlib.sha256(b"dashboard-cookie:" + self.password).hexdigest())

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "http" and scope["path"] == LOGIN_PATH:
            await self._login(scope, receive, send)
            return
        if self._authorized(scope):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        target = scope["path"] + ("?" + scope["query_string"].decode() if scope["query_string"] else "")
        await self._respond(send, 303, headers=[(b"location", f"{LOGIN_PATH}?next={quote(target)}".encode())])

    def _authorized(self, scope) -> bool:
        cookie = SimpleCookie(_header(scope, b"cookie"))
        if COOKIE_NAME not in cookie:
            return False
        try:
            self.signer.unsign(cookie[COOKIE_NAME].value, max_age=COOKIE_MAX_AGE)
            return True
        except BadSignature:
            return False

    async def _login(self, scope, receive, send):
        target = _safe_next(parse_qs(scope["query_string"].decode()).get("next", ["/"])[0])
        action = f"{LOGIN_PATH}?next={quote(target)}"
        if scope["method"] != "POST":
            await self._page(send, action)
            return
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body"):
                break
        password = parse_qs(body.decode()).get("password", [""])[0].encode()
        if not hmac.compare_digest(password, self.password):
            await asyncio.sleep(FAILED_LOGIN_DELAY_SECONDS)
            await self._page(send, action, error="Wrong password")
            return
        cookie = (f"{COOKIE_NAME}={self.signer.sign(b'ok').decode()}; Path=/; "
                  f"Max-Age={COOKIE_MAX_AGE}; HttpOnly; SameSite=Lax")
        if _header(scope, b"x-forwarded-proto") == "https":  # Render terminates TLS upstream
            cookie += "; Secure"
        await self._respond(send, 303, headers=[(b"location", target.encode()), (b"set-cookie", cookie.encode())])

    async def _page(self, send, action: str, error: str = ""):
        page = _LOGIN_PAGE.format(action=html.escape(action),
                                  error=f'<div class="error">{error}</div>' if error else "")
        await self._respond(send, 401 if error else 200, page.encode(),
                            [(b"content-type", b"text/html; charset=utf-8")])

    @staticmethod
    async def _respond(send, status: int, body: bytes = b"", headers=()):
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-length", str(len(body)).encode()), *headers]})
        await send({"type": "http.response.body", "body": body})


def create_app():
    """ASGI app for uvicorn --factory (so importing doesn't require the password)."""
    password = os.environ.get(PASSWORD_ENV_VAR)
    if not password:
        raise RuntimeError(f"Set {PASSWORD_ENV_VAR} to the dashboard password")
    apps = (
        marimo.create_asgi_app()
        .with_app(path="/net-worth", root=str(_HERE / "net_worth.py"))
        .with_app(path="", root=str(_HERE / "spending.py"))
        .build()
    )
    return PasswordGate(apps, password)
