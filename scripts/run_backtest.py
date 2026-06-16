"""
run_backtest.py — Backtest harness for June 1–10 window.

Tests two proposed changes — EV-sort and Slot gate — against baseline
(real recorded results from mlb_parlay_recommendations_v2 + mlb_parlay_legs_v2).

Read-only: queries mlb_scored_legs, mlb_parlay_recommendations_v2,
mlb_parlay_legs_v2. Never writes to production tables.

Build order (spec §10):
  Phase 1: load_baseline() + baseline metrics + report skeleton
  Phase 2: load_daily_leg_pools() + simulate_variant() engine
  Phase 3: ev_filter() — Variant 1
  Phase 4: slot_filter() — Variant 2
  Phase 5: combined_filter() — Variant 3
  Phase 6: CIs throughout, finalize report

Usage:
    python scripts/run_backtest.py                              # full run
    python scripts/run_backtest.py --baseline-only             # phase 1 gate
    python scripts/run_backtest.py --output reports/backtest_june1_10.txt
"""
from __future__ import annotations

import argparse
import contextlib
import io
import math
import os
import sys
from collections import defaultdict
from decimal import Decimal
from typing import Callable

import psycopg2
from psycopg2.extras import RealDictCursor

# Project root on sys.path so parlay_builder imports work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Load DATABASE_URL from .env if not already in environment
if not os.environ.get("DATABASE_URL"):
    _env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(_env_path):
        with open(_env_path) as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _v = _line.split("=", 1)
                    os.environ.setdefault(_k.strip(), _v.strip())

from src.engine.parlay_builder import build_parlays

WINDOW_START = "2026-06-01"
WINDOW_END   = "2026-06-10"

# From main.py — used verbatim for the slot gate variant
BATTING_ORDER_FAVORABLE: dict[tuple, range] = {
    ("hits",       "over"):  range(1, 6),
    ("strikeouts", "over"):  range(1, 7),
    ("totalBases", "under"): range(1, 10),
    ("hits",       "under"): range(1, 10),
}


# ── DB connection ─────────────────────────────────────────────────────────────

def get_conn():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg2.connect(url, cursor_factory=RealDictCursor)


# ── Math helpers ──────────────────────────────────────────────────────────────

def implied_prob(odds_str: str) -> float | None:
    """American odds string → implied probability (0-1). Returns None if unparseable."""
    try:
        o = float(odds_str)
        if o < 0:
            return abs(o) / (abs(o) + 100)
        else:
            return 100 / (o + 100)
    except (TypeError, ValueError):
        return None


def edge_value(leg: dict) -> float:
    """
    Estimated win prob − book implied prob.
    Estimated win prob = coverage_overall / 100.
    Falls back to coverage_pct if coverage_overall is NULL.
    Returns 0.0 if either side is uncomputable.
    """
    cov = leg.get("coverage_overall")
    if cov is None:
        cov = leg.get("coverage_pct")
    est = (cov or 0) / 100.0
    imp = implied_prob(str(leg.get("odds") or ""))
    if imp is None:
        return 0.0
    return est - imp


def confidence_interval_95(wins: int, total: int) -> float:
    """Returns ±half-width of 95% CI in percentage points."""
    if total == 0:
        return float("inf")
    p = wins / total
    return 1.96 * math.sqrt(p * (1 - p) / total) * 100


def parse_american_odds(val) -> int:
    """Convert Decimal/str/int odds to int. Returns 0 on failure."""
    try:
        if isinstance(val, Decimal):
            return int(val)
        if isinstance(val, str):
            return int(float(val.lstrip("+")))
        return int(val)
    except (TypeError, ValueError):
        return 0


def avg_american_odds(odds_list: list[int]) -> int:
    if not odds_list:
        return 0
    return round(sum(odds_list) / len(odds_list))


def breakeven_pct(avg_odds: int) -> float:
    """Book's implied breakeven win rate at given American odds."""
    if avg_odds >= 0:
        return 100 / (avg_odds + 100) * 100
    return abs(avg_odds) / (abs(avg_odds) + 100) * 100


# ── Data loading ──────────────────────────────────────────────────────────────

def load_baseline() -> tuple[list[dict], list[dict]]:
    """
    Load real recorded results from the DB.

    Returns:
        (leg_pool, parlay_rows)

        leg_pool    — all resolved scored legs in the window (integrity gates applied)
        parlay_rows — join of mlb_parlay_recommendations_v2 + mlb_parlay_legs_v2,
                      one row per leg per resolved parlay
    """
    conn = get_conn()
    cur = conn.cursor()

    # Baseline leg pool (spec §3)
    cur.execute("""
        SELECT
            id, run_date, player_name, team, stat, direction, line,
            odds, composite_score, coverage_overall, coverage_pct,
            game_pk, game_start_time, batting_order, result, in_parlay,
            odd_id, player_id, position
        FROM mlb_scored_legs
        WHERE run_date BETWEEN %s AND %s
          AND result IN ('won', 'lost')
          AND composite_score IS NOT NULL
          AND odds IS NOT NULL
          AND game_start_time IS NOT NULL
          AND (
              (stat = 'hits'        AND direction = 'over')
           OR (stat = 'strikeouts'  AND direction = 'over')
          )
        ORDER BY run_date, game_start_time
    """, (WINDOW_START, WINDOW_END))
    legs = [dict(r) for r in cur.fetchall()]

    # Baseline parlay results (spec §3)
    cur.execute("""
        SELECT
            p.id          AS parlay_id,
            p.run_date::text AS run_date,
            p.source,
            p.batch_id,
            p.total_odds,
            p.num_legs,
            p.outcome     AS parlay_outcome,
            l.player_name,
            l.stat,
            l.direction,
            l.line,
            l.odds,
            l.composite_score,
            l.outcome     AS leg_outcome
        FROM mlb_parlay_recommendations_v2 p
        JOIN mlb_parlay_legs_v2 l ON l.parlay_id = p.id
        WHERE p.run_date BETWEEN %s::date AND %s::date
          AND p.outcome IN ('won', 'lost')
          AND l.outcome IN ('won', 'lost')
        ORDER BY p.run_date, p.batch_id, p.id
    """, (WINDOW_START, WINDOW_END))
    parlay_rows = [dict(r) for r in cur.fetchall()]

    cur.close()
    conn.close()
    return legs, parlay_rows


def load_daily_leg_pools() -> dict[str, list[dict]]:
    """
    Load resolved scored legs per day for simulation.

    Adds best_odds / best_line aliases that parlay_builder expects.
    Legs with stat='totalBases' are excluded (shadow-only, spec §4.3 / main.py:866).
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT
            id, run_date, player_name, team, stat, direction, line,
            odds, composite_score, coverage_overall, coverage_pct,
            game_pk, game_start_time, batting_order, result, in_parlay,
            odd_id, player_id, position
        FROM mlb_scored_legs
        WHERE run_date BETWEEN %s AND %s
          AND result IN ('won', 'lost')
          AND composite_score IS NOT NULL
          AND odds IS NOT NULL
          AND game_start_time IS NOT NULL
          AND (
              (stat = 'hits'        AND direction = 'over')
           OR (stat = 'strikeouts'  AND direction = 'over')
          )
        ORDER BY run_date, game_start_time
    """, (WINDOW_START, WINDOW_END))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()

    pools: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        row["best_odds"] = row["odds"]   # parlay_builder reads best_odds
        row["best_line"] = row["line"]
        pools[row["run_date"]].append(row)
    return dict(pools)


# ── Baseline parlay parsing ───────────────────────────────────────────────────

def parse_baseline_parlays(parlay_rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Group parlay join rows into individual parlays.

    Returns:
        (parlay_list, selected_legs)
        parlay_list  — [{"won": bool, "odds": int, "source": str, "id": int}]
        selected_legs — flat list of all leg rows that appeared in resolved parlays
    """
    parlays_by_id: dict[int, dict] = {}
    for row in parlay_rows:
        pid = row["parlay_id"]
        if pid not in parlays_by_id:
            parlays_by_id[pid] = {
                "id":      pid,
                "outcome": row["parlay_outcome"],
                "source":  row.get("source", "unknown"),
                "odds":    parse_american_odds(row.get("total_odds")),
                "legs":    [],
            }
        parlays_by_id[pid]["legs"].append(row)

    parlay_list = []
    selected_legs = []
    for p in parlays_by_id.values():
        parlay_list.append({
            "won":    p["outcome"] == "won",
            "odds":   p["odds"],
            "source": p["source"],
            "id":     p["id"],
        })
        selected_legs.extend(p["legs"])

    return parlay_list, selected_legs


# ── Metrics ───────────────────────────────────────────────────────────────────

def compute_leg_metrics(legs: list[dict]) -> dict:
    total = len(legs)
    wins  = sum(1 for l in legs if l.get("result") == "won")
    wr    = wins / total * 100 if total else 0.0
    ci    = confidence_interval_95(wins, total)

    by_stat: dict[str, dict] = {}
    for leg in legs:
        key = f"{leg.get('stat', '?')}/{leg.get('direction', '?')}"
        if key not in by_stat:
            by_stat[key] = {"wins": 0, "total": 0}
        by_stat[key]["total"] += 1
        if leg.get("result") == "won":
            by_stat[key]["wins"] += 1

    by_stat_metrics = {}
    for k, v in by_stat.items():
        w2 = v["wins"] / v["total"] * 100 if v["total"] else 0.0
        by_stat_metrics[k] = {
            "win_rate": w2,
            "wins":     v["wins"],
            "total":    v["total"],
            "ci":       confidence_interval_95(v["wins"], v["total"]),
        }

    return {"total": total, "wins": wins, "win_rate": wr, "ci": ci, "by_stat": by_stat_metrics}


def compute_parlay_metrics(parlay_list: list[dict]) -> dict:
    """parlay_list: list of {"won": bool, "odds": int}"""
    total = len(parlay_list)
    wins  = sum(1 for p in parlay_list if p["won"])
    wr    = wins / total * 100 if total else 0.0
    ci    = confidence_interval_95(wins, total)
    valid_odds = [p["odds"] for p in parlay_list if p.get("odds") is not None]
    avg_odds   = avg_american_odds(valid_odds)
    be         = breakeven_pct(avg_odds) if valid_odds else 0.0
    edge_pp    = wr - be

    return {
        "total":     total,
        "wins":      wins,
        "win_rate":  wr,
        "ci":        ci,
        "avg_odds":  avg_odds,
        "breakeven": be,
        "edge":      edge_pp,
    }


# ── Pool filters ──────────────────────────────────────────────────────────────

def ev_filter(legs: list[dict]) -> list[dict]:
    """EV gate: exclude legs with edge <= 0. Return pool sorted by edge DESC."""
    pos = [l for l in legs if edge_value(l) > 0]
    return sorted(pos, key=edge_value, reverse=True)


def slot_filter(legs: list[dict]) -> list[dict]:
    """
    Slot gate: exclude legs where batting_order is known and outside favorable range.
    NULL batting_order legs are kept (unknown slot ≠ bad slot).
    Sort by composite_score DESC (same as current system).
    """
    kept = []
    for leg in legs:
        stat      = leg.get("stat", "")
        direction = leg.get("direction", "over")
        bo        = leg.get("batting_order")
        favorable = BATTING_ORDER_FAVORABLE.get((stat, direction), range(1, 10))
        if bo is None or bo in favorable:
            kept.append(leg)
    return sorted(kept, key=lambda l: l.get("composite_score", 0), reverse=True)


def combined_filter(legs: list[dict]) -> list[dict]:
    """Slot gate first (remove out-of-range known slots), then EV-sort."""
    slotted  = slot_filter(legs)
    pos_edge = [l for l in slotted if edge_value(l) > 0]
    return sorted(pos_edge, key=edge_value, reverse=True)


# ── Simulation engine ─────────────────────────────────────────────────────────

@contextlib.contextmanager
def _suppress_stdout():
    """Redirect stdout during builder calls to keep harness output clean."""
    old = sys.stdout
    sys.stdout = io.StringIO()
    try:
        yield
    finally:
        sys.stdout = old


def simulate_variant(
    daily_pools: dict[str, list[dict]],
    pool_filter: Callable[[list[dict]], list[dict]],
    top_n: int = 5,
) -> dict:
    """
    Simulate a variant across all days in the window.

    For each day:
      1. Apply pool_filter to that day's legs.
      2. Call build_parlays() — reused directly from parlay_builder (spec §8).
         NOTE: build_parlays() re-sorts the pool internally by composite_score
         before B&B exploration, and selects the best candidate by avg_composite.
         The EV-sort variant's pre-sort by edge therefore affects pool composition
         (via the EV gate) but not the final selection criterion. This is noted in
         the report.
      3. Derive simulated parlay outcome from legs' resolved `result` field.
         A simulated parlay wins iff ALL its legs' result == 'won'.

    Returns dict with:
      selected_legs     — all legs that appeared in simulated parlays
      simulated_parlays — [{"won": bool, "odds": int, "date": str}]
      days_no_parlays   — count of days where no parlays could be built
      all_pool_legs     — all legs in post-filter pool (for aggregate win rate)
    """
    selected_legs: list[dict]      = []
    simulated_parlays: list[dict]  = []
    days_no_parlays: int           = 0
    all_pool_legs: list[dict]      = []

    for run_date in sorted(daily_pools.keys()):
        day_legs = daily_pools[run_date]
        filtered = pool_filter(day_legs)
        all_pool_legs.extend(filtered)

        # num_games: count distinct game_pks in today's raw pool (proxy for slate size)
        num_games = len({l.get("game_pk") for l in day_legs if l.get("game_pk")})

        with _suppress_stdout():
            parlays = build_parlays(filtered, top_n=top_n, num_games=max(num_games, 2))

        if not parlays:
            days_no_parlays += 1
            continue

        for p in parlays:
            legs    = p["legs"]
            won     = all(l.get("result") == "won" for l in legs)
            odds_val = parse_american_odds(p.get("parlay_odds", "+0"))
            simulated_parlays.append({"won": won, "odds": odds_val, "date": run_date})
            selected_legs.extend(legs)

    return {
        "selected_legs":    selected_legs,
        "simulated_parlays": simulated_parlays,
        "days_no_parlays":  days_no_parlays,
        "all_pool_legs":    all_pool_legs,
    }


# ── EV-specific analysis ──────────────────────────────────────────────────────

def analyze_ev_gate(all_legs: list[dict]) -> dict:
    """Positive-edge vs zero/neg-edge win rates across the full pool."""
    pos = [l for l in all_legs if edge_value(l) > 0]
    neg = [l for l in all_legs if edge_value(l) <= 0]
    pos_wins = sum(1 for l in pos if l.get("result") == "won")
    neg_wins = sum(1 for l in neg if l.get("result") == "won")
    total    = len(all_legs)
    return {
        "pos_total":    len(pos),
        "pos_wins":     pos_wins,
        "pos_win_rate": pos_wins / len(pos) * 100 if pos else 0.0,
        "pos_ci":       confidence_interval_95(pos_wins, len(pos)),
        "neg_total":    len(neg),
        "neg_wins":     neg_wins,
        "neg_win_rate": neg_wins / len(neg) * 100 if neg else 0.0,
        "neg_ci":       confidence_interval_95(neg_wins, len(neg)),
        "total":        total,
    }


# ── Slot-specific analysis ────────────────────────────────────────────────────

def analyze_slot_distribution(legs: list[dict]) -> dict:
    """Break down win rates by slot bucket: slots 1-5, 6-9, unknown."""
    buckets: dict[str, list] = {"slots_1_5": [], "slots_6_9": [], "unknown": []}
    for leg in legs:
        bo = leg.get("batting_order")
        if bo is None:
            buckets["unknown"].append(leg)
        elif 1 <= int(bo) <= 5:
            buckets["slots_1_5"].append(leg)
        else:
            buckets["slots_6_9"].append(leg)

    result = {}
    for bucket, bucket_legs in buckets.items():
        total = len(bucket_legs)
        wins  = sum(1 for l in bucket_legs if l.get("result") == "won")
        result[bucket] = {
            "total":    total,
            "wins":     wins,
            "win_rate": wins / total * 100 if total else 0.0,
            "ci":       confidence_interval_95(wins, total),
        }
    return result


# ── Report formatting ─────────────────────────────────────────────────────────

def _fmt_leg_wr(win_rate: float, ci: float, total: int) -> str:
    if total == 0:
        return "N/A"
    return f"{win_rate:.1f}% ±{ci:.1f}pp ({total} legs)"


def _fmt_parlay_wr(win_rate: float, ci: float, total: int) -> str:
    if total == 0:
        return "N/A"
    return f"{win_rate:.1f}% ±{ci:.1f}pp ({total} parlays)"


def _fmt_edge(val: float) -> str:
    sign = "+" if val >= 0 else ""
    return f"{sign}{val:.1f}pp"


def _fmt_delta(variant_wr: float, baseline_wr: float) -> str:
    diff = variant_wr - baseline_wr
    sign = "+" if diff >= 0 else ""
    return f"{sign}{diff:.1f}pp vs baseline"


def print_report(
    baseline_legs: list[dict],
    baseline_parlay_list: list[dict],
    daily_pools: dict[str, list[dict]],
    ev_result: dict,
    slot_result: dict,
    combined_result: dict,
    output_file: str | None = None,
) -> None:
    lines: list[str] = []

    def w(s: str = ""):
        lines.append(s)

    bl_leg     = compute_leg_metrics(baseline_legs)
    bl_parlay  = compute_parlay_metrics(baseline_parlay_list)

    # Full pool for EV gate analysis (excludes totalBases — same as daily_pools)
    all_pool_flat = [l for day_legs in daily_pools.values() for l in day_legs]

    # ── Header ────────────────────────────────────────────────────────────────
    w("=" * 64)
    w("BACKTEST REPORT — June 1–10, 2026")
    w("=" * 64)
    w()
    w("WINDOW SUMMARY")
    w(f"  Resolved legs in window     : {len(baseline_legs)}")
    w(f"  Resolved parlays in window  : {len(baseline_parlay_list)}")
    w(f"  Date range                  : {WINDOW_START} to {WINDOW_END}")
    w()
    w("  IMPLEMENTATION NOTE: parlay_builder re-sorts pool by composite_score")
    w("  internally before B&B exploration. EV-sort variant applies an EV gate")
    w("  (exclude edge<=0 legs) to change the pool, but within-gate candidate")
    w("  selection still uses composite_score. The gate effect is what's being")
    w("  measured — not a pure EV-sorted ranking.")

    # ── Baseline ──────────────────────────────────────────────────────────────
    w()
    w("-" * 64)
    w("BASELINE (real recorded results)")
    w("-" * 64)
    w("  Leg-level:")
    w(f"    Overall win rate          : {_fmt_leg_wr(bl_leg['win_rate'], bl_leg['ci'], bl_leg['total'])}")
    w("    By stat/direction:")
    for key in sorted(bl_leg["by_stat"]):
        m   = bl_leg["by_stat"][key]
        pad = " " * max(0, 22 - len(key))
        w(f"      {key}{pad}: {_fmt_leg_wr(m['win_rate'], m['ci'], m['total'])}")
    w()
    w("  Parlay-level:")
    w(f"    Resolved parlays          : {bl_parlay['total']}")
    w(f"    Win rate                  : {_fmt_parlay_wr(bl_parlay['win_rate'], bl_parlay['ci'], bl_parlay['total'])}")
    w(f"    Avg combined odds         : +{bl_parlay['avg_odds']}")
    w(f"    Implied breakeven         : {bl_parlay['breakeven']:.1f}%")
    w(f"    Edge                      : {_fmt_edge(bl_parlay['edge'])}")
    w(f"    [Note: {bl_parlay['total']} parlays → ±{bl_parlay['ci']:.1f}pp CI]")
    # By source
    by_source: dict[str, list] = defaultdict(list)
    for p in baseline_parlay_list:
        by_source[p.get("source", "unknown")].append(p)
    w("    By source:")
    for src in sorted(by_source):
        sm = compute_parlay_metrics(by_source[src])
        w(f"      {src:<22}: {_fmt_parlay_wr(sm['win_rate'], sm['ci'], sm['total'])}")

    # ── Variant 1: EV-sort ────────────────────────────────────────────────────
    ev_gate    = analyze_ev_gate(all_pool_flat)
    ev_sel     = compute_leg_metrics(ev_result["selected_legs"])
    ev_pool    = compute_leg_metrics(ev_result["all_pool_legs"])
    ev_parlay  = compute_parlay_metrics(ev_result["simulated_parlays"])

    w()
    w("-" * 64)
    w("VARIANT 1: EV-SORT")
    w("-" * 64)
    w("  EV gate (simulation pool — totalBases excluded):")
    pct_pos = ev_gate["pos_total"] / ev_gate["total"] * 100 if ev_gate["total"] else 0
    w(f"    Legs with positive edge   : {ev_gate['pos_total']} / {ev_gate['total']} ({pct_pos:.1f}%)")
    w(f"    Positive-edge win rate    : {ev_gate['pos_win_rate']:.1f}% ±{ev_gate['pos_ci']:.1f}pp ({ev_gate['pos_total']} legs)")
    w(f"    Zero/neg-edge win rate    : {ev_gate['neg_win_rate']:.1f}% ±{ev_gate['neg_ci']:.1f}pp ({ev_gate['neg_total']} legs)  ← validates gate")
    w()
    w("  Leg-level:")
    w(f"    Post-gate pool win rate   : {_fmt_leg_wr(ev_pool['win_rate'], ev_pool['ci'], ev_pool['total'])}")
    w(f"    Selected leg win rate     : {_fmt_leg_wr(ev_sel['win_rate'], ev_sel['ci'], ev_sel['total'])}")
    w(f"    Baseline selected rate    : {_fmt_leg_wr(bl_leg['win_rate'], bl_leg['ci'], bl_leg['total'])}")
    w(f"    Delta vs baseline         : {_fmt_delta(ev_sel['win_rate'], bl_leg['win_rate'])}")
    w()
    w("  Parlay-level vs baseline:")
    w(f"    Win rate                  : {ev_parlay['win_rate']:.1f}% ±{ev_parlay['ci']:.1f}pp  vs  {bl_parlay['win_rate']:.1f}% ±{bl_parlay['ci']:.1f}pp baseline")
    w(f"    Delta vs baseline         : {_fmt_delta(ev_parlay['win_rate'], bl_parlay['win_rate'])}")
    w(f"    Avg combined odds         : +{ev_parlay['avg_odds']}  vs  +{bl_parlay['avg_odds']} baseline")
    w(f"    Edge                      : {_fmt_edge(ev_parlay['edge'])}  vs  {_fmt_edge(bl_parlay['edge'])} baseline")
    w(f"    Days with 0 parlays built : {ev_result['days_no_parlays']}")

    # ── Variant 2: Slot gate ──────────────────────────────────────────────────
    slot_sel    = compute_leg_metrics(slot_result["selected_legs"])
    slot_parlay = compute_parlay_metrics(slot_result["simulated_parlays"])
    slot_dist   = analyze_slot_distribution(slot_result["selected_legs"])

    s15  = slot_dist["slots_1_5"]
    s69  = slot_dist["slots_6_9"]
    sunk = slot_dist["unknown"]
    tot  = s15["total"] + s69["total"] + sunk["total"]
    def pct_of(n): return f"{n/tot*100:.1f}%" if tot else "0%"

    w()
    w("-" * 64)
    w("VARIANT 2: SLOT GATE")
    w("-" * 64)
    w("  Slot distribution (selected legs):")
    w(f"    Slots 1-5   : {s15['total']:>4} ({pct_of(s15['total']):<6}) — win rate {s15['win_rate']:.1f}% ±{s15['ci']:.1f}pp")
    w(f"    Slots 6-9   : {s69['total']:>4} ({pct_of(s69['total']):<6}) — win rate {s69['win_rate']:.1f}% ±{s69['ci']:.1f}pp")
    w(f"    Unknown slot: {sunk['total']:>4} ({pct_of(sunk['total']):<6}) — win rate {sunk['win_rate']:.1f}% ±{sunk['ci']:.1f}pp")
    w()
    w("  Leg-level vs baseline:")
    w(f"    Selected leg win rate     : {_fmt_leg_wr(slot_sel['win_rate'], slot_sel['ci'], slot_sel['total'])}")
    w(f"    Delta vs baseline         : {_fmt_delta(slot_sel['win_rate'], bl_leg['win_rate'])}")
    w()
    w("  Parlay-level vs baseline:")
    w(f"    Win rate                  : {slot_parlay['win_rate']:.1f}% ±{slot_parlay['ci']:.1f}pp  vs  {bl_parlay['win_rate']:.1f}% ±{bl_parlay['ci']:.1f}pp baseline")
    w(f"    Delta vs baseline         : {_fmt_delta(slot_parlay['win_rate'], bl_parlay['win_rate'])}")
    w(f"    Avg combined odds         : +{slot_parlay['avg_odds']}  vs  +{bl_parlay['avg_odds']} baseline")
    w(f"    Edge                      : {_fmt_edge(slot_parlay['edge'])}  vs  {_fmt_edge(bl_parlay['edge'])} baseline")
    w(f"    Days with 0 parlays built : {slot_result['days_no_parlays']}")

    # ── Variant 3: Combined ───────────────────────────────────────────────────
    comb_sel    = compute_leg_metrics(combined_result["selected_legs"])
    comb_parlay = compute_parlay_metrics(combined_result["simulated_parlays"])
    comb_dist   = analyze_slot_distribution(combined_result["selected_legs"])

    cs15  = comb_dist["slots_1_5"]
    cs69  = comb_dist["slots_6_9"]
    csunk = comb_dist["unknown"]
    ctot  = cs15["total"] + cs69["total"] + csunk["total"]
    def cpct(n): return f"{n/ctot*100:.1f}%" if ctot else "0%"

    w()
    w("-" * 64)
    w("VARIANT 3: COMBINED (EV-sort + Slot gate)")
    w("-" * 64)
    w("  Slot distribution (selected legs):")
    w(f"    Slots 1-5   : {cs15['total']:>4} ({cpct(cs15['total']):<6}) — win rate {cs15['win_rate']:.1f}% ±{cs15['ci']:.1f}pp")
    w(f"    Slots 6-9   : {cs69['total']:>4} ({cpct(cs69['total']):<6}) — win rate {cs69['win_rate']:.1f}% ±{cs69['ci']:.1f}pp")
    w(f"    Unknown slot: {csunk['total']:>4} ({cpct(csunk['total']):<6}) — win rate {csunk['win_rate']:.1f}% ±{csunk['ci']:.1f}pp")
    w()
    w("  Leg-level vs baseline:")
    w(f"    Selected leg win rate     : {_fmt_leg_wr(comb_sel['win_rate'], comb_sel['ci'], comb_sel['total'])}")
    w(f"    Delta vs baseline         : {_fmt_delta(comb_sel['win_rate'], bl_leg['win_rate'])}")
    w()
    w("  Parlay-level vs baseline:")
    w(f"    Win rate                  : {comb_parlay['win_rate']:.1f}% ±{comb_parlay['ci']:.1f}pp  vs  {bl_parlay['win_rate']:.1f}% ±{bl_parlay['ci']:.1f}pp baseline")
    w(f"    Delta vs baseline         : {_fmt_delta(comb_parlay['win_rate'], bl_parlay['win_rate'])}")
    w(f"    Avg combined odds         : +{comb_parlay['avg_odds']}  vs  +{bl_parlay['avg_odds']} baseline")
    w(f"    Edge                      : {_fmt_edge(comb_parlay['edge'])}  vs  {_fmt_edge(bl_parlay['edge'])} baseline")
    w(f"    Days with 0 parlays built : {combined_result['days_no_parlays']}")

    # ── Interpretation guide ──────────────────────────────────────────────────
    w()
    w("=" * 64)
    w("INTERPRETATION GUIDE")
    w("=" * 64)
    w("  CIs shown for every win rate.")
    w("  Formula: ±1.96 × sqrt(p(1-p)/n) × 100  (95% CI, percentage points)")
    w(f"  With {bl_parlay['total']} parlays: ±{bl_parlay['ci']:.1f}pp CI — need >{bl_parlay['ci']:.1f}pp")
    w("  improvement to distinguish signal from noise at parlay level.")
    w(f"  Leg-level ({len(baseline_legs)} legs): ±{bl_leg['ci']:.1f}pp CI — more trustworthy.")
    w()
    w("  Decision rule:")
    w("    Leg-level improves AND parlay-level direction consistent")
    w("    → strong signal, worth promoting to shadow pipeline.")
    w()
    w("    Leg-level improves, parlay-level goes wrong way")
    w("    → construction/correlation artifact, investigate first.")
    w()
    w("    Neither improves → discard the variant.")

    # ── Output ────────────────────────────────────────────────────────────────
    report = "\n".join(lines)
    print(report)

    if output_file:
        os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
        with open(output_file, "w") as fh:
            fh.write(report + "\n")
        print(f"\n[report] Written to {output_file}")


# ── CLI entry point ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="MLB backtest harness — June 1–10, 2026")
    parser.add_argument(
        "--baseline-only", action="store_true",
        help="Phase 1 gate: print baseline numbers and exit",
    )
    parser.add_argument(
        "--output", metavar="FILE",
        help="Write full report to FILE (e.g. reports/backtest_june1_10.txt)",
    )
    args = parser.parse_args()

    print("[backtest] Loading baseline...", flush=True)
    baseline_legs, parlay_rows = load_baseline()
    baseline_parlay_list, _ = parse_baseline_parlays(parlay_rows)
    print(f"[backtest] {len(baseline_legs)} resolved legs, {len(baseline_parlay_list)} resolved parlays", flush=True)

    # ── Phase 1 gate ──────────────────────────────────────────────────────────
    if args.baseline_only:
        bl_leg    = compute_leg_metrics(baseline_legs)
        bl_parlay = compute_parlay_metrics(baseline_parlay_list)

        print()
        print("=" * 64)
        print("BASELINE CHECK — Phase 1 gate")
        print("=" * 64)
        print(f"  Resolved legs        : {bl_leg['total']}")
        print(f"  Overall leg win rate : {bl_leg['win_rate']:.1f}% ±{bl_leg['ci']:.1f}pp")
        print("  By stat/direction:")
        for key in sorted(bl_leg["by_stat"]):
            m = bl_leg["by_stat"][key]
            print(f"    {key:<26}: {m['win_rate']:.1f}%  ({m['wins']}/{m['total']})")
        print()
        print(f"  Resolved parlays     : {bl_parlay['total']}")
        print(f"  Parlay win rate      : {bl_parlay['win_rate']:.1f}% ±{bl_parlay['ci']:.1f}pp")
        print(f"  Avg combined odds    : +{bl_parlay['avg_odds']}")
        print(f"  Implied breakeven    : {bl_parlay['breakeven']:.1f}%")
        print(f"  Edge                 : {_fmt_edge(bl_parlay['edge'])}")
        print()
        print("Known targets (spec §10):")
        print("  ~756 resolved legs | ~188 resolved parlays | ~19.1% parlay win rate")
        print("  hits/over ~64% | SO/over ~68%")
        print()
        leg_ok    = abs(bl_leg["total"] - 756) <= 50
        parlay_ok = abs(bl_parlay["total"] - 188) <= 30
        wr_ok     = abs(bl_parlay["win_rate"] - 19.1) <= 5
        if leg_ok and parlay_ok and wr_ok:
            print("✓ Baseline numbers match expected range — safe to proceed to full run.")
        else:
            print("⚠  One or more baseline numbers outside expected range.")
            print("   Investigate before running variants.")
        return

    # ── Phases 2–5: simulate variants ─────────────────────────────────────────
    print("[backtest] Loading daily leg pools...", flush=True)
    daily_pools = load_daily_leg_pools()
    print(f"[backtest] {len(daily_pools)} days, {sum(len(v) for v in daily_pools.values())} total legs", flush=True)

    print("[backtest] Simulating Variant 1 (EV-sort)...", flush=True)
    ev_result = simulate_variant(daily_pools, ev_filter)
    print(f"[backtest]   {len(ev_result['simulated_parlays'])} parlays, {ev_result['days_no_parlays']} days empty", flush=True)

    print("[backtest] Simulating Variant 2 (Slot gate)...", flush=True)
    slot_result = simulate_variant(daily_pools, slot_filter)
    print(f"[backtest]   {len(slot_result['simulated_parlays'])} parlays, {slot_result['days_no_parlays']} days empty", flush=True)

    print("[backtest] Simulating Variant 3 (Combined)...", flush=True)
    combined_result = simulate_variant(daily_pools, combined_filter)
    print(f"[backtest]   {len(combined_result['simulated_parlays'])} parlays, {combined_result['days_no_parlays']} days empty", flush=True)

    print("[backtest] Building report...\n", flush=True)
    print_report(
        baseline_legs=baseline_legs,
        baseline_parlay_list=baseline_parlay_list,
        daily_pools=daily_pools,
        ev_result=ev_result,
        slot_result=slot_result,
        combined_result=combined_result,
        output_file=args.output,
    )


if __name__ == "__main__":
    main()
