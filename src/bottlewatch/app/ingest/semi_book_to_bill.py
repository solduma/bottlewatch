"""SEMI book-to-bill scraper.

Fetches the public SEMI book-to-bill report page and extracts the
historical monthly ratio table. The ratio is a well-known leading
indicator for semiconductor lead-time pressure: a ratio > 1 means more
new orders than shipments, i.e. tightening.

Because the page is HTML and may change layout, the parser is
intentionally tolerant and returns an empty list (with a logged
warning) when the expected table is not found.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date

import httpx
from bs4 import BeautifulSoup

from bottlewatch.app.ingest.base import Adapter, Cadence, ProgressCallback, RawSignal
from bottlewatch.config import Settings

_LOGGER = logging.getLogger(__name__)

_DEFAULT_URL = "https://www.semi.org/en/market-info/statistics/semi-book-to-bill-report"

# Acceptable ratio formats: "1.12", "1.08", "0.95", etc.
_RATIO_RE = re.compile(r"(\d+\.\d+)")


@dataclass(frozen=True)
class _ParsedRow:
    period: str  # e.g. "2025-01"
    ratio: float


class SemiBookToBillAdapter(Adapter):
    """Scrape SEMI's monthly book-to-bill ratio.

    The adapter does not require an API key. It emits one
    `RawSignal` per successfully parsed month with
    `signal_name="book_to_bill_ratio"` and `segment="advanced_node_fabs"`
    (the canonical segment for the industry-level indicator).
    """

    name = "semi_book_to_bill"
    cadence = Cadence.MONTHLY

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def is_configured(self) -> tuple[bool, str]:
        return True, ""

    def fetch(
        self,
        period_start: date,
        period_end: date,
        progress: ProgressCallback | None = None,
    ) -> list[RawSignal]:
        """Fetch and parse the SEMI book-to-bill page.

        `period_start` and `period_end` are used to filter the parsed
        rows; the page itself returns all available history.
        """
        try:
            rows = self._fetch_and_parse()
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            _LOGGER.warning("semi_book_to_bill: HTTP error: %s", exc)
            return []

        if not rows:
            _LOGGER.warning("semi_book_to_bill: no ratio rows parsed from %s", _DEFAULT_URL)
            return []

        signals: list[RawSignal] = []
        for row in rows:
            try:
                year, month = map(int, row.period.split("-"))
                observed = date(year, month, 1)
            except (ValueError, TypeError):
                continue
            if not (period_start <= observed <= period_end):
                continue
            signals.append(
                RawSignal(
                    segment="advanced_node_fabs",
                    signal_name="book_to_bill_ratio",
                    value_num=row.ratio,
                    unit="ratio",
                    source=self.name,
                    source_id=f"semi_b2b:{row.period}",
                    observed_at=observed,
                )
            )
        return signals

    def _fetch_and_parse(self) -> list[_ParsedRow]:
        with httpx.Client(timeout=self._settings.eia_timeout_s, follow_redirects=True) as client:
            resp = client.get(_DEFAULT_URL)
            resp.raise_for_status()
        return _parse_page(resp.text)


def _parse_page(html: str) -> list[_ParsedRow]:
    """Parse the SEMI report page for a (period, ratio) table.

    Strategy:
    1. Look for tables whose headers include "Book-to-Bill" or "Ratio".
    2. For each row, find a period-looking cell (YYYY-MM or Month YYYY)
       and a ratio-looking cell.
    3. Fall back to regex-scanning all rows if no clear header is found.
    """
    soup = BeautifulSoup(html, "html.parser")
    rows: list[_ParsedRow] = []

    for table in soup.find_all("table"):
        header_text = " ".join(th.get_text(" ", strip=True) for th in table.find_all("th")).lower()
        if "book-to-bill" not in header_text and "ratio" not in header_text:
            continue
        for tr in table.find_all("tr"):
            cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
            if len(cells) < 2:
                continue
            period = _extract_period(cells)
            ratio = _extract_ratio(cells)
            if period and ratio is not None:
                rows.append(_ParsedRow(period=period, ratio=ratio))
        if rows:
            break

    if not rows:
        # Fallback: scan all table rows for any period + ratio pair.
        for table in soup.find_all("table"):
            for tr in table.find_all("tr"):
                cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
                period = _extract_period(cells)
                ratio = _extract_ratio(cells)
                if period and ratio is not None:
                    rows.append(_ParsedRow(period=period, ratio=ratio))

    return rows


_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

_PERIOD_RE = re.compile(r"(\d{4})[-/](\d{1,2})")
_YEAR_MONTH_RE = re.compile(
    r"(\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\b)\s+(\d{4})", re.IGNORECASE
)


def _extract_period(cells: list[str]) -> str | None:
    """Find a YYYY-MM period in the row cells."""
    for cell in cells:
        m = _PERIOD_RE.search(cell)
        if m:
            return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}"
        m2 = _YEAR_MONTH_RE.search(cell)
        if m2:
            month_name = m2.group(1).lower()[:3]
            month = _MONTHS.get(month_name)
            if month:
                return f"{int(m2.group(2)):04d}-{month:02d}"
    return None


def _extract_ratio(cells: list[str]) -> float | None:
    """Find the book-to-bill ratio in the row cells."""
    for cell in cells:
        # Skip cells that look like periods.
        if _PERIOD_RE.search(cell) or _YEAR_MONTH_RE.search(cell):
            continue
        m = _RATIO_RE.search(cell)
        if m:
            ratio = float(m.group(1))
            if 0.5 <= ratio <= 2.0:
                return ratio
    return None


def build_semi_book_to_bill_adapter(settings: Settings) -> SemiBookToBillAdapter:
    return SemiBookToBillAdapter(settings)
