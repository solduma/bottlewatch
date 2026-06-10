"""SEC EDGAR full-text adapter.

Walks the per-ticker submissions index, fetches 10-K/10-Q/8-K/20-F
filings, and counts capacity-related keyword mentions in the
Item 1A (Risk Factors) and Item 7/Item 2 (MD&A) sections.

The v1 keyword set ("lead time", "shortage", "capacity expansion")
was measured against real 10-Ks in the 2026-06-07 research.
The v1 plan's "CoWoS" / "advanced packaging" / "constrained
supply" / "backlog" list was rejected after measurement: those
phrases return 0-2 hits across the universe, with most of the
hits coming from defense/aero (not semis) and most filings
returning zero. See `research/03_data_sources.md` for the
fuller rationale.

Design notes (spec frozen 2026-06-07):

1. **Universe filter.** Same as `sec_insider`: dynamic EDGAR
   ticker-list fetch at adapter init, build `{ticker: cik}` map.
   Foreign listings (KS, TW, TSE, HK, SZ) are silently skipped.
   107 of 128 universe tickers are reachable.

2. **Per-ticker walk.** `data.sec.gov/submissions/CIK{cik}.json`
   returns the recent filings. We filter to forms in
   `{10-K, 10-Q, 8-K, 20-F, 10-K/A, 10-Q/A, 20-F/A}` and dates
   in the orchestrator's window. The primary doc URL is resolved
   via the per-accession `index.json` (same pattern as `sec_insider`).

3. **Section extraction.** BeautifulSoup strips HTML, then a
   regex finds the Item 1A and Item 7/Item 2 sections by their
   markers (`Item 1A.`, `Item 7.`, `Item 2.`). 8-K filings
   don't have these sections; we count keywords in the full text
   instead. If the marker regex doesn't match (some companies use
   `Item 1A:`, `Item 1A —`, etc.), we fall back to full-text count.

4. **Keyword counting.** Case-insensitive substring match for
   each phrase. `value_num = count` of distinct phrase matches
   in the section. One signal per (accession, keyword) regardless
   of count — even `value_num=0` is emitted, so downstream
   sees the filing was processed.

5. **Rate limit.** Same as `sec_insider`: 5 req/sec with
   `time.sleep(0.2)`. 107 tickers × 4 filings/ticker/year = ~430
   filings/year. ~3 minutes per monthly fetch.

6. **Retries.** `tenacity` 3x on transient errors (5xx, network,
   429). 4xx other than 429 propagates.

7. **Caching.** Stripped-text cache per accession under
   `data/cache/sec_edgar/{cik}/{acc_nodash}.txt`. The HTML is
   re-fetched only if the text cache is missing.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from bottlewatch.app.ingest.base import Adapter, Cadence, ProgressCallback, RawSignal
from bottlewatch.config import Settings

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# v1 keyword set. Measured 2026-06-07 against real EDGAR 10-Ks.
# See module docstring for the rejection of the v1 plan's list.
KEYWORDS: tuple[str, ...] = (
    "lead time",
    "shortage",
    "capacity expansion",
)

# Forms we process. Amendments accepted; 8-K processed (full-text).
ACCEPTED_FORMS: frozenset[str] = frozenset(
    {
        "10-K",
        "10-Q",
        "8-K",
        "20-F",
        "10-K/A",
        "10-Q/A",
        "20-F/A",
    }
)

# Inter-call sleep to stay under the SEC's 10 req/sec cap.
_REQUEST_DELAY_S = 0.2

# 1-day ticker-list TTL. Tickers change rarely; daily refresh
# is plenty.
_TICKER_LIST_TTL_DAYS = 1

# Transient conditions that warrant a retry. 4xx (other than 429)
# is caller error and propagates immediately.
_RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    httpx.TransportError,
    httpx.HTTPStatusError,
)


class _SECHardError(Exception):
    """Raised for non-retryable 4xx responses (bad accession URL, etc.)."""


# Item section markers. Some companies use `Item 1A.`, others
# `Item 1A:`, `Item 1A —`, or `Item 1A ` (newline-separated).
# The regex is permissive: matches the start of the section
# header. We find the next item marker to delimit the end.
_ITEM_1A_START_RE = re.compile(r"\bItem\s*1\s*A\s*[\.\:\-—]?\s", re.IGNORECASE)
_ITEM_1B_START_RE = re.compile(r"\bItem\s*1\s*B\s*[\.\:\-—]?\s", re.IGNORECASE)
_ITEM_2_START_RE = re.compile(r"\bItem\s*2\s*[\.\:\-—]?\s", re.IGNORECASE)
_ITEM_7_START_RE = re.compile(r"\bItem\s*7\s*[\.\:\-—]?\s", re.IGNORECASE)
_ITEM_7A_START_RE = re.compile(r"\bItem\s*7\s*A\s*[\.\:\-—]?\s", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class SECEdgarAdapter(Adapter):
    """Adapter for SEC EDGAR full-text (10-K/10-Q/8-K/20-F).

    Fetches per-ticker filings, strips HTML, and counts
    capacity-related keyword mentions in Item 1A + Item 7
    sections (full-text for 8-K). One signal per
    (accession, keyword), regardless of count.
    """

    name = "sec_edgar"
    cadence = Cadence.MONTHLY

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        # User-Agent is mandatory for SEC.
        self._headers = {
            "User-Agent": "Bottlewatch (iljoyoo@example.com)",
            "Accept-Encoding": "gzip, deflate",
        }
        # Lazy: the map is loaded on first fetch().
        self._ticker_to_cik: dict[str, int] = {}
        self._cik_to_ticker: dict[int, str] = {}

    # -- public adapter protocol ------------------------------------------------

    def is_configured(self) -> tuple[bool, str]:
        # EDGAR is free; no API key required. Only a User-Agent.
        return True, ""

    def fetch(
        self,
        period_start: date,
        period_end: date,
        progress: ProgressCallback | None = None,
    ) -> list[RawSignal]:
        """Pull capacity-keyword signals for the universe tickers
        in the [period_start, period_end] window.

        Algorithm:
        1. Ensure the ticker→CIK map is loaded.
        2. For each universe ticker with a CIK, fetch its recent
           submissions and filter to accepted forms in the window.
        3. For each accession, fetch + parse the primary doc HTML
           (cached on disk as stripped text).
        4. Extract Item 1A + Item 7 sections (or full text for 8-K).
        5. Count each keyword; emit one signal per (accession,
           keyword) with value_num = count.
        """
        self._load_universe_cik_map()
        signals: list[RawSignal] = []

        for ticker, cik in sorted(self._ticker_to_cik.items()):
            try:
                filings = self._fetch_recent_filings(cik, period_start, period_end)
            except _SECHardError as exc:
                _LOGGER.warning("sec_edgar: skipping ticker=%s: %s", ticker, exc)
                continue
            if not filings:
                continue

            for form, accession, filing_date in filings:
                section_text, _is_full_text = self._fetch_filing_text(cik, accession, form)
                if section_text is None:
                    # Malformed HTML; adapter already logged
                    continue
                for keyword in KEYWORDS:
                    count = self._count_phrase(section_text, keyword)
                    signals.append(self._build_signal(ticker, form, accession, filing_date, keyword, count))

        return signals

    # -- universe: ticker → CIK map -------------------------------------------

    def _load_universe_cik_map(self) -> None:
        """Build the {ticker: cik} map from EDGAR's ticker-list file.

        Caches the JSON to `data/cache/sec_edgar/tickers.json` for
        `_TICKER_LIST_TTL_DAYS`. No-op if the cache is fresh and
        already loaded.
        """
        if self._ticker_to_cik:
            return
        cache = self._cache_dir() / "tickers.json"
        payload: dict[str, Any] | None = None
        if cache.exists() and self._cache_is_fresh(cache):
            try:
                payload = json.loads(cache.read_text())
            except (OSError, json.JSONDecodeError):
                payload = None
        if payload is None:
            payload = self._fetch_ticker_list()
            try:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps(payload))
            except OSError as exc:
                _LOGGER.warning("sec_edgar: failed to cache ticker list: %s", exc)
        for entry in payload.values():
            ticker = entry.get("ticker")
            cik = entry.get("cik_str")
            if ticker and cik:
                self._ticker_to_cik[ticker] = int(cik)
                self._cik_to_ticker[int(cik)] = ticker

    @retry(
        retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1, max=10),
        reraise=True,
    )
    def _fetch_ticker_list(self) -> dict[str, Any]:
        url = "https://www.sec.gov/files/company_tickers.json"
        time.sleep(_REQUEST_DELAY_S)
        with httpx.Client(timeout=self._settings.eia_timeout_s) as client:
            resp = client.get(url, headers=self._headers, follow_redirects=True)
        if resp.status_code == 429 or resp.status_code >= 500:
            resp.raise_for_status()
        if resp.status_code >= 400:
            raise _SECHardError(f"EDGAR ticker list GET returned {resp.status_code}")
        return resp.json()

    # -- per-ticker submissions ------------------------------------------------

    def _fetch_recent_filings(self, cik: int, period_start: date, period_end: date) -> list[tuple[str, str, date]]:
        """Return [(form, accession, filing_date), ...] for the
        ticker's filings in [period_start, period_end] with form
        in `ACCEPTED_FORMS`.
        """
        url = f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
        try:
            payload = self._get_json(url)
        except _SECHardError as exc:
            raise _SECHardError(f"submissions fetch failed: {exc}") from exc

        recent = (payload.get("filings") or {}).get("recent") or {}
        forms = recent.get("form") or []
        accs = recent.get("accessionNumber") or []
        dates = recent.get("filingDate") or []
        out: list[tuple[str, str, date]] = []
        for form, acc, d in zip(forms, accs, dates):
            if form not in ACCEPTED_FORMS:
                continue
            try:
                filed = date.fromisoformat(d)
            except (TypeError, ValueError):
                continue
            if not (period_start <= filed <= period_end):
                continue
            out.append((form, acc, filed))
        return out

    @retry(
        retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1, max=10),
        reraise=True,
    )
    def _get_json(self, url: str) -> dict[str, Any]:
        time.sleep(_REQUEST_DELAY_S)
        with httpx.Client(timeout=self._settings.eia_timeout_s) as client:
            resp = client.get(url, headers=self._headers, follow_redirects=True)
        if resp.status_code == 429 or resp.status_code >= 500:
            resp.raise_for_status()
        if resp.status_code >= 400:
            raise _SECHardError(f"GET {url} returned {resp.status_code}")
        return resp.json()

    # -- per-filing text fetch + section extraction -----------------------------

    def _fetch_filing_text(self, cik: int, accession: str, form: str) -> tuple[str | None, bool]:
        """Fetch the primary doc HTML, strip to text, and extract
        the Item 1A + Item 7 sections (or full text for 8-K).

        Returns (text, is_full_text) where text is the section
        text or None on parse failure. Caches the stripped text
        to disk; subsequent calls hit the cache.
        """
        cache = self._cache_dir() / f"{cik}" / f"{accession.replace('-', '')}.txt"
        if cache.exists():
            try:
                text = cache.read_text()
                if form == "8-K":
                    return text, True
                return self._extract_sections(text, form)
            except OSError:
                pass  # fall through to refetch

        acc_nodash = accession.replace("-", "")
        primary = self._resolve_primary_doc_name(cik, acc_nodash, accession)
        if primary is None:
            primary = "form10k.htm"  # best guess for 10-K default
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{primary}"
        try:
            html = self._get_text(url)
        except _SECHardError as exc:
            _LOGGER.warning(
                "sec_edgar: primary doc fetch failed, accession=%s: %s",
                accession,
                exc,
            )
            return None, False
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None, False
            raise

        text = self._strip_html(html)
        # Cache the stripped text
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(text)
        except OSError as exc:
            _LOGGER.debug("sec_edgar: failed to cache accession %s: %s", accession, exc)

        if form == "8-K":
            return text, True
        return self._extract_sections(text, form)

    def _resolve_primary_doc_name(self, cik: int, acc_nodash: str, accession: str) -> str | None:
        """Fetch the accession's index.json; return the primary
        doc name. Returns None on 404.
        """
        index_cache = self._cache_dir() / f"{cik}" / f"{acc_nodash}.index.json"
        if index_cache.exists():
            try:
                payload = json.loads(index_cache.read_text())
            except (OSError, json.JSONDecodeError):
                payload = None
        else:
            payload = None

        if payload is None:
            url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/index.json"
            try:
                payload = self._get_json(url)
            except _SECHardError:
                return None
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    return None
                raise
            try:
                index_cache.parent.mkdir(parents=True, exist_ok=True)
                index_cache.write_text(json.dumps(payload))
            except OSError as exc:
                _LOGGER.debug("sec_edgar: failed to cache index for %s: %s", accession, exc)

        items = (payload.get("directory") or {}).get("item") or []
        for item in items:
            if str(item.get("primary", "")).lower() == "true":
                return item["name"]
        for item in items:
            if str(item.get("type", "")) in ACCEPTED_FORMS:
                return item["name"]
        return None

    @retry(
        retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1, max=10),
        reraise=True,
    )
    def _get_text(self, url: str) -> str:
        time.sleep(_REQUEST_DELAY_S)
        with httpx.Client(timeout=self._settings.eia_timeout_s) as client:
            resp = client.get(url, headers=self._headers, follow_redirects=True)
        if resp.status_code == 429 or resp.status_code >= 500:
            resp.raise_for_status()
        if resp.status_code == 404:
            raise _SECHardError(f"GET {url} returned 404")
        if resp.status_code >= 400:
            raise _SECHardError(f"GET {url} returned {resp.status_code}")
        return resp.text

    def _strip_html(self, html: str) -> str:
        """Strip HTML to plain text. Returns the text with one
        whitespace per token. Handles malformed HTML gracefully
        (BeautifulSoup's default parser is lenient).
        """
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception as exc:
            _LOGGER.warning("sec_edgar: HTML parse error: %s", exc)
            return ""
        # Use `.get_text(separator=' ')` to get one-space-separated
        # text; collapse runs of whitespace below.
        text = soup.get_text(separator=" ")
        return re.sub(r"\s+", " ", text).strip()

    def _extract_sections(self, text: str, form: str) -> tuple[str | None, bool]:
        """Extract Item 1A (Risk Factors) + Item 7 (MD&A, 10-K/20-F)
        or Item 2 (MD&A, 10-Q) sections from the stripped text.

        Returns (section_text, is_full_text). If the section
        markers can't be found, falls back to the full text
        (returns (text, True)) so keywords still get counted.

        Per the 2026-06-07 research, the Item 1A section is where
        ~80% of capacity language lives. The Item 7/Item 2
        section is supplementary.
        """
        # Find Item 1A start
        m_1a = _ITEM_1A_START_RE.search(text)
        if m_1a is None:
            # No Item 1A found; this is unusual for 10-K/10-Q/20-F.
            # Fall back to full text.
            return text, True
        start_1a = m_1a.end()

        # Find Item 1A end (= next Item marker; 1B or 2)
        end_candidates: list[int] = []
        m_1b = _ITEM_1B_START_RE.search(text, start_1a)
        if m_1b is not None:
            end_candidates.append(m_1b.start())
        m_2 = _ITEM_2_START_RE.search(text, start_1a)
        if m_2 is not None:
            end_candidates.append(m_2.start())
        m_7 = _ITEM_7_START_RE.search(text, start_1a)
        if m_7 is not None:
            end_candidates.append(m_7.start())
        end_1a = min(end_candidates) if end_candidates else len(text)
        section_1a = text[start_1a:end_1a]

        # For 10-K and 20-F: also extract Item 7
        # For 10-Q: extract Item 2 instead
        section_md = ""
        if form in ("10-K", "20-F", "10-K/A", "20-F/A"):
            m_7 = _ITEM_7_START_RE.search(text)
            if m_7 is not None:
                start_7 = m_7.end()
                end_candidates_7: list[int] = []
                m_7a = _ITEM_7A_START_RE.search(text, start_7)
                if m_7a is not None:
                    end_candidates_7.append(m_7a.start())
                # Item 7 typically ends at Item 8 (financials)
                m_8 = re.search(r"\bItem\s*8\s*[\.\:\-—]?\s", text[start_7:], re.IGNORECASE)
                if m_8 is not None:
                    end_candidates_7.append(start_7 + m_8.start())
                end_7 = min(end_candidates_7) if end_candidates_7 else len(text)
                section_md = text[start_7:end_7]
        elif form in ("10-Q", "10-Q/A"):
            m_2 = _ITEM_2_START_RE.search(text)
            if m_2 is not None:
                start_2 = m_2.end()
                # Item 2 typically ends at Item 3
                m_3 = re.search(r"\bItem\s*3\s*[\.\:\-—]?\s", text[start_2:], re.IGNORECASE)
                end_2 = start_2 + m_3.start() if m_3 is not None else len(text)
                section_md = text[start_2:end_2]

        combined = section_1a + " " + section_md
        return combined, False

    @staticmethod
    def _count_phrase(text: str, phrase: str) -> int:
        """Case-insensitive count of `phrase` occurrences in
        `text`. Uses a non-overlapping substring search.
        """
        return len(re.findall(re.escape(phrase), text, flags=re.IGNORECASE))

    # -- signal construction ---------------------------------------------------

    def _build_signal(
        self,
        ticker: str,
        form: str,
        accession: str,
        filing_date: date,
        keyword: str,
        count: int,
    ) -> RawSignal:
        segment, _subsegment = self._ticker_to_segment(ticker)
        acc_nodash = accession.replace("-", "")
        # Map keyword phrase to a snake_case signal_name.
        # "lead time" → "lead_time_mentions"
        signal_name = keyword.replace(" ", "_") + "_mentions"
        return RawSignal(
            segment=segment,
            subsegment="edgar_capacity",
            signal_name=signal_name,
            value_num=float(count),
            unit="count",
            source=self.name,
            source_id=f"edgar:{ticker}:{form}:{acc_nodash}:{keyword.replace(' ', '_')}",
            observed_at=filing_date,
            value_text=f"{count} mentions in {form}",
            tickers=json.dumps([ticker]),
            geography=None,  # EDGAR filings are US-listed by definition
        )

    def _ticker_to_segment(self, ticker: str) -> tuple[str, str | None]:
        """Read 02_universe.csv to map ticker to (segment, subsegment)."""
        csv_path = self._project_root() / "research" / "02_universe.csv"
        if not csv_path.exists():
            return ("unclassified", None)
        try:
            with csv_path.open() as f:
                next(f, None)
                for line in f:
                    parts = line.split(",")
                    if parts and parts[0].strip() == ticker:
                        return (
                            parts[3].strip() if len(parts) > 3 else "unclassified",
                            parts[4].strip() if len(parts) > 4 and parts[4].strip() else None,
                        )
        except OSError as exc:
            _LOGGER.debug("sec_edgar: could not read universe CSV for %s: %s", ticker, exc)
        return ("unclassified", None)

    # -- helpers ---------------------------------------------------------------

    def _cache_dir(self) -> Path:
        return self._settings.refresh_log_path.parent / "sec_edgar"

    def _project_root(self) -> Path:
        return Path(__file__).resolve().parents[4]

    @staticmethod
    def _cache_is_fresh(path: Path) -> bool:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return False
        age = datetime.now(tz=timezone.utc).timestamp() - mtime
        return age < _TICKER_LIST_TTL_DAYS * 86400


def build_sec_edgar_adapter(settings: Settings) -> SECEdgarAdapter:
    """Factory: the orchestrator calls this with a Settings instance."""
    return SECEdgarAdapter(settings)
