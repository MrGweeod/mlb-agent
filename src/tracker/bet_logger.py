"""
bet_logger.py — MLB Parlay Bet Tracker
Logs parlays placed by the user to PostgreSQL and prompts for input after recommendations.
"""

import json
from datetime import date, datetime

from src.utils.db import get_conn, now_utc


def init_bet_tables():
    """Ensure mlb_parlays and mlb_parlay_legs tables exist (handled by init_db, kept for safety)."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS mlb_parlays (
            id SERIAL PRIMARY KEY,
            date TEXT NOT NULL,
            recommendation_id INTEGER REFERENCES mlb_recommendations(id),
            agent_odds TEXT,
            final_odds TEXT,
            stake REAL,
            status TEXT DEFAULT 'pending',
            payout REAL,
            notes TEXT,
            created_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS mlb_parlay_legs (
            id SERIAL PRIMARY KEY,
            parlay_id INTEGER NOT NULL,
            player_name TEXT,
            stat TEXT,
            line REAL,
            odds TEXT,
            coverage_pct REAL,
            result TEXT DEFAULT 'pending',
            FOREIGN KEY (parlay_id) REFERENCES mlb_parlays(id)
        )
    """)
    conn.commit()
    cur.close()
    conn.close()


def log_bet(parlay, final_odds, stake, notes=""):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO mlb_parlays (date, agent_odds, final_odds, stake, status, notes, created_at)
        VALUES (%s, %s, %s, %s, 'pending', %s, %s)
        RETURNING id
    """, (
        str(date.today()),
        str(parlay["parlay_odds"]),
        final_odds,
        stake,
        notes,
        datetime.now().isoformat()
    ))
    parlay_id = cur.fetchone()["id"]

    for leg in parlay["legs"]:
        cur.execute("""
            INSERT INTO mlb_parlay_legs (parlay_id, player_name, stat, line, odds, coverage_pct)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            parlay_id,
            leg.get("player_name", ""),
            leg.get("stat", ""),
            leg.get("best_line", 0),
            str(leg.get("best_odds", "")),
            leg.get("coverage_pct", 0)
        ))

    conn.commit()
    cur.close()
    conn.close()
    return parlay_id


def prompt_and_log(parlays):
    """
    Called after recommendations are shown.
    Asks user if they placed a bet and logs it if so.
    """
    print("\n" + "=" * 40)
    try:
        answer = input("Did you place a bet? (y/n): ").strip().lower()
    except EOFError:
        return  # non-interactive run (background process, pipe, etc.)
    if answer != "y":
        print("No bet logged.")
        return

    print("\nWhich parlay did you place?")
    for i, p in enumerate(parlays, 1):
        print("  {} — {} odds, {} legs".format(i, p["parlay_odds"], p["num_legs"]))

    while True:
        try:
            choice = int(input("Enter parlay number: ").strip())
            if 1 <= choice <= len(parlays):
                break
            print("Please enter a number between 1 and {}".format(len(parlays)))
        except ValueError:
            print("Please enter a valid number")

    parlay = parlays[choice - 1]

    final_odds = input("What odds did DraftKings show? (e.g. +750): ").strip()

    while True:
        try:
            stake = float(input("How much did you stake? ($): ").strip().replace("$", ""))
            break
        except ValueError:
            print("Please enter a valid amount")

    notes = input("Any notes? (press Enter to skip): ").strip()

    parlay_id = log_bet(parlay, final_odds, stake, notes)

    print("\n✅ Bet logged! (ID: {})".format(parlay_id))
    print("   Parlay: {} odds → {} (DraftKings)".format(parlay["parlay_odds"], final_odds))
    print("   Stake: ${:.2f}".format(stake))
    if notes:
        print("   Notes: {}".format(notes))


def get_recent_bets(days=30):
    """Returns bets placed in the last N days."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT p.*, STRING_AGG(pl.player_name || ' ' || pl.stat || ' o' || pl.line, ' | ') as legs_summary
        FROM mlb_parlays p
        LEFT JOIN mlb_parlay_legs pl ON p.id = pl.parlay_id
        WHERE p.date >= (CURRENT_DATE - INTERVAL '{} days')::TEXT
        GROUP BY p.id
        ORDER BY p.date DESC
    """.format(int(days)))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in rows]


# Initialize tables on import
init_bet_tables()

if __name__ == "__main__":
    print("Recent bets:")
    bets = get_recent_bets()
    if not bets:
        print("  No bets logged yet.")
    for bet in bets:
        print("  {} | {} → {} | ${} | {} | {}".format(
            bet["date"], bet["agent_odds"], bet["final_odds"],
            bet["stake"], bet["status"], bet["legs_summary"]
        ))
