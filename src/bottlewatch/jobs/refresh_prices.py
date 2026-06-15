"""CLI job: refresh data/processed/prices.csv from a live price source."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path
from typing import Any

from bottlewatch.app.ingest.base import ProgressCallback
from bottlewatch.app.ingest.prices import run_refresh_prices
from bottlewatch.config import Settings, get_settings

_LOGGER = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_UNIVERSE = _PROJECT_ROOT / "research" / "02_universe.csv"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="bottlewatch-refresh-prices",
        description="Refresh equity prices for the backtest.",
    )
    parser.add_argument(
        "--source",
        type=str,
        default=None,
        choices=["csv", "yfinance", "alphavantage"],
        help="Price source. Default: PRICE_DATA_SOURCE setting.",
    )
    parser.add_argument(
        "--universe",
        type=Path,
        default=_DEFAULT_UNIVERSE,
        help="Path to the ticker universe CSV. Default: research/02_universe.csv.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Destination CSV. Default: PRICES_CSV_PATH setting.",
    )
    parser.add_argument(
        "--since",
        type=date.fromisoformat,
        default=None,
        help="Start date (YYYY-MM-DD). Default: today - price_lookback_days.",
    )
    parser.add_argument(
        "--until",
        type=date.fromisoformat,
        default=None,
        help="End date (YYYY-MM-DD). Default: today.",
    )
    return parser.parse_args(argv)


def _noop_progress(current: int, total: int, label: str) -> None:
    """Default progress callback: emits one log line per ticker."""
    if label:
        _LOGGER.info("[%d/%d] %s", current, total, label)


def run(
    *,
    settings: Settings | None = None,
    source: str | None = None,
    universe_path: Path | None = None,
    output_path: Path | None = None,
    start: date | None = None,
    end: date | None = None,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Public entry point; used by tests."""
    settings = settings or get_settings()
    return run_refresh_prices(
        settings=settings,
        universe_path=universe_path or _DEFAULT_UNIVERSE,
        output_path=output_path or settings.prices_csv_path,
        source=source,
        start=start,
        end=end,
        progress=progress,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    settings = get_settings()
    try:
        result = run(
            settings=settings,
            source=args.source,
            universe_path=args.universe,
            output_path=args.output or settings.prices_csv_path,
            start=args.since,
            end=args.until,
            progress=_noop_progress,
        )
    except FileNotFoundError as e:
        print(f"fatal: {e}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"fatal: {e}", file=sys.stderr)
        return 2

    print(f"{result['source']}: {result['tickers']} tickers, {result['rows_written']} rows written to {result['path']}")
    if result.get("detail"):
        print(result["detail"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
