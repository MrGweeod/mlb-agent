from dotenv import load_dotenv
from anthropic import Anthropic
from datetime import date
import os

load_dotenv()
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"), timeout=60.0)


def analyze_parlays(parlays):
    if not parlays:
        return "No parlays to analyze today."

    parlay_text = ""
    for i, p in enumerate(parlays, 1):
        parlay_text += "\nParlay {}: {} combined odds, {} legs\n".format(
            i, p["parlay_odds"], p["num_legs"]
        )
        for leg in p["legs"]:
            cov = leg.get("coverage_pct")
            cov_str = f"{cov:.1f}%" if cov is not None else "N/A"
            ev = leg.get("ev_per_unit")
            ev_str = f"{ev:+.3f}" if ev is not None else "N/A"
            opp_adj = leg.get("opponent_adjustment")
            opp_str = f"{opp_adj:+.2f}" if opp_adj is not None else "N/A"
            trend = leg.get("trend_score")
            trend_str = f"{trend:.1f}" if trend is not None else "N/A"
            matchup = f"{leg.get('team','?')} vs {leg.get('opponent','?')}"
            parlay_text += (
                f"  {leg['player_name']} ({matchup})\n"
                f"    {leg['stat']} {leg.get('direction','over')} {leg['best_line']}"
                f" @ {leg['best_odds']}\n"
                f"    Coverage: {cov_str} | EV: {ev_str}"
                f" | Trend score: {trend_str} | Opp adj: {opp_str}\n"
            )

    prompt = (
        "You are an MLB betting analyst. Analyze this parlay based ONLY on the "
        "statistical data provided below. Do NOT search for external information "
        "or make assumptions about injuries, lineups, or schedules.\n\n"
        + parlay_text +
        "\nEvaluate the following and be concise:\n\n"
        "COVERAGE QUALITY\n"
        "- Flag any leg below 60% coverage as a weak link\n"
        "- Note if coverage is well-distributed or stacked with marginal legs\n\n"
        "CORRELATION RISKS\n"
        "- Same-game stacking (max 3 legs per game recommended)\n"
        "- Pitcher K over + opposing batter hits over = correlated risk\n"
        "- Same player appearing more than once\n\n"
        "PARLAY CONSTRUCTION\n"
        "- Do the combined odds justify the number of legs?\n"
        "- Identify the strongest and weakest legs by coverage\n\n"
        "MATCHUP ANALYSIS\n"
        "- Which legs have the best opponent adjustments?\n"
        "- Any red flags in matchup quality?\n\n"
        "OVERALL RECOMMENDATION\n"
        "- Play as-is, modify, or skip — and why\n"
        "- If modify: which leg(s) to drop\n"
    )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    result = ""
    for block in response.content:
        if hasattr(block, "text"):
            result += block.text

    return result if result else "No analysis returned."


def get_injured_players(player_list):
    """
    Takes a list of player names, searches for their IL/injury status,
    and returns a set of names who are on the IL or scratched from tonight's lineup.
    """
    players = ", ".join(player_list)
    today = date.today().strftime("%B %d %Y")
    prompt = (
        f"Search the MLB transaction wire and lineup reports for {today}. "
        f"Check these players: {players}\n\n"
        "Reply with ONLY a raw comma-separated list of names who are on the IL, "
        "scratched from tonight's lineup, or otherwise unavailable to play tonight. "
        "Example reply: Aaron Judge, Freddie Freeman\n"
        "If none are unavailable, reply with exactly: NONE\n"
        "Do not include any other words, punctuation, or explanation. Just names or NONE."
    )
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=256,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": prompt}],
    )
    result = ""
    for block in response.content:
        if hasattr(block, "text"):
            result += block.text
    result = result.strip()
    if not result or result.upper() == "NONE":
        return set()
    names = set()
    for name in result.split(","):
        name = name.strip()
        if not name:
            continue
        # Defensive: skip entries that contain digits or are too short to be a
        # player name — guards against malformed LLM responses like "2026, 2026)"
        if any(c.isdigit() for c in name) or len(name) < 5:
            continue
        names.add(name)
    return names
