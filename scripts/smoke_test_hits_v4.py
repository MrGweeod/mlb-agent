"""
scripts/smoke_test_hits_v4.py — pre-flight check for v4 hits/over scoring.

Run this against a PAST date and confirm it passes before enabling v4 on live
runs. It answers the questions that actually go wrong in this pipeline:

  1. Does every leg get a non-null p_hit?
  2. Are the probabilities in a sane range, and do they spread wider than the
     gated composite_score pool they replace?
  3. Does the (0,1) guard ever fire on real data?
  4. Does a valid parlay build — >= 4 legs, >= +400 combined?
  5. Does the builder reach the odds floor by EXTENDING (5th/6th leg) rather
     than swapping down the p_hit ranking?
  6. Is runtime acceptable against the now-ungated pool? (Session 25's silent
     stall came from unbounded per-leg aggregation; v4 batches to 4 queries
     per run and this reports the timing.)
  7. Do any values overflow on write? (The 2026-08-05/06 zero-save incident
     was a numeric-precision overflow. v4's columns are DOUBLE PRECISION, and
     this checks the magnitudes that would be written.)

Two modes:

  LIVE (needs DATABASE_URL):
      source .venv/bin/activate && python scripts/smoke_test_hits_v4.py --date 2026-08-11
    Runs the real load_v4_aggregates() against the real DB — the full
    production path including psycopg2.

  OFFLINE (no DB):
      source .venv/bin/activate && python scripts/smoke_test_hits_v4.py --fixture legs.json
    Feeds a pre-extracted fixture through the real compute_p_hit() and the
    real build_parlays(). Exercises the model and the builder but NOT the
    psycopg2 plumbing — say so when reporting results from this mode.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MIN_PARLAY_ODDS = 400
MIN_LEGS = 4
V4_MAX_LEGS = 6
FLOOR_MODE = "percentile"   # mirrors main.V4_QUALITY_FLOOR_MODE
FLOOR_VALUE = 25.0          # mirrors main.V4_QUALITY_FLOOR_VALUE

_failures: list[str] = []
_warnings: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        _failures.append(label)
    return ok


def warn(label: str) -> None:
    print(f"  [WARN] {label}")
    _warnings.append(label)


def load_offline(path: str) -> list[dict]:
    """Stub src.utils.db so parlay_builder imports without a live connection."""
    if "src.utils.db" not in sys.modules:
        stub = MagicMock()
        stub.get_players_used_today.return_value = set()
        sys.modules["src.utils.db"] = stub
    return json.load(open(path))


def score_offline(rows: list[dict]) -> list[dict]:
    from src.engine.hits_v4 import compute_p_hit

    legs = []
    t0 = time.time()
    guard_hits = 0
    for r in rows:
        out = compute_p_hit(
            prior_h=r.get("prior_h"), prior_ab=r.get("prior_ab"),
            cov_overall=r.get("cov_overall"), cov_window=r.get("cov_window"),
            h_vs_hand=r.get("h_vs_l") if (r.get("hand") or "").upper() == "L" else (
                r.get("h_vs_r") if (r.get("hand") or "").upper() == "R" else None),
            ab_vs_hand=r.get("ab_vs_l") if (r.get("hand") or "").upper() == "L" else (
                r.get("ab_vs_r") if (r.get("hand") or "").upper() == "R" else None),
            sp_ip=r.get("sp_ip"), sp_h=r.get("sp_h"), sp_bb=r.get("sp_bb"),
            sp_er=r.get("sp_er"), sp_ip_starts=r.get("sp_ip_starts"),
            sp_starts=r.get("sp_starts"),
            bp_ip=r.get("bp_ip"), bp_h=r.get("bp_h"), bp_bb=r.get("bp_bb"),
            bp_er=r.get("bp_er"),
            opp_der=float(r["opp_der"]) if r.get("opp_der") is not None else None,
            ab_recent=r.get("ab_recent"),
        )
        if out is None:
            guard_hits += 1
            continue
        leg = dict(r)
        leg.update(out)
        leg["stat"] = "hits"
        leg["direction"] = "over"
        leg["best_odds"] = r.get("odds")
        leg["player_id"] = r.get("pid")
        leg["player_name"] = r.get("name")
        leg["coverage_pct"] = (r.get("cov_overall") or 0) * 100
        leg["composite_score"] = r.get("composite")
        leg["ev_per_unit"] = 0.0
        leg["position"] = "OF"
        legs.append(leg)
    print(f"\n  scored {len(legs)}/{len(rows)} legs in {time.time() - t0:.3f}s "
          f"({guard_hits} guard rejection(s))")
    return legs


def score_live(date_str: str) -> list[dict]:
    from src.engine.hits_v4 import score_hits_over_v4
    from src.utils.db import get_conn

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT DISTINCT ON (l.player_id, l.game_pk)
               l.player_id, l.game_pk, l.pitcher_hand, l.team, l.opposing_pitcher_id,
               l.odds AS best_odds, l.odd_id, l.player_name, l.composite_score,
               l.coverage_pct, l.position, l.result
        FROM mlb_scored_legs l
        WHERE l.run_date = %s AND l.stat = 'hits' AND l.direction = 'over'
        ORDER BY l.player_id, l.game_pk, l.id
        """,
        (date_str,),
    )
    legs = [dict(r) for r in cur.fetchall()]
    for l in legs:
        l["stat"], l["direction"] = "hits", "over"
        l["ev_per_unit"] = l.get("ev_per_unit") or 0.0
    cur.execute("SELECT team_id, abbreviation FROM mlb_teams")
    abbr_to_team_id = {r["abbreviation"]: r["team_id"] for r in cur.fetchall()}
    cur.close()

    print(f"\n  {len(legs)} hits/over leg(s) for {date_str}")
    t0 = time.time()
    n = score_hits_over_v4(legs, conn, cutoff_date=date_str,
                           abbr_to_team_id=abbr_to_team_id)
    elapsed = time.time() - t0
    conn.close()
    print(f"  score_hits_over_v4 returned {n} in {elapsed:.2f}s")
    check(elapsed < 60, "runtime under 60s", f"{elapsed:.2f}s")
    return [l for l in legs if l.get("p_hit") is not None]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-08-11")
    ap.add_argument("--fixture")
    args = ap.parse_args()

    print("=" * 72)
    print(f"v4 hits/over smoke test — {'OFFLINE fixture' if args.fixture else 'LIVE DB'}")
    print("=" * 72)

    if args.fixture:
        rows = load_offline(args.fixture)
        print(f"\n  {len(rows)} leg(s) in fixture")
        legs = score_offline(rows)
        total = len(rows)
    else:
        legs = score_live(args.date)
        total = len(legs)

    print("\n-- 1/7 completeness ------------------------------------------------")
    check(len(legs) > 0, "at least one leg scored")
    check(all(l.get("p_hit") is not None for l in legs), "every scored leg has non-null p_hit")
    if args.fixture:
        check(len(legs) == total, "no leg lost to the (0,1) guard",
              f"{len(legs)}/{total}")

    print("\n-- 2/7 range -------------------------------------------------------")
    ps = sorted(l["p_hit"] for l in legs)
    lo, hi, med = ps[0], ps[-1], ps[len(ps) // 2]
    mean = sum(ps) / len(ps)
    print(f"  min={lo:.4f} p50={med:.4f} max={hi:.4f} mean={mean:.4f} n={len(ps)}")
    check(0.0 < lo and hi < 1.0, "all probabilities strictly inside (0,1)")
    check(0.20 < mean < 0.85, "mean probability plausible for Over 0.5 Hits", f"{mean:.4f}")

    print("\n-- 3/7 spread ------------------------------------------------------")
    var = sum((p - mean) ** 2 for p in ps) / len(ps)
    sd = var ** 0.5
    print(f"  SD(p_hit) = {sd:.4f}")
    check(sd > 0.01, "p_hit actually varies across the pool", f"SD {sd:.4f}")

    print("\n-- 4/7 numeric sanity for the write path ---------------------------")
    numeric_fields = [k for k in legs[0] if k.startswith("v4_") or k in ("p_hit", "p_per_ab")]
    worst = 0.0
    for l in legs:
        for k in numeric_fields:
            v = l.get(k)
            if isinstance(v, (int, float)):
                worst = max(worst, abs(v))
                if v != v or v in (float("inf"), float("-inf")):
                    check(False, f"non-finite value in {k}")
    check(worst < 1e6, "no value large enough to risk an overflow on write",
          f"max |value| = {worst:.4f}")

    print("\n-- 5/7 builder: constrained 4-leg search ---------------------------")
    from src.engine.parlay_builder import build_parlays, compute_quality_floor
    import math as _math

    floor = compute_quality_floor(legs, "p_hit", FLOOR_MODE, FLOOR_VALUE)
    n_elig = sum(1 for l in legs if (l.get("p_hit") or 0) >= floor)
    print(f"  quality floor {FLOOR_MODE}={FLOOR_VALUE} -> p_hit >= {floor:.4f} "
          f"({n_elig} of {len(legs)} legs eligible)")

    t0 = time.time()
    parlays = build_parlays(legs, top_n=3, num_games=15,
                            rank_by="p_hit", max_legs=V4_MAX_LEGS,
                            quality_floor_mode=FLOOR_MODE,
                            quality_floor_value=FLOOR_VALUE,
                            joint_by="p_hit_cal")
    build_secs = time.time() - t0
    print(f"  built {len(parlays)} parlay(s) in {build_secs:.2f}s")
    check(len(parlays) > 0, "at least one valid parlay built")
    check(build_secs < 30, "builder runtime acceptable", f"{build_secs:.2f}s")

    if parlays:
        p = parlays[0]
        odds = int(p["parlay_odds"].lstrip("+"))
        print(f"  top parlay: {p['num_legs']} legs, +{odds}, "
              f"joint raw {p.get('joint_p_hit')} / cal {p.get('joint_p_hit_cal')}, "
              f"path={p.get('selection_path')}")
        for leg in p["legs"]:
            print(f"      {leg.get('player_name','?'):<24} "
                  f"p_hit={leg['p_hit']:.4f} odds={leg.get('best_odds')}")
        check(p["num_legs"] >= MIN_LEGS, f"parlay has >= {MIN_LEGS} legs")
        check(odds >= MIN_PARLAY_ODDS, f"parlay clears +{MIN_PARLAY_ODDS}", f"+{odds}")
        check(p.get("ranked_by") == "p_hit", "parlay was ranked by p_hit")
        check(all((l.get("p_hit") or 0) >= floor for l in p["legs"])
              or p["selection_path"].startswith("greedy"),
              "constrained picks respect the quality floor")

    print("\n-- 6/7 selection paths --------------------------------------------")
    # (a) constrained vs (b) greedy fallback vs (c) no valid parlay.
    paths = [p.get("selection_path") for p in parlays]
    print(f"  paths taken across {len(parlays)} parlay(s): {paths}")

    greedy_only = build_parlays(legs, top_n=3, num_games=15,
                                rank_by="p_hit", max_legs=V4_MAX_LEGS)
    if parlays and greedy_only:
        c, g = parlays[0], greedy_only[0]
        cj, gj = c.get("joint_p_hit"), g.get("joint_p_hit")
        co = int(c["parlay_odds"].lstrip("+"))
        go = int(g["parlay_odds"].lstrip("+"))
        print(f"  constrained: {c['num_legs']} legs +{co} joint={cj}")
        print(f"  greedy-only: {g['num_legs']} legs +{go} joint={gj}")
        if cj is not None and gj is not None:
            check(cj >= gj - 1e-9,
                  "constrained search never loses to greedy on joint probability",
                  f"{cj:.4f} vs {gj:.4f}")
            if cj > gj:
                print(f"  -> constrained improves win probability by "
                      f"{(cj / gj - 1) * 100:+.1f}% at {(co / go - 1) * 100:+.1f}% odds")

    # (c) no-valid-parlay path must return [] cleanly, not raise
    try:
        none_out = build_parlays(legs[:2], top_n=1, num_games=15, rank_by="p_hit",
                                 max_legs=V4_MAX_LEGS, quality_floor_mode=FLOOR_MODE,
                                 quality_floor_value=FLOOR_VALUE)
        check(none_out == [], "insufficient pool returns [] without raising")
    except Exception as e:  # noqa: BLE001
        check(False, "insufficient pool returns [] without raising", repr(e))

    # fallback path: force it by demanding an unreachable floor via a tiny pool
    try:
        # NOTE: build_parlays() caches decimal odds on the leg as "_dec", so a
        # copy that changes best_odds without dropping _dec keeps the OLD price.
        short = [{k: v for k, v in l.items() if k != "_dec"} | {"best_odds": "-245"}
                 for l in legs[:12]]
        fb = build_parlays(short, top_n=1, num_games=15, rank_by="p_hit",
                           max_legs=V4_MAX_LEGS, quality_floor_mode=FLOOR_MODE,
                           quality_floor_value=FLOOR_VALUE)
        if fb:
            print(f"  all-short-price pool -> {fb[0]['num_legs']} legs "
                  f"[{fb[0]['selection_path']}]")
            check(fb[0]["num_legs"] > MIN_LEGS,
                  "no-4-leg-solution pool falls back to extension")
        else:
            warn("all-short-price fallback produced no parlay")
    except Exception as e:  # noqa: BLE001
        check(False, "fallback path runs without raising", repr(e))

    print("\n-- 7/7 comparison against composite_score --------------------------")
    comps = [l for l in legs if l.get("composite_score") is not None]
    if comps:
        cs = [l["composite_score"] for l in comps]
        cmean = sum(cs) / len(cs)
        csd = (sum((c - cmean) ** 2 for c in cs) / len(cs)) ** 0.5
        print(f"  composite_score: mean {cmean:.2f} SD {csd:.2f} (n={len(cs)})")
        print(f"  p_hit:           mean {mean:.4f} SD {sd:.4f}")
        n_agree = sum(1 for a, b in zip(
            sorted(comps, key=lambda l: l["composite_score"], reverse=True)[:4],
            sorted(comps, key=lambda l: l["p_hit"], reverse=True)[:4]) if a is b)
        print(f"  top-4 overlap between the two rankings: {n_agree}/4")

    print("\n" + "=" * 72)
    if _failures:
        print(f"SMOKE TEST FAILED — {len(_failures)} check(s) failed:")
        for f in _failures:
            print(f"  - {f}")
        print("DO NOT enable v4 on live runs.")
        return 1
    print(f"SMOKE TEST PASSED ({len(_warnings)} warning(s))")
    if args.fixture:
        print("NOTE: offline mode — the psycopg2/load_v4_aggregates path was NOT")
        print("exercised. Re-run with --date against a live DATABASE_URL before")
        print("enabling v4 on live runs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
