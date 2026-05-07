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

import asyncio
import os
import json
import pathlib
import pytz
from datetime import date, datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

import threading

from aiohttp import web

from anthropic import Anthropic

# In-memory parlay cache — avoids re-running the full pipeline on every tab load.
_parlay_cache: dict = {
    "parlays": None,
    "generated_at": None,
    "timestamp": None,
    "lock": threading.Lock(),
}
_CACHE_TTL_MINUTES = 30

from src.utils.db import (
    get_scored_legs,
    get_todays_recommendations,
    get_training_analytics_data,
    get_training_dashboard_data,
    get_parlay_dashboard_data,
    get_ml_health_data,
    update_recommendation_analysis,
)
from src.engine.claude_agent import analyze_parlays

_ANTHROPIC_CLIENT = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"), timeout=60.0)

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
        est = pytz.timezone('America/New_York')
        current_time_est = datetime.now(est).strftime('%Y-%m-%d %H:%M:%S')
        return web.Response(
            text=json.dumps({'legs': legs, 'current_time_est': current_time_est}, default=str),
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


async def handle_dashboard(request: web.Request) -> web.Response:
    """Return parlay recommendation quality tracking for the dashboard view."""
    if not _check_auth(request):
        return web.Response(
            text=json.dumps({"error": "Unauthorized"}),
            content_type="application/json",
            status=401,
        )
    try:
        data = get_parlay_dashboard_data()
        return web.Response(
            text=json.dumps(data, default=str),
            content_type="application/json",
        )
    except Exception as exc:
        import traceback
        print(f"[handle_dashboard] ERROR: {exc}")
        traceback.print_exc()
        return web.Response(
            text=json.dumps({"error": str(exc)}),
            content_type="application/json",
            status=500,
        )


async def handle_training_analytics(request: web.Request) -> web.Response:
    """Return ML model health data for the Training tab."""
    if not _check_auth(request):
        return web.Response(
            text=json.dumps({"error": "Unauthorized"}),
            content_type="application/json",
            status=401,
        )
    try:
        data = get_ml_health_data()
        return web.Response(
            text=json.dumps(data, default=str),
            content_type="application/json",
        )
    except Exception as exc:
        return web.Response(
            text=json.dumps({"error": str(exc)}),
            content_type="application/json",
            status=500,
        )


async def handle_training_retrain(request: web.Request) -> web.Response:
    """POST /api/training/retrain — trigger ML model retraining (requires ADMIN_SECRET)."""
    if not _check_auth(request):
        return web.Response(
            text=json.dumps({"error": "Unauthorized"}),
            content_type="application/json",
            status=401,
        )
    try:
        body = await request.json()
    except Exception:
        body = {}

    secret = body.get("secret", "")
    expected_secret = os.getenv("ADMIN_SECRET", "change_me_in_railway")
    if secret != expected_secret:
        return web.Response(
            text=json.dumps({"error": "Invalid secret"}),
            content_type="application/json",
            status=403,
        )

    try:
        from scripts.train_ml_model import train

        def run_training():
            train(retrain=True)

        loop = asyncio.get_event_loop()
        asyncio.ensure_future(loop.run_in_executor(None, run_training))

        return web.Response(
            text=json.dumps({
                "status": "Training started",
                "message": "Check Railway logs for progress. Training takes 2-5 minutes.",
                "model_path": "models/leg_scorer_v2.pkl",
            }),
            content_type="application/json",
        )
    except Exception as exc:
        return web.Response(
            text=json.dumps({"error": str(exc)}),
            content_type="application/json",
            status=500,
        )


async def handle_analyze(request: web.Request) -> web.Response:
    """
    Call Claude to analyze a user-selected parlay from the web app.

    Request body:
        {"legs": [...], "combined_odds": "+1200"}

    Each leg must have: player_name, stat, line, direction, odds, coverage_pct,
    team, opponent. The endpoint bridges the web-app field names (line, odds)
    to the format analyze_parlays() expects (best_line, best_odds).

    Returns:
        {"analysis": "<Claude text>"}  or  {"error": "<message>"}
    """
    if not _check_auth(request):
        return web.Response(
            text=json.dumps({"error": "Unauthorized"}),
            content_type="application/json",
            status=401,
        )

    try:
        data = await request.json()
    except Exception:
        return web.Response(
            text=json.dumps({"error": "Invalid JSON body"}),
            content_type="application/json",
            status=400,
        )

    legs = data.get("legs", [])
    if not legs:
        return web.Response(
            text=json.dumps({"error": "No legs provided"}),
            content_type="application/json",
            status=400,
        )

    combined_odds = data.get("combined_odds", "+1000")

    # Bridge web-app field names → analyze_parlays() format
    parlay = {
        "legs": [
            {
                "player_name": leg.get("player_name", ""),
                "stat":        leg.get("stat", ""),
                "best_line":   leg.get("line"),
                "best_odds":   leg.get("odds", ""),
                "coverage_pct": leg.get("coverage_pct"),
                "team":        leg.get("team", ""),
                "opponent":    leg.get("opponent", ""),
                "position":    leg.get("position", ""),
                "direction":   leg.get("direction", "over"),
                "ev_per_unit": leg.get("ev_per_unit"),
                "trend_score": leg.get("trend_score"),
                "opponent_adjustment": leg.get("opponent_adjustment"),
            }
            for leg in legs
        ],
        "parlay_odds": combined_odds,
        "num_legs":    len(legs),
    }

    try:
        import asyncio
        loop = asyncio.get_event_loop()
        analysis = await loop.run_in_executor(None, analyze_parlays, [parlay])
    except Exception as exc:
        return web.Response(
            text=json.dumps({"error": str(exc)}),
            content_type="application/json",
            status=500,
        )

    return web.Response(
        text=json.dumps({"analysis": analysis}),
        content_type="application/json",
    )


async def handle_build_parlays(request: web.Request) -> web.Response:
    """
    Build parlays with smart in-memory caching to avoid re-running the pipeline
    on every tab load.

    Query params:
        refresh=true  - Force pipeline run, clear cache, return fresh results
        refresh=false - Return cached parlays if < 30 min old (default)
    """
    if not _check_auth(request):
        return web.Response(
            text=json.dumps({"error": "Unauthorized"}),
            content_type="application/json",
            status=401,
        )

    try:
        from src.engine.parlay_builder import build_hybrid_parlays

        force_refresh = request.rel_url.query.get("refresh", "false").lower() == "true"
        today = str(date.today())

        # Return cached result if still fresh and not a forced refresh
        with _parlay_cache["lock"]:
            cache_ts = _parlay_cache["timestamp"]
            cache_valid = (
                _parlay_cache["parlays"] is not None
                and cache_ts is not None
                and datetime.now() - cache_ts < timedelta(minutes=_CACHE_TTL_MINUTES)
            )
            if cache_valid and not force_refresh:
                age_min = (datetime.now() - cache_ts).total_seconds() / 60
                cached_parlays = _parlay_cache["parlays"] or []
                print(f"[build_parlays] Returning cached parlays (age: {age_min:.1f} min, {len(cached_parlays)} total, serving top 5)")
                return web.Response(
                    text=json.dumps({
                        "parlays": cached_parlays[:5],
                        "generated_at": _parlay_cache["generated_at"],
                    }, default=str),
                    content_type="application/json",
                )

        if force_refresh:
            print("[build_parlays] FORCE REFRESH — clearing cache and running pipeline")
            from main import run_pipeline
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, run_pipeline)
            print("[build_parlays] Pipeline complete — reading fresh legs from DB")
        else:
            print("[build_parlays] Cache miss — building parlays from DB legs")

        scored_legs = get_scored_legs(today)

        if not scored_legs:
            return web.Response(
                text=json.dumps({
                    "parlays": [],
                    "message": "No scored legs available for today",
                }),
                content_type="application/json",
            )

        et_tz = pytz.timezone("America/New_York")
        now_et = datetime.now(et_tz)
        cutoff = now_et - timedelta(minutes=5)

        upcoming_legs = []
        started_count = 0

        for leg in scored_legs:
            gst = leg.get("game_start_time")
            if not gst:
                upcoming_legs.append(leg)
                continue
            try:
                gt = datetime.strptime(str(gst), "%Y-%m-%d %H:%M:%S")
                if et_tz.localize(gt) > cutoff:
                    upcoming_legs.append(leg)
                else:
                    started_count += 1
            except Exception:
                upcoming_legs.append(leg)

        print(
            f"[build_parlays] {len(scored_legs)} scored legs → "
            f"{len(upcoming_legs)} upcoming (filtered {started_count} started)"
        )

        if len(upcoming_legs) < 4:
            return web.Response(
                text=json.dumps({
                    "parlays": [],
                    "message": (
                        f"Only {len(upcoming_legs)} upcoming legs available, "
                        "need at least 4 for parlays"
                    ),
                }),
                content_type="application/json",
            )

        qualifying_legs = []
        for leg in upcoming_legs:
            composite_score = leg.get("composite_score")
            # Fix: skip legs with None composite_score instead of comparing None >= 65
            if composite_score is None:
                continue
            if composite_score >= 65:
                qualifying_legs.append({
                    **leg,
                    "best_odds": leg.get("odds"),
                    "best_line": leg.get("line"),
                })

        print(f"[build_parlays] {len(qualifying_legs)} legs ≥65% ML score")

        if len(qualifying_legs) < 4:
            return web.Response(
                text=json.dumps({
                    "parlays": [],
                    "message": (
                        f"Only {len(qualifying_legs)} legs qualify (≥65% ML score), "
                        "need at least 4"
                    ),
                }),
                content_type="application/json",
            )

        parlays = build_hybrid_parlays(qualifying_legs, top_n=10)

        if not parlays:
            return web.Response(
                text=json.dumps({
                    "parlays": [],
                    "message": "No valid parlay combinations found in +1000 to +1500 range",
                }),
                content_type="application/json",
            )

        for parlay in parlays:
            raw_odds_str = parlay.get("parlay_odds", "+0")
            combined_odds = int(raw_odds_str.replace("+", ""))
            parlay["combined_odds"] = combined_odds

            legs = parlay.get("legs", [])
            win_prob = 1.0
            for leg in legs:
                coverage = (leg.get("composite_score") or 50) / 100
                win_prob *= coverage
            decimal_odds = (combined_odds / 100) + 1
            edge_pct = (win_prob * decimal_odds - 1) * 100
            parlay["win_probability"] = round(win_prob * 100, 1)
            parlay["edge_pct"] = round(edge_pct, 1)

        parlays.sort(key=lambda p: p.get("edge_pct", 0), reverse=True)

        for rank, parlay in enumerate(parlays, start=1):
            parlay["rank"] = rank

        from src.utils.sorting import sort_legs_by_game_time
        for parlay in parlays:
            parlay["legs"] = sort_legs_by_game_time(parlay.get("legs", []))

        top_5 = parlays[:5]
        generated_at = datetime.now(timezone.utc).isoformat()

        print(
            f"[build_parlays] Built {len(parlays)} parlays, saving ALL {len(parlays)}, returning top 5 "
            f"(edges: {[p['edge_pct'] for p in top_5]})"
        )

        # Cache ALL parlays for outcome tracking; UI receives top 5 at response time
        with _parlay_cache["lock"]:
            _parlay_cache["parlays"] = parlays
            _parlay_cache["generated_at"] = generated_at
            _parlay_cache["timestamp"] = datetime.now()
        print(f"[build_parlays] Cached {len(parlays)} parlays (expires in {_CACHE_TTL_MINUTES} min)")

        # Persist ALL parlays to DB for outcome tracking and ML training data
        from src.utils.db import save_parlay_recommendation
        run_time = datetime.now(timezone.utc)
        for parlay in parlays:
            try:
                save_parlay_recommendation({
                    "recommendation_date": date.today(),
                    "pipeline_run_time":   run_time,
                    "rank":                parlay["rank"],
                    "leg_odd_ids":         [leg["odd_id"] for leg in parlay.get("legs", []) if leg.get("odd_id")],
                    "combined_odds":       parlay.get("combined_odds", 0),
                    "win_probability":     parlay.get("win_probability", 0.0),
                    "edge_pct":            parlay.get("edge_pct", 0.0),
                })
            except Exception as _save_err:
                print(f"[build_parlays] Failed to save rank {parlay.get('rank')}: {_save_err}")

        return web.Response(
            text=json.dumps({
                "parlays": top_5,
                "generated_at": generated_at,
                "legs_analyzed": len(qualifying_legs),
                "total_combinations": len(parlays),
            }, default=str),
            content_type="application/json",
        )

    except Exception as exc:
        import traceback
        print(f"[build_parlays] Error: {exc}")
        traceback.print_exc()
        return web.Response(
            text=json.dumps({"error": str(exc)}),
            content_type="application/json",
            status=500,
        )


async def handle_recommendations(request: web.Request) -> web.Response:
    """Return today's pre-built parlay recommendations with hydrated leg details.

    Filters out legs whose games have already started (5-minute grace window)
    so stale morning pipeline results don't include in-progress games.
    """
    if not _check_auth(request):
        return web.Response(
            text=json.dumps({"error": "Unauthorized"}),
            content_type="application/json",
            status=401,
        )
    try:
        from datetime import datetime, timedelta
        import pytz

        recommendations = get_todays_recommendations()

        et_tz = pytz.timezone("America/New_York")
        now_et = datetime.now(et_tz)
        cutoff = now_et - timedelta(minutes=5)

        filtered = []
        for rec in recommendations:
            upcoming = []
            for leg in rec.get("legs", []):
                gst = leg.get("game_start_time")
                if not gst:
                    upcoming.append(leg)
                    continue
                try:
                    gt = datetime.strptime(str(gst), "%Y-%m-%d %H:%M:%S")
                    if et_tz.localize(gt) > cutoff:
                        upcoming.append(leg)
                except Exception:
                    upcoming.append(leg)
            if len(upcoming) >= 4:
                from src.utils.sorting import sort_legs_by_game_time
                rec["legs"] = sort_legs_by_game_time(upcoming)
                filtered.append(rec)

        total_in = len(recommendations)
        total_out = len(filtered)
        legs_out = sum(len(r["legs"]) for r in filtered)
        print(
            f"[handle_recommendations] {total_in} recs → {total_out} upcoming "
            f"({legs_out} legs after started-game filter)"
        )

        return web.Response(
            text=json.dumps({"recommendations": filtered}, default=str),
            content_type="application/json",
        )
    except Exception as exc:
        return web.Response(
            text=json.dumps({"error": str(exc)}),
            content_type="application/json",
            status=500,
        )


async def handle_regenerate_recommendations(request: web.Request) -> web.Response:
    """
    Re-run recommendation generation using today's already-scored legs.

    Fetches mlb_scored_legs for today (ET), filters to coverage >= 55%,
    calls generate_recommendations(), UPSERTs the results, then returns
    the freshly hydrated list from get_todays_recommendations().

    Returns: {"success": true, "recommendations": [...]}
    """
    if not _check_auth(request):
        return web.Response(
            text=json.dumps({"error": "Unauthorized"}),
            content_type="application/json",
            status=401,
        )

    try:
        from main import generate_recommendations
        from src.utils.db import save_parlay_recommendation

        today = datetime.now(_ET).date()
        legs = get_scored_legs(str(today))

        # Filter out games that have already started (5-min grace window)
        et_tz = pytz.timezone("America/New_York")
        now_et = datetime.now(et_tz)
        cutoff = now_et - timedelta(minutes=5)
        active_legs = []
        for leg in legs:
            gst = leg.get("game_start_time")
            if not gst:
                active_legs.append(leg)
                continue
            try:
                gt = datetime.strptime(gst, "%Y-%m-%d %H:%M:%S")
                if et_tz.localize(gt) > cutoff:
                    active_legs.append(leg)
            except Exception:
                active_legs.append(leg)

        print(f"[regenerate] {len(legs)} legs → {len(active_legs)} upcoming after filtering started games")

        if len(active_legs) < 4:
            return web.Response(
                text=json.dumps({
                    "success": True,
                    "recommendations": [],
                    "message": f"Not enough legs with upcoming games (need 4+, found {len(active_legs)})",
                }),
                content_type="application/json",
            )

        # Provide composite_score from coverage_pct so the parlay builder can
        # rank and filter legs without a full pipeline run.
        for leg in active_legs:
            leg["composite_score"] = leg.get("coverage_pct") or 50.0

        # Bridge DB field names → generate_recommendations() format
        qualifying_legs = [
            {**leg, "best_odds": leg.get("odds"), "best_line": leg.get("line")}
            for leg in active_legs
            if (leg.get("coverage_pct") or 0) >= 55
        ]

        loop = asyncio.get_event_loop()
        recommendations = await loop.run_in_executor(
            None, generate_recommendations, qualifying_legs
        )

        run_time = datetime.now(timezone.utc)
        for rank, rec in enumerate(recommendations, start=1):
            try:
                save_parlay_recommendation({
                    "recommendation_date": today,
                    "pipeline_run_time":   run_time,
                    "rank":                rank,
                    "leg_odd_ids":         [leg["odd_id"] for leg in rec["legs"]],
                    "combined_odds":       rec["combined_odds"],
                    "win_probability":     rec["win_probability"],
                    "edge_pct":            rec["edge_pct"],
                })
                print(f"[regenerate] Saved recommendation rank {rank}")
            except Exception as e:
                import traceback
                print(f"[regenerate] Failed to save rank {rank}: {e}")
                traceback.print_exc()

        fresh = get_todays_recommendations()
        return web.Response(
            text=json.dumps({"success": True, "recommendations": fresh}, default=str),
            content_type="application/json",
        )
    except Exception as exc:
        return web.Response(
            text=json.dumps({"error": str(exc)}),
            content_type="application/json",
            status=500,
        )


async def handle_refresh(request: web.Request) -> web.Response:
    """
    Trigger a fresh pipeline run: fetches SGO props for games starting >3h from
    now, rescores with the ML model, rebuilds parlays, and saves everything.

    Runs the full run_pipeline() in a thread executor with a starts_after cutoff
    of (now + 3 hours UTC) so we skip games that are too close to first pitch.
    The 3-hour window ensures coverage calculation and parlay building finish
    before any of the fetched games start.

    Returns:
        {"success": true, "legs_count": N, "recommendations_count": N, "timestamp": "..."}
    """
    if not _check_auth(request):
        return web.Response(
            text=json.dumps({"error": "Unauthorized"}),
            content_type="application/json",
            status=401,
        )

    try:
        from main import run_pipeline
        from src.utils.db import get_scored_legs, get_todays_recommendations
        from datetime import timezone, timedelta as _td

        et_tz = pytz.timezone("America/New_York")
        now_et = datetime.now(et_tz)

        # Only fetch games starting >3 hours from now to save API quota
        cutoff_utc = datetime.now(timezone.utc) + _td(hours=3)

        print(
            f"[refresh] Triggered at {now_et.strftime('%H:%M ET')} — "
            f"fetching games starting after {(now_et + _td(hours=3)).strftime('%H:%M ET')}"
        )

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, run_pipeline, cutoff_utc)

        # Count what was saved for this run date
        today_str = str(now_et.date())
        legs = get_scored_legs(today_str)
        recs = get_todays_recommendations()

        return web.Response(
            text=json.dumps({
                "success": True,
                "legs_count": len(legs),
                "recommendations_count": len(recs),
                "timestamp": now_et.isoformat(),
            }),
            content_type="application/json",
        )
    except Exception as exc:
        return web.Response(
            text=json.dumps({"error": str(exc)}),
            content_type="application/json",
            status=500,
        )


async def handle_train_model(request: web.Request) -> web.Response:
    """Trigger ML model training (admin only — requires ADMIN_SECRET)."""
    secret          = request.rel_url.query.get("secret", "")
    expected_secret = os.getenv("ADMIN_SECRET", "change_me_in_railway")

    if secret != expected_secret:
        return web.Response(
            text=json.dumps({"error": "Invalid secret"}),
            content_type="application/json",
            status=403,
        )

    try:
        from scripts.train_ml_model import train

        def run_training():
            train(retrain=True)

        loop = asyncio.get_event_loop()
        asyncio.ensure_future(loop.run_in_executor(None, run_training))

        return web.Response(
            text=json.dumps({
                "status":     "Training started",
                "message":    "Check Railway logs for progress. Training takes 2-5 minutes.",
                "model_path": "models/leg_scorer_v2.pkl",
            }),
            content_type="application/json",
        )
    except Exception as exc:
        return web.Response(
            text=json.dumps({"error": str(exc)}),
            content_type="application/json",
            status=500,
        )


async def handle_analyze_recommendation(request: web.Request) -> web.Response:
    """
    Generate and persist Claude analysis for a specific recommendation.

    Request body: {"recommendation_id": 123}

    Fetches the recommendation's hydrated legs from today's recommendations,
    calls Claude for a 2-3 sentence parlay analysis, saves it, and returns it.

    Returns: {"analysis": "..."}
    """
    if not _check_auth(request):
        return web.Response(
            text=json.dumps({"error": "Unauthorized"}),
            content_type="application/json",
            status=401,
        )

    try:
        body = await request.json()
    except Exception:
        return web.Response(
            text=json.dumps({"error": "Invalid JSON body"}),
            content_type="application/json",
            status=400,
        )

    recommendation_id = body.get("recommendation_id")
    parlay_direct = body.get("parlay")

    if parlay_direct:
        # Parlay data passed directly from frontend (dynamic build, no DB record)
        rec = parlay_direct
        recommendation_id = None
    elif recommendation_id:
        # Find the recommendation in today's DB list
        try:
            all_recs = get_todays_recommendations()
            rec = next((r for r in all_recs if r["id"] == int(recommendation_id)), None)
        except Exception as exc:
            return web.Response(
                text=json.dumps({"error": str(exc)}),
                content_type="application/json",
                status=500,
            )

        if not rec:
            return web.Response(
                text=json.dumps({"error": "Recommendation not found"}),
                content_type="application/json",
                status=404,
            )
    else:
        return web.Response(
            text=json.dumps({"error": "recommendation_id or parlay required"}),
            content_type="application/json",
            status=400,
        )

    # If analysis was already generated, return it immediately
    if rec.get("analysis"):
        return web.Response(
            text=json.dumps({"analysis": rec["analysis"]}),
            content_type="application/json",
        )

    # Build the prompt
    legs = rec.get("legs", [])
    legs_text = "\n".join(
        f"- {leg.get('player_name', 'Unknown')} ({leg.get('team', '?')}) "
        f"{leg.get('stat', '')} {leg.get('direction', 'over')} {leg.get('line', '?')} "
        f"@ {leg.get('odds', '?')} | coverage: {leg.get('coverage_pct', 'N/A')}%"
        for leg in legs
    )
    win_prob = rec.get("win_probability", 0.0)
    combined_odds = rec.get("combined_odds", 0)

    prompt = (
        "Analyze this MLB parlay recommendation. Explain why these legs work together, "
        "any correlation considerations, and overall strength.\n\n"
        f"Legs:\n{legs_text}\n\n"
        f"Combined odds: +{combined_odds}\n"
        f"Projected win probability: {win_prob:.1f}%\n\n"
        "Provide 2-3 sentences explaining why this is a good bet."
    )

    # Call Claude
    try:
        import asyncio

        def _claude_call() -> str:
            response = _ANTHROPIC_CLIENT.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text

        loop = asyncio.get_event_loop()
        analysis = await loop.run_in_executor(None, _claude_call)
    except Exception as exc:
        return web.Response(
            text=json.dumps({"error": f"Claude error: {exc}"}),
            content_type="application/json",
            status=500,
        )

    # Persist only when we have a DB-backed recommendation_id
    if recommendation_id:
        try:
            update_recommendation_analysis(int(recommendation_id), analysis)
        except Exception as exc:
            print(f"  [server] failed to save analysis for rec {recommendation_id}: {exc}")

    return web.Response(
        text=json.dumps({"analysis": analysis}),
        content_type="application/json",
    )


def create_app() -> web.Application:
    """Build and return the aiohttp Application object."""
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/legs", handle_legs)
    app.router.add_get("/api/health", handle_health)
    app.router.add_get("/api/dashboard", handle_dashboard)
    app.router.add_get("/api/training-analytics", handle_training_analytics)
    app.router.add_post("/api/analyze", handle_analyze)
    app.router.add_get("/api/build-parlays", handle_build_parlays)
    app.router.add_get("/api/recommendations", handle_recommendations)
    app.router.add_post("/api/recommendations/regenerate", handle_regenerate_recommendations)
    app.router.add_post("/api/analyze-recommendation", handle_analyze_recommendation)
    app.router.add_post("/api/refresh", handle_refresh)
    app.router.add_get("/api/train-model", handle_train_model)
    app.router.add_post("/api/training/retrain", handle_training_retrain)
    return app


_ET = ZoneInfo("America/New_York")
# Three daily pipeline runs (label, time-ET, function):
#   morning  9:00 AM — resolution only (run_morning_pipeline)
#   midday  12:00 PM — targeted refresh, no SGO (run_targeted_pipeline)
#   evening  5:30 PM — targeted refresh, no SGO (run_targeted_pipeline)
_PIPELINE_SCHEDULE = [
    (dtime(9,  0),  "morning"),   # 9:00 AM ET — resolution only
    (dtime(12, 0),  "midday"),    # 12:00 PM ET — fresh props + scoring
    (dtime(17, 30), "evening"),   # 5:30 PM ET — final lineup refresh
]

# Startup catch-up window: run if we restart within N minutes after a slot
_CATCHUP_WINDOW_MINS = 120


async def _pipeline_scheduler() -> None:
    """
    Background task that runs scheduled pipelines at 9 AM, 12 PM, and 5:30 PM ET.

    9 AM    → run_morning_pipeline()   (resolution only — no SGO)
    12 PM   → run_targeted_pipeline()  (targeted SGO fetch + lineup check)
    5:30 PM → run_targeted_pipeline()  (targeted SGO fetch + lineup check)

    On startup, if we're within _CATCHUP_WINDOW_MINS of a missed slot, runs
    that slot's pipeline immediately (Railway redeploy recovery).
    """
    from main import run_morning_pipeline, run_targeted_pipeline

    print("[scheduler] Morning pipeline scheduled at 9:00 AM ET (resolution only)")
    print("[scheduler] Midday pipeline scheduled at 12:00 PM ET (targeted SGO fetch + lineup check)")
    print("[scheduler] Evening pipeline scheduled at 5:30 PM ET (targeted SGO fetch + lineup check)")

    # ── Startup catch-up ──────────────────────────────────────────────────────
    now_startup = datetime.now(_ET)
    startup_total_mins = now_startup.hour * 60 + now_startup.minute

    for slot_time, slot_label in _PIPELINE_SCHEDULE:
        slot_mins = slot_time.hour * 60 + slot_time.minute
        if slot_mins <= startup_total_mins < slot_mins + _CATCHUP_WINDOW_MINS:
            print(
                f"[scheduler] Startup at {now_startup.strftime('%H:%M ET')} — "
                f"within {slot_label} catch-up window, running now..."
            )
            try:
                loop = asyncio.get_event_loop()
                if slot_label == "morning":
                    await loop.run_in_executor(None, run_morning_pipeline)
                else:
                    await loop.run_in_executor(None, run_targeted_pipeline)
                print(f"[scheduler] Startup catch-up ({slot_label}) complete")
            except Exception as exc:
                print(f"[scheduler] Startup catch-up ({slot_label}) error: {exc}")
            break  # only one catch-up per startup

    while True:
        now = datetime.now(_ET)
        today = now.date()

        # Find the next scheduled slot that hasn't passed yet
        next_run = None
        next_label = None
        for slot_time, slot_label in _PIPELINE_SCHEDULE:
            candidate = datetime.combine(today, slot_time, tzinfo=_ET)
            if candidate > now:
                next_run = candidate
                next_label = slot_label
                break

        # All today's slots passed — schedule first slot tomorrow
        if next_run is None:
            import datetime as _dt
            tomorrow = today + _dt.timedelta(days=1)
            next_run = datetime.combine(tomorrow, _PIPELINE_SCHEDULE[0][0], tzinfo=_ET)
            next_label = _PIPELINE_SCHEDULE[0][1]

        sleep_secs = (next_run - datetime.now(_ET)).total_seconds()
        print(
            f"[scheduler] next {next_label} pipeline at "
            f"{next_run.strftime('%Y-%m-%d %H:%M ET')} "
            f"(in {sleep_secs / 3600:.1f}h)"
        )
        await asyncio.sleep(max(sleep_secs, 1))

        print(f"[scheduler] running {next_label} pipeline at {datetime.now(_ET).strftime('%H:%M ET')}")
        try:
            loop = asyncio.get_event_loop()
            if next_label == "morning":
                await loop.run_in_executor(None, run_morning_pipeline)
            else:
                await loop.run_in_executor(None, run_targeted_pipeline)
        except Exception as exc:
            print(f"[scheduler] {next_label} pipeline error: {exc}")


async def start_server() -> web.AppRunner:
    """
    Start the aiohttp server and pipeline scheduler.

    Returns the AppRunner so the caller can clean it up on shutdown.
    """
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", _PORT)
    await site.start()
    print(f"[web] Server started on port {_PORT}")

    # Start the background pipeline scheduler
    asyncio.ensure_future(_pipeline_scheduler())
    print("[web] Pipeline scheduler started (9 AM resolution, 12 PM + 5:30 PM full pipeline)")

    return runner


if __name__ == "__main__":
    async def _main() -> None:
        runner = await start_server()
        try:
            await asyncio.Event().wait()  # run until interrupted
        finally:
            await runner.cleanup()

    asyncio.run(_main())
