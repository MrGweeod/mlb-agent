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
import os
import pathlib
import time
from datetime import date

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from dashboard_api.shape import build_dashboard
from dashboard_api.db import get_legs_by_odd_ids, save_dashboard_parlay
from src.utils.odds_math import american_to_decimal

_STATIC_DIR = pathlib.Path(__file__).parent / "static"

app = FastAPI(title="MLB Slate Explorer API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # single-user tool
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

_WEB_APP_PASSWORD = os.getenv("WEB_APP_PASSWORD", "")
_PITCHER_POS = frozenset({"SP", "RP", "P"})


def _check_auth(request: Request) -> bool:
    """Mirrors src/web/server.py's _check_auth exactly: grant only on a
    precise password match, never on "anything but 401" (Session 18
    auth-hardening lesson, ARCHITECTURE_DECISIONS.md §22)."""
    if not _WEB_APP_PASSWORD:
        return True  # no password configured — open access

    qs_pw = request.query_params.get("password", "")
    if qs_pw and qs_pw == _WEB_APP_PASSWORD:
        return True

    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer ") and auth[7:] == _WEB_APP_PASSWORD:
        return True

    return False

_CACHE_TTL_SECONDS = 30 * 60
_cache: dict = {"date": None, "data": None, "fetched_at": 0.0}


@app.get("/api/dashboard")
def get_dashboard(request: Request):
    if not _check_auth(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
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
def force_refresh(request: Request):
    if not _check_auth(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    _cache.update(date=None, data=None, fetched_at=0.0)
    return get_dashboard(request)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/dashboard/parlay")
async def post_dashboard_parlay(request: Request):
    """
    POST /api/dashboard/parlay — log a hand-picked parlay from the Slate
    Explorer UI. Body: {"odd_ids": ["id1", ...]} (4-6 entries).

    Never trusts line/odds/coverage from the client — every leg is
    re-fetched fresh from mlb_scored_legs by odd_id before validation.
    Saved with source='dashboard_pick' (distinct from /manual's
    'manual_pick' — see SUPABASE_SCHEMA_REFERENCE.md).
    """
    if not _check_auth(request):
        return JSONResponse(status_code=401, content={"success": False, "error": "Unauthorized"})

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"success": False, "error": "Invalid JSON body"})

    odd_ids = body.get("odd_ids", [])
    if not isinstance(odd_ids, list) or len(odd_ids) < 4 or len(odd_ids) > 6:
        return JSONResponse(status_code=400, content={"success": False, "error": "must select 4-6 legs"})

    odd_ids = [str(x) for x in odd_ids]
    if len(odd_ids) != len(set(odd_ids)):
        return JSONResponse(status_code=400, content={"success": False, "error": "duplicate odd_ids in submission"})

    run_date = date.today().isoformat()

    try:
        all_legs = get_legs_by_odd_ids(run_date, odd_ids)
    except Exception as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": f"DB error fetching legs: {exc}"})

    found_ids = {str(l.get("odd_id", "")) for l in all_legs}
    missing = [oid for oid in odd_ids if oid not in found_ids]
    if missing:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": f"odd_ids not found for {run_date}: {missing}"},
        )

    # Validate: no duplicate batter (player_id)
    batter_pids: dict = {}
    for leg in all_legs:
        pos = leg.get("position", "")
        pid = leg.get("player_id") or leg.get("player_name", "")
        if pos not in _PITCHER_POS:
            if pid in batter_pids:
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "error": f"duplicate batter in selection: {leg.get('player_name')}"},
                )
            batter_pids[pid] = True

    # Validate: max 2 legs per game_pk
    game_counts: dict = {}
    for leg in all_legs:
        gk = leg.get("game_pk") or leg.get("team", "")
        game_counts[gk] = game_counts.get(gk, 0) + 1
        if game_counts[gk] > 2:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": f"more than 2 legs from game {gk}"},
            )

    # Compute combined American odds
    combined_dec = 1.0
    for leg in all_legs:
        odds_raw = leg.get("best_odds") or leg.get("odds")
        if odds_raw is None:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": f"missing odds for leg {leg.get('odd_id')}"},
            )
        combined_dec *= american_to_decimal(str(odds_raw))

    combined_odds = int((combined_dec - 1) * 100)
    meets_floor = combined_odds >= 400

    try:
        parlay_id = save_dashboard_parlay(all_legs, run_date, combined_odds)
    except Exception as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": f"DB error saving parlay: {exc}"})

    return {
        "success": True,
        "parlay_id": parlay_id,
        "combined_odds": combined_odds,
        "meets_floor": meets_floor,
        "legs": len(all_legs),
    }


# Mounted last so it only catches paths not matched by the explicit API
# routes above (e.g. "/", "/support.js", "/styles.css") — html=True serves
# index.html for "/", and index.html's own "./support.js"/"styles.css"
# references resolve correctly since everything is served flat from here.
app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
