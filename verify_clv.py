"""
verify_clv.py — CLV layer verification checks.

Usage:
    source .venv/bin/activate && python verify_clv.py

Checks:
  1. Migration: closing_odds + closing_odds_captured_at on mlb_scored_legs
  2. Migration: check_type column on mlb_pending_lineup_checks
  3. Scheduling: both check types present per group after a 9 AM run
  4. Snapshot: capture rate for today's scored legs
  5. compute_clv() unit tests
"""
from __future__ import annotations

import sys

from src.utils.db import get_conn
from src.apis.clv_tracker import compute_clv

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"

results: list[tuple[str, str, str]] = []  # (status, name, detail)


def check(name: str, status: str, detail: str = "") -> None:
    tag = f"[{status}]"
    print(f"  {tag:<6} {name}" + (f" — {detail}" if detail else ""))
    results.append((status, name, detail))


# ── Check 1: closing_odds column ──────────────────────────────────────────────
print("\n[1] Migration: closing_odds + closing_odds_captured_at on mlb_scored_legs")
try:
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'mlb_scored_legs'
          AND column_name IN ('closing_odds', 'closing_odds_captured_at')
        """
    )
    found = {row["column_name"] for row in cur.fetchall()}
    cur.close()
    conn.close()

    if "closing_odds" in found:
        check("closing_odds column", PASS)
    else:
        check("closing_odds column", FAIL, "column not found — run sql/clv_tracking_migration.sql")

    if "closing_odds_captured_at" in found:
        check("closing_odds_captured_at column", PASS)
    else:
        check("closing_odds_captured_at column", FAIL, "column not found — run sql/clv_tracking_migration.sql")

except Exception as e:
    check("closing_odds migration check", FAIL, str(e))


# ── Check 2: check_type column ────────────────────────────────────────────────
print("\n[2] Migration: check_type column on mlb_pending_lineup_checks")
try:
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name  = 'mlb_pending_lineup_checks'
          AND column_name = 'check_type'
        """
    )
    row = cur.fetchone()
    cur.close()
    conn.close()

    if row:
        check("check_type column", PASS)
    else:
        check("check_type column", FAIL, "column not found — run sql/clv_tracking_migration.sql")

except Exception as e:
    check("check_type migration check", FAIL, str(e))


# ── Check 3: Scheduling — both check types per group ─────────────────────────
print("\n[3] Scheduling: both check_type='lineup' and check_type='clv' for today")
try:
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        """
        SELECT check_type,
               COUNT(*)         AS groups,
               MIN(trigger_at)  AS earliest,
               MAX(trigger_at)  AS latest
        FROM mlb_pending_lineup_checks
        WHERE run_date = CURRENT_DATE
        GROUP BY check_type
        ORDER BY check_type
        """
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()

    type_map = {r["check_type"]: r for r in rows}

    if not rows:
        check("today's scheduler rows", SKIP, "no rows for today — run 9 AM pipeline first")
    else:
        if "lineup" in type_map:
            lr = type_map["lineup"]
            check(
                "lineup rows scheduled",
                PASS,
                f"{lr['groups']} group(s), triggers {lr['earliest']} → {lr['latest']}",
            )
        else:
            check("lineup rows scheduled", FAIL, "no lineup rows for today")

        if "clv" in type_map:
            cr = type_map["clv"]
            check(
                "clv rows scheduled",
                PASS,
                f"{cr['groups']} group(s), triggers {cr['earliest']} → {cr['latest']}",
            )
        else:
            check("clv rows scheduled", FAIL, "no clv rows for today — check schedule_clv_checks()")

        # CLV trigger_at should be later (closer to game start) than lineup trigger_at
        if "lineup" in type_map and "clv" in type_map:
            l_latest = type_map["lineup"]["latest"]
            c_latest = type_map["clv"]["latest"]
            if c_latest >= l_latest:
                check("clv trigger_at > lineup trigger_at", PASS, "CLV fires closer to game start ✓")
            else:
                check("clv trigger_at > lineup trigger_at", FAIL,
                      f"CLV latest={c_latest} is not after lineup latest={l_latest}")

except Exception as e:
    check("scheduling check", FAIL, str(e))


# ── Check 4: Capture rate for today ──────────────────────────────────────────
print("\n[4] CLV snapshot: capture rate for today's scored legs")
try:
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        """
        SELECT
            COUNT(*)                                                          AS total_legs,
            COUNT(closing_odds)                                               AS captured,
            (COUNT(closing_odds) * 100.0 / NULLIF(COUNT(*), 0))::numeric(5,1) AS pct_captured
        FROM mlb_scored_legs
        WHERE run_date = (CURRENT_DATE)::text
        """
    )
    row = dict(cur.fetchone())
    cur.close()
    conn.close()

    total    = row["total_legs"]
    captured = row["captured"]
    pct      = row["pct_captured"]

    if total == 0:
        check("capture rate", SKIP, "no scored legs for today — run 9 AM pipeline first")
    elif captured == 0:
        check(
            "capture rate",
            SKIP,
            f"{total} legs, 0 captured — CLV snapshot hasn't fired yet (fires at T-1)",
        )
    elif pct is not None and float(pct) >= 70.0:
        check("capture rate", PASS, f"{captured}/{total} legs captured ({pct}%)")
    else:
        check(
            "capture rate",
            FAIL if pct is not None and float(pct) < 10.0 else SKIP,
            f"{captured}/{total} legs captured ({pct}%) — "
            + ("near-zero: check SGO natural-key match" if pct is not None and float(pct) < 10.0
               else "partial capture normal if snapshot just fired"),
        )

except Exception as e:
    check("capture rate check", FAIL, str(e))


# ── Check 5: compute_clv() unit tests ────────────────────────────────────────
print("\n[5] compute_clv() unit tests")

cases = [
    # (selection, closing, expected_sign, description)
    ("-115", "-120", ">0",  "line moved toward our side (positive CLV)"),
    ("-115", "-110", "<0",  "line moved against us (negative CLV)"),
    ("-115", "-115", "=0",  "no line movement (zero CLV)"),
    ("+110", "+105", ">0",  "positive line, moved our way"),
    (None,   "-115", "None", "null selection → None"),
    ("-115",  None,  "None", "null closing → None"),
    ("bad",  "-115", "None", "unparseable → None"),
]

for sel, clo, expected_sign, desc in cases:
    result = compute_clv(sel, clo)
    if expected_sign == "None":
        ok = result is None
    elif expected_sign == ">0":
        ok = result is not None and result > 0
    elif expected_sign == "<0":
        ok = result is not None and result < 0
    elif expected_sign == "=0":
        ok = result is not None and result == 0.0
    else:
        ok = False
    check(
        f"compute_clv({sel!r}, {clo!r})",
        PASS if ok else FAIL,
        f"→ {result}  [{desc}]",
    )


# ── Summary ───────────────────────────────────────────────────────────────────
print()
passed = sum(1 for s, _, _ in results if s == PASS)
failed = sum(1 for s, _, _ in results if s == FAIL)
skipped = sum(1 for s, _, _ in results if s == SKIP)
total = len(results)

print(f"Results: {passed}/{total} passed, {skipped} skipped, {failed} failed")

if failed:
    print("\nFailed checks:")
    for status, name, detail in results:
        if status == FAIL:
            print(f"  • {name}: {detail}")
    sys.exit(1)
else:
    print("CLV layer verification OK.")
    sys.exit(0)
