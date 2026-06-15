"""Tests for the SEMI book-to-bill scraper."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import respx

from bottlewatch.app.ingest import SemiBookToBillAdapter
from bottlewatch.app.ingest.semi_book_to_bill import _parse_page, build_semi_book_to_bill_adapter
from bottlewatch.config import Settings


@pytest.fixture
def adapter(tmp_path: Path) -> SemiBookToBillAdapter:
    s = Settings(
        app_env="test",
        database_url="sqlite:///:memory:",
        refresh_log_path=tmp_path / "refresh.log",
    )
    return build_semi_book_to_bill_adapter(s)


def _html_with_table(rows: list[tuple[str, float]]) -> str:
    body_rows = "\n".join(f"<tr><td>{period}</td><td>{ratio:.2f}</td></tr>" for period, ratio in rows)
    return f"""<html><body>
<table>
  <thead>
    <tr><th>Month</th><th>Book-to-Bill Ratio</th></tr>
  </thead>
  <tbody>
    {body_rows}
  </tbody>
</table>
</body></html>
"""


def test_adapter_emits_book_to_bill_signals(adapter: SemiBookToBillAdapter, tmp_path: Path) -> None:
    rows = [
        ("2025-01", 1.05),
        ("2025-02", 1.12),
        ("2025-03", 1.20),
    ]
    with respx.mock(base_url="https://www.semi.org") as mock:
        mock.get("/en/market-info/statistics/semi-book-to-bill-report").respond(200, text=_html_with_table(rows))
        signals = adapter.fetch(date(2025, 1, 1), date(2025, 3, 31))

    assert len(signals) == 3
    assert all(s.signal_name == "book_to_bill_ratio" for s in signals)
    assert all(s.segment == "advanced_node_fabs" for s in signals)
    assert signals[-1].value_num == pytest.approx(1.20)


def test_adapter_returns_empty_on_http_error(adapter: SemiBookToBillAdapter) -> None:
    with respx.mock(base_url="https://www.semi.org") as mock:
        mock.get("/en/market-info/statistics/semi-book-to-bill-report").respond(503)
        signals = adapter.fetch(date(2025, 1, 1), date(2025, 3, 31))
    assert signals == []


def test_adapter_skips_out_of_window_rows(adapter: SemiBookToBillAdapter) -> None:
    rows = [
        ("2024-01", 0.90),
        ("2025-01", 1.05),
        ("2025-02", 1.12),
    ]
    with respx.mock(base_url="https://www.semi.org") as mock:
        mock.get("/en/market-info/statistics/semi-book-to-bill-report").respond(200, text=_html_with_table(rows))
        signals = adapter.fetch(date(2025, 1, 1), date(2025, 2, 28))

    assert len(signals) == 2
    assert signals[0].observed_at == date(2025, 1, 1)
    assert signals[1].observed_at == date(2025, 2, 1)


def test_parse_page_finds_table_by_header() -> None:
    html = """
    <html><body>
    <table>
      <tr><th>Month</th><th>Book-to-Bill Ratio</th></tr>
      <tr><td>Jan 2025</td><td>1.05</td></tr>
      <tr><td>Feb 2025</td><td>1.12</td></tr>
    </table>
    </body></html>
    """
    rows = _parse_page(html)
    assert len(rows) == 2
    assert rows[0].period == "2025-01"
    assert rows[0].ratio == pytest.approx(1.05)
    assert rows[1].period == "2025-02"


def test_parse_page_ignores_invalid_ratios() -> None:
    html = """
    <html><body>
    <table>
      <tr><th>Month</th><th>Book-to-Bill Ratio</th></tr>
      <tr><td>Jan 2025</td><td>0.1</td></tr>
      <tr><td>Feb 2025</td><td>5.0</td></tr>
      <tr><td>Mar 2025</td><td>1.15</td></tr>
    </table>
    </body></html>
    """
    rows = _parse_page(html)
    # 0.1 and 5.0 are outside the [0.5, 2.0] sanity band.
    assert len(rows) == 1
    assert rows[0].ratio == pytest.approx(1.15)


def test_semi_lead_time_growth_uses_book_to_bill_raw() -> None:
    from bottlewatch.app.score.extractors import lead_time_growth
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class _Row:
        signal_name: str
        value_num: float | None
        observed_at: date

    signals = [
        _Row("book_to_bill_ratio", 1.3, date(2025, 1, 1)),
    ]
    result = lead_time_growth("advanced_node_fabs", signals)  # type: ignore[arg-type]
    assert result is not None
    assert result.raw_value == pytest.approx(1.3)
    assert result.source_key == "semi_book_to_bill"


def test_semi_lead_time_growth_falls_back_to_ppi_semis_raw() -> None:
    from bottlewatch.app.score.extractors import lead_time_growth
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class _Row:
        signal_name: str
        value_num: float | None
        observed_at: date

    def _add_months(d: date, n: int) -> date:
        year = d.year + (d.month - 1 + n) // 12
        month = (d.month - 1 + n) % 12 + 1
        from calendar import monthrange

        last_day = monthrange(year, month)[1]
        return date(year, month, min(d.day, last_day))

    base = date(2025, 1, 1)
    signals = [_Row("ppi_semis", 100.0, base)]
    for i in range(12):
        # +25% YoY
        v = 100.0 + ((i + 1) * (125 - 100) / 12)
        signals.append(_Row("ppi_semis", v, _add_months(base, i + 1)))
    # No book_to_bill_ratio present, so fallback to ppi_semis YoY (raw 0.25).
    result = lead_time_growth("hbm_memory", signals)  # type: ignore[arg-type]
    assert result is not None
    assert result.raw_value == pytest.approx(0.25)
    assert result.source_key == "semi_ppi"
