"""
runner.py — Async-friendly wrappers around pipeline and tracker functions.

Each function here corresponds to one Discord slash command. They run the
underlying pipeline/tracker logic in a thread pool executor so they don't
block the Discord bot's async event loop, and return structured data that
formatter.py can turn into Discord embeds.

All heavy work (scoring, API calls, DB queries) happens inside
run_in_executor so the bot stays responsive while jobs are running.
"""
from __future__ import annotations

import asyncio
from datetime import date

from src.utils.db import get_conn


async def pipeline_run() -> tuple[list[dict], str]:
    """
    Run the full MLB parlay pipeline in a background thread.

    Calls main.run_pipeline() which covers all pipeline stages: IL/transactions,
    props, qualifying legs, injury filter, scoring, parlay builder, and LLM
    analysis. Returns the raw parlay dicts and Claude's analysis text so the
    bot can format them into Discord embeds.

    Returns:
        (parlays, analysis) — parlays is a list of parlay dicts, analysis
        is the plain-English Claude string. Both are empty if no parlays found.
    """
    loop = asyncio.get_event_loop()

    def _run():
        from main import run_pipeline
        return run_pipeline()

    return await loop.run_in_executor(None, _run)


async def pipeline_resolve() -> str:
    """
    Run the outcome resolver in a background thread.

    Fetches box scores for all pending recommendation legs and marks each
    won/lost. Returns a plain-text summary of what was resolved, suitable
    for posting directly to Discord.

    Returns:
        A multi-line string summarising resolved parlays and leg outcomes.
    """
    loop = asyncio.get_event_loop()

    def _resolve():
        import io, sys
        from datetime import date, timedelta
        from src.tracker.outcome_resolver import resolve_recommendations, resolve_all_legs
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            resolve_recommendations(verbose=True)
            # Also resolve the full scored-leg pool for yesterday and today
            # (box-score approach: 1 API call per game, covers all players)
            yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
            today     = date.today().strftime("%Y-%m-%d")
            resolve_all_legs(yesterday, verbose=True)
            resolve_all_legs(today, verbose=True)
        finally:
            sys.stdout = old_stdout
        return buf.getvalue().strip() or "Nothing to resolve."

    return await loop.run_in_executor(None, _resolve)


async def pipeline_status() -> list[dict]:
    """
    Fetch all pending recommendations from the database.

    Returns a list of dicts, each representing one pending parlay with its
    legs attached. Used by the /status command to show what's waiting for
    resolution.

    Returns:
        List of parlay dicts with a 'legs' key containing their leg rows.
        Empty list if nothing is pending.
    """
    loop = asyncio.get_event_loop()

    def _status():
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM mlb_recommendations WHERE status = 'pending' ORDER BY date DESC, id"
        )
        recs = cur.fetchall()
        result = []
        for rec in recs:
            rec_dict = dict(rec)
            cur.execute(
                "SELECT player_name, stat, line, odds, coverage_pct, p_over, result, team "
                "FROM mlb_recommendation_legs WHERE recommendation_id = %s ORDER BY id",
                (rec_dict["id"],)
            )
            rec_dict["legs"] = [dict(l) for l in cur.fetchall()]
            result.append(rec_dict)
        cur.close()
        conn.close()
        return result

    return await loop.run_in_executor(None, _status)


async def pipeline_calibration() -> dict:
    """
    Compute calibration metrics from all resolved recommendation legs.

    Pulls Brier scores, calibration buckets, leg hit rate, parlay hit rate,
    and EV accuracy from the database and returns them as a structured dict
    so formatter.py can build a Discord embed without any display logic here.

    Returns:
        Dict with keys: n_legs, leg_hit_rate, n_parlays, parlay_hit_rate,
        brier_bayes, brier_coverage, calibration_buckets, pos_ev_win_rate,
        neg_ev_win_rate. Values are None when insufficient data exists.
    """
    loop = asyncio.get_event_loop()

    def _calibration():
        from src.tracker.calibration import (
            _load_resolved_legs,
            _load_resolved_parlays,
            _brier_score,
            _calibration_buckets,
        )

        legs = _load_resolved_legs()
        parlays = _load_resolved_parlays()

        if not legs:
            return {"n_legs": 0}

        wins = sum(1 for l in legs if l["result"] == "won")
        p_wins = sum(1 for p in parlays if p["status"] == "won") if parlays else 0

        brier_bayes = _brier_score(legs, "p_over")
        cov_legs = [{**l, "_cov": l["coverage_pct"] / 100} for l in legs if l.get("coverage_pct")]
        brier_cov = _brier_score(cov_legs, "_cov") if cov_legs else None

        bayes_legs = [l for l in legs if l.get("p_over") is not None]
        buckets = _calibration_buckets(bayes_legs, "p_over") if bayes_legs else []

        ev_legs = [l for l in legs if l.get("ev_per_unit") is not None]
        pos_ev = [l for l in ev_legs if l["ev_per_unit"] > 0]
        neg_ev = [l for l in ev_legs if l["ev_per_unit"] <= 0]

        return {
            "n_legs": len(legs),
            "leg_wins": wins,
            "leg_hit_rate": wins / len(legs),
            "n_parlays": len(parlays),
            "parlay_wins": p_wins,
            "parlay_hit_rate": p_wins / len(parlays) if parlays else None,
            "brier_bayes": brier_bayes,
            "brier_cov": brier_cov,
            "n_bayes_legs": len(bayes_legs),
            "n_cov_legs": len(cov_legs),
            "calibration_buckets": buckets,
            "pos_ev_wins": sum(1 for l in pos_ev if l["result"] == "won"),
            "pos_ev_total": len(pos_ev),
            "neg_ev_wins": sum(1 for l in neg_ev if l["result"] == "won"),
            "neg_ev_total": len(neg_ev),
        }

    return await loop.run_in_executor(None, _calibration)
