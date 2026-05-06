"""
injury_context.py — Injury context check for MLB lineup consistency filter.

Distinguishes between:
  - 60-day IL placements (expanded role for replacement player — KEEP)
  - 10-day IL placements (temporary injury — replacement may be volatile)

Used by the lineup consistency filter to decide whether to void a leg
when a player's lineup consistency is low: if the low consistency is
explained by a team-mate being on the 60-day IL (expanded permanent role),
the player likely has a stable spot and should NOT be voided.
"""
from __future__ import annotations

import datetime
import statsapi


def get_player_position(player_id: int) -> str:
    """Return the player's primary position code (e.g. 'CF', 'SP', '1B')."""
    try:
        info = statsapi.player_stat_data(player_id, group="hitting", type="career")
        # Fallback: use lookup
        people = statsapi.lookup_player(str(player_id))
        if people:
            return people[0].get("primaryPosition", {}).get("abbreviation", "")
        return ""
    except Exception:
        return ""


def check_expanded_role_due_to_injury(
    player_id: int,
    team_abbr: str,
    today: str,
) -> dict:
    """
    Check if a player's expanded/inconsistent lineup role is explained by a
    team-mate being on the 60-day IL (which typically means the replacement
    player has a locked-in role for an extended period).

    Args:
        player_id:  MLB person ID of the prop player
        team_abbr:  Team abbreviation (e.g. 'NYY')
        today:      Date string 'YYYY-MM-DD'

    Returns:
        {
            "has_expanded_role": bool,
            "reason": str,          # human-readable explanation
            "il_type": str | None,  # '60-day' | '10-day' | None
        }
    """
    try:
        txns = statsapi.get(
            "transactions",
            {"startDate": today, "endDate": today},
        )
        entries = txns.get("transactions", [])
        sixty_day_il = []
        ten_day_il = []
        for txn in entries:
            txn_type = txn.get("typeCode", "")
            # IL placements have typeCode TRANSACTION_IL
            if txn_type != "TRANSACTION_IL":
                continue
            note = (txn.get("typeDesc") or "").lower()
            team = txn.get("toTeam") or txn.get("team") or {}
            team_name = (team.get("abbreviation") or "").upper()
            if team_name != team_abbr.upper():
                continue
            if "60" in note:
                sixty_day_il.append(txn)
            elif "10" in note:
                ten_day_il.append(txn)

        if sixty_day_il:
            return {
                "has_expanded_role": True,
                "reason": f"Team-mate on 60-day IL ({len(sixty_day_il)} placement(s)) — expanded role likely permanent",
                "il_type": "60-day",
            }
        if ten_day_il:
            return {
                "has_expanded_role": False,
                "reason": f"Team-mate on 10-day IL ({len(ten_day_il)} placement(s)) — role may be temporary",
                "il_type": "10-day",
            }
        return {
            "has_expanded_role": False,
            "reason": "No IL placements found for team today",
            "il_type": None,
        }
    except Exception as e:
        return {
            "has_expanded_role": False,
            "reason": f"Error checking IL context: {e}",
            "il_type": None,
        }
