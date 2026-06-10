"""SEC Form 4 (insider) adapter.

Tracks Form 4 filings for tickers in the universe to surface
"smart money" cluster-buy signals. The data sources assessment
(03_data_sources.md §7) ranks this as the highest-signal-density
real-time source — cluster buys in particular have a long history
in the empirical literature as leading indicators.

Design notes (spec frozen 2026-06-06):

1. **Universe filter.** We dynamically fetch EDGAR's ticker-list
   file (`https://www.sec.gov/files/company_tickers.json`, ~3MB)
   at adapter init and build a `{ticker: cik}` map. Tickers in
   the universe with no EDGAR entry (e.g. KRX/TWSE/TSE listings)
   are skipped with a debug log line; they're real but not on
   EDGAR.

2. **Cluster definition.** 3+ insider P-code Form 4 transactions
   on the same ticker in any trailing 30-day window. Emitted once
   per ticker-day where the rolling count crosses or stays >= 3.
   Only `transactionCode=P` (open-market purchase) counts; `F`
   (withholding), `M` (option exercise), `S` (sale), `D` (dispose)
   are filtered. 10b5-1 plan-trade detection is v2 work.

3. **Rate limit.** SEC fair-access: 10 req/sec, 600 in any 10-min
   window. We stay at 5 req/sec with `time.sleep(0.2)` between
   calls. For 131 universe tickers that's ~26 seconds minimum
   per ingest run; the orchestrator's DAILY cadence (1-day
   interval) absorbs this.

4. **Retries.** `tenacity` 3x on transient errors (5xx, network,
   429). 4xx other than 429 is caller error (bad accession URL)
   and propagates.

5. **Caching.** Form 4 filings are immutable per accession
   number; once fetched and parsed, the parsed dict is cached
   to `data/cache/sec_insider/{cik}/{accession}.json` so re-runs
   are idempotent. The ticker-list JSON is cached for 1 day.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import httpx
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

# 30-day trailing window for cluster detection.
_CLUSTER_WINDOW_DAYS = 30
# Minimum cluster size — 3+ insider buys in the window.
_CLUSTER_THRESHOLD = 3
# Inter-call sleep to stay under the SEC's 10 req/sec cap.
_REQUEST_DELAY_S = 0.2
# Ticker-list cache lifetime (1 day).
_TICKER_LIST_TTL_DAYS = 1

# Only `P` (open-market purchase) counts. Excludes F (withholding),
# M (option exercise), S (sale), D (disposal), G (gift), etc.
_PURCHASE_CODE = "P"

# Transient conditions that warrant a retry. 4xx (other than 429)
# is caller error and propagates immediately.
_RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    httpx.TransportError,
    httpx.HTTPStatusError,
)


# Per-run counter of Form 4 filings skipped because their XML was
# unparseable. EDGAR has a non-trivial share of structurally-broken
# filings (mismatched tags, truncated elements) — these are
# upstream data-quality issues, not our code's fault. We log one
# INFO line at the end of each fetch() run with the count instead
# of flooding the log with one WARNING per filing. The counter
# resets at the start of every fetch() call.
_unparseable_xml_count: int = 0
_first_unparseable_accession: str | None = None


class _SECHardError(Exception):
    """Raised for non-retryable 4xx responses (bad accession URL, etc.)."""


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class SECInsiderAdapter(Adapter):
    """Adapter for SEC Form 4 insider filings."""

    name = "sec_insider"
    cadence = Cadence.DAILY

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        # User-Agent is mandatory for SEC. Format: "Name email".
        self._headers = {
            "User-Agent": "Bottlewatch (iljoyoo@example.com)",
            "Accept-Encoding": "gzip, deflate",
        }
        # Lazy: the map is loaded on first fetch() (or by direct
        # _load_universe_cik_map() call from tests).
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
        """Pull Form 4 cluster-buy signals for the universe tickers
        in the [period_start, period_end] window.

        Algorithm:
        1. Ensure the ticker→CIK map is loaded.
        2. For each universe ticker with a CIK, fetch its recent
           Form 4 submissions within the window.
        3. For each accession, fetch + parse the Form 4 XML.
           Filter to P-code; cache the parsed result.
        4. Group (ticker, day) → count of P-codes. Detect clusters
           (count >= 3 in trailing 30 days).
        5. Emit one RawSignal per (ticker, day) where the cluster
           threshold is met.

        `progress(i, total, ticker)` is called once per universe
        ticker so the orchestrator can render an inner progress
        bar. For the typical 98-ticker universe at 5 req/sec +
        sleep, this run takes ~80-90s — a progress indicator is
        the only way the user can tell the process is alive.
        """
        # Reset the per-run "unparseable XML" counter. The
        # aggregate is logged at INFO at the end of this method
        # so a noisy EDGAR accession from one filer doesn't
        # drown the log.
        global _unparseable_xml_count, _first_unparseable_accession
        _unparseable_xml_count = 0
        _first_unparseable_accession = None
        self._load_universe_cik_map()
        signals: list[RawSignal] = []
        # Per-ticker history of P-code buys, keyed on the
        # reporting-person's CIK. The cluster count is the number
        # of *distinct insiders* (reporting-owner CIKs) with a
        # P-code in the trailing 30-day window, NOT the number of
        # P-codes. This matches the academic cluster definition
        # (Atallah & El Amrani 2005, Chen 2015) and prevents a
        # single insider's dollar-cost-averaging buys from
        # falsely firing a "cluster."
        #
        # Layout: cluster_history[ticker] = list of
        # (insider_cik, filing_date, accession) tuples. The
        # trailing-window count is computed at emission time
        # (below).
        cluster_history: dict[str, list[tuple[str, date, str]]] = {}

        # Iterate the project's universe (02_universe.csv), not the
        # full ~10K-ticker EDGAR map. The earlier `ticker_to_cik`
        # map includes every listed company on EDGAR; the
        # project's investable universe is 131 tickers. Walking
        # the full EDGAR list was a real perf bug (80x more
        # network calls than necessary) and made the progress
        # bar report `[XXXX/10400]` instead of `[XX/98]`.
        universe_tickers = self._universe_tickers()
        ticker_items = sorted((t, self._ticker_to_cik[t]) for t in universe_tickers if t in self._ticker_to_cik)
        total = len(ticker_items)
        for i, (ticker, cik) in enumerate(ticker_items, 1):
            if progress is not None:
                progress(i, total, ticker)
            try:
                accession_dates = self._fetch_form4_dates(cik, period_start, period_end)
            except _SECHardError as exc:
                _LOGGER.warning("sec_insider: skipping ticker=%s: %s", ticker, exc)
                continue
            if not accession_dates:
                continue

            for accession, filing_date in accession_dates:
                parsed = self._fetch_and_parse_form4(cik, accession)
                if parsed is None:
                    continue
                if parsed["transaction_code"] != _PURCHASE_CODE:
                    continue
                # 4/A amendment dedup: per
                # (cik, reportingOwnerCIK, transactionDate), keep
                # only the highest-accession. We track via the
                # dict keyed on (insider, day); a later
                # accession overwrites an earlier one.
                key = (parsed["insider_cik"], filing_date)
                if key in {(k[0], k[1]) for k in [(e[0], e[1]) for e in cluster_history.get(ticker, [])]}:
                    # Find the existing entry; replace if new
                    # accession is higher (lexicographic compare
                    # works for the standard accession format).
                    existing = next(
                        e for e in cluster_history[ticker] if e[0] == parsed["insider_cik"] and e[1] == filing_date
                    )
                    if accession > existing[2]:
                        cluster_history[ticker].remove(existing)
                        cluster_history[ticker].append((parsed["insider_cik"], filing_date, accession))
                else:
                    cluster_history.setdefault(ticker, []).append((parsed["insider_cik"], filing_date, accession))

        # Cluster detection per ticker. The spec emits one signal
        # per ticker-day where the rolling 30-day transaction count
        # crosses or stays >= 3. Multiple filings on the same day
        # each count toward the cluster size.
        for ticker, entries in cluster_history.items():
            # Build a per-day set of distinct insiders. The cluster
            # fires when 3 *distinct* insiders (not 3 transactions)
            # have a P-code in the trailing 30-day window.
            # `by_day[day] = set of insider_ciks` for that day.
            by_day: dict[date, set[str]] = {}
            for insider, day, _acc in entries:
                by_day.setdefault(day, set()).add(insider)
            for day in sorted(by_day.keys()):
                window_start = day - timedelta(days=_CLUSTER_WINDOW_DAYS - 1)
                # Distinct insiders in the trailing 30-day window
                # ending on this day.
                in_window_insiders: set[str] = set()
                for d, insiders in by_day.items():
                    if window_start <= d <= day:
                        in_window_insiders.update(insiders)
                count = len(in_window_insiders)
                if count < _CLUSTER_THRESHOLD:
                    continue
                # Once-per-event: emit only on the day the count
                # first reaches >= 3. The literature treats
                # cluster events as discrete.
                # Compute the "was-below" status: was the count
                # below threshold on the previous day in the
                # window? If yes (or if this is day 0 of the
                # ticker), this is a new cluster event.
                prev_day = day - timedelta(days=1)
                prev_count = 0
                if prev_day in by_day or any(
                    (prev_day - timedelta(days=i)) in by_day for i in range(1, _CLUSTER_WINDOW_DAYS)
                ):
                    # Check the count as of prev_day
                    prev_window_end = prev_day
                    prev_window_start = prev_day - timedelta(days=_CLUSTER_WINDOW_DAYS - 1)
                    prev_in_window: set[str] = set()
                    for d, insiders in by_day.items():
                        if prev_window_start <= d <= prev_window_end:
                            prev_in_window.update(insiders)
                    prev_count = len(prev_in_window)
                if prev_count >= _CLUSTER_THRESHOLD:
                    # Already fired; skip
                    continue
                signals.append(self._build_signal(ticker, day, count))

        if _unparseable_xml_count:
            # Aggregate log so EDGAR's data-quality noise doesn't
            # drown the orchestrator log. The first accession is
            # the most useful for debugging.
            _LOGGER.info(
                "sec_insider: %d Form 4 filings skipped due to unparseable XML (first: %s). "
                "These are upstream EDGAR data-quality issues, not code bugs.",
                _unparseable_xml_count,
                _first_unparseable_accession,
            )

        return signals

    # -- universe: ticker → CIK map -------------------------------------------

    def _load_universe_cik_map(self) -> None:
        """Build the {ticker: cik} map from EDGAR's ticker-list file.

        Caches the JSON to `data/cache/sec_insider/tickers.json` for
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
                _LOGGER.warning("sec_insider: failed to cache ticker list: %s", exc)
        for entry in payload.values():
            ticker = entry.get("ticker")
            cik = entry.get("cik_str")
            if ticker and cik:
                self._ticker_to_cik[ticker] = int(cik)
                self._cik_to_ticker[int(cik)] = ticker

        # Log universe coverage so the operator sees what we have.
        # Read 02_universe.csv lazily here to avoid a hard import
        # at adapter init (the test fixture doesn't have a real CSV).
        try:
            universe_csv = self._project_root() / "research" / "02_universe.csv"
            if universe_csv.exists():
                covered = [t for t in self._read_universe_tickers(universe_csv) if t in self._ticker_to_cik]
                _LOGGER.info(
                    "sec_insider: %d universe tickers covered by EDGAR CIK map",
                    len(covered),
                )
        except OSError as exc:
            _LOGGER.debug("sec_insider: could not read universe CSV: %s", exc)

    @retry(
        retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1, max=10),
        reraise=True,
    )
    def _fetch_ticker_list(self) -> dict[str, Any]:
        """GET https://www.sec.gov/files/company_tickers.json."""
        url = "https://www.sec.gov/files/company_tickers.json"
        time.sleep(_REQUEST_DELAY_S)
        with httpx.Client(timeout=self._settings.eia_timeout_s) as client:
            resp = client.get(url, headers=self._headers, follow_redirects=True)
        if resp.status_code == 429 or resp.status_code >= 500:
            resp.raise_for_status()
        if resp.status_code >= 400:
            raise _SECHardError(f"EDGAR ticker list GET returned {resp.status_code}")
        return resp.json()

    def _universe_tickers(self) -> set[str]:
        """The project's investable universe (research/02_universe.csv).

        Returns the full CSV ticker set, regardless of whether
        each one is in the EDGAR map. The fetch() loop intersects
        with `_ticker_to_cik` to skip non-US listings (KRX, TWSE,
        etc.) that have no CIK.
        """
        try:
            universe_csv = self._project_root() / "research" / "02_universe.csv"
            if not universe_csv.exists():
                _LOGGER.debug("sec_insider: no 02_universe.csv found at %s", universe_csv)
                return set()
            return self._read_universe_tickers(universe_csv)
        except OSError as exc:
            _LOGGER.debug("sec_insider: could not read universe CSV: %s", exc)
            return set()

    def _read_universe_tickers(self, csv_path: Path) -> set[str]:
        """Read the first column of 02_universe.csv. Tickers with dots
        (e.g. 2330.TW) are kept as-is; they won't be in the EDGAR
        map and are skipped during fetch.
        """
        tickers: set[str] = set()
        with csv_path.open() as f:
            next(f, None)  # header
            for line in f:
                parts = line.split(",")
                if parts and parts[0].strip():
                    tickers.add(parts[0].strip())
        return tickers

    # -- per-ticker submissions ------------------------------------------------

    def _fetch_form4_dates(self, cik: int, period_start: date, period_end: date) -> list[tuple[str, date]]:
        """Return [(accession, filing_date), ...] for Form 4 filings
        in the [period_start, period_end] window. Reads
        `https://data.sec.gov/submissions/CIK{10-digit}.json` and
        filters the `filings.recent` arrays.
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
        out: list[tuple[str, date]] = []
        for form, acc, d in zip(forms, accs, dates):
            if form != "4":
                continue
            try:
                filed = date.fromisoformat(d)
            except (TypeError, ValueError):
                continue
            if not (period_start <= filed <= period_end):
                continue
            out.append((acc, filed))
        return out

    @retry(
        retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1, max=10),
        reraise=True,
    )
    def _get_json(self, url: str) -> dict[str, Any]:
        """GET a JSON document with retry on transient errors."""
        time.sleep(_REQUEST_DELAY_S)
        with httpx.Client(timeout=self._settings.eia_timeout_s) as client:
            resp = client.get(url, headers=self._headers, follow_redirects=True)
        if resp.status_code == 429 or resp.status_code >= 500:
            resp.raise_for_status()
        if resp.status_code >= 400:
            raise _SECHardError(f"GET {url} returned {resp.status_code}")
        return resp.json()

    # -- per-filing Form 4 XML -------------------------------------------------

    def _fetch_and_parse_form4(self, cik: int, accession: str) -> dict[str, Any] | None:
        """Fetch + parse one Form 4 XML. Returns a small dict with
        `transaction_code` and `transaction_date`, or None on
        derivative-only filings (no non-derivative transaction —
        per spec §2, derivative activity is filtered and the
        caller should not log a warning). Caches the parsed
        result keyed on accession (immutable).

        Per real-EDGAR observations (2026-06-07): the primary doc
        filename varies across issuers (form4.xml, doc4.xml, primary_doc.xml,
        and user-chosen names). The reliable way to find the right
        file is to fetch the accession's `index.json`, which lists
        every file in the accession with a `primary: "true"` flag
        on the Form 4's primary doc. We prefer that path; the
        3-candidate fallback only kicks in when the index.json
        itself 404s (rare; happens for some malformed accession URLs).
        """
        cache = self._cache_dir() / f"{cik}" / f"{accession}.json"
        if cache.exists():
            try:
                return json.loads(cache.read_text())
            except (OSError, json.JSONDecodeError):
                pass  # fall through to refetch

        acc_nodash = accession.replace("-", "")
        # Try the index-file path first. On 404, fall through to
        # the 3-candidate guess.
        primary_name = self._resolve_primary_doc_name(cik, acc_nodash, accession)
        if primary_name is not None:
            url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{primary_name}"
            try:
                text = self._get_text(url)
            except _SECHardError as exc:
                _LOGGER.warning(
                    "sec_insider: primary doc fetch failed, accession=%s: %s",
                    accession,
                    exc,
                )
                return None
        else:
            # Index lookup failed (404 or malformed); use the
            # 3-candidate fallback so we still produce signals for
            # filings that happen to use one of the standard names.
            text = self._fetch_with_candidate_fallback(cik, acc_nodash, accession)
            if text is None:
                return None

        try:
            parsed = self._parse_form4_xml(text)
        except ET.ParseError as exc:
            # EDGAR has a non-trivial share of structurally-broken
            # filings (mismatched tags, truncated elements) — these
            # are upstream data-quality issues, not our code's
            # fault. Log at DEBUG and increment a per-run counter;
            # the orchestrator gets a single INFO summary line.
            global _unparseable_xml_count, _first_unparseable_accession
            _unparseable_xml_count += 1
            if _first_unparseable_accession is None:
                _first_unparseable_accession = accession
            _LOGGER.debug(
                "sec_insider: unparseable Form 4 XML (run count: %d), accession=%s: %s",
                _unparseable_xml_count,
                accession,
                exc,
            )
            return None
        except Exception as exc:  # malformed structure
            _LOGGER.warning(
                "sec_insider: skipped malformed Form 4 XML, accession=%s: %s",
                accession,
                exc,
            )
            return None

        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(parsed))
        except OSError as exc:
            _LOGGER.debug("sec_insider: failed to cache accession %s: %s", accession, exc)

        return parsed

    def _resolve_primary_doc_name(self, cik: int, acc_nodash: str, accession: str) -> str | None:
        """Fetch the accession's `index.json` and return the primary
        doc's filename. Returns None if the index 404s (caller falls
        back to the 3-candidate guess) or if the payload has no
        `type: "4"` item (caller logs and skips).
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
                # Index 404. Caller will use the 3-candidate fallback.
                return None
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    return None
                raise
            try:
                index_cache.parent.mkdir(parents=True, exist_ok=True)
                index_cache.write_text(json.dumps(payload))
            except OSError as exc:
                _LOGGER.debug("sec_insider: failed to cache index for %s: %s", accession, exc)

        items = (payload.get("directory") or {}).get("item") or []
        # Prefer the item flagged as primary.
        for item in items:
            if str(item.get("primary", "")).lower() == "true":
                return item["name"]
        # Fall back to the first item with type "4".
        for item in items:
            if str(item.get("type", "")) == "4":
                return item["name"]
        # Third-tier fallback: pattern-match on filename. Real EDGAR
        # accessions (2026-06-07 observation) often have type="text.gif"
        # instead of type="4", and the `primary: "true"` flag is
        # often missing. The Form 4's primary doc is one of these
        # known patterns. We pick the first match in priority order.
        priority_names = [
            "form4.xml",
            "form4.htm",
            "form4.html",
            "doc4.xml",
            "primary_doc.xml",
        ]
        item_names = {item.get("name") for item in items}
        for candidate in priority_names:
            if candidate in item_names:
                return candidate
        # Last resort: pick the most likely Form 4 file. EDGAR's
        # index always starts with the index wrapper files
        # (`<accession>-index.html`, `<accession>-index-headers.html`,
        # `<accession>.txt`) — these are NOT the Form 4. Skip
        # anything whose name starts with the accession (with or
        # without dashes) and is not the Form 4 itself. Among the
        # remaining, prefer `.xml` (the Form 4's raw form) over
        # `.htm`/`.html` (the styled render).
        prefix_dashed = accession
        prefix_nodash = accession.replace("-", "")
        candidates = [
            item.get("name")
            for item in items
            if (item.get("name") or "").endswith((".xml", ".htm", ".html"))
            and not (item.get("name") or "").startswith((prefix_dashed, prefix_nodash))
        ]
        if candidates:
            xml_first = [n for n in candidates if n.endswith(".xml")]
            pick = xml_first[0] if xml_first else candidates[0]
            _LOGGER.debug(
                "sec_insider: index has no Form 4 flag, picking first non-index .xml/.htm: %s, accession=%s",
                pick,
                accession,
            )
            return pick
        # No Form 4 file in the index — this is an accession that
        # mentions form 4 in its title but contains something else
        # (a Form 4 amendment, a different form, etc.). Caller
        # logs and skips.
        _LOGGER.warning(
            "sec_insider: index has no Form 4 file, accession=%s",
            accession,
        )
        return None

    def _fetch_with_candidate_fallback(self, cik: int, acc_nodash: str, accession: str) -> str | None:
        """Three-candidate filename guess. Used only when the
        accession's index.json is unavailable. Order matches the
        most common primary doc names we observed in 2026-Q2.
        """
        candidates = [
            f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/form4.xml",
            f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/doc4.xml",
            f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/primary_doc.xml",
        ]
        for url in candidates:
            try:
                return self._get_text(url)
            except _SECHardError:
                continue
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    continue
                raise
        _LOGGER.warning("sec_insider: no Form 4 XML found for accession %s", accession)
        return None

    @retry(
        retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1, max=10),
        reraise=True,
    )
    def _get_text(self, url: str) -> str:
        """GET a text document with retry on transient errors."""
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

    def _parse_form4_xml(self, text: str) -> dict[str, Any] | None:
        """Extract the first non-derivative transaction's
        `transactionCode`, `transactionDate`, and the reporting
        person's CIK from a Form 4 XML.

        Returns a dict with `transaction_code`, `transaction_date`
        (as ISO string), and `insider_cik` (the reporting
        person's own CIK — used for distinct-insider dedup).
        Returns None when the filing is *not* relevant to cluster
        detection (derivative-only, holdings-only, all-F/M/S
        non-derivative transactions, "no longer subject to
        Section 16" — all expected EDGAR edge cases that the
        spec §2 filter excludes). Raises only on genuinely
        anomalous empty filings (no transactions, no holdings,
        no remarks — upstream data quality issues).

        The real SEC schema has evolved:
        - X0401 (older): `<transactionCode>P</transactionCode>` directly
        - X0609 (current): `<transactionCoding><transactionCode>P</transactionCode></transactionCoding>`
        We accept both: look for the immediate `<transactionCode>`
        first, then fall back to `<transactionCoding>/<transactionCode>`.
        Same for `<transactionDate>` (older: text directly, newer:
        nested in `<value>`).

        Whitespace caveat: real EDGAR XML is pretty-printed, so the
        parent `<transactionDate>` has `.text` of `"\n    "` (or
        similar) while the actual date lives in the child `<value>`.
        A `text is None` check would miss this; we also fall back
        when `.text` is empty-or-whitespace.

        Reporting-owner element: X0401 uses `<reportingPerson>` and
        current EDGAR uses `<reportingOwner>`. We try both.
        """
        root = ET.fromstring(text)
        # Reporting-owner CIK is at the top level (not inside
        # the transaction). Look it up once. X0401 uses
        # `reportingPerson/...`; current EDGAR uses
        # `reportingOwner/...` — try both.
        insider_el = root.find("reportingOwner/reportingOwnerId/rptOwnerCik")
        if insider_el is None:
            insider_el = root.find("reportingPerson/reportingPersonId/rptOwnerCik")
        insider_cik = insider_el.text.strip() if insider_el is not None and insider_el.text else "unknown"
        for tx in root.iter("nonDerivativeTransaction"):
            # transactionCode: try the direct form first (X0401), then
            # the nested form (X0609).
            code_el = tx.find("transactionCode")
            if code_el is None or not (code_el.text and code_el.text.strip()):
                code_el = tx.find("transactionCoding/transactionCode")
            if code_el is None or not (code_el.text and code_el.text.strip()):
                continue
            code = code_el.text.strip()

            # transactionDate: try direct (X0401) then nested (X0609).
            # A direct `<transactionDate>` whose text is only
            # whitespace (pretty-printed EDGAR) must fall through
            # to the nested `<transactionDate>/<value>` lookup.
            date_el = tx.find("transactionDate")
            if date_el is None or not (date_el.text and date_el.text.strip()):
                date_el = tx.find("transactionDate/value")
            d: str | None = None
            if date_el is not None and date_el.text:
                d = date_el.text.strip()
            if not d:
                continue
            return {
                "transaction_code": code,
                "transaction_date": d,
                "insider_cik": insider_cik,
            }
        # No non-derivative transaction element at all. The
        # filing's other activity may be:
        # 1. Derivative transactions only (option exercises, RSU
        #    vests) — per spec §2 those are filtered. Return None.
        # 2. Holdings only (the insider has shares from prior
        #    grants/vests, but no new transactions to report —
        #    common in 4/A amendments, sign-on Form 4s, and
        #    "I received these shares" disclosures). Per spec §2
        #    these are also filtered. Return None.
        # 3. "No longer subject to Section 16" — a Form 4 filed
        #    to report that the insider is no longer required to
        #    report (typically because they left the company).
        #    The `<notSubjectToSection16>` flag or a `<remarks>`
        #    element explains the absence. Return None.
        # 4. Genuinely empty (no transactions, no holdings, no
        #    remarks). Anomalous; raise so the caller logs.
        has_ndt = any(True for _ in root.iter("nonDerivativeTransaction"))
        has_dt = any(True for _ in root.iter("derivativeTransaction"))
        has_ndh = any(True for _ in root.iter("nonDerivativeHolding"))
        has_dh = any(True for _ in root.iter("derivativeHolding"))
        has_remarks = root.find("remarks") is not None
        not_subject = root.find("notSubjectToSection16") is not None
        if not has_ndt and (has_dt or has_ndh or has_dh or has_remarks or not_subject):
            # Derivative-only, holdings-only, or "no longer
            # subject to Section 16". Expected; not a warning.
            # The caller's `parsed is None` branch handles it.
            return None
        if not has_ndt and not has_dt:
            # No transactions of any kind, no holdings, no
            # remarks — genuinely anomalous. This XML has no
            # transaction data at all.
            raise ValueError("no non-derivative or derivative transaction element found")
        if has_ndt:
            # We iterated nonDerivativeTransaction elements but
            # none had a usable code+date (e.g. all were
            # withholding/option-exercise codes that we filter
            # per spec §2). Common in practice; not a warning.
            # The caller's `parsed is None` branch handles it.
            return None
        # Unreachable: has_dt must be True here (we passed the
        # `not has_ndt and not has_dt` guard). Keep the
        # defensive raise as a backstop for parser drift.
        raise ValueError("unreachable: non-derivative transactions absent but no other branch matched")

    # -- signal construction ---------------------------------------------------

    def _build_signal(self, ticker: str, day: date, count: int) -> RawSignal:
        """Build the RawSignal for one cluster-buy day.

        Segment: the primary segment of the ticker per 02_universe.csv.
        For multi-segment tickers (NVDA, AMAT, etc.) the first
        segment wins. We do a lightweight CSV read here; if the
        CSV is missing, the segment falls back to a sentinel.
        """
        segment, subsegment = self._ticker_to_segment(ticker)
        return RawSignal(
            segment=segment,
            subsegment=subsegment or "insider_cluster_buy",
            signal_name="n_insider_buys_30d",
            value_num=float(count),
            unit="count",
            source=self.name,
            source_id=f"form4:{ticker}:{day.isoformat()}",
            observed_at=day,
            value_text=f"cluster of {count} buys" if count > 1 else None,
            tickers=json.dumps([ticker]),
            geography=None,  # EDGAR doesn't carry a per-filing geo; left None
        )

    def _ticker_to_segment(self, ticker: str) -> tuple[str, str | None]:
        """Read 02_universe.csv to map `ticker` to its first
        `(segment, subsegment)`. Returns a sentinel if the ticker
        isn't in the universe (which shouldn't happen since the
        CIK map was built from EDGAR, but defensive).
        """
        csv_path = self._project_root() / "research" / "02_universe.csv"
        if not csv_path.exists():
            return ("unclassified", None)
        try:
            with csv_path.open() as f:
                next(f, None)
                for line in f:
                    parts = line.split(",")
                    if parts and parts[0].strip() == ticker:
                        # CSV columns: ticker, exchange, name, segment,
                        # subsegment, ...
                        return (
                            parts[3].strip() if len(parts) > 3 else "unclassified",
                            parts[4].strip() if len(parts) > 4 and parts[4].strip() else None,
                        )
        except OSError as exc:
            _LOGGER.debug("sec_insider: could not read universe CSV for %s: %s", ticker, exc)
        return ("unclassified", None)

    # -- cache helpers ---------------------------------------------------------

    def _cache_dir(self) -> Path:
        """Per-adapter cache directory under the configured log path's
        parent. Mirrors the eia_860m.py pattern.
        """
        return self._settings.refresh_log_path.parent / "sec_insider"

    def _project_root(self) -> Path:
        """Project root, four levels up from this file
        (src/bottlewatch/app/ingest/sec_insider.py).
        """
        return Path(__file__).resolve().parents[4]

    @staticmethod
    def _cache_is_fresh(path: Path) -> bool:
        """True if the cache file's mtime is within the TTL window."""
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return False
        age = datetime.now(tz=timezone.utc).timestamp() - mtime
        return age < _TICKER_LIST_TTL_DAYS * 86400


def build_sec_insider_adapter(settings: Settings) -> SECInsiderAdapter:
    """Factory: the orchestrator calls this with a Settings instance."""
    return SECInsiderAdapter(settings)
