"""
rotowire.py — Context-only scraper for RotoWire MLB lineup and injury pages.

Not a hard dependency: never gates legs. Returns [] silently on any failure.
"""
import logging
from datetime import date as _date
from html.parser import HTMLParser

import requests

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}
_TIMEOUT = 10

LINEUP_URL = "https://www.rotowire.com/baseball/daily-lineups.php"
INJURY_URL = "https://www.rotowire.com/baseball/injury-report.php"


class _TextExtractor(HTMLParser):
    """Collect visible text, skipping script/style/noscript blocks."""

    def __init__(self):
        super().__init__()
        self._skip = 0
        self.chunks: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self._skip = max(0, self._skip - 1)

    def handle_data(self, data):
        if self._skip:
            return
        stripped = data.strip()
        if stripped:
            self.chunks.append(stripped)


def _fetch_text(url: str) -> list[str]:
    """Fetch URL and return visible text chunks. Returns [] on any failure."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        parser = _TextExtractor()
        parser.feed(resp.text)
        return parser.chunks
    except Exception as exc:
        logger.debug("rotowire fetch failed (%s): %s", url, exc)
        return []


def get_lineup_notes(date: "_date | None" = None) -> list[str]:
    """
    Return visible text from RotoWire's daily MLB lineups page.
    Includes player names, lineup positions, and pitcher notes.
    Returns [] silently on any failure.
    """
    return _fetch_text(LINEUP_URL)


def get_injury_notes(date: "_date | None" = None) -> list[str]:
    """
    Return visible text from RotoWire's MLB injury report page.
    Includes player names, injury status, and return timelines.
    Returns [] silently on any failure.
    """
    return _fetch_text(INJURY_URL)
