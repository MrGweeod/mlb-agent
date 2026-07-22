"""
dashboard_api/odds_extra.py — moneyline/run-line extraction for the Games
card. Kept out of src/apis/sportsgameodds.py (the production file) because
mlb-agent has never otherwise fetched moneyline/spread markets (it's a
player-props parlay agent).

Read live at request time from the same SGO event object build_dashboard()
already fetches for games/pitchers/batters — not persisted to Supabase.
(If a future feature needs historical moneyline/spread tracking, e.g. CLV
analysis, that's a separate schema/pipeline decision, not needed here.)

Keys confirmed 2026-07-22 against a live event via the diagnostic fallback
this file used to carry (see git history) — the "unclaimed odds keys" log
showed 'points-away-game-ml-away' / 'points-home-game-ml-home' and
'points-away-game-sp-away' / 'points-home-game-sp-home', following the same
'{stat}-{scope}-game-{market}-{direction}' convention as the confirmed
get_totals_props() keys in src/apis/sportsgameodds.py, but with "away"/"home"
in the scope position rather than "all".
"""

_ML_KEYS = {"away": "points-away-game-ml-away", "home": "points-home-game-ml-home"}
_SP_KEYS = {"away": "points-away-game-sp-away", "home": "points-home-game-sp-home"}


def get_moneyline_and_spread(game) -> dict:
    odds = game.get('odds', {}) or {}
    result = {
        "ml": {"away": None, "home": None},
        "rl": {"awayLine": None, "awayOdds": None, "homeLine": None, "homeOdds": None},
    }

    for side, k in _ML_KEYS.items():
        mkt = odds.get(k)
        if not mkt:
            continue
        dk = mkt.get('byBookmaker', {}).get('draftkings', {})
        if dk.get('available') and dk.get('odds') is not None:
            result["ml"][side] = int(dk['odds'])

    for side, k in _SP_KEYS.items():
        mkt = odds.get(k)
        if not mkt:
            continue
        dk = mkt.get('byBookmaker', {}).get('draftkings', {})
        if not dk.get('available'):
            continue
        line_field = "awayLine" if side == "away" else "homeLine"
        odds_field = "awayOdds" if side == "away" else "homeOdds"
        if dk.get('spread') is not None:
            result["rl"][line_field] = float(dk['spread'])
        if dk.get('odds') is not None:
            result["rl"][odds_field] = int(dk['odds'])

    return result
