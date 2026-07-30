"""
verify_sgo_billing.py — Empirical verification of SGO billing granularity and
/events response completeness (Task 1 of the SGO capture handoff).

Why this needed a real test rather than trusting mlb_sgo_request_log history:
mlb_sgo_request_log.entities_consumed is computed LOCALLY as
`len(response['data'])` inside sportsgameodds.py's _sgo_get() (see that
file — this is our own code's count of events returned, not something SGO's
API asserts is what it billed us for). That local count tracking the day's
game count (9-16) across months of logs is expected almost by construction,
since /events returns one object per game/event regardless of how many
markets are nested inside each one's `odds` dict — it does NOT by itself
distinguish per-event from per-market billing, because it never counted
markets at all.

The actual test: call SGO's own account-level usage counter
(/account/usage → data.rateLimits.per-month.current-entities) immediately
before and immediately after ONE /events call, and see whether the delta
matches the number of EVENTS returned or something much larger (the number
of MARKETS returned, summed across all events, which could be 10-50x higher
given alt lines).

Also checks response completeness: does includeAltLines=true with no market
filter actually return a market for every player with a posted line across
the 5 target categories, or is there a smaller default subset applied?

Usage:
    python -m scripts.verify_sgo_billing
    python -m scripts.verify_sgo_billing --date 2026-07-30

Environment variables required: SPORTSGAMEODDS_API_KEY, DATABASE_URL
"""
from __future__ import annotations

import argparse
import json
from datetime import date

import requests

from src.apis.sportsgameodds import BASE_URL, API_KEY, get_todays_games, get_player_props, get_totals_props

# The 5 target market categories from the handoff, mapped to how we'd detect
# them in a parsed event's odds dict / our own parsing functions.
_TARGET_STAT_PREFIXES = {
    "pitcher_strikeouts": ("pitching_strikeouts",),
    "batter_hits": ("batting_hits",),
    "batter_strikeouts": ("batting_strikeouts",),
    "batter_total_bases": ("batting_totalBases",),
}


def _get_usage() -> dict:
    r = requests.get(f"{BASE_URL}/account/usage", params={"apiKey": API_KEY}, timeout=10)
    r.raise_for_status()
    data = r.json().get("data", {})
    monthly = data.get("rateLimits", {}).get("per-month", {})
    return {
        "current_entities": monthly.get("current-entities"),
        "max_entities": monthly.get("max-entities"),
        "raw": monthly,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=date.today().isoformat())
    args = ap.parse_args()

    print(f"[verify] Target date: {args.date}")
    print()

    print("[verify] Step 1: usage BEFORE the test call")
    before = _get_usage()
    print(f"  current-entities: {before['current_entities']}  (cap: {before['max_entities']})")
    print()

    print("[verify] Step 2: making ONE /events call (includeAltLines=true, no market filter)")
    events = get_todays_games(date=args.date)
    n_events = len(events)
    print(f"  events returned: {n_events}")
    print()

    print("[verify] Step 3: usage AFTER the test call")
    after = _get_usage()
    print(f"  current-entities: {after['current_entities']}  (cap: {after['max_entities']})")
    print()

    if isinstance(before["current_entities"], (int, float)) and isinstance(after["current_entities"], (int, float)):
        delta = after["current_entities"] - before["current_entities"]
        print(f"[verify] DELTA (billed this call, per SGO's own account counter): {delta}")
        print(f"[verify] events returned this call: {n_events}")
        if n_events:
            print(f"[verify] delta / events ratio: {delta / n_events:.2f}")
    else:
        delta = None
        print("[verify] Could not compute delta — current-entities missing or non-numeric on one side "
              "(possibly 'unlimited' tier). Raw usage payloads printed above.")

    print()
    print("[verify] Step 4: market count within the returned events (for comparison against the delta)")
    total_markets = 0
    per_event_market_counts = []
    for ev in events:
        odds = ev.get("odds", {}) or {}
        total_markets += len(odds)
        per_event_market_counts.append(len(odds))
    print(f"  total distinct odds/market keys across all {n_events} events: {total_markets}")
    if per_event_market_counts:
        print(f"  per-event market count: min={min(per_event_market_counts)} "
              f"max={max(per_event_market_counts)} avg={total_markets / len(per_event_market_counts):.0f}")
    if delta is not None and total_markets:
        print(f"  delta / total_markets ratio: {delta / total_markets:.4f}")

    print()
    print("[verify] Step 5: response completeness check — target market coverage")
    for label, prefixes in _TARGET_STAT_PREFIXES.items():
        players_with_market = set()
        for ev in events:
            odds = ev.get("odds", {}) or {}
            for k, v in odds.items():
                if any(k.startswith(p) for p in prefixes) and "MLB" in k:
                    pname = (v or {}).get("playerID") or k
                    players_with_market.add(pname)
        print(f"  {label}: {len(players_with_market)} distinct players with a posted market")

    game_total_props = sum(len(get_totals_props(ev)) for ev in events)
    print(f"  game_lines (moneyline/spread/total legs parsed via get_totals_props): {game_total_props}")
    if game_total_props == 0 and events:
        print("  [debug] get_totals_props() returned 0 -- get_totals_props() is not called anywhere")
        print("  [debug] else in the codebase (confirmed via grep), so this may be stale/never-validated")
        print("  [debug] parsing logic rather than a real absence of game-total markets. Dumping raw")
        print("  [debug] odds keys from event 0 that look game-level (contain 'game', 'ml', 'spread',")
        print("  [debug] 'total', 'ou', or 'runs') to check the actual live key format:")
        sample_odds = (events[0].get("odds", {}) or {})
        game_level_keys = [
            k for k in sample_odds
            if any(tok in k.lower() for tok in ("game-ml", "game-sp", "all-game", "home-game", "away-game"))
        ]
        for k in sorted(game_level_keys)[:20]:
            print(f"    {k}")
        print(f"  [debug] {len(game_level_keys)} total game-level-looking keys found in event 0's odds dict")

    print()
    print("[verify] Step 6: pagination/truncation check")
    for i, ev in enumerate(events[:1]):
        print(f"  sample event top-level keys: {sorted(ev.keys())}")
    print(f"  events returned ({n_events}) vs. requested limit (20) — "
          f"{'AT LIMIT, possible truncation, investigate' if n_events >= 20 else 'under limit, no truncation signal'}")

    print()
    print("[verify] DONE. Report the DELTA, events-returned, and total_markets numbers back before proceeding to Task 3.")


if __name__ == "__main__":
    main()
