"""
server.py — Lightweight aiohttp web server for the MLB Parlay Agent.

Runs in the same asyncio event loop as the Discord bot. Serves:
  GET /              → src/web/static/index.html  (mobile parlay builder UI)
  GET /api/legs      → JSON array of today's scored legs
  GET /api/health    → {"status": "ok", "date": "YYYY-MM-DD"}

Authentication:
  All /api/* routes require the WEB_APP_PASSWORD env var to match either:
    - Query param:   ?password=<value>
    - Header:        Authorization: Bearer <value>

  The root route (/) is served without auth so the HTML page can load.
  The page itself prompts for the password before calling /api/legs.

Environment variables:
  WEB_APP_PASSWORD   — Required. Simple shared secret for the API.
  PORT               — Optional. Defaults to 8080. Railway sets this automatically.
"""
from __future__ import annotations

import os
import json
import pathlib
from datetime import date

from aiohttp import web

from src.utils.db import get_scored_legs

_PASSWORD = os.getenv("WEB_APP_PASSWORD", "")
_STATIC_DIR = pathlib.Path(__file__).parent / "static"
_PORT = int(os.getenv("PORT", "8080"))


def _check_auth(request: web.Request) -> bool:
    """Return True if the request carries a valid WEB_APP_PASSWORD."""
    if not _PASSWORD:
        return True  # no password configured — open access

    # Check query string first
    qs_pw = request.rel_url.query.get("password", "")
    if qs_pw and qs_pw == _PASSWORD:
        return True

    # Check Authorization: Bearer header
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer ") and auth[7:] == _PASSWORD:
        return True

    return False


async def handle_index(request: web.Request) -> web.Response:
    """Serve the mobile web app HTML without auth (the page asks for the password itself)."""
    index = _STATIC_DIR / "index.html"
    if not index.exists():
        return web.Response(text="Web app not found", status=404)
    return web.Response(
        body=index.read_bytes(),
        content_type="text/html",
        charset="utf-8",
    )


async def handle_legs(request: web.Request) -> web.Response:
    """Return today's scored legs as a JSON array."""
    if not _check_auth(request):
        return web.Response(
            text=json.dumps({"error": "Unauthorized"}),
            content_type="application/json",
            status=401,
        )

    date_param = request.rel_url.query.get("date", str(date.today()))
    try:
        legs = get_scored_legs(date_param)
        # Convert None to null safely via json.dumps (psycopg2 returns Python None)
        return web.Response(
            text=json.dumps(legs, default=str),
            content_type="application/json",
        )
    except Exception as exc:
        return web.Response(
            text=json.dumps({"error": str(exc)}),
            content_type="application/json",
            status=500,
        )


async def handle_health(request: web.Request) -> web.Response:
    """Liveness probe — returns 200 with date. No auth required."""
    return web.Response(
        text=json.dumps({"status": "ok", "date": str(date.today())}),
        content_type="application/json",
    )


def create_app() -> web.Application:
    """Build and return the aiohttp Application object."""
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/legs", handle_legs)
    app.router.add_get("/api/health", handle_health)
    return app


async def start_server() -> web.AppRunner:
    """
    Start the aiohttp server and return the runner so the caller can clean it up.

    The runner is attached to the existing asyncio event loop — call this from
    an async context (e.g. bot's setup_hook or on_ready) so it shares the loop
    with discord.py.

    Usage in bot.py:
        runner = await start_server()
        # runner.cleanup() on shutdown if needed
    """
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", _PORT)
    await site.start()
    print(f"[web] Server started on port {_PORT}")
    return runner
