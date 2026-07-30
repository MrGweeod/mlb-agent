"""
test_prop_legs_resolution.py — Isolated test for resolve_prop_legs_history()
using KNOWN outcomes from an already-backfilled, already-completed game
(2026-03-26, game_pk 823649: Freddy Peralta 7 K in the box score, Bo
Bichette 0-for-4), rather than waiting a full day for real capture +
resolution to flow through naturally.

Inserts synthetic pending rows with predictable expected outcomes, resolves
them, checks the result, then DELETES the synthetic rows it created —
leaves no test data behind in mlb_prop_legs_history.

Usage:
    python -m scripts.test_prop_legs_resolution

Environment variables required: DATABASE_URL
"""
from __future__ import annotations

from src.pipelines.prop_legs_capture import resolve_prop_legs_history
from src.utils.db import get_conn

GAME_PK = 823649           # 2026-03-26, home 121 (Peralta's team) vs away 134
PERALTA_ID = 642547        # pitcher, 7 K in this game (confirmed earlier this session)
BICHETTE_ID = 666182       # batter, 0-for-4 in this game
HOME_TEAM_ID = 121
AWAY_TEAM_ID = 134

# (label, row, expected_result)
TEST_CASES = [
    ("Peralta K's over 6.5 (actual 7 -> should WIN)",
     dict(player_id=PERALTA_ID, game_pk=GAME_PK, stat="strikeouts", line=6.5, direction="over",
          sportsbook="draftkings", market_scope="player", player_role="pitcher"),
     "won"),
    ("Peralta K's under 6.5 (actual 7 -> should LOSE)",
     dict(player_id=PERALTA_ID, game_pk=GAME_PK, stat="strikeouts", line=6.5, direction="under",
          sportsbook="draftkings", market_scope="player", player_role="pitcher"),
     "lost"),
    ("Bichette hits over 0.5 (actual 0 -> should LOSE)",
     dict(player_id=BICHETTE_ID, game_pk=GAME_PK, stat="hits", line=0.5, direction="over",
          sportsbook="draftkings", market_scope="player", player_role="batter"),
     "lost"),
    ("Bichette hits under 0.5 (actual 0 -> should WIN)",
     dict(player_id=BICHETTE_ID, game_pk=GAME_PK, stat="hits", line=0.5, direction="under",
          sportsbook="draftkings", market_scope="player", player_role="batter"),
     "won"),
    ("Home moneyline (home won 11-7 -> should WIN)",
     dict(player_id=None, game_pk=GAME_PK, stat="moneyline", line=0.0, direction="home",
          sportsbook="draftkings", market_scope="game", player_role=None),
     "won"),
    ("Away moneyline (away lost -> should LOSE)",
     dict(player_id=None, game_pk=GAME_PK, stat="moneyline", line=0.0, direction="away",
          sportsbook="draftkings", market_scope="game", player_role=None),
     "lost"),
    ("Game total over 15.5 (actual 18 runs -> should WIN)",
     dict(player_id=None, game_pk=GAME_PK, stat="total", line=15.5, direction="over",
          sportsbook="draftkings", market_scope="game", player_role=None),
     "won"),
]


def main():
    conn = get_conn()
    cur = conn.cursor()
    inserted_ids = []

    try:
        for label, row, _expected in TEST_CASES:
            cur.execute(
                """
                INSERT INTO mlb_prop_legs_history
                    (player_id, game_pk, stat, line, direction, sportsbook,
                     market_scope, player_role, result, odds_history)
                VALUES (%(player_id)s, %(game_pk)s, %(stat)s, %(line)s, %(direction)s, %(sportsbook)s,
                        %(market_scope)s, %(player_role)s, 'pending', '[]'::jsonb)
                RETURNING id
                """,
                row,
            )
            inserted_ids.append(cur.fetchone()["id"])
        conn.commit()
        print(f"[test] Inserted {len(inserted_ids)} synthetic pending rows")

        resolve_prop_legs_history(cur)
        conn.commit()

        print()
        print("[test] Results:")
        n_pass = 0
        for (label, _row, expected), row_id in zip(TEST_CASES, inserted_ids):
            cur.execute("SELECT result, actual_value FROM mlb_prop_legs_history WHERE id = %s", (row_id,))
            actual_row = cur.fetchone()
            got = actual_row["result"]
            ok = "PASS" if got == expected else "FAIL"
            n_pass += (ok == "PASS")
            print(f"  [{ok}] {label}: expected={expected} got={got} actual_value={actual_row['actual_value']}")

        print()
        print(f"[test] {n_pass}/{len(TEST_CASES)} passed")

    finally:
        if inserted_ids:
            cur.execute("DELETE FROM mlb_prop_legs_history WHERE id = ANY(%s)", (inserted_ids,))
            conn.commit()
            print(f"[test] Cleaned up {len(inserted_ids)} synthetic rows")
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
