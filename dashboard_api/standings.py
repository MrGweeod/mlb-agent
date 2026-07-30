"""
dashboard_api/standings.py — MLB.com-style standings table for the Diamond
Line dashboard, sourced from the new reference schema (mlb_team_standings +
mlb_team_standings_splits, populated by scripts/backfill_reference_snapshots.py
and scripts/daily_reference_refresh.py) rather than a live API call.

Reuses the shared src/utils/db.py get_conn() — same pattern as queries.py.

`wcgb` sign convention: scripts/backfill_reference_snapshots.py stores a
NEGATIVE wcgb for "holds a wildcard spot, this many games clear of the
cutoff" (MLB.com displays this as "+X.X") and a positive value for "chasing
a spot, this many games back". _fmt_gb() below reconstructs the "+" display
from the sign. games_back (division) never goes negative — the division
leader is always "-", per MLB's own convention — so this is a no-op there.
"""
from src.utils.db import get_conn

# MLB.com's column order for the "wide" splits section.
_SPLIT_COLUMNS = [
    ("extra_innings", "XTRA"),
    ("one_run", "1 RUN"),
    ("day", "DAY"),
    ("night", "NIGHT"),
    ("grass", "GRASS"),
    ("turf", "TURF"),
    ("vs_east", "EAST"),
    ("vs_central", "CENTRAL"),
    ("vs_west", "WEST"),
    ("vs_al", "AL/NL"),  # AL/NL is really two values; see _al_nl_combined below
    ("vs_rhp", "VS. R"),
    ("vs_lhp", "VS. L"),
]


def _fmt_gb(v) -> str:
    if v is None:
        return "-"
    v = float(v)
    if v == 0.0:
        return "-"
    return f"+{abs(v):.1f}" if v < 0 else f"{v:.1f}"


def _fmt_wl(split: dict | None) -> str:
    if not split or split.get("wins") is None or split.get("losses") is None:
        return "-"
    return f"{split['wins']}-{split['losses']}"


def get_standings() -> dict:
    """
    Returns {"as_of_date": "...", "divisions": [{"name": ..., "teams": [...]}]}
    grouped in MLB.com order (AL East/Central/West, NL East/Central/West),
    each team sorted by win_pct descending within its division.
    """
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT max(as_of_date) AS d FROM mlb_team_standings")
    as_of = cur.fetchone()["d"]
    if as_of is None:
        cur.close()
        conn.close()
        return {"as_of_date": None, "divisions": []}

    cur.execute(
        """
        SELECT s.team_id, s.wins, s.losses, s.win_pct, s.division_rank,
               s.games_back, s.wcgb, s.streak,
               t.name, t.abbreviation, t.division, t.league
        FROM mlb_team_standings s
        JOIN mlb_teams t ON t.team_id = s.team_id
        WHERE s.as_of_date = %s
        ORDER BY t.division, s.win_pct DESC NULLS LAST
        """,
        (as_of,),
    )
    team_rows = [dict(r) for r in cur.fetchall()]

    cur.execute(
        """
        SELECT team_id, split_type, wins, losses, pct
        FROM mlb_team_standings_splits
        WHERE as_of_date = %s
        """,
        (as_of,),
    )
    splits_by_team: dict[int, dict[str, dict]] = {}
    for row in cur.fetchall():
        splits_by_team.setdefault(row["team_id"], {})[row["split_type"]] = dict(row)

    cur.close()
    conn.close()

    divisions: dict[str, list[dict]] = {}
    for t in team_rows:
        splits = splits_by_team.get(t["team_id"], {})
        al = splits.get("vs_al")
        nl = splits.get("vs_nl")
        # Show the OTHER league's record (an AL team's meaningful cross-league
        # number is its NL record, and vice versa) — matches MLB.com's single
        # "AL/NL" column, which always shows interleague record.
        al_nl = nl if t["league"] == "American League" else al

        shaped = {
            "name": t["name"],
            "abbreviation": t["abbreviation"],
            "wins": t["wins"],
            "losses": t["losses"],
            "pct": round(float(t["win_pct"]), 3) if t["win_pct"] is not None else None,
            "gb": _fmt_gb(t["games_back"]),
            "wcgb": _fmt_gb(t["wcgb"]),
            "streak": t["streak"],
            "xtra": _fmt_wl(splits.get("extra_innings")),
            "oneRun": _fmt_wl(splits.get("one_run")),
            "day": _fmt_wl(splits.get("day")),
            "night": _fmt_wl(splits.get("night")),
            "grass": _fmt_wl(splits.get("grass")),
            "turf": _fmt_wl(splits.get("turf")),
            "east": _fmt_wl(splits.get("vs_east")),
            "central": _fmt_wl(splits.get("vs_central")),
            "west": _fmt_wl(splits.get("vs_west")),
            "alNl": _fmt_wl(al_nl),
            "vsR": _fmt_wl(splits.get("vs_rhp")),
            "vsL": _fmt_wl(splits.get("vs_lhp")),
        }
        divisions.setdefault(t["division"], []).append(shaped)

    # MLB.com ordering
    order = [
        "American League East", "American League Central", "American League West",
        "National League East", "National League Central", "National League West",
    ]
    result = [{"name": d, "teams": divisions[d]} for d in order if d in divisions]
    # Any division name we didn't anticipate still shows up, just at the end.
    for d, teams in divisions.items():
        if d not in order:
            result.append({"name": d, "teams": teams})

    return {"as_of_date": as_of.isoformat() if hasattr(as_of, "isoformat") else str(as_of), "divisions": result}
