#!/usr/bin/env python3
"""Diagnostic helper for score-band calibration.

Usage:
    python research/scripts/calibrate_score_bands.py
    python research/scripts/calibrate_score_bands.py --regenerate

Loads ``data/reports/phase3_backtest.json`` (or regenerates it via the
``bottlewatch-backtest`` job with ``--regenerate``), ranks segments by
information coefficient (Spearman rho), and prints the worst-calibrated
segments so a human can adjust ``research/config/score_bands.json``.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Project root: research/scripts/calibrate_score_bands.py -> ../../
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_REPORT = _PROJECT_ROOT / "data" / "reports" / "phase3_backtest.json"
_BACKTEST_MODULE = "bottlewatch.jobs.backtest"




@dataclass(frozen=True)
class SegmentDiag:
    segment: str
    n: int
    rho: float | None
    p_value: float | None
    miscalibration_score: float


def _load_report(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"report not found at {path}")
    return json.loads(path.read_text())


def _regenerate_report(output: Path) -> None:
    """Run the backtest CLI and write ``output``.

    This depends on a populated DB and ``data/processed/prices.csv``.
    If either is missing the CLI will fail loudly, which is the desired
    behavior for a regeneration command.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            _BACKTEST_MODULE,
            "--output",
            str(output),
            "--horizon",
            "near",
            "--forward-days",
            "90",
            "--start",
            "2024-03-01",
            "--end",
            "2026-03-01",
        ],
        capture_output=True,
        text=True,
        cwd=str(_PROJECT_ROOT),
    )
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        raise SystemExit(result.returncode)


def _analyze(report: dict[str, Any]) -> list[SegmentDiag]:
    """Rank per-segment IC rows by miscalibration (lowest rho first).

    The heuristic: segments with negative or near-zero IC are the most
    likely to have a fixed band that diverges from the rolling 5-year
    band. We also penalize small samples lightly so a noisy -0.30 with
    n=5 does not drown out a stable -0.08 with n=24.
    """
    rows: list[SegmentDiag] = []
    for row in report.get("per_segment_ic", []):
        segment = row["segment"]
        rho = row.get("rho")
        n = row.get("n", 0)
        if rho is None:
            continue
        rows.append(
            SegmentDiag(
                segment=segment,
                n=n,
                rho=rho,
                p_value=row.get("p_value"),
                miscalibration_score=-rho + max(0, 20 - n) / 100.0,
            )
        )
    return sorted(rows, key=lambda d: d.miscalibration_score, reverse=True)


def _format_p(p: float | None) -> str:
    if p is None:
        return "n/a"
    return f"{p:.3f}"


def _print_summary(report: dict[str, Any], worst: list[SegmentDiag]) -> None:
    rho = report.get("overall_ic")
    print(f"Phase 3 backtest report: {_DEFAULT_REPORT}")
    print(f"Horizon     : {report.get('horizon')}")
    print(f"Forward days: {report.get('forward_days')}")
    print(f"Overall IC  : {rho}")
    print(f"Eval points : {report.get('n_eval_points')}")
    print()
    print("Worst-calibrated segments (lowest IC, adjusted for sample size):")
    print(f"{'rank':>4}  {'segment':<24} {'n':>4} {'rho':>7} {'p':>7}")
    print("-" * 50)
    for i, d in enumerate(worst[:5], start=1):
        print(f"{i:>4}. {d.segment:<24} {d.n:>4} {d.rho:>7.3f} {_format_p(d.p_value):>7}")
    print()
    print("Suggested next step:")
    if worst:
        top = worst[0]
        print(f"  Review research/config/score_bands.json for '{top.segment}' (rho={top.rho:.3f}, n={top.n}).")
    else:
        print("  No segments flagged.")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose score-band calibration from the Phase 3 backtest report.")
    parser.add_argument(
        "--report",
        type=Path,
        default=_DEFAULT_REPORT,
        help="Path to phase3_backtest.json. Default: data/reports/phase3_backtest.json.",
    )
    parser.add_argument(
        "--regenerate",
        action="store_true",
        help="Regenerate the report via bottlewatch-backtest before analyzing.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.regenerate:
        _regenerate_report(args.report)
    report = _load_report(args.report)
    worst = _analyze(report)
    _print_summary(report, worst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
