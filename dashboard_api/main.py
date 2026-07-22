"""
dashboard_api/main.py — the dashboard service entrypoint.

Deployed as a SECOND Railway service in the same project as mlb-agent's bot,
pointed at this same repo, with its own start command:

    uvicorn dashboard_api.main:app --host 0.0.0.0 --port $PORT

(run from the repo ROOT, not from inside dashboard_api/, so `src.apis...`
imports resolve — same as the existing bot service.)

Shares the mlb-agent service's env vars (DATABASE_URL, SPORTSGAMEODDS_API_KEY)
— Railway can share variables across services in the same project, or you can
just copy them into this service's own variables tab.
"""
import time
from datetime import date

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from dashboard_api.shape import build_dashboard

app = FastAPI(title="MLB Slate Explorer API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # single-user tool
    allow_methods=["GET"],
    allow_headers=["*"],
)

_CACHE_TTL_SECONDS = 30 * 60
_cache: dict = {"date": None, "data": None, "fetched_at": 0.0}


@app.get("/api/dashboard")
def get_dashboard():
    today = date.today().isoformat()
    now = time.time()
    if (
        _cache["data"] is not None
        and _cache["date"] == today
        and (now - _cache["fetched_at"]) < _CACHE_TTL_SECONDS
    ):
        return _cache["data"]
    try:
        data = build_dashboard(today)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"dashboard build failed: {e}")
    _cache.update(date=today, data=data, fetched_at=now)
    return data


@app.get("/api/dashboard/refresh")
def force_refresh():
    _cache.update(date=None, data=None, fetched_at=0.0)
    return get_dashboard()


@app.get("/health")
def health():
    return {"status": "ok"}
