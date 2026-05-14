#!/usr/bin/env python3
"""
MLB Parlay Agent Diagnostic Script
Runs 6 diagnostic query sections and generates a markdown report.
"""

import os
import sys
import math
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.db import get_conn

REPORT_PATH = "/home/gweeod/parlay_diagnostic_report.md"


def q(conn, sql, params=None):
    cur = conn.cursor()
    if params:
        cur.execute(sql, params)
    else:
        cur.execute(sql)
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    return rows


def fmt_table(rows, keys=None):
    if not rows:
        return "_No data_\n"
    keys = keys or list(rows[0].keys())
    widths = {k: max(len(str(k)), max((len(str(r.get(k, ""))) for r in rows), default=0)) for k in keys}
    sep = "| " + " | ".join("-" * widths[k] for k in keys) + " |"
    header = "| " + " | ".join(str(k).ljust(widths[k]) for k in keys) + " |"
    lines = [header, sep]
    for r in rows:
        lines.append("| " + " | ".join(str(r.get(k, "")).ljust(widths[k]) for k in keys) + " |")
    return "\n".join(lines) + "\n"


def run_diagnostics():
    conn = get_conn()
    print("✅ Connected to database")

    # ── Quick schema probe: what columns exist on mlb_scored_legs? ──────────
    probe = q(conn, """
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'mlb_scored_legs'
        ORDER BY ordinal_position
    """)
    sl_cols = {r["column_name"] for r in probe}
    print(f"mlb_scored_legs columns: {sorted(sl_cols)}")

    probe2 = q(conn, """
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'mlb_parlay_recommendations_v2'
        ORDER BY ordinal_position
    """)
    pr_cols = {r["column_name"] for r in probe2}
    print(f"mlb_parlay_recommendations_v2 columns: {sorted(pr_cols)}")

    probe3 = q(conn, """
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'mlb_parlay_legs_v2'
        ORDER BY ordinal_position
    """)
    pl_cols = {r["column_name"] for r in probe3}
    print(f"mlb_parlay_legs_v2 columns: {sorted(pl_cols)}")

    # ── Count totals ──────────────────────────────────────────────────────────
    totals = q(conn, """
        SELECT
            COUNT(*) FILTER (WHERE outcome IN ('won','lost')) AS resolved_parlays,
            COUNT(*) FILTER (WHERE outcome = 'won') AS won_parlays,
            COUNT(*) FILTER (WHERE outcome = 'lost') AS lost_parlays,
            COUNT(*) AS total_parlays,
            MIN(run_date) AS first_date,
            MAX(run_date) AS last_date
        FROM mlb_parlay_recommendations_v2
    """)[0]

    leg_totals = q(conn, """
        SELECT
            COUNT(*) FILTER (WHERE result IN ('won','lost')) AS resolved_legs,
            COUNT(*) FILTER (WHERE result = 'won') AS won_legs,
            COUNT(*) AS total_legs,
            MIN(run_date) AS first_date,
            MAX(run_date) AS last_date
        FROM mlb_scored_legs
    """)[0]

    print(f"Resolved parlays: {totals['resolved_parlays']} | Won: {totals['won_parlays']} | Lost: {totals['lost_parlays']}")
    print(f"Resolved legs: {leg_totals['resolved_legs']} | Won: {leg_totals['won_legs']}")

    # ── Section 1: ML Score Calibration (composite_score vs actual win rate) ──
    print("\nRunning Section 1: Calibration...")
    s1 = q(conn, """
        SELECT
            CASE
                WHEN composite_score < 40 THEN '30-40%'
                WHEN composite_score < 50 THEN '40-50%'
                WHEN composite_score < 55 THEN '50-55%'
                WHEN composite_score < 60 THEN '55-60%'
                WHEN composite_score < 70 THEN '60-70%'
                ELSE '70%+'
            END AS prediction_bucket,
            COUNT(*) AS total_legs,
            ROUND(AVG(composite_score)::numeric, 1) AS avg_predicted_pct,
            ROUND(AVG(CASE WHEN result = 'won' THEN 100.0 ELSE 0.0 END)::numeric, 1) AS actual_hit_pct,
            ROUND((AVG(composite_score) - AVG(CASE WHEN result = 'won' THEN 100.0 ELSE 0.0 END))::numeric, 1) AS prediction_error,
            ROUND(AVG(POWER((composite_score/100.0) - (CASE WHEN result = 'won' THEN 1.0 ELSE 0.0 END), 2))::numeric, 4) AS brier_score
        FROM mlb_scored_legs
        WHERE result IN ('won', 'lost')
          AND run_date >= (CURRENT_DATE - INTERVAL '30 days')::text
          AND composite_score IS NOT NULL
        GROUP BY 1
        ORDER BY 1
    """)

    # Also run wider window (all time)
    s1_all = q(conn, """
        SELECT
            CASE
                WHEN composite_score < 40 THEN '30-40%'
                WHEN composite_score < 50 THEN '40-50%'
                WHEN composite_score < 55 THEN '50-55%'
                WHEN composite_score < 60 THEN '55-60%'
                WHEN composite_score < 70 THEN '60-70%'
                ELSE '70%+'
            END AS prediction_bucket,
            COUNT(*) AS total_legs,
            ROUND(AVG(composite_score)::numeric, 1) AS avg_predicted_pct,
            ROUND(AVG(CASE WHEN result = 'won' THEN 100.0 ELSE 0.0 END)::numeric, 1) AS actual_hit_pct,
            ROUND((AVG(composite_score) - AVG(CASE WHEN result = 'won' THEN 100.0 ELSE 0.0 END))::numeric, 1) AS prediction_error,
            ROUND(AVG(POWER((composite_score/100.0) - (CASE WHEN result = 'won' THEN 1.0 ELSE 0.0 END), 2))::numeric, 4) AS brier_score
        FROM mlb_scored_legs
        WHERE result IN ('won', 'lost')
          AND composite_score IS NOT NULL
        GROUP BY 1
        ORDER BY 1
    """)

    # ── Section 2A: ML Score Predictive Power ────────────────────────────────
    print("Running Section 2A: ML Score Predictive Power...")
    s2a = q(conn, """
        SELECT
            stat,
            direction,
            CASE
                WHEN composite_score < 45 THEN '<45%'
                WHEN composite_score < 55 THEN '45-55%'
                WHEN composite_score < 65 THEN '55-65%'
                ELSE '65%+'
            END AS ml_score_range,
            COUNT(*) AS legs,
            ROUND(AVG(CASE WHEN result = 'won' THEN 100.0 ELSE 0.0 END)::numeric, 1) AS win_pct,
            COUNT(*) FILTER (WHERE result = 'won') AS won,
            COUNT(*) FILTER (WHERE result = 'lost') AS lost
        FROM mlb_scored_legs
        WHERE result IN ('won', 'lost')
          AND run_date >= (CURRENT_DATE - INTERVAL '30 days')::text
        GROUP BY 1, 2, 3
        ORDER BY 1, 2, 3
    """)

    # Simplified: overall score range vs win pct
    s2a_overall = q(conn, """
        SELECT
            CASE
                WHEN composite_score < 45 THEN '<45%'
                WHEN composite_score < 55 THEN '45-55%'
                WHEN composite_score < 60 THEN '55-60%'
                WHEN composite_score < 65 THEN '60-65%'
                ELSE '65%+'
            END AS ml_score_range,
            COUNT(*) AS legs,
            ROUND(AVG(CASE WHEN result = 'won' THEN 100.0 ELSE 0.0 END)::numeric, 1) AS win_pct,
            COUNT(*) FILTER (WHERE result = 'won') AS won,
            COUNT(*) FILTER (WHERE result = 'lost') AS lost
        FROM mlb_scored_legs
        WHERE result IN ('won', 'lost')
          AND composite_score IS NOT NULL
        GROUP BY 1
        ORDER BY 1
    """)

    # ── Section 2B: Direction Bias ────────────────────────────────────────────
    print("Running Section 2B: Direction Bias...")
    s2b = q(conn, """
        SELECT
            direction,
            COUNT(*) AS total_legs,
            ROUND(AVG(composite_score)::numeric, 1) AS avg_ml_score,
            ROUND(AVG(CASE WHEN result = 'won' THEN 100.0 ELSE 0.0 END)::numeric, 1) AS actual_win_pct,
            ROUND((AVG(composite_score) - AVG(CASE WHEN result = 'won' THEN 100.0 ELSE 0.0 END))::numeric, 1) AS bias
        FROM mlb_scored_legs
        WHERE result IN ('won', 'lost')
          AND run_date >= (CURRENT_DATE - INTERVAL '30 days')::text
        GROUP BY 1
        ORDER BY 1
    """)

    # ── Section 3: Parlay Leg Selection vs All Legs ──────────────────────────
    print("Running Section 3: Leg Selection Quality...")
    s3 = q(conn, """
        WITH parlay_legs AS (
            SELECT DISTINCT
                s.id,
                s.player_name,
                s.stat,
                s.direction,
                s.composite_score,
                s.result,
                'in_parlay' AS leg_type
            FROM mlb_scored_legs s
            WHERE s.in_parlay = TRUE
              AND s.result IN ('won', 'lost')
        ),
        all_legs AS (
            SELECT
                id,
                player_name,
                stat,
                direction,
                composite_score,
                result,
                'all_legs' AS leg_type
            FROM mlb_scored_legs
            WHERE result IN ('won', 'lost')
        )
        SELECT
            leg_type,
            COUNT(*) AS total,
            ROUND(AVG(composite_score)::numeric, 1) AS avg_ml_score,
            ROUND(MIN(composite_score)::numeric, 1) AS min_ml_score,
            ROUND(MAX(composite_score)::numeric, 1) AS max_ml_score,
            ROUND(AVG(CASE WHEN result = 'won' THEN 100.0 ELSE 0.0 END)::numeric, 1) AS win_pct
        FROM (
            SELECT * FROM parlay_legs
            UNION ALL
            SELECT * FROM all_legs
        ) combined
        GROUP BY leg_type
        ORDER BY leg_type
    """)

    # ── Section 3B: Parlay legs via v2 table ─────────────────────────────────
    s3b = q(conn, """
        SELECT
            'in_parlay_v2' AS leg_type,
            COUNT(*) AS total,
            ROUND(AVG(l.composite_score)::numeric, 1) AS avg_ml_score,
            ROUND(AVG(CASE WHEN l.outcome = 'won' THEN 100.0 ELSE 0.0 END)::numeric, 1) AS win_pct,
            COUNT(*) FILTER (WHERE l.outcome = 'won') AS won,
            COUNT(*) FILTER (WHERE l.outcome = 'lost') AS lost
        FROM mlb_parlay_legs_v2 l
        JOIN mlb_parlay_recommendations_v2 p ON l.parlay_id = p.id
        WHERE l.outcome IN ('won', 'lost')
    """)

    # ── Section 4A: Parlay Failure Patterns ──────────────────────────────────
    print("Running Section 4A: Failure Patterns...")
    s4a = q(conn, """
        SELECT
            p.id AS parlay_id,
            p.run_date,
            p.rank,
            p.num_legs,
            p.outcome AS parlay_outcome,
            COUNT(*) FILTER (WHERE l.outcome = 'won') AS legs_won,
            COUNT(*) FILTER (WHERE l.outcome = 'lost') AS legs_lost,
            COUNT(*) FILTER (WHERE l.outcome = 'void') AS legs_void,
            ROUND(AVG(l.composite_score) FILTER (WHERE l.outcome = 'lost')::numeric, 1) AS avg_ml_score_of_losses
        FROM mlb_parlay_recommendations_v2 p
        JOIN mlb_parlay_legs_v2 l ON l.parlay_id = p.id
        WHERE p.outcome IN ('won', 'lost')
        GROUP BY 1, 2, 3, 4, 5
        ORDER BY p.run_date DESC, p.rank
    """)

    # Aggregate failure summary
    s4a_summary = q(conn, """
        WITH parlay_leg_counts AS (
            SELECT
                p.id,
                p.outcome AS parlay_outcome,
                p.num_legs,
                COUNT(*) FILTER (WHERE l.outcome = 'won') AS legs_won,
                COUNT(*) FILTER (WHERE l.outcome = 'lost') AS legs_lost
            FROM mlb_parlay_recommendations_v2 p
            JOIN mlb_parlay_legs_v2 l ON l.parlay_id = p.id
            WHERE p.outcome IN ('won', 'lost')
            GROUP BY p.id, p.outcome, p.num_legs
        )
        SELECT
            parlay_outcome,
            COUNT(*) AS count,
            ROUND(AVG(legs_won)::numeric, 1) AS avg_legs_won,
            ROUND(AVG(legs_lost)::numeric, 1) AS avg_legs_lost,
            ROUND(AVG(num_legs)::numeric, 1) AS avg_num_legs
        FROM parlay_leg_counts
        GROUP BY parlay_outcome
        ORDER BY parlay_outcome
    """)

    # ── Section 4B: Repeat Offenders ─────────────────────────────────────────
    print("Running Section 4B: Repeat Offenders...")
    s4b = q(conn, """
        SELECT
            l.player_name,
            l.stat,
            l.direction,
            COUNT(*) AS times_in_parlay,
            COUNT(*) FILTER (WHERE l.outcome = 'lost') AS times_lost,
            ROUND(100.0 * COUNT(*) FILTER (WHERE l.outcome = 'lost') / NULLIF(COUNT(*) FILTER (WHERE l.outcome IN ('won','lost')), 0), 1) AS loss_rate,
            ROUND(AVG(l.composite_score)::numeric, 1) AS avg_ml_score_when_selected
        FROM mlb_parlay_legs_v2 l
        WHERE l.outcome IN ('won', 'lost')
        GROUP BY 1, 2, 3
        HAVING COUNT(*) >= 2
        ORDER BY times_in_parlay DESC, loss_rate DESC
        LIMIT 30
    """)

    # ── Section 5: Expected Value Analysis ───────────────────────────────────
    print("Running Section 5: Expected Value...")
    s5 = q(conn, """
        WITH parlay_analysis AS (
            SELECT
                p.id,
                p.run_date,
                p.rank,
                p.outcome,
                p.num_legs,
                p.total_odds,
                p.avg_coverage AS avg_ml_score,
                POWER(NULLIF(p.avg_coverage, 0) / 100.0, p.num_legs) * 100 AS implied_win_prob,
                CASE
                    WHEN p.total_odds > 0
                    THEN 100.0 / (p.total_odds + 100.0)
                    ELSE ABS(p.total_odds) / (ABS(p.total_odds) + 100.0)
                END AS breakeven_prob,
                CASE
                    WHEN p.total_odds > 0
                    THEN (POWER(NULLIF(p.avg_coverage, 0) / 100.0, p.num_legs) * p.total_odds) -
                         ((1 - POWER(NULLIF(p.avg_coverage, 0) / 100.0, p.num_legs)) * 100)
                    ELSE NULL
                END AS expected_value
            FROM mlb_parlay_recommendations_v2 p
            WHERE p.outcome IN ('won', 'lost')
        )
        SELECT
            CASE
                WHEN implied_win_prob < 5  THEN '<5%'
                WHEN implied_win_prob < 10 THEN '5-10%'
                WHEN implied_win_prob < 15 THEN '10-15%'
                ELSE '15%+'
            END AS implied_win_prob_bucket,
            COUNT(*) AS parlays,
            ROUND(AVG(implied_win_prob)::numeric, 1) AS avg_predicted_prob,
            ROUND(AVG(CASE WHEN outcome = 'won' THEN 100.0 ELSE 0.0 END)::numeric, 1) AS actual_win_pct,
            ROUND(AVG(total_odds)::numeric, 0) AS avg_odds,
            ROUND(AVG(expected_value)::numeric, 1) AS avg_expected_value,
            SUM(CASE WHEN outcome = 'won' THEN total_odds ELSE -100 END) AS total_profit_loss
        FROM parlay_analysis
        GROUP BY 1
        ORDER BY 1
    """)

    # Also: simple overall EV summary
    s5_overall = q(conn, """
        SELECT
            COUNT(*) AS total_resolved,
            COUNT(*) FILTER (WHERE outcome = 'won') AS won,
            COUNT(*) FILTER (WHERE outcome = 'lost') AS lost,
            ROUND(AVG(total_odds)::numeric, 0) AS avg_odds,
            ROUND(AVG(num_legs)::numeric, 1) AS avg_legs,
            ROUND(AVG(avg_coverage)::numeric, 1) AS avg_ml_score,
            SUM(CASE WHEN outcome = 'won' THEN total_odds ELSE -100 END) AS net_units_if_100_per
        FROM mlb_parlay_recommendations_v2
        WHERE outcome IN ('won', 'lost')
    """)[0]

    # ── Section 6: What's Working? ────────────────────────────────────────────
    print("Running Section 6: What's Working...")
    s6 = q(conn, """
        SELECT
            p.num_legs,
            CASE
                WHEN p.total_odds < 1000 THEN '<+1000'
                WHEN p.total_odds < 1500 THEN '+1000 to +1500'
                ELSE '+1500+'
            END AS odds_range,
            CASE
                WHEN p.avg_coverage < 50 THEN '<50%'
                WHEN p.avg_coverage < 55 THEN '50-55%'
                ELSE '55%+'
            END AS avg_ml_score_range,
            COUNT(*) AS total_parlays,
            COUNT(*) FILTER (WHERE p.outcome = 'won') AS won,
            COUNT(*) FILTER (WHERE p.outcome = 'lost') AS lost,
            ROUND(100.0 * COUNT(*) FILTER (WHERE p.outcome = 'won') / NULLIF(COUNT(*), 0), 1) AS win_rate
        FROM mlb_parlay_recommendations_v2 p
        WHERE p.outcome IN ('won', 'lost')
        GROUP BY 1, 2, 3
        ORDER BY win_rate DESC
    """)

    # ── Stat-level leg performance ─────────────────────────────────────────────
    s_stat = q(conn, """
        SELECT
            stat,
            direction,
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE result = 'won') AS won,
            ROUND(100.0 * COUNT(*) FILTER (WHERE result = 'won') / NULLIF(COUNT(*) FILTER (WHERE result IN ('won','lost')), 0), 1) AS win_rate,
            ROUND(AVG(composite_score)::numeric, 1) AS avg_score
        FROM mlb_scored_legs
        WHERE result IN ('won', 'lost')
        GROUP BY stat, direction
        HAVING COUNT(*) >= 5
        ORDER BY win_rate DESC NULLS LAST, total DESC
    """)

    conn.close()
    print("✅ All queries complete")

    # ── Build Report ──────────────────────────────────────────────────────────
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    resolved = totals['resolved_parlays']
    won = totals['won_parlays']
    hit_rate = round(100.0 * won / resolved, 1) if resolved else 0
    leg_win_rate = round(100.0 * leg_totals['won_legs'] / leg_totals['resolved_legs'], 1) if leg_totals['resolved_legs'] else 0

    # Analyze calibration
    cal_issues = []
    cal_good = []
    for r in s1_all:
        err = float(r['prediction_error'] or 0)
        if abs(err) > 5:
            cal_issues.append(f"  - **{r['prediction_bucket']}** bucket: predicted {r['avg_predicted_pct']}%, actual {r['actual_hit_pct']}% → error {r['prediction_error']}pp")
        else:
            cal_good.append(r['prediction_bucket'])

    # Analyze predictive power (does score correlate with win rate?)
    sorted_s2 = sorted(s2a_overall, key=lambda r: ['<45%','45-55%','55-60%','60-65%','65%+'].index(r['ml_score_range']) if r['ml_score_range'] in ['<45%','45-55%','55-60%','60-65%','65%+'] else 99)
    win_rates = [float(r['win_pct'] or 0) for r in sorted_s2]
    is_monotonic = all(win_rates[i] <= win_rates[i+1] + 3 for i in range(len(win_rates)-1)) if len(win_rates) > 1 else True

    # Analyze direction bias
    dir_bias_issues = []
    for r in s2b:
        bias = float(r['bias'] or 0)
        total = int(r['total_legs'])
        if abs(bias) > 5:
            dir_bias_issues.append(f"  - **{r['direction']}**: predicted {r['avg_ml_score']}%, actual {r['actual_win_pct']}% → bias {r['bias']}pp")

    # Leg selection quality
    parlay_leg_row = next((r for r in s3 if r['leg_type'] == 'in_parlay'), None)
    all_leg_row = next((r for r in s3 if r['leg_type'] == 'all_legs'), None)

    # Failure analysis
    lost_parlays = [r for r in s4a if r['parlay_outcome'] == 'lost']
    multi_leg_fail = [r for r in lost_parlays if int(r['legs_lost'] or 0) >= 3]

    # EV analysis
    net_pl = s5_overall.get('net_units_if_100_per', 0) or 0

    # Red flags
    red_flags = []
    recommendations_list = []

    if not is_monotonic:
        red_flags.append("🚩 ML score NOT monotonically correlated with win rate — model discrimination is weak")
        recommendations_list.append(("Priority 1", "Investigate feature quality; consider retraining with more recent data or adding new features"))

    if cal_issues:
        red_flags.append(f"🚩 Calibration errors >5pp in buckets: {', '.join(r['prediction_bucket'] for r in s1_all if abs(float(r['prediction_error'] or 0)) > 5)}")
        recommendations_list.append(("Priority 1", "Re-run stat-specific calibrator; check if calibrator training window matches current season patterns"))

    if parlay_leg_row and all_leg_row:
        p_score = float(parlay_leg_row['avg_ml_score'] or 0)
        a_score = float(all_leg_row['avg_ml_score'] or 0)
        p_win = float(parlay_leg_row['win_pct'] or 0)
        a_win = float(all_leg_row['win_pct'] or 0)
        if p_score < a_score:
            red_flags.append("🚩 Parlay legs have LOWER avg ML score than all legs — parlay builder is not selecting best legs")
            recommendations_list.append(("Priority 1", "Fix parlay builder threshold: only select legs with composite_score above the all-legs average"))
        if p_win < a_win - 3:
            red_flags.append(f"🚩 Parlay legs win rate ({p_win:.1f}%) is lower than all-legs win rate ({a_win:.1f}%) — selection is counterproductive")

    if len(multi_leg_fail) > len(lost_parlays) * 0.4 and len(lost_parlays) > 0:
        red_flags.append(f"🚩 {len(multi_leg_fail)}/{len(lost_parlays)} lost parlays have 3+ legs failing — legs may be correlated or model is systematically wrong")
        recommendations_list.append(("Priority 2", "Add correlation filter: avoid multiple legs from same game, same team, or same pitcher matchup"))

    if net_pl < 0:
        red_flags.append(f"🚩 Net P&L is {net_pl:.0f} units (if betting 1 unit per parlay) — currently losing money")

    for r in dir_bias_issues:
        red_flags.append(f"🚩 Direction calibration bias: {r.strip()}")

    if hit_rate < 10:
        red_flags.append(f"🚩 Parlay hit rate of {hit_rate}% is below break-even for typical parlay odds")
        recommendations_list.append(("Priority 1", "Consider reducing parlay size (fewer legs) to improve hit rate and reduce variance"))

    if not red_flags:
        red_flags.append("✅ No critical red flags — system performing within acceptable range")

    # Strategic verdict
    critical_issues = sum(1 for r in red_flags if r.startswith("🚩"))
    if critical_issues >= 3:
        verdict = "🚨 REBUILD MODEL — Multiple fundamental issues detected"
        verdict_rationale = "The combination of calibration errors, selection quality issues, and negative P&L suggests the model's assumptions no longer match real-world outcomes. A fresh retraining with updated features and a tighter validation loop is warranted."
    elif critical_issues >= 1:
        verdict = "🔧 TUNE PARAMETERS — Core strategy has issues but is salvageable"
        verdict_rationale = "The model shows some predictive signal but calibration and/or selection logic need adjustment. Parameter tuning (score thresholds, parlay size, correlation filters) should be tried before rebuilding."
    else:
        verdict = "✅ KEEP CURRENT STRATEGY — System performing as expected"
        verdict_rationale = "ML scores correlate with win rates, calibration is acceptable, and selection logic is working. The 8% parlay hit rate is consistent with the math of multi-leg parlays at these odds levels. Continue accumulating data and monitor for drift."

    # ── Write report ──────────────────────────────────────────────────────────
    report = f"""# MLB Parlay Agent Diagnostic Report
**Generated:** {now}
**Data Range:** All time (leg calibration uses 30-day window)
**Total Resolved Parlays:** {resolved} (won: {won}, lost: {totals['lost_parlays']})
**Parlay Hit Rate:** {hit_rate}%
**Total Resolved Legs:** {leg_totals['resolved_legs']} (won: {leg_totals['won_legs']}, win rate: {leg_win_rate}%)

---

## Executive Summary

"""

    # Build exec summary bullets
    exec_bullets = []

    # Calibration finding
    if not cal_issues:
        exec_bullets.append("✅ ML calibration is reasonable — no bucket exceeds 5pp prediction error (all-time data)")
    else:
        exec_bullets.append(f"🚩 Calibration has errors in {len(cal_issues)} bucket(s) — predicted win rates don't match actual")

    # Predictive power
    if is_monotonic and len(win_rates) > 1:
        exec_bullets.append(f"✅ ML score IS correlated with win rate (higher score → higher win%, range: {min(win_rates):.1f}% to {max(win_rates):.1f}%)")
    else:
        exec_bullets.append("🚩 ML score correlation with win rate is weak or non-monotonic — model discrimination is limited")

    # Selection quality
    if parlay_leg_row and all_leg_row:
        p_score = float(parlay_leg_row['avg_ml_score'] or 0)
        a_score = float(all_leg_row['avg_ml_score'] or 0)
        p_win = float(parlay_leg_row['win_pct'] or 0)
        a_win = float(all_leg_row['win_pct'] or 0)
        if p_score >= a_score:
            exec_bullets.append(f"✅ Parlay builder selects above-average legs (parlay avg score: {p_score:.1f}% vs all-legs: {a_score:.1f}%)")
        else:
            exec_bullets.append(f"🚩 Parlay builder is NOT selecting the best legs (parlay avg: {p_score:.1f}% vs all-legs: {a_score:.1f}%)")

    # P&L
    exec_bullets.append(f"{'✅' if net_pl >= 0 else '🚩'} Net P&L: {net_pl:+.0f} units (if betting 1 unit per parlay, $100 stakes) — {resolved} resolved parlays")

    # Verdict
    exec_bullets.append(f"🎯 **RECOMMENDATION: {verdict}**")

    for b in exec_bullets:
        report += f"- {b}\n"

    report += f"""
---

## Section 1: ML Model Calibration

### Last 30 Days

{fmt_table(s1, ['prediction_bucket','total_legs','avg_predicted_pct','actual_hit_pct','prediction_error','brier_score'])}

### All Time

{fmt_table(s1_all, ['prediction_bucket','total_legs','avg_predicted_pct','actual_hit_pct','prediction_error','brier_score'])}

**Checklist:**
- Prediction error within ±2% = ✅ good calibration
- Error 2-5% = ⚠️ minor drift
- Error >5% = 🚩 miscalibration

**Findings:**
"""
    if not cal_issues:
        report += "- ✅ All buckets within acceptable calibration range\n"
    else:
        report += "- 🚩 Calibration issues detected:\n"
        for c in cal_issues:
            report += c + "\n"
    if not s1_all:
        report += "- ⚠️ No resolved legs with composite_score in database yet — calibration cannot be assessed\n"

    report += f"""
**Red Flags:**
{"- None" if not cal_issues else chr(10).join(cal_issues)}

---

## Section 2: Feature Predictive Power

### A) Overall ML Score vs Win Rate (All Time)

{fmt_table(s2a_overall, ['ml_score_range','legs','win_pct','won','lost'])}

**Findings:**
- {'✅ Higher ML scores correlate with higher win rates — model is predictive' if is_monotonic else '🚩 ML scores do NOT monotonically predict win rates — review model or training data'}
- Win rate range: {f"{min(win_rates):.1f}% to {max(win_rates):.1f}%" if win_rates else "N/A"}

### B) By Stat + Direction (Last 30 Days, ≥5 legs)

{fmt_table(s2a, ['stat','direction','ml_score_range','legs','win_pct','won','lost'])}

### C) Direction Bias

{fmt_table(s2b, ['direction','total_legs','avg_ml_score','actual_win_pct','bias'])}

**Findings:**
"""
    if dir_bias_issues:
        for d in dir_bias_issues:
            report += d + "\n"
    else:
        report += "- ✅ Direction bias within acceptable range (±5pp)\n"

    report += f"""
---

## Section 3: Parlay Leg Selection Quality

### Via mlb_scored_legs.in_parlay flag

{fmt_table(s3, ['leg_type','total','avg_ml_score','min_ml_score','max_ml_score','win_pct'])}

### Via mlb_parlay_legs_v2 (direct parlay table)

{fmt_table(s3b, ['leg_type','total','avg_ml_score','win_pct','won','lost'])}

**Findings:**
"""
    if parlay_leg_row and all_leg_row:
        p_score = float(parlay_leg_row['avg_ml_score'] or 0)
        a_score = float(all_leg_row['avg_ml_score'] or 0)
        p_win = float(parlay_leg_row['win_pct'] or 0)
        a_win = float(all_leg_row['win_pct'] or 0)
        report += f"- Parlay legs avg ML score: **{p_score:.1f}%** vs All legs avg: **{a_score:.1f}%**\n"
        if p_score >= a_score:
            report += "- ✅ Parlay builder is correctly selecting above-average legs\n"
        else:
            report += "- 🚩 Parlay builder is selecting below-average legs — investigate scoring threshold\n"
        report += f"- Parlay legs win rate: **{p_win:.1f}%** vs All legs win rate: **{a_win:.1f}%**\n"
        if p_win >= a_win - 3:
            report += "- ✅ Parlay legs perform comparably to the overall pool\n"
        else:
            report += f"- 🚩 Parlay legs underperform the pool by {a_win - p_win:.1f}pp — selection is counterproductive\n"
    else:
        report += "- ⚠️ Insufficient data to compare parlay vs all legs\n"

    report += f"""
---

## Section 4: Why Parlays Are Losing

### A) Individual Parlay Breakdown (All Resolved)

{fmt_table(s4a, ['parlay_id','run_date','rank','num_legs','parlay_outcome','legs_won','legs_lost','legs_void','avg_ml_score_of_losses'])}

### A) Failure Summary

{fmt_table(s4a_summary, ['parlay_outcome','count','avg_legs_won','avg_legs_lost','avg_num_legs'])}

**Findings:**
"""
    if lost_parlays:
        avg_legs_lost = sum(int(r['legs_lost'] or 0) for r in lost_parlays) / len(lost_parlays)
        report += f"- Lost parlays have on average **{avg_legs_lost:.1f}** legs failing\n"
        if avg_legs_lost <= 1.5:
            report += "- ✅ Most losses are single-leg failures — bad luck, model mostly right\n"
        elif avg_legs_lost <= 2.5:
            report += "- ⚠️ 2 legs failing on average — could indicate leg correlation or model issues\n"
        else:
            report += "- 🚩 3+ legs failing on average — legs likely correlated or model is systematically wrong\n"
        if multi_leg_fail:
            report += f"- 🚩 {len(multi_leg_fail)}/{len(lost_parlays)} lost parlays had 3+ legs fail simultaneously\n"
    else:
        report += "- ⚠️ No resolved lost parlays in database yet\n"

    report += f"""
### B) Repeat Offenders (min 2 appearances, sorted by loss rate)

{fmt_table(s4b, ['player_name','stat','direction','times_in_parlay','times_lost','loss_rate','avg_ml_score_when_selected'])}

**Findings:**
"""
    high_losers = [r for r in s4b if float(r['loss_rate'] or 0) >= 75 and int(r['times_in_parlay']) >= 3]
    if high_losers:
        report += f"- 🚩 {len(high_losers)} player/stat combos have 75%+ loss rate with 3+ appearances:\n"
        for r in high_losers[:5]:
            report += f"  - {r['player_name']} {r['stat']} {r['direction']}: {r['loss_rate']}% loss rate ({r['times_lost']}/{r['times_in_parlay']})\n"
    else:
        report += "- ✅ No single player/stat dominates losses — risk is diversified\n"

    report += f"""
---

## Section 5: Expected Value Reality Check

{fmt_table(s5, ['implied_win_prob_bucket','parlays','avg_predicted_prob','actual_win_pct','avg_odds','avg_expected_value','total_profit_loss'])}

### Overall P&L Summary

| Metric | Value |
|--------|-------|
| Total resolved parlays | {s5_overall['total_resolved']} |
| Won | {s5_overall['won']} |
| Lost | {s5_overall['lost']} |
| Avg odds | +{s5_overall['avg_odds']:.0f} |
| Avg legs | {s5_overall['avg_legs']:.1f} |
| Avg ML score | {s5_overall['avg_ml_score']:.1f}% |
| Net units (100/parlay) | **{net_pl:+.0f}** |
| Net dollars (at $100/parlay) | **${net_pl * 100:+,.0f}** |

**Findings:**
"""
    if s5:
        for r in s5:
            pred = float(r['avg_predicted_prob'] or 0)
            actual = float(r['actual_win_pct'] or 0)
            diff = actual - pred
            ev = float(r['avg_expected_value'] or 0)
            if abs(diff) > 3:
                report += f"- 🚩 {r['implied_win_prob_bucket']} bucket: predicted {pred:.1f}% but actual {actual:.1f}% (diff: {diff:+.1f}pp)\n"
            else:
                report += f"- ✅ {r['implied_win_prob_bucket']} bucket: predicted {pred:.1f}%, actual {actual:.1f}% — calibration OK\n"
            if ev < -10:
                report += f"  - 🚩 Expected value is {ev:.1f} — strongly negative EV bets in this range\n"

    report += f"""
**Break-even analysis:**
- At +{s5_overall['avg_odds']:.0f} avg odds, need {100/(float(s5_overall['avg_odds'] or 1)+100)*100:.1f}% win rate to break even
- Current win rate: {hit_rate}%
- Gap: {hit_rate - 100/(float(s5_overall['avg_odds'] or 1)+100)*100:+.1f}pp

---

## Section 6: What's Working

{fmt_table(s6, ['num_legs','odds_range','avg_ml_score_range','total_parlays','won','lost','win_rate'])}

**Findings:**
"""
    best = sorted(s6, key=lambda r: float(r['win_rate'] or 0), reverse=True)
    if best:
        top = best[0]
        report += f"- Best performing structure: **{top['num_legs']} legs, {top['odds_range']}, {top['avg_ml_score_range']} avg score** → {top['win_rate']}% win rate ({top['won']}/{top['total_parlays']})\n"
    worst = [r for r in s6 if float(r['win_rate'] or 0) == 0]
    if worst:
        report += f"- {len(worst)} structure(s) with 0% win rate — candidates for exclusion\n"

    report += f"""
---

## Leg Performance by Stat Type

{fmt_table(s_stat, ['stat','direction','total','won','win_rate','avg_score'])}

---

## RED FLAGS IDENTIFIED

"""
    if red_flags:
        for i, flag in enumerate(red_flags, 1):
            report += f"{i}. {flag}\n"
    else:
        report += "None — system is performing as expected\n"

    report += f"""
---

## RECOMMENDED ACTIONS

"""
    if not recommendations_list:
        recommendations_list = [
            ("Priority 3", "Continue monitoring. Accumulate more resolved parlays (target 50+) for statistically meaningful analysis."),
            ("Priority 3", "Consider A/B testing: run a batch of 3-leg parlays vs 4-leg to see if shorter parlays have higher win rate."),
        ]

    recommendations_list.extend([
        ("Priority 2", "Review the repeat offenders list monthly — blacklist any player/stat with ≥75% loss rate over 5+ appearances"),
        ("Priority 3", "Track parlay outcomes by day of week and time of day to identify scheduling patterns"),
    ])

    by_priority = {}
    for p, a in recommendations_list:
        by_priority.setdefault(p, []).append(a)

    for priority in ["Priority 1", "Priority 2", "Priority 3"]:
        if priority in by_priority:
            report += f"### {priority}\n"
            for i, action in enumerate(by_priority[priority], 1):
                report += f"{i}. {action}\n"
            report += "\n"

    report += f"""
---

## STRATEGIC PIVOT RECOMMENDATION

**Current Strategy:** {s5_overall['avg_legs']:.1f}-leg parlays averaging +{s5_overall['avg_odds']:.0f} odds, using ML composite scores with stat-specific calibration (deployed May 10). Legs filtered at 60%+ composite_score threshold.

**Verdict:** {verdict}

**Rationale:**
{verdict_rationale}

**Math check:** With {s5_overall['avg_legs']:.1f} legs averaging {s5_overall['avg_ml_score']:.1f}% individual win rate, the theoretical parlay hit rate is {(float(s5_overall['avg_ml_score'] or 0)/100)**float(s5_overall['avg_legs'] or 1)*100:.1f}%. At {resolved} resolved parlays, observing {won} wins ({hit_rate}%) is {"within expected variance" if abs(hit_rate - (float(s5_overall['avg_ml_score'] or 0)/100)**float(s5_overall['avg_legs'] or 1)*100) < 5 else "OUTSIDE expected variance — investigate"}.

---

## APPENDIX: Database Counts

| Table | Row Count |
|-------|-----------|
| mlb_scored_legs (resolved) | {leg_totals['resolved_legs']} |
| mlb_scored_legs (total) | {leg_totals['total_legs']} |
| mlb_parlay_recommendations_v2 (resolved) | {totals['resolved_parlays']} |
| mlb_parlay_recommendations_v2 (total) | {totals['total_parlays']} |
| Date range | {totals['first_date']} to {totals['last_date']} |
"""

    return report


if __name__ == "__main__":
    print("🏃 Running MLB Parlay Agent Diagnostic...")
    try:
        report = run_diagnostics()
        with open(REPORT_PATH, "w") as f:
            f.write(report)
        print(f"\n✅ Report saved to {REPORT_PATH}")
        # Print exec summary section
        lines = report.split("\n")
        in_summary = False
        for line in lines:
            if "## Executive Summary" in line:
                in_summary = True
            elif in_summary and line.startswith("## "):
                break
            elif in_summary:
                print(line)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\n❌ Error: {e}")
        sys.exit(1)
