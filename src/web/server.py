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

# In-memory parlay cache — avoids re-running the full pipeline on every tab load.
_parlay_cache: dict = {
    "parlays": None,
    "generated_at": None,
    "timestamp": None,
    "lock": threading.Lock(),
}

# In-memory regenerate job status — single-process deployment (railway.toml:
# startCommand = "python src/web/server.py"), so a plain dict is safe.
# status: "idle" | "running" | "success" | "failed"
_regen_job: dict = {
    "status": "idle",
    "error": None,
    "started_at": None,
    "finished_at": None,
    "lock": threading.Lock(),
}
_CACHE_TTL_MINUTES = 30

from src.utils.db import (
    get_scored_legs,
    get_manual_legs,
    get_todays_recommendations,
    get_training_analytics_data,
    get_training_dashboard_data,
    get_parlay_dashboard_data,
    get_ml_health_data,
    get_recommendation_history,
    save_parlay_recommendations_v2,
)

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
        # Only show legs with usable odds in the UI (-300 to +300).
        # The parlay builder already filters by odds during construction; this
        # keeps the Legs tab from displaying -1000+ garbage props.
        filtered_legs = []
        for leg in legs:
            try:
                odds_int = int(float(leg.get("odds") or 0))
            except (TypeError, ValueError):
                continue
            if -300 <= odds_int <= 300:
                filtered_legs.append(leg)
        est = pytz.timezone('America/New_York')
        current_time_est = datetime.now(est).strftime('%Y-%m-%d %H:%M:%S')
        return web.Response(
            text=json.dumps({'legs': filtered_legs, 'current_time_est': current_time_est}, default=str),
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
        cutoff = now_et + timedelta(minutes=15)

        upcoming_legs = []
        started_count = 0
        null_count = 0

        for leg in scored_legs:
            gst = leg.get("game_start_time")
            if not gst:
                null_count += 1
                continue  # fail-closed: missing time = exclude
            try:
                gt = datetime.strptime(str(gst), "%Y-%m-%d %H:%M:%S")
                if et_tz.localize(gt) > cutoff:
                    upcoming_legs.append(leg)
                else:
                    started_count += 1
            except Exception:
                null_count += 1
                continue  # fail-closed: unparseable time = exclude

        print(
            f"[build_parlays] {len(scored_legs)} scored legs → "
            f"{len(upcoming_legs)} upcoming (filtered {started_count} started, {null_count} missing time)"
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

        anchor_legs = []
        swing_legs  = []
        for leg in upcoming_legs:
            composite_score = leg.get("composite_score")
            if composite_score is None:
                continue
            leg_type = leg.get("leg_type", "")
            enriched = {
                **leg,
                "best_odds": leg.get("odds"),
                "best_line": leg.get("line"),
            }
            if leg_type == "anchor" and composite_score >= 75:
                anchor_legs.append(enriched)
            elif leg_type == "swing" and composite_score >= 55:
                swing_legs.append(enriched)

        print(f"[build_parlays] {len(anchor_legs)} anchor + {len(swing_legs)} swing legs")

        if len(anchor_legs) < 3 or len(swing_legs) < 2:
            return web.Response(
                text=json.dumps({
                    "parlays": [],
                    "message": (
                        f"Only {len(anchor_legs)} anchor + {len(swing_legs)} swing legs qualify, "
                        "need at least 3 anchor + 2 swing"
                    ),
                }),
                content_type="application/json",
            )

        parlays = build_hybrid_parlays(anchor_legs, swing_legs, top_n=10)

        if not parlays:
            return web.Response(
                text=json.dumps({
                    "parlays": [],
                    "message": "No valid parlay combinations found in +900 to +1100 range",
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
                "legs_analyzed": len(anchor_legs) + len(swing_legs),
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
    """Return today's parlay recommendations (latest batch) from v2 schema."""
    if not _check_auth(request):
        return web.Response(
            text=json.dumps({"error": "Unauthorized"}),
            content_type="application/json",
            status=401,
        )
    try:
        from src.utils.db import get_conn

        today = str(datetime.now(_ET).date())

        conn = get_conn()
        cur = conn.cursor()

        # Get latest batch_id for today — order by MAX(created_at) DESC so v2 batches
        # (format YYYY-MM-DD_HH:MM:SS) aren't shadowed by old v1 batches (v1_YYYY-MM-DD_N)
        # which sort lexicographically later because 'v' > any digit.
        print(f"[recommendations] Querying for run_date={today}")
        cur.execute(
            """
            SELECT DISTINCT batch_id, source, MAX(created_at) AS created_at
            FROM mlb_parlay_recommendations_v2
            WHERE run_date = %s
            GROUP BY batch_id, source
            ORDER BY MAX(created_at) DESC
            LIMIT 1
            """,
            (today,),
        )
        batch_row = cur.fetchone()

        if not batch_row:
            cur.close()
            conn.close()
            return web.Response(
                text=json.dumps({"parlays": [], "generated_at": None, "source": None}),
                content_type="application/json",
            )

        batch_id = batch_row["batch_id"]
        source = batch_row["source"]
        generated_at = batch_row["created_at"]

        # Get ALL parlays from this batch (alias to match frontend field names)
        cur.execute(
            """
            SELECT id, rank,
                   total_odds AS combined_odds,
                   avg_coverage,
                   num_legs,
                   outcome,
                   created_at
            FROM mlb_parlay_recommendations_v2
            WHERE batch_id = %s
            ORDER BY rank
            """,
            (batch_id,),
        )
        parlays = [dict(r) for r in cur.fetchall()]

        # Hydrate legs for each parlay (alias coverage → coverage_pct)
        for parlay in parlays:
            parlay["edge_pct"] = 0.0
            cur.execute(
                """
                SELECT player_id, player_name, team, stat, line,
                       direction, odds, coverage AS coverage_pct, ev, outcome
                FROM mlb_parlay_legs_v2
                WHERE parlay_id = %s
                ORDER BY id
                """,
                (parlay["id"],),
            )
            parlay["legs"] = [dict(r) for r in cur.fetchall()]
            # Compute win_probability as product of leg coverages
            win_prob = 1.0
            for leg in parlay["legs"]:
                cov_pct = leg.get("coverage_pct") or 50
                cov = float(cov_pct) / 100.0
                win_prob *= cov
            parlay["win_probability"] = round(win_prob * 100, 1)

        cur.close()
        conn.close()

        print(f"[recommendations] Returning {len(parlays)} parlays from batch {batch_id}")

        return web.Response(
            text=json.dumps({
                "parlays": parlays,
                "generated_at": generated_at,
                "source": source,
            }, default=str),
            content_type="application/json",
        )
    except Exception as exc:
        print(f"[ERROR] handle_recommendations failed: {exc}")
        import traceback
        traceback.print_exc()
        return web.Response(
            text=json.dumps({"error": str(exc)}),
            content_type="application/json",
            status=500,
        )


async def handle_recommendation_history(request: web.Request) -> web.Response:
    """
    Return all parlay recommendation batches for a given date.

    URL param: date (YYYY-MM-DD). Defaults to today.

    Returns an array of batches (newest first), each with full parlay and leg
    details — used by the Picks tab to display all daily recommendations, not
    just the latest batch.
    """
    if not _check_auth(request):
        return web.Response(
            text=json.dumps({"error": "Unauthorized"}),
            content_type="application/json",
            status=401,
        )
    date_param = request.rel_url.query.get("date", str(date.today()))
    try:
        history = get_recommendation_history(date_param)
        print(f"[history] Fetched {len(history)} batches for {date_param}")
        return web.Response(
            text=json.dumps(history, default=str),
            content_type="application/json",
        )
    except Exception as exc:
        print(f"[ERROR] handle_recommendation_history failed: {exc}")
        import traceback
        traceback.print_exc()
        return web.Response(
            text=json.dumps({"error": str(exc)}),
            content_type="application/json",
            status=500,
        )


def _fetch_missing_game_times(legs: list[dict], run_date: str) -> list[dict]:
    """
    Fallback: for legs with NULL game_start_time, fetch from MLB-StatsAPI on-the-fly.
    Tries game_pk lookup first; always also runs schedule lookup as backup.
    Persists filled times to the database so future requests don't re-fetch.
    """
    import statsapi
    from src.utils.db import get_conn

    missing = [leg for leg in legs if not leg.get("game_start_time")]
    if not missing:
        return legs

    has_pk = sum(1 for leg in missing if leg.get("game_pk"))
    print(f"[_fetch_missing_game_times] {len(missing)}/{len(legs)} legs missing time; {has_pk} have game_pk, {len(missing) - has_pk} do not")

    et_tz = pytz.timezone("America/New_York")
    gk_to_time: dict[int, str] = {}

    # Strategy 1: fetch by game_pk (fast, exact)
    unique_pks = {leg["game_pk"] for leg in missing if leg.get("game_pk")}
    print(f"[_fetch_missing_game_times] Strategy 1: fetching {len(unique_pks)} unique game_pks via statsapi.get")
    for gk in unique_pks:
        try:
            game_data = statsapi.get("game", {"gamePk": gk})
            raw = game_data["gameData"]["datetime"]["dateTime"]
            utc_dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            gk_to_time[gk] = utc_dt.astimezone(et_tz).strftime("%Y-%m-%d %H:%M:%S")
        except Exception as e:
            print(f"[_fetch_missing_game_times] Warning: could not fetch time for game_pk {gk}: {e}")
    print(f"[_fetch_missing_game_times] Strategy 1 resolved {len(gk_to_time)}/{len(unique_pks)} game_pks")

    # Strategy 2: schedule lookup by team name — ALWAYS run as a reliable backup
    team_to_time: dict[str, str] = {}
    try:
        schedule = statsapi.schedule(date=run_date)
        print(f"[_fetch_missing_game_times] Strategy 2: schedule returned {len(schedule)} games for {run_date}")
        for game in schedule:
            raw = game.get("game_datetime", "")
            if not raw:
                continue
            try:
                utc_dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                gst = utc_dt.astimezone(et_tz).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                continue
            for key in ("away_name", "home_name"):
                name = game.get(key, "")
                if name:
                    team_to_time[name] = gst
        print(f"[_fetch_missing_game_times] Strategy 2 built {len(team_to_time)} team→time mappings")
    except Exception as e:
        print(f"[_fetch_missing_game_times] Warning: schedule fallback failed: {e}")

    # Fill in-memory and track which legs got updated for DB persistence
    filled = 0
    db_updates: list[dict] = []  # legs that got a new game_start_time
    for leg in missing:
        gk = leg.get("game_pk")
        new_time: str | None = None
        if gk and gk in gk_to_time:
            new_time = gk_to_time[gk]
        else:
            team = leg.get("team", "") or ""
            if team in team_to_time:
                new_time = team_to_time[team]
            else:
                # partial match
                for api_team, gst in team_to_time.items():
                    if team and (team in api_team or api_team in team):
                        new_time = gst
                        break

        if new_time:
            leg["game_start_time"] = new_time
            db_updates.append(leg)
            filled += 1
        else:
            print(f"[_fetch_missing_game_times] No time found for team={leg.get('team')!r} game_pk={leg.get('game_pk')}")

    print(f"[_fetch_missing_game_times] Filled {filled}/{len(missing)} missing game times")

    # Persist to DB so repeated calls (and future requests) don't re-fetch
    if db_updates:
        try:
            conn = get_conn()
            cur = conn.cursor()
            for leg in db_updates:
                cur.execute(
                    """
                    UPDATE mlb_scored_legs
                    SET game_start_time = %s
                    WHERE run_date = %s
                      AND player_name = %s
                      AND stat = %s
                      AND direction = %s
                    """,
                    (leg["game_start_time"], run_date, leg["player_name"], leg["stat"], leg["direction"]),
                )
            conn.commit()
            cur.close()
            conn.close()
            print(f"[_fetch_missing_game_times] Persisted {len(db_updates)} game times to database")
        except Exception as e:
            print(f"[_fetch_missing_game_times] Warning: DB persist failed: {e}")

    return legs


async def handle_regenerate_recommendations(request: web.Request) -> web.Response:
    """
    Re-run the targeted pipeline: fetches fresh SGO odds for today's legs,
    updates composite_scores, and rebuilds parlay recommendations.

    Delegates entirely to run_targeted_pipeline() and returns immediately.
    Check Railway logs for progress.

    Returns: {"status": "triggered", "message": "..."}
    """
    if not _check_auth(request):
        return web.Response(
            text=json.dumps({"error": "Unauthorized"}),
            content_type="application/json",
            status=401,
        )

    try:
        from main import run_full_refresh_pipeline

        print("[regenerate] Triggering full fresh pipeline run (fresh SGO fetch + re-score)")

        with _regen_job["lock"]:
            _regen_job["status"] = "running"
            _regen_job["error"] = None
            _regen_job["started_at"] = datetime.now(timezone.utc).isoformat()
            _regen_job["finished_at"] = None

        def _run():
            try:
                run_full_refresh_pipeline(source="manual")
                print("[regenerate] Pipeline completed successfully")
                with _regen_job["lock"]:
                    _regen_job["status"] = "success"
                    _regen_job["finished_at"] = datetime.now(timezone.utc).isoformat()
            except Exception as _e:
                import traceback
                print(f"[regenerate] Pipeline error: {_e}")
                traceback.print_exc()
                with _regen_job["lock"]:
                    _regen_job["status"] = "failed"
                    _regen_job["error"] = str(_e)
                    _regen_job["finished_at"] = datetime.now(timezone.utc).isoformat()

        threading.Thread(target=_run, daemon=True).start()

        return web.Response(
            text=json.dumps({
                "status": "triggered",
                "message": "Fresh pipeline run started. Check Railway logs for progress.",
            }),
            content_type="application/json",
        )
    except Exception as exc:
        import traceback as _tb
        print(f"[regenerate] UNHANDLED ERROR: {exc}\n{_tb.format_exc()}")
        with _regen_job["lock"]:
            _regen_job["status"] = "failed"
            _regen_job["error"] = str(exc)
            _regen_job["finished_at"] = datetime.now(timezone.utc).isoformat()
        return web.Response(
            text=json.dumps({"error": str(exc)}),
            content_type="application/json",
            status=500,
        )


async def handle_regenerate_status(request: web.Request) -> web.Response:
    """Return the current status of the most recent regenerate pipeline run."""
    if not _check_auth(request):
        return web.Response(
            text=json.dumps({"error": "Unauthorized"}),
            content_type="application/json",
            status=401,
        )

    with _regen_job["lock"]:
        payload = {
            "status": _regen_job["status"],
            "error": _regen_job["error"],
            "started_at": _regen_job["started_at"],
            "finished_at": _regen_job["finished_at"],
        }

    return web.Response(
        text=json.dumps(payload),
        content_type="application/json",
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



async def handle_run_pipeline(request: web.Request) -> web.Response:
    """
    Manual trigger for the targeted refresh pipeline (run_targeted_pipeline).
    POST /api/admin/run_pipeline

    Runs in a background thread so this returns immediately.
    Check Railway logs for pipeline progress.
    """
    if not _check_auth(request):
        return web.Response(
            text=json.dumps({"error": "Unauthorized"}),
            content_type="application/json",
            status=401,
        )

    try:
        from main import run_targeted_pipeline
        import threading

        triggered_at = datetime.now(ZoneInfo("America/New_York")).isoformat()
        print(f"[admin] Manual pipeline triggered at {triggered_at}")

        def _run():
            try:
                run_targeted_pipeline(source="manual")
                print("[admin] Pipeline completed successfully")
            except Exception as _e:
                import traceback
                print(f"[admin] Pipeline error: {_e}")
                traceback.print_exc()

        threading.Thread(target=_run, daemon=True).start()

        return web.Response(
            text=json.dumps({
                "status": "triggered",
                "message": "Pipeline started in background. Check Railway logs for progress.",
                "timestamp": triggered_at,
            }),
            content_type="application/json",
        )
    except Exception as exc:
        return web.Response(
            text=json.dumps({"status": "error", "message": str(exc)}),
            content_type="application/json",
            status=500,
        )


async def handle_run_full_pipeline(request: web.Request) -> web.Response:
    """
    Manual trigger for the full morning pipeline (run_morning_pipeline).
    POST /api/admin/run_full_pipeline

    Fetches fresh props from SGO, runs full coverage calculation, enrichment,
    scoring, and parlay building. Runs in a background thread and returns immediately.
    Check Railway logs for pipeline progress.
    """
    if not _check_auth(request):
        return web.Response(
            text=json.dumps({"error": "Unauthorized"}),
            content_type="application/json",
            status=401,
        )

    try:
        from main import run_morning_pipeline
        import threading

        triggered_at = datetime.now(ZoneInfo("America/New_York")).isoformat()
        print(f"[admin] Manual full pipeline triggered at {triggered_at}")

        def _run():
            try:
                run_morning_pipeline(source="manual")
                print("[admin] Full pipeline completed successfully")
            except Exception as _e:
                import traceback
                print(f"[admin] Full pipeline error: {_e}")
                traceback.print_exc()

        threading.Thread(target=_run, daemon=True).start()

        return web.Response(
            text=json.dumps({
                "status": "triggered",
                "message": "Full pipeline started in background. Check Railway logs for progress.",
                "timestamp": triggered_at,
            }),
            content_type="application/json",
        )
    except Exception as exc:
        return web.Response(
            text=json.dumps({"status": "error", "message": str(exc)}),
            content_type="application/json",
            status=500,
        )


async def handle_manual(request: web.Request) -> web.Response:
    """Serve the manual parlay builder HTML without auth (page handles its own password prompt)."""
    page = _STATIC_DIR / "manual.html"
    if not page.exists():
        return web.Response(text="Manual dashboard not found", status=404)
    return web.Response(
        body=page.read_bytes(),
        content_type="text/html",
        charset="utf-8",
    )


async def handle_manual_legs(request: web.Request) -> web.Response:
    """
    GET /api/manual/legs?date=YYYY-MM-DD

    Return all scored legs for the requested date, enriched with pitcher
    vulnerability data where available. Requires auth.
    """
    if not _check_auth(request):
        return web.Response(
            text=json.dumps({"error": "Unauthorized"}),
            content_type="application/json",
            status=401,
        )
    run_date = request.rel_url.query.get("date", "")
    if not run_date:
        return web.Response(
            text=json.dumps({"error": "Missing required query param: date"}),
            content_type="application/json",
            status=400,
        )
    try:
        legs = await asyncio.get_event_loop().run_in_executor(
            None, get_manual_legs, run_date
        )
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


async def handle_manual_parlay(request: web.Request) -> web.Response:
    """
    POST /api/manual/parlay

    Body JSON: {"run_date": "YYYY-MM-DD", "odd_ids": ["id1", ...]}

    Validates legs server-side, computes combined odds, saves via
    save_parlay_recommendations_v2 with source='manual_pick'.
    Requires auth.
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

    run_date = body.get("run_date", "")
    odd_ids  = body.get("odd_ids", [])

    if not run_date:
        return web.Response(
            text=json.dumps({"error": "Missing run_date"}),
            content_type="application/json",
            status=400,
        )
    if not isinstance(odd_ids, list) or len(odd_ids) < 4 or len(odd_ids) > 6:
        return web.Response(
            text=json.dumps({"error": "odd_ids must be a list of 4–6 items"}),
            content_type="application/json",
            status=400,
        )
    if len(odd_ids) != len(set(str(x) for x in odd_ids)):
        return web.Response(
            text=json.dumps({"error": "Duplicate odd_ids in submission"}),
            content_type="application/json",
            status=400,
        )

    # Re-fetch leg data server-side to prevent client-side tampering
    try:
        all_legs = await asyncio.get_event_loop().run_in_executor(
            None, get_manual_legs, run_date
        )
    except Exception as exc:
        return web.Response(
            text=json.dumps({"error": f"DB error fetching legs: {exc}"}),
            content_type="application/json",
            status=500,
        )

    odd_id_set = {str(x) for x in odd_ids}
    selected = [l for l in all_legs if str(l.get("odd_id", "")) in odd_id_set]

    if len(selected) != len(odd_ids):
        found = {str(l.get("odd_id", "")) for l in selected}
        missing = odd_id_set - found
        return web.Response(
            text=json.dumps({"error": f"odd_ids not found for date {run_date}: {sorted(missing)}"}),
            content_type="application/json",
            status=400,
        )

    # Validate: no duplicate batter player_id
    _PITCHER_POS = frozenset({"SP", "RP", "P"})
    batter_pids: dict = {}
    for leg in selected:
        pos = leg.get("position", "")
        pid = leg.get("player_id") or leg.get("player_name", "")
        if pos not in _PITCHER_POS:
            if pid in batter_pids:
                return web.Response(
                    text=json.dumps({"error": f"Duplicate batter player in selection: {leg.get('player_name')}"}),
                    content_type="application/json",
                    status=400,
                )
            batter_pids[pid] = True

    # Validate: max 2 legs per game_pk
    game_counts: dict = {}
    for leg in selected:
        gk = leg.get("game_pk") or leg.get("team", "")
        game_counts[gk] = game_counts.get(gk, 0) + 1
        if game_counts[gk] > 2:
            return web.Response(
                text=json.dumps({"error": f"More than 2 legs from game {gk}"}),
                content_type="application/json",
                status=400,
            )

    # Compute combined American odds
    from src.utils.odds_math import american_to_decimal
    combined_dec = 1.0
    for leg in selected:
        odds_raw = leg.get("best_odds") or leg.get("odds")
        if odds_raw is None:
            return web.Response(
                text=json.dumps({"error": f"Missing odds for leg {leg.get('odd_id')}"}),
                content_type="application/json",
                status=400,
            )
        combined_dec *= american_to_decimal(str(odds_raw))

    combined_odds = int((combined_dec - 1) * 100)
    meets_floor = combined_odds >= 400

    rec = {
        "legs":         selected,
        "combined_odds": combined_odds,
        "edge_pct":     None,
    }

    try:
        batch_id = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: save_parlay_recommendations_v2([rec], run_date, source="manual_pick"),
        )
    except Exception as exc:
        return web.Response(
            text=json.dumps({"error": f"DB error saving parlay: {exc}"}),
            content_type="application/json",
            status=500,
        )

    return web.Response(
        text=json.dumps({
            "status": "saved",
            "batch_id": batch_id,
            "combined_odds": f"+{combined_odds}",
            "num_legs": len(selected),
            "meets_floor": meets_floor,
        }),
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
    app.router.add_get("/api/build-parlays", handle_build_parlays)
    app.router.add_get("/api/recommendations", handle_recommendations)
    app.router.add_get("/api/recommendations/history", handle_recommendation_history)
    app.router.add_post("/api/recommendations/regenerate", handle_regenerate_recommendations)
    app.router.add_get("/api/recommendations/regenerate/status", handle_regenerate_status)
    app.router.add_post("/api/refresh", handle_refresh)
    app.router.add_get("/api/train-model", handle_train_model)
    app.router.add_post("/api/training/retrain", handle_training_retrain)
    app.router.add_post("/api/admin/run_pipeline", handle_run_pipeline)
    app.router.add_post("/api/admin/run_full_pipeline", handle_run_full_pipeline)
    app.router.add_get("/manual", handle_manual)
    app.router.add_get("/api/manual/legs", handle_manual_legs)
    app.router.add_post("/api/manual/parlay", handle_manual_parlay)
    return app


_ET = ZoneInfo("America/New_York")
# Three daily pipeline runs (label, time-ET, function):
#   morning  9:00 AM — resolve yesterday + full fetch/score/build for today (run_morning_pipeline)
#   midday  12:00 PM — full fresh props fetch, no resolution (run_full_refresh_pipeline)
#   evening  5:30 PM — full fresh props fetch, no resolution (run_full_refresh_pipeline)
_PIPELINE_SCHEDULE = [
    (dtime(9,  0),  "morning"),   # 9:00 AM ET — resolution + full fetch/score/build
    (dtime(12, 0),  "midday"),    # 12:00 PM ET — full fresh props, skip resolution
    (dtime(17, 30), "evening"),   # 5:30 PM ET — full fresh props, skip resolution
]

# Startup catch-up window: run if we restart within N minutes after a slot
_CATCHUP_WINDOW_MINS = 120


async def _pipeline_scheduler() -> None:
    """
    Background task that runs scheduled pipelines at 9 AM, 12 PM, and 5:30 PM ET.

    9 AM    → run_morning_pipeline()      (resolve yesterday + full fetch/score/build for today)
    12 PM   → run_full_refresh_pipeline() (full fresh props fetch, skip resolution)
    5:30 PM → run_full_refresh_pipeline() (full fresh props fetch, skip resolution)

    On startup, if we're within _CATCHUP_WINDOW_MINS of a missed slot, runs
    that slot's pipeline immediately (Railway redeploy recovery).
    """
    from main import run_morning_pipeline, run_full_refresh_pipeline

    print("[scheduler] Morning pipeline scheduled at 9:00 AM ET (resolution + full fetch/score/build)")
    print("[scheduler] Midday pipeline scheduled at 12:00 PM ET (full fresh props, skip resolution)")
    print("[scheduler] Evening pipeline scheduled at 5:30 PM ET (full fresh props, skip resolution)")

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
                    await loop.run_in_executor(None, run_full_refresh_pipeline, slot_label)
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
                await loop.run_in_executor(None, run_full_refresh_pipeline, next_label)
        except Exception as exc:
            print(f"[scheduler] {next_label} pipeline error: {exc}")


async def _lineup_drain_scheduler() -> None:
    """
    Background task that polls mlb_pending_lineup_checks every minute and fires
    run_lineup_check() for any rows where trigger_at <= now() and status='pending'.

    Runs independently of the main pipeline scheduler.  One bad game never
    crashes the loop — exceptions are caught per-row and status set to 'failed'.
    """
    from main import LINEUP_DRAIN_INTERVAL_MINUTES

    print(f"[lineup_drain] Drain cron started (interval: {LINEUP_DRAIN_INTERVAL_MINUTES}m)")

    while True:
        await asyncio.sleep(LINEUP_DRAIN_INTERVAL_MINUTES * 60)
        try:
            from src.apis.lineup_confirmation import drain_due_lineup_checks
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, drain_due_lineup_checks)
        except Exception as exc:
            print(f"[lineup_drain] drain error (non-fatal): {exc}")


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
    print("[web] Pipeline scheduler started (9 AM resolution + full fetch, 12 PM + 5:30 PM full refresh, skip resolution)")

    # Start the lineup-confirmation drain cron (event-driven, every 1 min)
    asyncio.ensure_future(_lineup_drain_scheduler())
    print("[web] Lineup drain cron started (polls mlb_pending_lineup_checks every 1 min)")

    return runner


if __name__ == "__main__":
    async def _main() -> None:
        runner = await start_server()
        try:
            await asyncio.Event().wait()  # run until interrupted
        finally:
            await runner.cleanup()

    asyncio.run(_main())
