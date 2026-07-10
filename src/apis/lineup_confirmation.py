"""
lineup_confirmation.py — Event-driven lineup confirmation worker.

Architecture:
  drain_due_lineup_checks()     called every LINEUP_DRAIN_INTERVAL_MINUTES from server.py
    └── run_lineup_check(row)   fetches lineups, annotates legs, triggers resolution
          └── run_confirmed_lineup_resolution()  rebuilds affected parlays if needed

Batting order format (confirmed against live statsapi responses 2026-06-11):
  liveData.boxscore.teams.{side}.battingOrder  →  list of player_id integers in slot order
  Slot = list index + 1 (1-9).  Empty list = lineup not yet posted.
  Individual player battingOrder field: "100"=slot1 … "900"=slot9 (subs use x01+).
  We use the list-index method as it is simpler and unambiguous.
"""
from __future__ import annotations

import traceback
from datetime import date, datetime, timedelta, timezone
from typing import Any

import statsapi

from src.utils.db import get_conn


# ABR aliases at the API boundary (per project architecture rule)
ABR_ALIASES: dict[str, str] = {
    "ATH": "OAK",
    "AZ":  "ARI",
}


# ── Drain loop ────────────────────────────────────────────────────────────────

def drain_due_lineup_checks() -> None:
    """
    Poll mlb_pending_lineup_checks for rows where trigger_at <= now() and
    status='pending'.  Atomically claim each row then call run_lineup_check().

    Safe to run concurrently — the status='pending' guard prevents double-claim.
    One failed row never blocks the rest of the slate.
    """
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        """
        SELECT id, run_date, start_time_group, game_pks, trigger_at, pass_number, check_type
        FROM mlb_pending_lineup_checks
        WHERE status = 'pending' AND trigger_at <= now()
        ORDER BY trigger_at
        """,
    )
    due_rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()

    if not due_rows:
        return

    print(f"[lineup_drain] {len(due_rows)} check(s) due")

    for row in due_rows:
        row_id = row["id"]

        # Atomically claim: only proceed if we flip the row from pending → running
        conn2 = get_conn()
        cur2  = conn2.cursor()
        cur2.execute(
            """
            UPDATE mlb_pending_lineup_checks
               SET status = 'running', fired_at = now()
             WHERE id = %s AND status = 'pending'
            """,
            (row_id,),
        )
        claimed = cur2.rowcount
        conn2.commit()
        cur2.close()
        conn2.close()

        if claimed == 0:
            # Another drain instance already claimed it — skip
            continue

        try:
            if row.get("check_type") == "clv":
                # CLV removed 2026-07-07: no SGO call; mark done with a note.
                # schedule_clv_checks() no longer inserts these rows, but handle
                # any that already exist in the queue without calling SGO.
                note = "clv-disabled: CLV tracking removed (no demonstrated predictive value, ~75% of SGO volume)"
            else:
                note = run_lineup_check(row)
            _finish_check(row_id, "done", note)
        except Exception as exc:
            tb = traceback.format_exc()[-500:]
            print(f"[lineup_drain] row {row_id} failed: {exc}")
            _finish_check(row_id, "failed", str(exc)[:400])


def _finish_check(row_id: int, status: str, note: str | None) -> None:
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        """
        UPDATE mlb_pending_lineup_checks
           SET status = %s, completed_at = now(), result_note = %s
         WHERE id = %s
        """,
        (status, note, row_id),
    )
    conn.commit()
    cur.close()
    conn.close()


# ── Lineup-check worker ───────────────────────────────────────────────────────

def run_lineup_check(row: dict) -> str:
    """
    For each game_pk in row, fetch the posted lineup and annotate legs.

    Returns a one-line result_note summary string.
    """
    from main import BATTING_ORDER_FAVORABLE

    run_date_str = str(row["run_date"])
    game_pks: list[int] = list(row["game_pks"])

    print(f"[lineup_check] run_date={run_date_str} pass={row.get('pass_number',1)} games={game_pks}")

    # ── Step 1: Build player→{in_lineup, slot} map per game ──────────────────
    game_player_maps: dict[int, dict[int, dict]] = {}   # game_pk → player_id → {in_lineup, slot}

    for game_pk in game_pks:
        try:
            resp = statsapi.get("game", {"gamePk": game_pk, "hydrate": "lineups"})
            boxscore = resp.get("liveData", {}).get("boxscore", {})
            teams    = boxscore.get("teams", {})

            player_map: dict[int, dict] = {}
            lineup_posted = False

            for side in ("away", "home"):
                batting_order: list[int] = teams.get(side, {}).get("battingOrder", [])
                if batting_order:
                    lineup_posted = True
                    for slot_idx, pid in enumerate(batting_order):
                        try:
                            player_map[int(pid)] = {
                                "in_lineup": True,
                                "batting_order_slot": slot_idx + 1,
                            }
                        except (ValueError, TypeError):
                            pass

            game_player_maps[game_pk] = {
                "players":        player_map,
                "lineup_posted":  lineup_posted,
            }

            status_str = f"{len(player_map)} players" if lineup_posted else "NOT posted"
            print(f"  [lineup_check] game_pk={game_pk}: {status_str}")

        except Exception as _e:
            print(f"  [lineup_check] game_pk={game_pk} fetch error: {_e} — skipping")
            game_player_maps[game_pk] = {"players": {}, "lineup_posted": False}

    # ── Step 2: Annotate mlb_scored_legs ─────────────────────────────────────
    legs_annotated = _annotate_scored_legs(
        run_date_str, game_player_maps, BATTING_ORDER_FAVORABLE
    )

    # ── Step 3: Annotate mlb_parlay_legs_v2 ──────────────────────────────────
    parlay_legs_annotated = _annotate_parlay_legs(
        run_date_str, game_player_maps, BATTING_ORDER_FAVORABLE
    )

    # ── Step 4: Collect affected parlays that need resolution ─────────────────
    scratched_count, oor_count = _count_bad_states(run_date_str, game_pks)
    affected_parlay_ids = _find_affected_parlays(run_date_str, game_pks)

    clr_result: dict = {}
    if affected_parlay_ids:
        print(
            f"  [lineup_check] {len(affected_parlay_ids)} parlay(s) contain SCRATCHED"
            f" legs — triggering resolution"
        )
        try:
            clr_result = run_confirmed_lineup_resolution(run_date_str, affected_parlay_ids)
        except Exception as _res_err:
            print(f"  [lineup_check] resolution failed (non-fatal): {_res_err}")

    resolved_count = clr_result.get("rebuilt", 0) + clr_result.get("kept", 0)
    note = (
        f"{len(game_pks)} games, {legs_annotated} legs annotated, "
        f"{scratched_count} scratched, {oor_count} out_of_range, "
        f"{resolved_count} parlay(s) resolved"
    )
    print(f"  [lineup_check] {note}")
    return note


# ── Annotation helpers ────────────────────────────────────────────────────────

def _lineup_check_status(
    pid: int,
    stat: str,
    direction: str,
    game_info: dict,
    favorable: dict[tuple, range],
) -> tuple[str, int | None]:
    """
    Return (lineup_check_status, batting_order_slot) for one player/leg.

    States:
      MISSING_LINEUP_CONFIRMATION  — lineup not yet posted for this game
      LINEUP_CONFIRMED             — in lineup + favorable slot (or unknown stat pair)
      BATTING_ORDER_OUT_OF_RANGE   — in lineup but slot outside favorable range
      SCRATCHED                    — lineup posted, player absent
    """
    if not game_info.get("lineup_posted"):
        return "MISSING_LINEUP_CONFIRMATION", None

    player_map: dict[int, dict] = game_info.get("players", {})
    player_info = player_map.get(pid)

    if player_info is None:
        return "SCRATCHED", None

    slot = player_info.get("batting_order_slot")
    favorable_range = favorable.get((stat, direction), range(1, 10))

    if slot is not None and slot not in favorable_range:
        return "BATTING_ORDER_OUT_OF_RANGE", slot

    return "LINEUP_CONFIRMED", slot


def _annotate_scored_legs(
    run_date_str: str,
    game_player_maps: dict[int, dict],
    favorable: dict[tuple, range],
) -> int:
    """Annotate mlb_scored_legs rows for games in this check. Returns count updated."""
    conn = get_conn()
    cur  = conn.cursor()

    # player_id in mlb_scored_legs is TEXT — cast to int for matching
    cur.execute(
        """
        SELECT id, player_id, stat, direction, game_pk
        FROM mlb_scored_legs
        WHERE run_date = %s
          AND game_pk = ANY(%s)
          AND player_id IS NOT NULL
        """,
        (run_date_str, list(game_player_maps.keys())),
    )
    legs = [dict(r) for r in cur.fetchall()]

    checked_at = datetime.utcnow()
    updated = 0

    for leg in legs:
        game_pk = int(leg["game_pk"])
        game_info = game_player_maps.get(game_pk, {"players": {}, "lineup_posted": False})

        try:
            pid = int(leg["player_id"])
        except (TypeError, ValueError):
            continue

        status, slot = _lineup_check_status(
            pid, leg["stat"], leg.get("direction", "over"), game_info, favorable
        )

        cur.execute(
            """
            UPDATE mlb_scored_legs
               SET lineup_check_status = %s,
                   batting_order       = %s,
                   lineup_checked_at   = %s
             WHERE id = %s
            """,
            (status, slot, checked_at, leg["id"]),
        )
        updated += 1

    conn.commit()
    cur.close()
    conn.close()
    return updated


def _annotate_parlay_legs(
    run_date_str: str,
    game_player_maps: dict[int, dict],
    favorable: dict[tuple, range],
) -> int:
    """Annotate mlb_parlay_legs_v2 rows for today's parlays. Returns count updated."""
    conn = get_conn()
    cur  = conn.cursor()

    # player_id in mlb_parlay_legs_v2 is INTEGER; game_id = game_pk
    cur.execute(
        """
        SELECT pl.id, pl.player_id, pl.stat, pl.direction, pl.game_id
        FROM mlb_parlay_legs_v2 pl
        JOIN mlb_parlay_recommendations_v2 pr ON pr.id = pl.parlay_id
        WHERE pr.run_date = %s
          AND pl.game_id = ANY(%s)
          AND pl.player_id IS NOT NULL
        """,
        (run_date_str, list(game_player_maps.keys())),
    )
    legs = [dict(r) for r in cur.fetchall()]

    checked_at = datetime.now(timezone.utc)
    updated = 0

    for leg in legs:
        game_pk = int(leg["game_id"])
        game_info = game_player_maps.get(game_pk, {"players": {}, "lineup_posted": False})

        try:
            pid = int(leg["player_id"])
        except (TypeError, ValueError):
            continue

        status, slot = _lineup_check_status(
            pid, leg["stat"], leg.get("direction", "over"), game_info, favorable
        )

        cur.execute(
            """
            UPDATE mlb_parlay_legs_v2
               SET lineup_check_status = %s,
                   batting_order       = %s,
                   lineup_checked_at   = %s
             WHERE id = %s
            """,
            (status, slot, checked_at, leg["id"]),
        )
        updated += 1

    conn.commit()
    cur.close()
    conn.close()
    return updated


def _count_bad_states(run_date_str: str, game_pks: list[int]) -> tuple[int, int]:
    """Return (scratched_count, out_of_range_count) from mlb_scored_legs for today."""
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        """
        SELECT lineup_check_status, COUNT(*) AS cnt
        FROM mlb_scored_legs
        WHERE run_date = %s
          AND game_pk = ANY(%s)
          AND lineup_check_status IN ('SCRATCHED', 'BATTING_ORDER_OUT_OF_RANGE')
        GROUP BY lineup_check_status
        """,
        (run_date_str, game_pks),
    )
    scratched = out_of_range = 0
    for row in cur.fetchall():
        if row["lineup_check_status"] == "SCRATCHED":
            scratched = row["cnt"]
        else:
            out_of_range = row["cnt"]
    cur.close()
    conn.close()
    return scratched, out_of_range


def _find_affected_parlays(run_date_str: str, game_pks: list[int]) -> list[int]:
    """
    Return parlay IDs (from mlb_parlay_recommendations_v2) that:
      - are today's non-superseded pending parlays
      - contain at least one leg in game_pks with status SCRATCHED or OUT_OF_RANGE
    """
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        """
        SELECT DISTINCT pr.id
        FROM mlb_parlay_recommendations_v2 pr
        JOIN mlb_parlay_legs_v2 pl ON pl.parlay_id = pr.id
        WHERE pr.run_date = %s
          AND pr.outcome = 'pending'
          AND pr.superseded_by_batch_id IS NULL
          AND pl.game_id = ANY(%s)
          AND pl.lineup_check_status = 'SCRATCHED'
        """,
        (run_date_str, game_pks),
    )
    ids = [row["id"] for row in cur.fetchall()]
    cur.close()
    conn.close()
    return ids


# ── Resolution run type ───────────────────────────────────────────────────────

def run_confirmed_lineup_resolution(run_date_str: str, affected_parlay_ids: list[int]) -> dict:
    """
    Resolve parlays whose legs contain SCRATCHED player(s).

    BATTING_ORDER_OUT_OF_RANGE is annotation-only (Jul 2, 2026) — only SCRATCHED
    triggers resolution.

    Scratch logic (Session 19):
      • All remaining legs' games are >1 hr out  → rebuild replacement parlay.
      • Any remaining leg's game is ≤1 hr out or started → reduce path:
          – Drop scratched leg(s): mark them void in mlb_parlay_legs_v2.
          – ≥3 survivors: update num_legs/total_odds, parlay stays pending.
          – <3 survivors: void the whole parlay (SCRATCHED_NO_REBUILD).
      • Second scratch on already-reduced parlay → same rule re-applied.
      • superseded_by_batch_id is set ONLY when a replacement parlay was actually inserted.
        Thin-pool and no-rebuild paths leave it NULL and use a distinct superseded_reason.

    Returns dict: {rebuilt, kept, thin_pool, voided_no_rebuild}
    """
    from main import (
        POOL_MIN_COVERAGE,
        POOL_MIN_ODDS,
        POOL_MAX_ODDS,
    )
    from src.engine.parlay_builder import build_parlays, TOTAL_LEGS
    from src.utils.sorting import sort_legs_by_game_time
    from src.utils.time_utils import now_et as _now_et

    now_et = _now_et()

    print(f"[clr] Starting confirmed_lineup_resolution for {len(affected_parlay_ids)} parlay(s)")

    # ── Step 1: Build replacement pool from upcoming scored legs ─────────────
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        """
        SELECT *
        FROM mlb_scored_legs
        WHERE run_date = %s
          AND game_start_time IS NOT NULL
          AND game_start_time::timestamptz > now()
          AND (lineup_check_status IN ('LINEUP_CONFIRMED', 'MISSING_LINEUP_CONFIRMATION')
               OR lineup_check_status IS NULL)
          AND composite_score IS NOT NULL
        """,
        (run_date_str,),
    )
    pool_rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()

    eligible_pool = []
    for leg in pool_rows:
        direction = (leg.get("direction") or "over").lower()
        cov_floor = 40.0 if direction == "under" else POOL_MIN_COVERAGE
        comp      = leg.get("composite_score") or 0
        if comp < cov_floor:
            continue
        try:
            odds_val = float(leg.get("odds") or 0)
        except (TypeError, ValueError):
            continue
        if not (POOL_MIN_ODDS <= odds_val <= POOL_MAX_ODDS):
            continue
        leg["best_odds"] = leg.get("odds")
        leg["best_line"] = leg.get("line")
        eligible_pool.append(leg)

    eligible_pool = [l for l in eligible_pool if l.get("stat") != "totalBases"]
    print(f"[clr] Replacement pool: {len(eligible_pool)} eligible upcoming legs (totalBases excluded)")

    # ── Step 2: Seconds until start for each game (DB-level, avoids TZ parsing) ─
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        """
        SELECT DISTINCT game_pk,
               EXTRACT(EPOCH FROM (game_start_time::timestamptz - now())) AS seconds_until_start
        FROM mlb_scored_legs
        WHERE run_date = %s
          AND game_pk IS NOT NULL
          AND game_start_time IS NOT NULL
        """,
        (run_date_str,),
    )
    game_seconds: dict[int, float] = {
        int(r["game_pk"]): float(r["seconds_until_start"] or 0)
        for r in cur.fetchall()
    }
    cur.close()
    conn.close()

    # ── Step 3: Fetch affected parlay details (include game_id/odds/outcome) ──
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        """
        SELECT pr.id, pr.rank, pr.batch_id,
               array_agg(json_build_object(
                   'leg_id',              pl.id,
                   'player_id',           pl.player_id,
                   'player_name',         pl.player_name,
                   'lineup_check_status', pl.lineup_check_status,
                   'stat',                pl.stat,
                   'direction',           pl.direction,
                   'game_id',             pl.game_id,
                   'odds',                pl.odds,
                   'outcome',             pl.outcome
               )) AS legs
        FROM mlb_parlay_recommendations_v2 pr
        JOIN mlb_parlay_legs_v2 pl ON pl.parlay_id = pr.id
        WHERE pr.id = ANY(%s)
        GROUP BY pr.id, pr.rank, pr.batch_id
        """,
        (affected_parlay_ids,),
    )
    affected_parlays = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()

    if not affected_parlays:
        print("[clr] No affected parlays found — nothing to resolve")
        return {"rebuilt": 0, "kept": 0, "thin_pool": 0, "voided_no_rebuild": 0}

    batch_id = f"clr_{run_date_str}_{now_et.strftime('%H%M')}"

    rebuilt           = 0
    kept              = 0
    thin_pool         = 0
    voided_no_rebuild = 0
    ONE_HOUR_SECONDS  = 3600.0
    used_replacement_player_ids: set[str] = set()

    for parlay in affected_parlays:
        parlay_id = parlay["id"]
        all_legs  = parlay["legs"]

        # Newly scratched legs (exclude ones already voided by a prior scratch on this parlay)
        bad_legs = [
            l for l in all_legs
            if l.get("lineup_check_status") == "SCRATCHED"
            and l.get("outcome") != "void"
        ]
        # Legs currently alive (not voided, not newly scratched)
        surviving_legs = [
            l for l in all_legs
            if l.get("outcome") != "void"
            and l.get("lineup_check_status") != "SCRATCHED"
        ]

        if not bad_legs:
            print(f"[clr] Parlay {parlay_id}: no new scratches — skipping")
            continue

        bad_leg_ids    = [l["leg_id"] for l in bad_legs]
        bad_player_ids = {str(l["player_id"]) for l in bad_legs}
        bad_reasons    = "; ".join(
            f"{l['player_name']} {l['lineup_check_status']}" for l in bad_legs
        )

        # Check whether any surviving leg's game is ≤1 hour from now / already started.
        # Unknown start time → treat as close (conservative: don't rebuild).
        any_game_close = False
        for leg in surviving_legs:
            gid     = leg.get("game_id")
            seconds = game_seconds.get(gid) if gid is not None else None
            if seconds is None or seconds <= ONE_HOUR_SECONDS:
                any_game_close = True
                break

        if any_game_close:
            # ── REDUCE PATH ──────────────────────────────────────────────────
            # Drop the scratched leg(s) only; keep parlay alive if ≥3 survive.
            _void_legs(bad_leg_ids)

            if len(surviving_legs) >= 3:
                _reduce_parlay(parlay_id, surviving_legs)
                kept += 1
                print(
                    f"[clr] Parlay {parlay_id}: dropped {len(bad_legs)} scratch(es), "
                    f"{len(surviving_legs)} survivors — parlay kept (SCRATCHED_NO_REBUILD)"
                )
            else:
                _void_parlay(parlay_id, f"SCRATCHED_NO_REBUILD: {bad_reasons}")
                voided_no_rebuild += 1
                print(
                    f"[clr] Parlay {parlay_id}: only {len(surviving_legs)} survivor(s) "
                    f"after scratch — voided (SCRATCHED_NO_REBUILD)"
                )
            continue

        # ── REBUILD PATH ─────────────────────────────────────────────────────
        # All remaining legs' games are >1 hr out — try a full replacement.
        available_pool = [
            leg for leg in eligible_pool
            if str(leg.get("player_id")) not in bad_player_ids
            and str(leg.get("player_id")) not in used_replacement_player_ids
        ]

        if len(available_pool) < TOTAL_LEGS:
            print(
                f"[clr] Pool too thin for parlay {parlay_id} "
                f"({len(available_pool)} legs < {TOTAL_LEGS} required) — voiding"
            )
            thin_pool += 1
            _void_parlay(parlay_id, f"THIN_POOL_NO_REBUILD: {bad_reasons}")
            continue

        candidates = build_parlays(available_pool, top_n=10, num_games=15)
        if not candidates:
            print(f"[clr] Builder produced no candidates for parlay {parlay_id} — voiding")
            thin_pool += 1
            _void_parlay(parlay_id, f"THIN_POOL_NO_REBUILD: {bad_reasons}")
            continue

        best             = candidates[0]
        replacement_legs = best["legs"]

        conn = get_conn()
        cur  = conn.cursor()

        coverages = [l.get("coverage_pct") for l in replacement_legs if l.get("coverage_pct")]
        avg_cov   = round(sum(coverages) / len(coverages), 3) if coverages else None
        evs       = [l.get("ev_per_unit") for l in replacement_legs if l.get("ev_per_unit")]
        avg_ev    = round(sum(evs) / len(evs), 4) if evs else None
        try:
            total_odds = int(best["parlay_odds"].lstrip("+"))
        except (ValueError, AttributeError):
            total_odds = None

        cur.execute(
            """
            INSERT INTO mlb_parlay_recommendations_v2
                (run_date, rank, total_odds, avg_coverage, avg_ev, num_legs,
                 outcome, source, batch_id, edge_percent)
            VALUES (%s, %s, %s, %s, %s, %s, 'pending', 'confirmed_lineup_resolution', %s, %s)
            RETURNING id
            """,
            (
                run_date_str,
                parlay["rank"],
                total_odds,
                avg_cov,
                avg_ev,
                len(replacement_legs),
                batch_id,
                best.get("avg_composite"),
            ),
        )
        new_parlay_id = cur.fetchone()["id"]

        for leg in sort_legs_by_game_time(replacement_legs):
            cur.execute(
                """
                INSERT INTO mlb_parlay_legs_v2
                    (parlay_id, player_id, player_name, team, stat, line,
                     direction, odds, composite_score, opponent_adjustment,
                     coverage, ev, game_id, opposing_pitcher_id,
                     opposing_pitcher_name, outcome,
                     lineup_check_status, batting_order, lineup_checked_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                        'pending', %s, %s, now())
                """,
                (
                    new_parlay_id,
                    leg.get("player_id"),
                    leg.get("player_name"),
                    leg.get("team"),
                    leg.get("stat"),
                    leg.get("best_line") or leg.get("line"),
                    leg.get("direction", "over"),
                    leg.get("best_odds") or leg.get("odds"),
                    leg.get("composite_score"),
                    leg.get("opponent_adjustment"),
                    leg.get("coverage_pct"),
                    leg.get("ev_per_unit"),
                    leg.get("game_pk"),
                    leg.get("opposing_pitcher_id"),
                    leg.get("opposing_pitcher_name"),
                    leg.get("lineup_check_status"),
                    leg.get("batting_order"),
                ),
            )

        conn.commit()
        cur.close()
        conn.close()

        # Only now set superseded_by_batch_id — a real replacement was inserted.
        _void_parlay(parlay_id, f"lineup_resolution: {bad_reasons}", batch_id=batch_id)
        used_replacement_player_ids.update(
            str(l.get("player_id")) for l in replacement_legs
        )
        rebuilt += 1
        print(
            f"[clr] Parlay {parlay_id} superseded by new parlay {new_parlay_id} "
            f"(batch={batch_id})"
        )

    print(
        f"[clr] Done: {rebuilt} rebuilt, {kept} kept-reduced, {thin_pool} thin-pool, "
        f"{voided_no_rebuild} voided-no-rebuild (batch={batch_id})"
    )
    return {
        "rebuilt":           rebuilt,
        "kept":              kept,
        "thin_pool":         thin_pool,
        "voided_no_rebuild": voided_no_rebuild,
    }


def _void_parlay(parlay_id: int, reason: str, *, batch_id: str | None = None) -> None:
    """
    Mark a parlay and all its legs void.

    batch_id: when provided, sets superseded_by_batch_id — use ONLY when a
              replacement parlay was actually inserted under that batch_id.
              When None (thin pool, no-rebuild, reduce-path), leaves
              superseded_by_batch_id NULL.
    """
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        """
        UPDATE mlb_parlay_recommendations_v2
           SET outcome                = 'void',
               superseded_by_batch_id = %s,
               superseded_reason      = %s
         WHERE id = %s
        """,
        (batch_id, reason, parlay_id),
    )
    cur.execute(
        "UPDATE mlb_parlay_legs_v2 SET outcome = 'void' WHERE parlay_id = %s",
        (parlay_id,),
    )
    conn.commit()
    cur.close()
    conn.close()


def _void_legs(leg_ids: list[int]) -> None:
    """
    Mark specific parlay legs void without touching the parent parlay record.
    Used in the reduce path to drop only the scratched leg(s).
    """
    if not leg_ids:
        return
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        "UPDATE mlb_parlay_legs_v2 SET outcome = 'void' WHERE id = ANY(%s)",
        (leg_ids,),
    )
    conn.commit()
    cur.close()
    conn.close()


def _reduce_parlay(parlay_id: int, surviving_legs: list[dict]) -> None:
    """
    Recalculate num_legs and total_odds on a parlay from its surviving legs.
    The parlay outcome remains 'pending' — only structural counts are updated.
    """
    from src.utils.odds_math import american_to_decimal

    num_legs: int       = len(surviving_legs)
    total_odds: int | None = None
    try:
        dec_product = 1.0
        for leg in surviving_legs:
            dec_product *= american_to_decimal(str(leg["odds"]))
        total_odds = int((dec_product - 1) * 100)
    except Exception:
        pass

    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        """
        UPDATE mlb_parlay_recommendations_v2
           SET num_legs   = %s,
               total_odds = %s
         WHERE id = %s
        """,
        (num_legs, total_odds, parlay_id),
    )
    conn.commit()
    cur.close()
    conn.close()
