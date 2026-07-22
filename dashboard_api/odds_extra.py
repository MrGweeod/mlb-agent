"""
dashboard_api/odds_extra.py — moneyline/run-line extraction for the Games
card. Kept out of src/apis/sportsgameodds.py (the production file) because:

⚠️ UNVERIFIED KEY NAMES. mlb-agent has never fetched moneyline/spread markets
(it's a player-props parlay agent) — nothing to copy. The keys below are a
best-guess extrapolation from the ONE confirmed pattern in sportsgameodds.py
(get_totals_props()'s 'runs-all-game-ou-over'/'under'), NOT a confirmed SGO
convention. Includes a diagnostic fallback that logs unclaimed odds keys on a
miss, so the first live run surfaces the real names instead of guessing again.

Action item: run once against a live event, check logs for `[SGO][diag]`
lines, hardcode the confirmed keys, delete the fallback scan.
"""

_KNOWN_NON_ML_SP_PREFIXES = ("runs-all-game-ou", "runs-home-game-ou", "runs-away-game-ou")


def get_moneyline_and_spread(game) -> dict:
    odds = game.get('odds', {}) or {}
    result = {
        "ml": {"away": None, "home": None},
        "rl": {"awayLine": None, "awayOdds": None, "homeLine": None, "homeOdds": None},
    }

    ml_candidates = {
        "away": ["points-all-game-ml-away", "moneyline-away"],
        "home": ["points-all-game-ml-home", "moneyline-home"],
    }
    sp_candidates = {
        "away": ["points-all-game-sp-away", "spread-away"],
        "home": ["points-all-game-sp-home", "spread-home"],
    }

    for side, keys in ml_candidates.items():
        for k in keys:
            mkt = odds.get(k)
            if not mkt:
                continue
            dk = mkt.get('byBookmaker', {}).get('draftkings', {})
            if dk.get('available') and dk.get('odds') is not None:
                result["ml"][side] = int(dk['odds'])
                break

    for side, keys in sp_candidates.items():
        for k in keys:
            mkt = odds.get(k)
            if not mkt:
                continue
            dk = mkt.get('byBookmaker', {}).get('draftkings', {})
            if dk.get('available'):
                line_field = "awayLine" if side == "away" else "homeLine"
                odds_field = "awayOdds" if side == "away" else "homeOdds"
                if dk.get('spread') is not None:
                    result["rl"][line_field] = float(dk['spread'])
                if dk.get('odds') is not None:
                    result["rl"][odds_field] = int(dk['odds'])
                break

    if result["ml"]["away"] is None and result["ml"]["home"] is None:
        unclaimed = [k for k in odds.keys() if not k.startswith(_KNOWN_NON_ML_SP_PREFIXES)]
        if unclaimed:
            print(f"[SGO][diag] moneyline/spread keys not matched. Unclaimed odds keys: {sorted(unclaimed)}")

    return result
