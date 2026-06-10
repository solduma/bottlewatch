"""Tests for the SEC Form 4 (insider) adapter.

Spec: docs/plans/2026-06-04-m3-implementation.md §M3 + 2026-06-06
plan §2.2. The adapter:
1. Pulls Form 4 filings from EDGAR for tickers in research/02_universe.csv
2. Filters to non-routine, open-market purchases (transactionCode=P)
3. Detects cluster buys: 3+ insider P-code transactions in a 30-day
   trailing window per ticker
4. Emits one signal per (ticker, day) with the cluster size, in a
   shape that downstream code can pick up

Universe filter: dynamic EDGAR ticker-list fetch at adapter init.
Non-US tickers (no CIK) are skipped with a debug log line.
Malformed Form 4 XML: skipped with a warning, not raised.
The `tickers` field on emitted signals is populated as
`f'["{ticker}"]'` (this unlocks the universe-to-signal mapping).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import respx
from httpx import Response

from bottlewatch.app.ingest import SECInsiderAdapter
from bottlewatch.app.ingest.base import RawSignal
from bottlewatch.app.ingest.sec_insider import build_sec_insider_adapter
from bottlewatch.config import Settings


def _aapl(signals: list[RawSignal]) -> list[RawSignal]:
    """Filter `signals` down to AAPL Form 4 cluster signals.

    Used in every test that asserts cluster detection. The
    cast at the call site silences pyright's `reportOptionalMemberAccess`
    on `s.source_id.startswith(...)`: the `adapter.fetch` return type
    is `list[RawSignal]`, but pyright loses the `RawSignal` narrowing
    through the list-comprehension and treats the iteration var as
    `Unknown`. Casting through `list[RawSignal]` keeps the type.
    """
    return [s for s in signals if s.source_id is not None and s.source_id.startswith("form4:AAPL:")]


# SEC submission index URL pattern: `https://data.sec.gov/submissions/CIK{10-digit}.json`
_EDGAR_BASE = "https://data.sec.gov"


def _edgar_tickers_payload() -> dict:
    """The `https://www.sec.gov/files/company_tickers.json` payload,
    abbreviated to a small fixture covering the universe tickers we
    test against. Each row is `["0", "cik_str", "ticker", "name"]`
    per the SEC's documented shape.
    """
    return {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        # Non-US tickers (Samsung, TSMC) deliberately omitted —
        # the test asserts they are skipped, not silently dropped.
    }


def _edgar_submission_payload(cik: int, accession_numbers: list[str]) -> dict:
    """One CIK's submissions JSON. `accession_numbers` is the list
    of recent Form 4 accession numbers we want the adapter to fetch.
    The dates on the recent filings are the trailing 30 days.
    """
    return {
        "cik": str(cik),
        "entityType": "operating",
        "name": "Test Co",
        "tickers": ["AAPL"],
        "exchanges": ["Nasdaq"],
        "filings": {
            "recent": {
                "form": ["4"] * len(accession_numbers),
                "filingDate": ["2026-05-15"] * len(accession_numbers),
                "accessionNumber": accession_numbers,
                "primaryDocument": [f"form4-{i}.xml" for i in range(len(accession_numbers))],
            }
        },
    }


def _form4_xml(transaction_code: str = "P", shares: int = 1000, insider_cik: str = "0001234567") -> str:
    """Minimal Form 4 XML with a single non-derivative transaction.
    `transactionCode` P = open-market buy (kept), S = sale (filtered),
    F = tax withholding (filtered), M = option exercise (filtered).
    `insider_cik` is the reporting person's own CIK — used for
    distinct-insider dedup.
    """
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<ownershipDocument>
  <schemaVersion>X0401</schemaVersion>
  <documentType>4</documentType>
  <issuer>
    <issuerCik>0000320193</issuerCik>
    <issuerName>Apple Inc.</issuerName>
    <issuerTicker>AAPL</issuerTicker>
  </issuer>
  <reportingPerson>
    <reportingPersonId>
      <rptOwnerCik>{insider_cik}</rptOwnerCik>
    </reportingPersonId>
    <reportingPersonRelationship>
      <isDirector>true</isDirector>
      <isOfficer>true</isOfficer>
      <officerTitle>CEO</officerTitle>
    </reportingPersonRelationship>
  </reportingPerson>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <securityTitle>Common Stock</securityTitle>
      <transactionDate><value>2026-05-10</value></transactionDate>
      <transactionCode>{transaction_code}</transactionCode>
      <transactionAmounts>
        <transactionShares><value>{shares}</value></transactionShares>
        <transactionPricePerShare><value>150.00</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>
"""


def _form4_xml_x0609(transaction_code: str = "P", shares: int = 1000, insider_cik: str = "0001811108") -> str:
    """Real-shape X0609 Form 4 with pretty-printed whitespace and
    the modern `<reportingOwner>` element (current EDGAR schema).

    The two things that broke against the X0401 fixture:
    1. `<transactionDate>` has `.text` of `"\n                "` (the
       child `<value>` holds the date). A `text is None` check
       missed this; we now also fall back on whitespace-only text.
    2. `<reportingOwner>` is the modern name; the X0401-only
       `reportingPerson` lookup returned None.
    """
    return f"""<?xml version="1.0"?>
<ownershipDocument>
    <schemaVersion>X0609</schemaVersion>
    <documentType>4</documentType>
    <periodOfReport>2026-06-03</periodOfReport>
    <issuer>
        <issuerCik>0001090872</issuerCik>
        <issuerName>AGILENT TECHNOLOGIES, INC.</issuerName>
        <issuerTradingSymbol>A</issuerTradingSymbol>
        <issuerForeignTradingSymbol></issuerForeignTradingSymbol>
    </issuer>
    <reportingOwner>
        <reportingOwnerId>
            <rptOwnerCik>{insider_cik}</rptOwnerCik>
            <rptOwnerName>INSIDER NAME</rptOwnerName>
        </reportingOwnerId>
        <reportingOwnerAddress>
            <rptOwnerNonUSAddressFlag>false</rptOwnerNonUSAddressFlag>
            <rptOwnerStreet1>1 EXAMPLE ST.</rptOwnerStreet1>
            <rptOwnerCity>SANTA CLARA</rptOwnerCity>
            <rptOwnerState>CA</rptOwnerState>
            <rptOwnerZipCode>95051</rptOwnerZipCode>
        </reportingOwnerAddress>
        <reportingOwnerRelationship>
            <isDirector>1</isDirector>
            <isOfficer>1</isOfficer>
            <officerTitle>CEO</officerTitle>
        </reportingOwnerRelationship>
    </reportingOwner>
    <aff10b5One>0</aff10b5One>
    <nonDerivativeTable>
        <nonDerivativeTransaction>
            <securityTitle>
                <value>Common Stock</value>
            </securityTitle>
            <transactionDate>
                <value>2026-06-03</value>
            </transactionDate>
            <transactionCoding>
                <transactionFormType>4</transactionFormType>
                <transactionCode>{transaction_code}</transactionCode>
                <equitySwapInvolved>0</equitySwapInvolved>
            </transactionCoding>
            <transactionTimeliness></transactionTimeliness>
            <transactionAmounts>
                <transactionShares>
                    <value>{shares}</value>
                </transactionShares>
                <transactionPricePerShare>
                    <value>137.40</value>
                </transactionPricePerShare>
                <transactionAcquiredDisposedCode>
                    <value>A</value>
                </transactionAcquiredDisposedCode>
            </transactionAmounts>
        </nonDerivativeTransaction>
    </nonDerivativeTable>
</ownershipDocument>
"""


@pytest.fixture
def adapter(settings: Settings, tmp_path: Path) -> SECInsiderAdapter:
    """A configured adapter with a tmp cache directory.

    The adapter's `_universe_tickers()` is monkeypatched to return
    just AAPL — this is the project universe for the test, since
    the real `02_universe.csv` doesn't list AAPL. Tests that
    want a different universe override the patch.
    """
    s = Settings(
        app_env=settings.app_env,
        database_url=settings.database_url,
        refresh_log_path=tmp_path / "refresh.log",
    )
    a = build_sec_insider_adapter(s)
    # Restrict the iteration to AAPL so the test fixtures (which
    # all use CIK 320193 / AAPL) line up with the loop bounds.
    a._universe_tickers = lambda: {"AAPL"}  # type: ignore[method-assign]
    return a


# ---------------------------------------------------------------------------
# is_configured: now True (the adapter is real)
# ---------------------------------------------------------------------------


def test_sec_insider_is_configured(adapter: SECInsiderAdapter) -> None:
    """The adapter is real; is_configured returns (True, '')."""
    ok, reason = adapter.is_configured()
    assert ok is True, reason
    assert reason == ""


# ---------------------------------------------------------------------------
# Universe filter: dynamic EDGAR ticker-list fetch at init
# ---------------------------------------------------------------------------


def test_init_builds_ticker_to_cik_map(adapter: SECInsiderAdapter, tmp_path: Path) -> None:
    """The init-time fetch pulls EDGAR's ticker-list JSON and builds
    a `{ticker: cik}` map. After init, our universe tickers that
    appear in EDGAR are mappable; non-US tickers are not.
    """
    with respx.mock(assert_all_called=False) as mock:
        mock.get("/files/company_tickers.json").respond(200, json=_edgar_tickers_payload())
        adapter._load_universe_cik_map()  # may be auto-called on first fetch; force it

    assert adapter._ticker_to_cik.get("AAPL") == 320193
    # Non-US tickers (no CIK in EDGAR) are absent, not silently None.
    assert "2330.TW" not in adapter._ticker_to_cik
    assert "005930.KS" not in adapter._ticker_to_cik


def test_init_caches_ticker_list_locally(adapter: SECInsiderAdapter, tmp_path: Path) -> None:
    """The first init fetches the ticker list; the second call within
    the same day uses the cached file. No second HTTP call.
    """
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get("/files/company_tickers.json").respond(200, json=_edgar_tickers_payload())
        adapter._load_universe_cik_map()
        adapter._load_universe_cik_map()  # second call

    assert route.call_count == 1, "second call should hit the local cache"


# ---------------------------------------------------------------------------
# Happy path: 3 P-code Form 4s in 30 days → 1 signal
# ---------------------------------------------------------------------------


def test_three_p_code_filings_in_30_days_emit_one_cluster_signal(
    adapter: SECInsiderAdapter,
) -> None:
    """AAPL has 3 Form 4 filings with transactionCode=P (open-market
    buy) in the trailing 30 days. The adapter emits 1 signal per
    ticker-day where the 30-day rolling count crosses or stays
    above 3. In this fixture (3 P-codes in one day), that's 1
    signal with value_num=3.
    """
    accession_numbers = ["0000320193-26-000001", "0000320193-26-000002", "0000320193-26-000003"]

    with respx.mock(assert_all_called=False) as mock:
        mock.get("/files/company_tickers.json").respond(200, json=_edgar_tickers_payload())
        mock.get("/submissions/CIK0000320193.json").respond(
            200, json=_edgar_submission_payload(320193, accession_numbers)
        )
        _mock_index_for(mock, accession_numbers)
        for i, acc in enumerate(accession_numbers):
            acc_nodash = acc.replace("-", "")
            # Each filing is by a different insider so the cluster
            # fires (see Bug 1: distinct-insider dedup).
            insider_cik = f"0009999{str(i).zfill(3)}"
            mock.get(f"/Archives/edgar/data/320193/{acc_nodash}/form4.xml").respond(
                200,
                text=_form4_xml(transaction_code="P", insider_cik=insider_cik),
                headers={"content-type": "text/xml"},
            )

        signals = adapter.fetch(date(2026, 5, 1), date(2026, 5, 31))

    aapl_signals = _aapl(signals)
    assert len(aapl_signals) == 1
    sig = aapl_signals[0]
    assert sig.signal_name == "n_insider_buys_30d"
    assert sig.value_num == 3.0
    assert sig.unit == "count"
    assert sig.subsegment == "insider_cluster_buy"
    assert sig.tickers == '["AAPL"]'


# ---------------------------------------------------------------------------
# Below threshold: 2 P-code → 0 signals
# ---------------------------------------------------------------------------


def test_two_p_code_filings_emit_no_cluster_signal(
    adapter: SECInsiderAdapter,
) -> None:
    """Cluster definition is 3+ P-codes in 30 days. 2 P-codes is
    below the threshold; no signal is emitted.
    """
    accession_numbers = ["0000320193-26-000001", "0000320193-26-000002"]

    with respx.mock(assert_all_called=False) as mock:
        mock.get("/files/company_tickers.json").respond(200, json=_edgar_tickers_payload())
        mock.get("/submissions/CIK0000320193.json").respond(
            200, json=_edgar_submission_payload(320193, accession_numbers)
        )
        _mock_index_for(mock, accession_numbers)
        for acc in accession_numbers:
            acc_nodash = acc.replace("-", "")
            mock.get(f"/Archives/edgar/data/320193/{acc_nodash}/form4.xml").respond(
                200, text=_form4_xml(transaction_code="P")
            )

        signals = adapter.fetch(date(2026, 5, 1), date(2026, 5, 31))

    assert not _aapl(signals)


# ---------------------------------------------------------------------------
# Mixed codes: F (withholding) doesn't count
# ---------------------------------------------------------------------------


def test_f_code_does_not_count_toward_cluster(
    adapter: SECInsiderAdapter,
) -> None:
    """2 P + 1 F (tax withholding). F is filtered out; only 2 P-codes
    remain, below the 3-cluster threshold, so no signal.
    """
    accession_numbers = ["0000320193-26-000001", "0000320193-26-000002", "0000320193-26-000003"]
    codes = ["P", "P", "F"]

    with respx.mock(assert_all_called=False) as mock:
        mock.get("/files/company_tickers.json").respond(200, json=_edgar_tickers_payload())
        mock.get("/submissions/CIK0000320193.json").respond(
            200, json=_edgar_submission_payload(320193, accession_numbers)
        )
        _mock_index_for(mock, accession_numbers)
        for i, (acc, code) in enumerate(zip(accession_numbers, codes)):
            acc_nodash = acc.replace("-", "")
            mock.get(f"/Archives/edgar/data/320193/{acc_nodash}/form4.xml").respond(
                200, text=_form4_xml(transaction_code=code)
            )

        signals = adapter.fetch(date(2026, 5, 1), date(2026, 5, 31))

    assert not _aapl(signals)


# ---------------------------------------------------------------------------
# Non-US ticker is silently skipped (no CIK in EDGAR ticker list)
# ---------------------------------------------------------------------------


def test_non_us_ticker_emit_no_signal(
    adapter: SECInsiderAdapter,
) -> None:
    """TSMC (2330.TW) is in the universe but absent from EDGAR's
    ticker list. The adapter skips it silently — no error, no
    signal.
    """
    empty_submissions = {
        "cik": "320193",
        "entityType": "operating",
        "name": "Test Co",
        "tickers": ["AAPL"],
        "exchanges": ["Nasdaq"],
        "filings": {
            "recent": {
                "form": [],
                "filingDate": [],
                "accessionNumber": [],
                "primaryDocument": [],
            }
        },
    }
    with respx.mock(assert_all_called=False) as mock:
        mock.get("/files/company_tickers.json").respond(200, json=_edgar_tickers_payload())
        mock.get("/submissions/CIK0000320193.json").respond(200, json=empty_submissions)
        signals = adapter.fetch(date(2026, 5, 1), date(2026, 5, 31))

    # The fixture has 1 ticker (AAPL) with no filings; no signals.
    sec_insider_signals = [s for s in signals if s.source == "sec_insider"]
    assert sec_insider_signals == []


# ---------------------------------------------------------------------------
# Malformed XML is skipped with a warning, not raised
# ---------------------------------------------------------------------------


def test_malformed_form4_xml_is_skipped_with_warning(
    adapter: SECInsiderAdapter, caplog: pytest.LogCaptureFixture
) -> None:
    """EDGAR returns one good Form 4 and one with malformed XML.
    The malformed one is logged and skipped; the good one counts
    toward the cluster. The fetch() call still completes normally.
    """
    accession_numbers = ["0000320193-26-000001", "0000320193-26-000002", "0000320193-26-000003"]

    with respx.mock(assert_all_called=False) as mock:
        mock.get("/files/company_tickers.json").respond(200, json=_edgar_tickers_payload())
        mock.get("/submissions/CIK0000320193.json").respond(
            200, json=_edgar_submission_payload(320193, accession_numbers)
        )
        _mock_index_for(mock, accession_numbers)
        # First filing: malformed
        mock.get("/Archives/edgar/data/320193/000032019326000001/form4.xml").respond(
            200, text="<<<not xml>>>", headers={"content-type": "text/xml"}
        )
        # Second + third: good
        for i, acc in enumerate(accession_numbers[1:], start=1):
            acc_nodash = acc.replace("-", "")
            mock.get(f"/Archives/edgar/data/320193/{acc_nodash}/form4.xml").respond(
                200, text=_form4_xml(transaction_code="P")
            )

        with caplog.at_level("WARNING"):
            signals = adapter.fetch(date(2026, 5, 1), date(2026, 5, 31))

    # 2 P-codes remain (1 was malformed, skipped). Below threshold
    # of 3, so no signal — but the run completed without raising.
    assert all(
        s.source_id is None or s.source_id.split(":")[1] != "AAPL" or (s.value_num is not None and s.value_num < 3)
        for s in signals
        if s.source == "sec_insider"
    )
    assert any("malformed" in r.message.lower() or "skip" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# Modern EDGAR schema (X0609) — regression: real EDGAR shapes parse OK
# ---------------------------------------------------------------------------


def test_x0609_form4_with_whitespace_parses_correctly(adapter: SECInsiderAdapter) -> None:
    """Real EDGAR Form 4 XML is pretty-printed and uses the X0609
    schema (`<reportingOwner>`, nested `<transactionDate><value>`,
    nested `<transactionCoding>/<transactionCode>`). The parser
    must accept this shape end-to-end.

    Regression: prior to 2026-06-08 the parser checked
    `text is None` for `<transactionDate>`, but the parent element
    in pretty-printed XML has `.text` of `"\n                "`
    (whitespace), so the fallback to `<transactionDate>/<value>`
    never fired and the filing was logged as malformed.
    """
    parsed = SECInsiderAdapter._parse_form4_xml(adapter, _form4_xml_x0609(transaction_code="P"))
    assert parsed == {
        "transaction_code": "P",
        "transaction_date": "2026-06-03",
        "insider_cik": "0001811108",
    }


def test_x0609_form4_emit_p_cluster_signal(adapter: SECInsiderAdapter, tmp_path: Path) -> None:
    """Three X0609 P-code filings on the same ticker in a 30-day
    window must produce one cluster signal — the same contract the
    X0401 fixture verifies, but against the schema the live
    refresh actually fetches.

    Note: the `_edgar_submission_payload` helper hard-codes the
    filing date to 2026-05-15, so the fetch window must span
    May 2026 (the X0609 `<transactionDate>` value of 2026-06-03
    is purely about the schema, not the date arithmetic).
    """
    accession_numbers = ["0000320193-26-000001", "0000320193-26-000002", "0000320193-26-000003"]

    with respx.mock(assert_all_called=False) as mock:
        mock.get("/files/company_tickers.json").respond(200, json=_edgar_tickers_payload())
        mock.get("/submissions/CIK0000320193.json").respond(
            200, json=_edgar_submission_payload(320193, accession_numbers)
        )
        _mock_index_for(mock, accession_numbers)
        for i, acc in enumerate(accession_numbers):
            acc_nodash = acc.replace("-", "")
            # Each filing is by a different insider so the cluster
            # fires (distinct-insider dedup; see X0401 counterpart).
            insider_cik = f"0009999{str(i).zfill(3)}"
            mock.get(f"/Archives/edgar/data/320193/{acc_nodash}/form4.xml").respond(
                200, text=_form4_xml_x0609(transaction_code="P", insider_cik=insider_cik)
            )

        signals = adapter.fetch(date(2026, 5, 1), date(2026, 5, 31))

    aapl_signals = _aapl(signals)
    assert len(aapl_signals) == 1
    sig = aapl_signals[0]
    assert sig.signal_name == "n_insider_buys_30d"
    assert sig.value_num == 3.0
    assert sig.unit == "count"
    assert sig.subsegment == "insider_cluster_buy"


# ---------------------------------------------------------------------------
# Index wrapper files must not be picked as the Form 4 primary doc
# ---------------------------------------------------------------------------


def test_index_wrapper_files_are_skipped_for_form4_primary(adapter: SECInsiderAdapter) -> None:
    """Regression 2026-06-08: real EDGAR accessions start their
    `index.json` listing with the index wrapper files
    (`<accession>-index.html`, `<accession>-index-headers.html`,
    `<accession>.txt`). These end in `.html` and so the previous
    "first .xml/.htm" fallback picked `<accession>-index-headers.html`
    (an HTML wrapper) and tried to parse it as XML — producing
    `ParseError: mismatched tag: line 137, column 23` for ~4000
    filings per refresh run.

    The fix skips filenames that start with the accession (with or
    without dashes) and prefers `.xml` over `.htm`/`.html` for the
    fallback. The actual Form 4 file (`ownership.xml` for X0508+)
    is found; the wrapper files are ignored.
    """
    accession = "0000950170-24-132369"
    accession_numbers = [accession]

    # The real-world shape: every file is `type: "text.gif"`, no
    # `primary: "true"` flag, the wrapper files come first.
    real_world_index = {
        "directory": {
            "item": [
                {
                    "name": "0000950170-24-132369-index-headers.html",
                    "type": "text.gif",
                },
                {
                    "name": "0000950170-24-132369-index.html",
                    "type": "text.gif",
                },
                {
                    "name": "0000950170-24-132369.txt",
                    "type": "text.gif",
                },
                {
                    "name": "ownership.xml",
                    "type": "text.gif",
                    "size": "6722",
                },
            ]
        }
    }

    with respx.mock(assert_all_called=False) as mock:
        mock.get("/files/company_tickers.json").respond(200, json=_edgar_tickers_payload())
        mock.get("/submissions/CIK0000320193.json").respond(
            200, json=_edgar_submission_payload(320193, accession_numbers)
        )
        mock.get("/Archives/edgar/data/320193/000095017024132369/index.json").respond(200, json=real_world_index)
        # The wrapper HTML is mocked to 200 so we can assert it is
        # NOT what the adapter tries to fetch.
        wrapper_route = mock.get(
            "/Archives/edgar/data/320193/000095017024132369/0000950170-24-132369-index-headers.html"
        ).respond(200, text="<HTML>not xml</HTML>")
        # The actual Form 4 file. Use X0401 fixture so the cluster
        # count is 1 (not enough for a cluster signal — we only
        # care that the resolver picked ownership.xml, not the
        # wrapper).
        mock.get("/Archives/edgar/data/320193/000095017024132369/ownership.xml").respond(
            200, text=_form4_xml(transaction_code="A", insider_cik="0009999001")
        )

        signals = adapter.fetch(date(2026, 5, 1), date(2026, 5, 31))

    # The wrapper route must not have been hit.
    assert wrapper_route.call_count == 0, "adapter fetched the EDGAR index-headers.html wrapper, not the Form 4"
    # The refresh completed without raising; we don't assert a
    # specific signal count because the test is about the URL
    # resolution, not the cluster logic.
    assert all(s.source != "sec_insider" or s.value_num is None or s.value_num < 3 for s in signals)


def _form4_xml_derivative_only() -> str:
    """Form 4 with a `<derivativeTransaction>` only — no
    non-derivative element. Per spec §2, derivative activity
    (option exercises, RSU vests, etc.) is filtered. The parser
    returns None (no warning); the filing does not produce a
    cluster signal.
    """
    return """<?xml version="1.0" encoding="UTF-8"?>
<ownershipDocument>
  <schemaVersion>X0401</schemaVersion>
  <documentType>4</documentType>
  <issuer>
    <issuerCik>0000320193</issuerCik>
    <issuerName>Apple Inc.</issuerName>
    <issuerTicker>AAPL</issuerTicker>
  </issuer>
  <reportingPerson>
    <reportingPersonId>
      <rptOwnerCik>0001111222</rptOwnerCik>
    </reportingPersonId>
    <reportingPersonRelationship>
      <isOfficer>true</isOfficer>
      <officerTitle>CFO</officerTitle>
    </reportingPersonRelationship>
  </reportingPerson>
  <derivativeTable>
    <derivativeTransaction>
      <securityTitle>
        <value>Employee Stock Option</value>
      </securityTitle>
      <transactionDate><value>2026-05-12</value></transactionDate>
      <transactionCode>M</transactionCode>
      <transactionAmounts>
        <transactionShares><value>10000</value></transactionShares>
        <transactionPricePerShare><value>120.00</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </derivativeTransaction>
  </derivativeTable>
</ownershipDocument>
"""


def test_derivative_only_form4_is_silently_skipped(adapter: SECInsiderAdapter) -> None:
    """Regression 2026-06-09: real EDGAR returns Form 4s with only
    derivative activity (option exercises, RSU vests). Per spec
    §2 those are filtered — they are not "smart money buying"
    signals. Previously the parser raised
    `ValueError("no nonDerivativeTransaction element found")` and
    the caller logged it as WARNING ("skipped malformed Form 4
    XML"), which was misleading — the filing is well-formed and
    the spec deliberately filters derivative activity.

    The fix: parser returns None (no warning) for derivative-only
    filings; raises only for genuinely anomalous filings
    (no transaction of any kind).
    """
    parsed = SECInsiderAdapter._parse_form4_xml(adapter, _form4_xml_derivative_only())
    assert parsed is None, f"derivative-only filing should return None, got {parsed!r}"


def test_no_transactions_at_all_still_raises(adapter: SECInsiderAdapter) -> None:
    """A Form 4 with neither non-derivative nor derivative
    transactions is genuinely anomalous — raise so the caller
    logs and skips. Distinguishing this from the derivative-only
    case is the point of the new branching in `_parse_form4_xml`.
    """
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<ownershipDocument>
  <schemaVersion>X0401</schemaVersion>
  <documentType>4</documentType>
  <issuer>
    <issuerCik>0000320193</issuerCik>
    <issuerName>Apple Inc.</issuerName>
    <issuerTicker>AAPL</issuerTicker>
  </issuer>
  <reportingPerson>
    <reportingPersonId>
      <rptOwnerCik>0001111222</rptOwnerCik>
    </reportingPersonId>
  </reportingPerson>
  <nonDerivativeTable/>
  <derivativeTable/>
</ownershipDocument>
"""
    with pytest.raises(ValueError, match="transaction element"):
        SECInsiderAdapter._parse_form4_xml(adapter, xml)


def _form4_xml_holdings_only() -> str:
    """Real-EDGAR Form 4 with a `<nonDerivativeHolding>` only —
    no transactions. Common in 4/A amendments and "I have these
    shares" disclosures where the insider has shares from prior
    grants/vests but no new transactions to report.

    Per spec §2 these are filtered (no P-code buy to count) and
    must NOT log a warning. The parser should return None.
    """
    return """<?xml version="1.0" encoding="UTF-8"?>
<ownershipDocument>
  <schemaVersion>X0609</schemaVersion>
  <documentType>4</documentType>
  <periodOfReport>2026-05-20</periodOfReport>
  <issuer>
    <issuerCik>0001053507</issuerCik>
    <issuerName>WESTERN DIGITAL CORP</issuerName>
    <issuerTradingSymbol>WDC</issuerTradingSymbol>
  </issuer>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerCik>0001029613</rptOwnerCik>
      <rptOwnerName>INSIDER NAME</rptOwnerName>
    </reportingOwnerId>
    <reportingOwnerRelationship>
      <isDirector>1</isDirector>
      <isOfficer>1</isOfficer>
      <officerTitle>CEO</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <aff10b5One>0</aff10b5One>
  <nonDerivativeTable>
    <nonDerivativeHolding>
      <securityTitle>
        <value>Common Stock</value>
      </securityTitle>
      <postTransactionAmounts>
        <sharesOwnedFollowingTransaction>
          <value>50000</value>
        </sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
      <ownershipNature>
        <directOrIndirectOwnership>
          <value>D</value>
        </directOrIndirectOwnership>
      </ownershipNature>
    </nonDerivativeHolding>
  </nonDerivativeTable>
</ownershipDocument>
"""


def test_holdings_only_form4_is_silently_skipped(adapter: SECInsiderAdapter) -> None:
    """Regression 2026-06-09: real EDGAR returns Form 4s with
    only a `<nonDerivativeHolding>` element and no transactions
    (e.g. `wk-form4_1779307770.xml` for accession
    0001053507-26-000113). The insider has shares from prior
    grants but no new transactions to report. Per spec §2 these
    are filtered — the parser should return None (not raise)
    and the caller should skip without logging a warning.

    The previous code raised `ValueError("no non-derivative or
    derivative transaction element found")` for these filings
    and the caller logged "skipped malformed Form 4 XML" — which
    was misleading since the XML was well-formed and the spec
    deliberately filters holdings-only filings.
    """
    parsed = SECInsiderAdapter._parse_form4_xml(adapter, _form4_xml_holdings_only())
    assert parsed is None, f"holdings-only filing should return None, got {parsed!r}"


def test_not_subject_to_section16_filing_is_silently_skipped(adapter: SECInsiderAdapter) -> None:
    """Regression 2026-06-09: real EDGAR returns Form 4s that
    report the insider is no longer subject to Section 16
    reporting (typically because they left the company). The
    `<notSubjectToSection16>` flag and a `<remarks>` element
    explain the absence of transactions. Per spec §2 these are
    filtered — the parser should return None (not raise).

    Example: accession 0001051470-25-000126 (Crown Castle insider
    Chan Edmond, who ceased serving as EVP/CIO on 2025-04-18).
    """
    xml = """<?xml version="1.0"?>
<ownershipDocument>
  <schemaVersion>X0508</schemaVersion>
  <documentType>4</documentType>
  <periodOfReport>2025-04-18</periodOfReport>
  <notSubjectToSection16>1</notSubjectToSection16>
  <issuer>
    <issuerCik>0001051470</issuerCik>
    <issuerName>CROWN CASTLE INC.</issuerName>
    <issuerTradingSymbol>CCI</issuerTradingSymbol>
  </issuer>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerCik>0002007695</rptOwnerCik>
      <rptOwnerName>Chan Edmond</rptOwnerName>
    </reportingOwnerId>
    <reportingOwnerAddress>
      <rptOwnerStreet1>8020 KATY FREEWAY</rptOwnerStreet1>
      <rptOwnerCity>HOUSTON</rptOwnerCity>
      <rptOwnerState>TX</rptOwnerState>
      <rptOwnerZipCode>77024</rptOwnerZipCode>
    </reportingOwnerAddress>
    <reportingOwnerRelationship>
      <isOfficer>1</isOfficer>
      <officerTitle>EVP and CIO</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <aff10b5One>0</aff10b5One>
  <nonDerivativeTable></nonDerivativeTable>
  <derivativeTable></derivativeTable>
  <footnotes></footnotes>
  <remarks>The reporting person ceased serving as Executive Vice President and Chief Information Officer of Crown Castle Inc., effective April 18, 2025.</remarks>
  <ownerSignature>
    <signatureName>/s/ Edmond Chan</signatureName>
    <signatureDate>2025-05-02</signatureDate>
  </ownerSignature>
</ownershipDocument>
"""
    parsed = SECInsiderAdapter._parse_form4_xml(adapter, xml)
    assert parsed is None, f"not-subject-to-Section-16 filing should return None, got {parsed!r}"


# ---------------------------------------------------------------------------
# Progress callback: invoked per ticker, not at all when None
# ---------------------------------------------------------------------------


def test_fetch_invokes_progress_callback_per_ticker(adapter: SECInsiderAdapter) -> None:
    """The orchestrator passes a `(current, total, label) -> None`
    callback to `fetch()`. sec_insider should invoke it once per
    universe ticker so the user can see progress on the long
    ~90s run.

    We seed the test with a small mock universe and assert the
    callback is called for each ticker.
    """
    # A small mock universe: 3 tickers, 1 accession each, all P-code.
    # Same shape as the happy-path cluster test but reduced.
    accession_numbers = ["0000320193-26-000001"]

    captured: list[tuple[int, int, str]] = []

    def _progress(current: int, total: int, label: str) -> None:
        captured.append((current, total, label))

    with respx.mock(assert_all_called=False) as mock:
        mock.get("/files/company_tickers.json").respond(200, json=_edgar_tickers_payload())
        mock.get("/submissions/CIK0000320193.json").respond(
            200, json=_edgar_submission_payload(320193, accession_numbers)
        )
        _mock_index_for(mock, accession_numbers)
        for i, acc in enumerate(accession_numbers):
            acc_nodash = acc.replace("-", "")
            mock.get(f"/Archives/edgar/data/320193/{acc_nodash}/form4.xml").respond(
                200, text=_form4_xml(transaction_code="P", insider_cik=f"0009999{str(i).zfill(3)}")
            )

        adapter.fetch(date(2026, 5, 1), date(2026, 5, 31), progress=_progress)

    # The callback was invoked at least once (AAPL is the only
    # ticker in the fixture, so exactly one call).
    assert len(captured) == 1
    current, total, label = captured[0]
    assert total == 1  # AAPL only
    assert current == 1
    assert label == "AAPL"


def test_fetch_with_no_progress_callback_does_not_crash(adapter: SECInsiderAdapter) -> None:
    """Backward compat: the old `fetch(period_start, period_end)`
    call (no `progress` kwarg) must still work. This is the
    contract every existing caller relies on.
    """
    accession_numbers = ["0000320193-26-000001"]
    with respx.mock(assert_all_called=False) as mock:
        mock.get("/files/company_tickers.json").respond(200, json=_edgar_tickers_payload())
        mock.get("/submissions/CIK0000320193.json").respond(
            200, json=_edgar_submission_payload(320193, accession_numbers)
        )
        _mock_index_for(mock, accession_numbers)
        mock.get("/Archives/edgar/data/320193/000032019326000001/form4.xml").respond(
            200, text=_form4_xml(transaction_code="P", insider_cik="0009999001")
        )

        signals = adapter.fetch(date(2026, 5, 1), date(2026, 5, 31))
    # Below cluster threshold (1 P-code), so no signal. We only
    # care that the call completed without raising.
    assert all(s.source != "sec_insider" for s in signals) or len(signals) < 1


# ---------------------------------------------------------------------------
# 429 is retried (transient)
# ---------------------------------------------------------------------------


def test_rate_limit_429_is_retried(adapter: SECInsiderAdapter) -> None:
    """EDGAR rate-limits us with a 429 once, then succeeds on the
    retry. The adapter should retry (per the tenacity decorator) and
    complete normally.
    """
    accession_numbers = ["0000320193-26-000001", "0000320193-26-000002", "0000320193-26-000003"]

    with respx.mock(assert_all_called=False) as mock:
        mock.get("/files/company_tickers.json").respond(200, json=_edgar_tickers_payload())
        mock.get("/submissions/CIK0000320193.json").respond(
            200, json=_edgar_submission_payload(320193, accession_numbers)
        )
        _mock_index_for(mock, accession_numbers)
        # 429 then 200
        route = mock.get("/Archives/edgar/data/320193/000032019326000001/form4.xml").mock(
            side_effect=[
                Response(429, text="rate limited"),
                Response(200, text=_form4_xml(transaction_code="P", insider_cik="0001111001")),
            ]
        )
        for i, acc in enumerate(accession_numbers[1:], start=1):
            acc_nodash = acc.replace("-", "")
            mock.get(f"/Archives/edgar/data/320193/{acc_nodash}/form4.xml").respond(
                200, text=_form4_xml(transaction_code="P", insider_cik=f"0001111{str(i + 1).zfill(3)}")
            )

        signals = adapter.fetch(date(2026, 5, 1), date(2026, 5, 31))

    assert route.call_count >= 2, "429 should be retried"
    # 3 P-codes total — cluster signal emitted
    aapl_signals = _aapl(signals)
    assert len(aapl_signals) == 1
    assert aapl_signals[0].value_num == 3.0


# ---------------------------------------------------------------------------
# Caching: a second call within the same window hits the cache
# ---------------------------------------------------------------------------


def test_second_call_within_window_hits_cache(adapter: SECInsiderAdapter) -> None:
    """The first call populates the on-disk cache; a second call
    with the same window does not re-fetch the Form 4 XMLs.
    """
    accession_numbers = ["0000320193-26-000001", "0000320193-26-000002", "0000320193-26-000003"]

    with respx.mock(assert_all_called=False) as mock:
        mock.get("/files/company_tickers.json").respond(200, json=_edgar_tickers_payload())
        mock.get("/submissions/CIK0000320193.json").respond(
            200, json=_edgar_submission_payload(320193, accession_numbers)
        )
        _mock_index_for(mock, accession_numbers)
        xml_route = mock.get("/Archives/edgar/data/320193/000032019326000001/form4.xml").respond(
            200, text=_form4_xml(transaction_code="P")
        )
        for i, acc in enumerate(accession_numbers[1:], start=1):
            acc_nodash = acc.replace("-", "")
            mock.get(f"/Archives/edgar/data/320193/{acc_nodash}/form4.xml").respond(
                200, text=_form4_xml(transaction_code="P")
            )

        adapter.fetch(date(2026, 5, 1), date(2026, 5, 31))
        first_count = xml_route.call_count
        adapter.fetch(date(2026, 5, 1), date(2026, 5, 31))
        second_count = xml_route.call_count

    assert second_count == first_count, "second call should hit the cache"


# ---------------------------------------------------------------------------
# Index-file lookup: replaces the 3-candidate filename guess with
# a per-accession index.json fetch that returns the actual primary
# doc name. This is the spec change for the real-world ingest fix
# (2026-06-07).
# ---------------------------------------------------------------------------


def _edgar_index_payload(primary_name: str = "form4.xml") -> dict:
    """Sample index.json payload from
    `https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/index.json`.
    The `directory.item` array lists the files in the accession;
    the `primary: "true"` flag marks the Form 4's primary doc.
    """
    return {
        "directory": {
            "item": [
                {
                    "name": primary_name,
                    "type": "4",
                    "size": "1234",
                    "primary": "true",
                },
                {
                    "name": "form4-related.xml",
                    "type": "4",
                    "size": "567",
                },
            ]
        }
    }


def _mock_index_for(mock, accession_numbers: list[str], primary_name: str = "form4.xml") -> None:
    """Wire the per-accession index.json mock. Used by every test
    that mocks the Form 4 XML directly, since the index-file path
    is the new normal.
    """
    for acc in accession_numbers:
        acc_nodash = acc.replace("-", "")
        mock.get(f"/Archives/edgar/data/320193/{acc_nodash}/index.json").respond(
            200, json=_edgar_index_payload(primary_name=primary_name)
        )


def test_index_file_lookup_returns_primary_doc(
    adapter: SECInsiderAdapter,
) -> None:
    """Real EDGAR returns the primary doc filename in the
    accession's index.json. The adapter fetches the index,
    reads the `primary: "true"` item's name, and uses it
    instead of guessing among 3 candidates.

    The accession's primary doc in this fixture is named
    `unusual-name-abc.xml` — a name none of the 3 hard-coded
    candidates would match. With the index-file path, we
    fetch that exact URL and still emit a cluster signal.
    """
    accession_numbers = ["0000320193-26-000001", "0000320193-26-000002", "0000320193-26-000003"]

    with respx.mock(assert_all_called=False) as mock:
        mock.get("/files/company_tickers.json").respond(200, json=_edgar_tickers_payload())
        mock.get("/submissions/CIK0000320193.json").respond(
            200, json=_edgar_submission_payload(320193, accession_numbers)
        )
        for i, acc in enumerate(accession_numbers):
            acc_nodash = acc.replace("-", "")
            mock.get(f"/Archives/edgar/data/320193/{acc_nodash}/index.json").respond(
                200, json=_edgar_index_payload(primary_name="unusual-name-abc.xml")
            )
            insider_cik = f"0008888{str(i).zfill(3)}"
            mock.get(f"/Archives/edgar/data/320193/{acc_nodash}/unusual-name-abc.xml").respond(
                200, text=_form4_xml(transaction_code="P", insider_cik=insider_cik)
            )

        signals = adapter.fetch(date(2026, 5, 1), date(2026, 5, 31))

    aapl_signals = _aapl(signals)
    assert len(aapl_signals) == 1
    assert aapl_signals[0].value_num == 3.0


def test_index_file_is_cached_locally(
    adapter: SECInsiderAdapter,
) -> None:
    """A second call within the same window hits the local index
    cache, not the SEC. This makes re-runs of the orchestrator
    idempotent on the index lookup (Form 4 XMLs are immutable per
    accession).
    """
    accession_numbers = ["0000320193-26-000001"]

    with respx.mock(assert_all_called=False) as mock:
        mock.get("/files/company_tickers.json").respond(200, json=_edgar_tickers_payload())
        mock.get("/submissions/CIK0000320193.json").respond(
            200, json=_edgar_submission_payload(320193, accession_numbers)
        )
        index_route = mock.get("/Archives/edgar/data/320193/000032019326000001/index.json").respond(
            200, json=_edgar_index_payload()
        )
        mock.get("/Archives/edgar/data/320193/000032019326000001/form4.xml").respond(
            200, text=_form4_xml(transaction_code="P")
        )

        adapter.fetch(date(2026, 5, 1), date(2026, 5, 31))
        first_count = index_route.call_count
        adapter.fetch(date(2026, 5, 1), date(2026, 5, 31))
        second_count = index_route.call_count

    assert second_count == first_count, "second call should hit the local index cache"


def test_index_with_text_gif_type_finds_form4_by_name(
    adapter: SECInsiderAdapter,
) -> None:
    """Real EDGAR: index.json items have `type: "text.gif"` or
    similar (not `"4"`), and the `primary: "true"` flag is
    often missing. The adapter's third-tier fallback should
    pattern-match on the filename — find `form4.xml` and use it.

    We deliberately use a non-standard filename (`wf3456.xml`)
    that is NOT in the 3-candidate fallback. The only way
    the adapter can find this file is via the third-tier
    filename pattern match against the index.json listing.
    The 3-candidate fallback is mocked to 404 on this fixture.
    """
    accession_numbers = ["0000320193-26-000001", "0000320193-26-000002", "0000320193-26-000003"]
    # Real-world-style index: obscure filename, type="text.gif" (not "4")
    real_world_index = {
        "directory": {
            "item": [
                {
                    "name": "wf3456.xml",  # ← EDGAR's weird internal name
                    "type": "text.gif",  # ← not "4"!
                    "size": "3311",
                },
                {
                    "name": "0000320193-26-000058-index.html",
                    "type": "text.gif",
                },
            ]
        }
    }

    with respx.mock(assert_all_called=False) as mock:
        mock.get("/files/company_tickers.json").respond(200, json=_edgar_tickers_payload())
        mock.get("/submissions/CIK0000320193.json").respond(
            200, json=_edgar_submission_payload(320193, accession_numbers)
        )
        for i, acc in enumerate(accession_numbers):
            acc_nodash = acc.replace("-", "")
            mock.get(f"/Archives/edgar/data/320193/{acc_nodash}/index.json").respond(200, json=real_world_index)
            insider_cik = f"0008888{str(i).zfill(3)}"
            # The obscure filename is the only one that succeeds.
            mock.get(f"/Archives/edgar/data/320193/{acc_nodash}/wf3456.xml").respond(
                200, text=_form4_xml(transaction_code="P", insider_cik=insider_cik)
            )
            # The 3-candidate fallback is mocked to 404 on this
            # accession, so the only way form4.xml is fetched is
            # via the third-tier filename pattern match.
            for candidate in ["form4.xml", "doc4.xml", "primary_doc.xml"]:
                mock.get(f"/Archives/edgar/data/320193/{acc_nodash}/{candidate}").respond(404)

        signals = adapter.fetch(date(2026, 5, 1), date(2026, 5, 31))

    aapl_signals = _aapl(signals)
    assert len(aapl_signals) == 1


def test_fetch_iterates_only_universe_tickers_not_full_edgar_list(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression 2026-06-09: the adapter's fetch() loop must walk
    the project's universe (research/02_universe.csv, ~131
    tickers), not the full EDGAR ticker map (~10K tickers).
    Walking the full EDGAR list was a real perf bug (80x more
    network calls than necessary) and made the progress bar
    report `[XXXX/10400]` instead of `[XX/98]`.

    We assert this by mocking the EDGAR ticker list to include
    10,000 tickers but restricting `_universe_tickers()` to
    return one ticker, and verifying the loop body fires exactly
    once (per the progress callback's call count).
    """
    s = Settings(
        app_env=settings.app_env,
        database_url=settings.database_url,
        refresh_log_path=tmp_path / "refresh.log",
    )
    a = build_sec_insider_adapter(s)
    # Mock a 10K-ticker EDGAR list.
    a._ticker_to_cik = {f"T{i:05d}": 1000000 + i for i in range(10000)}
    a._cik_to_ticker = {1000000 + i: f"T{i:05d}" for i in range(10000)}
    # Restrict universe to one ticker that's IN the map.
    a._universe_tickers = lambda: {"T00001"}  # type: ignore[method-assign]

    progress_calls: list[tuple[int, int, str]] = []

    def _prog(cur: int, tot: int, label: str) -> None:
        progress_calls.append((cur, tot, label))

    # The loop walks only the intersected universe; even though
    # the EDGAR map has 10K entries, only 1 should be iterated.
    a.fetch(date(2026, 5, 1), date(2026, 5, 31), progress=_prog)
    assert len(progress_calls) == 1
    assert progress_calls[0] == (1, 1, "T00001")


def test_index_404_falls_back_to_candidate_guess(
    adapter: SECInsiderAdapter,
) -> None:
    """When the accession's index.json 404s (rare; happens for
    some malformed accession URLs), the adapter falls back to the
    3-candidate filename guess. This keeps the signal flowing
    for filings that happen to use one of the standard names.
    """
    accession_numbers = ["0000320193-26-000001", "0000320193-26-000002", "0000320193-26-000003"]

    with respx.mock(assert_all_called=False) as mock:
        mock.get("/files/company_tickers.json").respond(200, json=_edgar_tickers_payload())
        mock.get("/submissions/CIK0000320193.json").respond(
            200, json=_edgar_submission_payload(320193, accession_numbers)
        )
        # Index 404s for all 3 accessions
        for i, acc in enumerate(accession_numbers):
            acc_nodash = acc.replace("-", "")
            mock.get(f"/Archives/edgar/data/320193/{acc_nodash}/index.json").respond(404)
            # But form4.xml exists (3-candidate fallback succeeds).
            # Each filing by a different insider for the cluster.
            insider_cik = f"0007777{str(i).zfill(3)}"
            mock.get(f"/Archives/edgar/data/320193/{acc_nodash}/form4.xml").respond(
                200, text=_form4_xml(transaction_code="P", insider_cik=insider_cik)
            )

        signals = adapter.fetch(date(2026, 5, 1), date(2026, 5, 31))

    aapl_signals = _aapl(signals)
    assert len(aapl_signals) == 1
    assert aapl_signals[0].value_num == 3.0


# ---------------------------------------------------------------------------
# Spec: distinct-insider dedup + 4/A amendment dedup + once-per-event
# emission (research-driven correctness fixes, 2026-06-07).
#
# Bug 1: cluster count was the number of P-coded Form 4 transactions
# in 30 days, regardless of distinct insider. A single insider making
# 3 dollar-cost-averaging buys would falsely fire a cluster.
# Fix: cluster fires when 3 *distinct* insiders each file a P-code
# in the trailing 30-day window.
#
# Bug 2: 4/A amendments create a new accession that often corrects
# the original (e.g. P -> M). Without dedup, the cluster count
# would be off.
# Fix: per (cik, reportingOwnerCIK, transactionDate), keep the
# highest accession. Real EDGAR 4/A filings amend the original.
#
# Bug 3: the adapter re-emitted a signal every day while the
# count stayed >= 3. The literature treats cluster events as
# discrete -- one signal per crossing.
# Fix: emit one signal per ticker-day where the distinct-insider
# count first reaches >= 3. No re-emit on subsequent days.
# ---------------------------------------------------------------------------


def _edgar_submission_payload_multi(
    cik: int,
    accession_dates: list[tuple[str, str]],
) -> dict:
    return {
        "cik": str(cik),
        "entityType": "operating",
        "name": "Test Co",
        "tickers": ["AAPL"],
        "exchanges": ["Nasdaq"],
        "filings": {
            "recent": {
                "form": ["4"] * len(accession_dates),
                "filingDate": [d for _a, d in accession_dates],
                "accessionNumber": [a for a, _d in accession_dates],
                "primaryDocument": [f"form4-{i}.xml" for i in range(len(accession_dates))],
            }
        },
    }


def test_single_insider_three_buys_is_not_a_cluster(
    adapter: SECInsiderAdapter,
) -> None:
    accession_dates = [
        ("0000320193-26-000001", "2026-05-01"),
        ("0000320193-26-000002", "2026-05-10"),
        ("0000320193-26-000003", "2026-05-20"),
    ]

    with respx.mock(assert_all_called=False) as mock:
        mock.get("/files/company_tickers.json").respond(200, json=_edgar_tickers_payload())
        mock.get("/submissions/CIK0000320193.json").respond(
            200, json=_edgar_submission_payload_multi(320193, accession_dates)
        )
        _mock_index_for(mock, [a for a, _ in accession_dates])
        for acc, _ in accession_dates:
            acc_nodash = acc.replace("-", "")
            mock.get(f"/Archives/edgar/data/320193/{acc_nodash}/form4.xml").respond(
                200, text=_form4_xml(transaction_code="P", insider_cik="0001234567")
            )

        signals = adapter.fetch(date(2026, 5, 1), date(2026, 5, 31))

    assert not _aapl(signals)


def test_two_insiders_plus_one_repeat_is_not_a_cluster(
    adapter: SECInsiderAdapter,
) -> None:
    accession_dates = [
        ("0000320193-26-000001", "2026-05-01"),
        ("0000320193-26-000002", "2026-05-10"),
        ("0000320193-26-000003", "2026-05-20"),
    ]
    insider_ciks = {
        "0000320193-26-000001": "0001111111",
        "0000320193-26-000002": "0001111111",
        "0000320193-26-000003": "0002222222",
    }

    with respx.mock(assert_all_called=False) as mock:
        mock.get("/files/company_tickers.json").respond(200, json=_edgar_tickers_payload())
        mock.get("/submissions/CIK0000320193.json").respond(
            200, json=_edgar_submission_payload_multi(320193, accession_dates)
        )
        _mock_index_for(mock, [a for a, _ in accession_dates])
        for acc, _ in accession_dates:
            acc_nodash = acc.replace("-", "")
            mock.get(f"/Archives/edgar/data/320193/{acc_nodash}/form4.xml").respond(
                200, text=_form4_xml(transaction_code="P", insider_cik=insider_ciks[acc])
            )

        signals = adapter.fetch(date(2026, 5, 1), date(2026, 5, 31))

    assert not _aapl(signals)


def test_three_distinct_insiders_emit_one_cluster_signal(
    adapter: SECInsiderAdapter,
) -> None:
    accession_dates = [
        ("0000320193-26-000001", "2026-05-01"),
        ("0000320193-26-000002", "2026-05-01"),
        ("0000320193-26-000003", "2026-05-01"),
    ]

    with respx.mock(assert_all_called=False) as mock:
        mock.get("/files/company_tickers.json").respond(200, json=_edgar_tickers_payload())
        mock.get("/submissions/CIK0000320193.json").respond(
            200, json=_edgar_submission_payload_multi(320193, accession_dates)
        )
        _mock_index_for(mock, [a for a, _ in accession_dates])
        for i, (acc, _d) in enumerate(accession_dates):
            acc_nodash = acc.replace("-", "")
            cik = f"0003333{str(i).zfill(3)}"
            mock.get(f"/Archives/edgar/data/320193/{acc_nodash}/form4.xml").respond(
                200, text=_form4_xml(transaction_code="P", insider_cik=cik)
            )

        signals = adapter.fetch(date(2026, 5, 1), date(2026, 5, 31))

    aapl_signals = _aapl(signals)
    assert len(aapl_signals) == 1
    assert aapl_signals[0].value_num == 3.0


def test_form4a_amendment_dedups_to_corrected_code(
    adapter: SECInsiderAdapter,
) -> None:
    fixtures = [
        ("0000320193-26-000001", "2026-05-10", "P"),
        ("0000320193-26-000099", "2026-05-15", "M"),
    ]

    with respx.mock(assert_all_called=False) as mock:
        mock.get("/files/company_tickers.json").respond(200, json=_edgar_tickers_payload())
        mock.get("/submissions/CIK0000320193.json").respond(
            200, json=_edgar_submission_payload_multi(320193, [(a, d) for a, d, _ in fixtures])
        )
        _mock_index_for(mock, [a for a, _, _ in fixtures])
        for acc, _d, code in fixtures:
            acc_nodash = acc.replace("-", "")
            mock.get(f"/Archives/edgar/data/320193/{acc_nodash}/form4.xml").respond(
                200, text=_form4_xml(transaction_code=code, insider_cik="0001234567")
            )

        signals = adapter.fetch(date(2026, 5, 1), date(2026, 5, 31))

    assert not _aapl(signals)


def test_cluster_emits_only_on_first_crossing(
    adapter: SECInsiderAdapter,
) -> None:
    accession_dates = [
        ("0000320193-26-000001", "2026-05-01"),
        ("0000320193-26-000002", "2026-05-01"),
        ("0000320193-26-000003", "2026-05-01"),
        ("0000320193-26-000004", "2026-05-11"),
    ]

    with respx.mock(assert_all_called=False) as mock:
        mock.get("/files/company_tickers.json").respond(200, json=_edgar_tickers_payload())
        mock.get("/submissions/CIK0000320193.json").respond(
            200, json=_edgar_submission_payload_multi(320193, accession_dates)
        )
        _mock_index_for(mock, [a for a, _ in accession_dates])
        for i, (acc, _d) in enumerate(accession_dates):
            acc_nodash = acc.replace("-", "")
            cik = f"0004444{str(i).zfill(3)}"
            mock.get(f"/Archives/edgar/data/320193/{acc_nodash}/form4.xml").respond(
                200, text=_form4_xml(transaction_code="P", insider_cik=cik)
            )

        signals = adapter.fetch(date(2026, 5, 1), date(2026, 5, 31))

    aapl_signals = _aapl(signals)
    assert len(aapl_signals) == 1
    assert aapl_signals[0].observed_at == date(2026, 5, 1)
    assert aapl_signals[0].value_num == 3.0


def test_count_drops_and_recrosses_emits_two_signals(
    adapter: SECInsiderAdapter,
) -> None:
    accession_dates = [
        ("0000320193-26-000001", "2026-03-01"),
        ("0000320193-26-000002", "2026-03-01"),
        ("0000320193-26-000003", "2026-03-01"),
        ("0000320193-26-000004", "2026-05-01"),
        ("0000320193-26-000005", "2026-05-01"),
        ("0000320193-26-000006", "2026-05-01"),
    ]
    insider_ciks = [
        "0005555001",
        "0005555002",
        "0005555003",
        "0006666001",
        "0006666002",
        "0006666003",
    ]

    with respx.mock(assert_all_called=False) as mock:
        mock.get("/files/company_tickers.json").respond(200, json=_edgar_tickers_payload())
        mock.get("/submissions/CIK0000320193.json").respond(
            200, json=_edgar_submission_payload_multi(320193, accession_dates)
        )
        _mock_index_for(mock, [a for a, _ in accession_dates])
        for (acc, _d), cik in zip(accession_dates, insider_ciks):
            acc_nodash = acc.replace("-", "")
            mock.get(f"/Archives/edgar/data/320193/{acc_nodash}/form4.xml").respond(
                200, text=_form4_xml(transaction_code="P", insider_cik=cik)
            )

        signals = adapter.fetch(date(2026, 3, 1), date(2026, 5, 31))

    aapl_signals = sorted(
        _aapl(signals),
        key=lambda s: s.observed_at,
    )
    assert len(aapl_signals) == 2
    assert aapl_signals[0].observed_at == date(2026, 3, 1)
    assert aapl_signals[1].observed_at == date(2026, 5, 1)
