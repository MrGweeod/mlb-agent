"""
dashboard_api/shape.py — builds {games, battersAll, pitchersAll} for
GET /api/dashboard.

Imports src.apis.mlb_stats and src.apis.sportsgameodds DIRECTLY — the real
production modules, not copies — because this now lives inside the mlb-agent
repo. dashboard_api/queries.py, season_stats.py, and odds_extra.py hold only
what's genuinely new for this dashboard.

Known assumptions (flagged, not silently baked in — verify against a live
run before trusting fully):
  - `position == 'P'` separates a pitcher's own strikeout-prop rows from
    batter strikeout ("1+ Ks") prop rows, both stat='strikeouts'. Unverified.
  - Pitcher `last5` kLine/result comes from joining each real last-5 start
    against mlb_scored_legs for that (pitcher_name, run_date, stat=
    'strikeouts'). No match → kLine/result are None, not fabricated.
  - Game `favML`/`sortMinutes` and the `network` field's national-broadcast-only
    coverage — see _build_games().
"""
from datetime import date as date_type

from src.apis import mlb_stats
from src.apis import sportsgameodds as sgo
from src.utils.time_utils import parse_game_start_et

from dashboard_api import queries
from dashboard_api import season_stats
from dashboard_api import odds_extra

SEASON = date_type.today().year

_INNING_STATE_ABBR = {"top": "TOP", "bottom": "BOT", "middle": "MID", "end": "END"}


def _format_time_et(raw_utc: str) -> str:
    """statsapi's game_datetime uses a trailing "Z" (e.g. "...T17:05:00Z"),
    which parse_game_start_et's docstring doesn't list as an accepted format
    (only " "-separated or explicit "+00:00") — normalize before parsing."""
    if not raw_utc:
        return ""
    try:
        normalized = raw_utc.replace("Z", "+00:00")
        return parse_game_start_et(normalized).strftime("%-I:%M %p ET")
    except ValueError:
        return ""


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "TH"
    else:
        suffix = {1: "ST", 2: "ND", 3: "RD"}.get(n % 10, "TH")
    return f"{n}{suffix}"


def _format_inning(current_inning, inning_state: str) -> str | None:
    if not current_inning or not inning_state:
        return None
    abbr = _INNING_STATE_ABBR.get(inning_state.lower(), inning_state.upper()[:3])
    return f"{abbr} {_ordinal(int(current_inning))}"


def _abbr(team_name: str) -> str:
    MAP = {
        "New York Yankees": "NYY", "Boston Red Sox": "BOS", "Toronto Blue Jays": "TOR",
        "Baltimore Orioles": "BAL", "Tampa Bay Rays": "TB", "Chicago White Sox": "CWS",
        "Cleveland Guardians": "CLE", "Detroit Tigers": "DET", "Kansas City Royals": "KC",
        "Minnesota Twins": "MIN", "Houston Astros": "HOU", "Los Angeles Angels": "LAA",
        "Oakland Athletics": "OAK", "Seattle Mariners": "SEA", "Texas Rangers": "TEX",
        "Atlanta Braves": "ATL", "Miami Marlins": "MIA", "New York Mets": "NYM",
        "Philadelphia Phillies": "PHI", "Washington Nationals": "WSH", "Chicago Cubs": "CHC",
        "Cincinnati Reds": "CIN", "Milwaukee Brewers": "MIL", "Pittsburgh Pirates": "PIT",
        "St. Louis Cardinals": "STL", "Arizona Diamondbacks": "ARI", "Colorado Rockies": "COL",
        "Los Angeles Dodgers": "LAD", "San Diego Padres": "SD", "San Francisco Giants": "SF",
    }
    return MAP.get(team_name, team_name[:3].upper())


def _build_games(run_date: str) -> tuple[list[dict], dict]:
    """`network` comes from statsapi's national_broadcasts field, which only
    covers national TV (ESPN, Fox, etc.) — most games are regional-only and
    will correctly show "" here since MLB Stats API doesn't expose regional
    broadcast data. Not a bug; confirmed 2026-07-22 (1 of 17 games that day
    had a populated value)."""
    schedule = mlb_stats.get_schedule(run_date)
    standings = mlb_stats.get_standings(SEASON)
    sgo_games_by_key = {}
    try:
        for g in sgo.get_todays_games():
            teams = g.get("teams", {})
            home = (teams.get("home", {}).get("names") or {}).get("short", "")
            away = (teams.get("away", {}).get("names") or {}).get("short", "")
            sgo_games_by_key[(away, home)] = g
    except Exception as e:
        print(f"[shape] sgo.get_todays_games() failed, proceeding with no odds: {e}")

    games = []
    lookup = {}
    for i, g in enumerate(schedule):
        away_abbr = _abbr(g.get("away_name", ""))
        home_abbr = _abbr(g.get("home_name", ""))

        ml_rl = {"ml": {"away": None, "home": None},
                 "rl": {"awayLine": None, "awayOdds": None, "homeLine": None, "homeOdds": None}}
        sgo_game = sgo_games_by_key.get((away_abbr, home_abbr))
        if sgo_game:
            try:
                ml_rl = odds_extra.get_moneyline_and_spread(sgo_game)
            except Exception as e:
                print(f"[shape] get_moneyline_and_spread failed for {away_abbr}@{home_abbr}: {e}")

        status_raw = (g.get("status") or "").lower()
        status = "final" if "final" in status_raw else ("live" if "in progress" in status_raw else "scheduled")

        shaped = {
            "id": i + 1,
            "status": status,
            "time": _format_time_et(g.get("game_datetime", "")),
            "inning": _format_inning(g.get("current_inning"), g.get("inning_state", "")) if status == "live" else None,
            "away": {
                "abbr": away_abbr, "record": standings.get(g.get("away_id"), ""),
                "pitcher": g.get("away_probable_pitcher", ""),
                "score": g.get("away_score") if status != "scheduled" else None,
            },
            "home": {
                "abbr": home_abbr, "record": standings.get(g.get("home_id"), ""),
                "pitcher": g.get("home_probable_pitcher", ""),
                "score": g.get("home_score") if status != "scheduled" else None,
            },
            "venue": g.get("venue_name", ""),
            "network": ", ".join(g.get("national_broadcasts") or []),
            "ml": ml_rl["ml"],
            "rl": ml_rl["rl"],
            "favML": abs(ml_rl["ml"]["away"] or ml_rl["ml"]["home"] or 0) or None,
            "sortMinutes": i,
            "_game_pk": g.get("game_id"),
        }
        games.append(shaped)
        lookup[g.get("game_id")] = shaped

    return games, lookup


def _split_by_direction(legs_for_stat: list[dict]) -> tuple[dict | None, dict | None]:
    over = next((l for l in legs_for_stat if l["direction"] == "over"), None)
    under = next((l for l in legs_for_stat if l["direction"] == "under"), None)
    return over, under


def _build_batter(player_legs: list[dict], game_lookup: dict) -> dict:
    first = player_legs[0]
    game_pk = first.get("game_pk")
    game = game_lookup.get(game_pk, {})
    game_label = f"{game.get('away', {}).get('abbr', '?')} @ {game.get('home', {}).get('abbr', '?')}"

    by_stat: dict[str, list[dict]] = {}
    for l in player_legs:
        by_stat.setdefault(l["stat"], []).append(l)

    hits_over, hits_under = _split_by_direction(by_stat.get("hits", []))
    tb_over, tb_under = _split_by_direction(by_stat.get("totalBases", []))
    so_over, _ = _split_by_direction(by_stat.get("strikeouts", []))

    stats = season_stats.get_batter_season_stats(int(first["player_id"]), SEASON) or {}
    gamelog_raw = mlb_stats.get_batter_game_log(int(first["player_id"]), SEASON)
    gamelog = [
        {
            "date": s.get("date", ""),
            "opp": _abbr((s.get("opponent") or {}).get("name", "")),
            "ab": s.get("stat", {}).get("atBats", 0),
            "h": s.get("stat", {}).get("hits", 0),
            "k": s.get("stat", {}).get("strikeOuts", 0),
            "tb": s.get("stat", {}).get("totalBases", 0),
        }
        for s in gamelog_raw[-10:][::-1]
    ]

    opp_pitcher_stats = None
    if first.get("opposing_pitcher_id") and first.get("pitcher_era") is not None:
        opp_pitcher_stats = {
            "era": float(first["pitcher_era"]) if first.get("pitcher_era") is not None else None,
            "k9": float(first["pitcher_k9"]) if first.get("pitcher_k9") is not None else None,
            "whip": None, "wins": None, "losses": None, "last5": [],
            # whip/W-L/last5 intentionally left out here to avoid an extra
            # API round-trip per batter card (~10/game) — see Pitchers-shape
            # cards below for the full stat line, one per starter (2/game).
        }

    return {
        "id": f"{game_pk}-{first['player_id']}",
        "gameId": game.get("id"),
        "gameLabel": game_label,
        "name": first["player_name"],
        "team": first.get("team", ""),
        "pos": first.get("position", ""),
        "opp": first.get("opponent", ""),
        "oppPitcher": first.get("pitcher_name", ""),
        "ba": stats.get("ba"), "kPct": stats.get("kPct"),
        "bbPct": stats.get("bbPct"), "obp": stats.get("obp"),
        "hitsLine": hits_over["line"] if hits_over else (hits_under["line"] if hits_under else None),
        "hitsOverOdds": float(hits_over["odds"]) if hits_over and hits_over.get("odds") else None,
        "hitsUnderOdds": float(hits_under["odds"]) if hits_under and hits_under.get("odds") else None,
        "hitsOverCov": hits_over.get("coverage_overall") if hits_over else None,
        "hitsUnderCov": hits_under.get("coverage_overall") if hits_under else None,
        "soOdds": float(so_over["odds"]) if so_over and so_over.get("odds") else None,
        "soCov": so_over.get("coverage_overall") if so_over else None,
        "tbLine": tb_over["line"] if tb_over else (tb_under["line"] if tb_under else None),
        "tbOverOdds": float(tb_over["odds"]) if tb_over and tb_over.get("odds") else None,
        "tbUnderOdds": float(tb_under["odds"]) if tb_under and tb_under.get("odds") else None,
        "tbOverCov": tb_over.get("coverage_overall") if tb_over else None,
        "tbUnderCov": tb_under.get("coverage_overall") if tb_under else None,
        "gamelog": gamelog,
        "oppPitcherStats": opp_pitcher_stats,
    }


def _build_pitcher(pitcher_id: str, pitcher_name: str, team: str, opp: str, game) -> dict:
    game_label = f"{game.get('away', {}).get('abbr', '?')} @ {game.get('home', {}).get('abbr', '?')}"
    stats = season_stats.get_pitcher_season_stats(int(pitcher_id), SEASON) or {}
    log = mlb_stats.get_pitcher_game_log(int(pitcher_id), SEASON)
    last5_starts = log[-5:][::-1]

    scored_by_date: dict[str, dict] = {}
    for d in {s.get("date", "") for s in last5_starts}:
        if not d:
            continue
        try:
            rows = queries.get_qualified_scored_legs(d, min_coverage=0)
            match = next(
                (r for r in rows if r.get("pitcher_name") == pitcher_name and r.get("stat") == "strikeouts"
                 and r.get("position") == "P"),
                None,
            )
            if match:
                scored_by_date[d] = match
        except Exception:
            pass

    last5 = []
    for s in last5_starts:
        d = s.get("date", "")
        stat = s.get("stat", {})
        matched = scored_by_date.get(d)
        last5.append({
            "date": d,
            "opp": _abbr((s.get("opponent") or {}).get("name", "")),
            "ip": stat.get("inningsPitched", 0),
            "er": stat.get("earnedRuns", 0),
            "k": stat.get("strikeOuts", 0),
            "kLine": matched.get("line") if matched else None,
            "result": matched.get("result") if matched else None,
        })

    return {
        "id": f"{game.get('_game_pk')}-{pitcher_id}",
        "gameId": game.get("id"),
        "gameLabel": game_label,
        "name": pitcher_name, "team": team, "opp": opp,
        "stats": {
            "era": stats.get("era"), "k9": stats.get("k9"), "whip": stats.get("whip"),
            "wins": stats.get("wins"), "losses": stats.get("losses"), "last5": last5,
        },
    }


def build_dashboard(run_date: str) -> dict:
    games, game_lookup = _build_games(run_date)
    legs = queries.get_qualified_scored_legs(run_date)

    batter_legs = [l for l in legs if l.get("position") != "P"]
    by_player: dict[tuple, list[dict]] = {}
    for l in batter_legs:
        by_player.setdefault((l.get("player_id"), l.get("game_pk")), []).append(l)
    battersAll = [_build_batter(v, game_lookup) for v in by_player.values() if v]

    pitchersAll = []
    seen_pitchers = set()
    for g in games:
        for side in ("away", "home"):
            pname = g[side]["pitcher"]
            if not pname or pname in seen_pitchers:
                continue
            seen_pitchers.add(pname)
            pid = next(
                (l.get("opposing_pitcher_id") for l in legs
                 if l.get("pitcher_name") == pname and l.get("opposing_pitcher_id")),
                None,
            )
            if not pid:
                continue
            team_abbr = g[side]["abbr"]
            opp_abbr = g["home"]["abbr"] if side == "away" else g["away"]["abbr"]
            pitchersAll.append(_build_pitcher(pid, pname, team_abbr, opp_abbr, g))

    for g in games:
        g.pop("_game_pk", None)

    return {"date": run_date, "games": games, "battersAll": battersAll, "pitchersAll": pitchersAll}
