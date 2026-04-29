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
from datetime import date, datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

from aiohttp import web

from anthropic import Anthropic

from src.utils.db import (
    get_scored_legs,
    get_todays_recommendations,
    get_training_analytics_data,
    get_training_dashboard_data,
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
    """Return calibration and performance analytics for the dashboard view."""
    if not _check_auth(request):
        return web.Response(
            text=json.dumps({"error": "Unauthorized"}),
            content_type="application/json",
            status=401,
        )
    try:
        data = get_training_dashboard_data()
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


async def handle_training_analytics(request: web.Request) -> web.Response:
    """Return training data analytics for the Training Data tab."""
    if not _check_auth(request):
        return web.Response(
            text=json.dumps({"error": "Unauthorized"}),
            content_type="application/json",
            status=401,
        )
    try:
        data = get_training_analytics_data()
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


async def handle_recommendations(request: web.Request) -> web.Response:
    """Return today's pre-built parlay recommendations with hydrated leg details."""
    if not _check_auth(request):
        return web.Response(
            text=json.dumps({"error": "Unauthorized"}),
            content_type="application/json",
            status=401,
        )
    try:
        recommendations = get_todays_recommendations()
        return web.Response(
            text=json.dumps({"recommendations": recommendations}, default=str),
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

        run_time = datetime.now()
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
    if not recommendation_id:
        return web.Response(
            text=json.dumps({"error": "recommendation_id required"}),
            content_type="application/json",
            status=400,
        )

    # Find the recommendation in today's list
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

    # Persist and return
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
    app.router.add_get("/api/recommendations", handle_recommendations)
    app.router.add_post("/api/recommendations/regenerate", handle_regenerate_recommendations)
    app.router.add_post("/api/analyze-recommendation", handle_analyze_recommendation)
    app.router.add_get("/api/train-model", handle_train_model)
    return app


_ET = ZoneInfo("America/New_York")
_PIPELINE_SCHEDULE = [
    dtime(9, 0),    # 9:00 AM ET
    dtime(12, 0),   # 12:00 PM ET
    dtime(17, 30),  # 5:30 PM ET
]


async def _pipeline_scheduler() -> None:
    """
    Background task that runs run_pipeline() at 9 AM, 12 PM, and 5:30 PM ET.

    Computes the next scheduled time on each iteration, sleeps until then,
    then runs the pipeline in a thread executor (it's synchronous/blocking).
    """
    from main import run_pipeline

    while True:
        now = datetime.now(_ET)
        today = now.date()

        # Find the next scheduled time today that hasn't passed yet
        next_run = None
        for t in _PIPELINE_SCHEDULE:
            candidate = datetime.combine(today, t, tzinfo=_ET)
            if candidate > now:
                next_run = candidate
                break

        # All today's slots passed — schedule first slot tomorrow
        if next_run is None:
            import datetime as _dt
            tomorrow = today + _dt.timedelta(days=1)
            next_run = datetime.combine(tomorrow, _PIPELINE_SCHEDULE[0], tzinfo=_ET)

        sleep_secs = (next_run - datetime.now(_ET)).total_seconds()
        print(
            f"[scheduler] next pipeline run at "
            f"{next_run.strftime('%Y-%m-%d %H:%M ET')} "
            f"(in {sleep_secs / 3600:.1f}h)"
        )
        await asyncio.sleep(max(sleep_secs, 1))

        print(f"[scheduler] running pipeline at {datetime.now(_ET).strftime('%H:%M ET')}")
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, run_pipeline)
        except Exception as exc:
            print(f"[scheduler] pipeline error: {exc}")


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
    print("[web] Pipeline scheduler started (9:00 AM / 12:00 PM / 5:30 PM ET)")

    return runner


if __name__ == "__main__":
    async def _main() -> None:
        runner = await start_server()
        try:
            await asyncio.Event().wait()  # run until interrupted
        finally:
            await runner.cleanup()

    asyncio.run(_main())
