from dotenv import load_dotenv
from anthropic import Anthropic
from datetime import date
import os

load_dotenv()
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def analyze_parlays(parlays):
    if not parlays:
        return "No parlays to analyze today."

    players = set()
    for p in parlays:
        for leg in p["legs"]:
            players.add(leg["player_name"])

    player_list = ", ".join(players)

    parlay_text = ""
    for i, p in enumerate(parlays, 1):
        parlay_text += "\nParlay {}: {} odds, {} legs\n".format(i, p["parlay_odds"], p["num_legs"])
        for leg in p["legs"]:
            parlay_text += "  - {} {} over {} ({}) - hit rate: {}%\n".format(
                leg["player_name"], leg["stat"], leg["best_line"],
                leg["best_odds"], leg["coverage_pct"]
            )

    prompt = (
        "You are an MLB betting analyst.\n\n"
        "First, search for today's lineup and IL/injury status for these players: {}\n\n".format(player_list) +
        "Then review these parlay recommendations and for each one:\n"
        "1. Give a 1-2 sentence explanation of why each leg makes sense tonight given the pitching matchup\n"
        "2. Flag any IL placement, lineup scratch, or batting order concern you found\n"
        "3. Give an overall confidence rating: HIGH, MEDIUM, or LOW\n" +
        parlay_text +
        "\nBe concise and practical. No fluff."
    )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
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
