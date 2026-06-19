"""GET /api/v1/tickers.

Returns the investable universe as one row per (ticker, segment)
pair from `research/02_universe.csv`. Each row is annotated with the
current regime from the `scores` table (joined on segment).

The plan says: read from the ontology ABox, fall back to CSV. For
M2, the CSV is the source of truth (per plan §2.3: "the CSV is
kept as a human-edited input — easier to review in a spreadsheet
than Turtle — but is the build input, not the runtime source").
The CSV is loaded once per request (small file, <200 rows) and
joined to the materialized scores in memory.

M3 can add a SPARQL-backed path once the ontology ABox is queried
in the hot path.
"""

from __future__ import annotations

import csv
import logging
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from bottlewatch.app.db import Score
from bottlewatch.app.value_chain import SEGMENT_TO_NODE_ID, load_value_chain_json
from bottlewatch.app import segments_meta


_LOGGER = logging.getLogger(__name__)

router = APIRouter(tags=["tickers"])


class TickerRow(BaseModel):
    ticker: str
    exchange: str
    name: str
    segment: str
    subsegment: str | None
    exposure_pct: float | None
    market_cap_bucket: str
    mcap_usd: float | None
    currency_hedge: str
    notes: str
    regime: str | None
    regime_confidence: str | None


# Project root: src/bottlewatch/app/api/tickers.py -> ../../../../  (4 levels)
_UNIVERSE_CSV = Path(__file__).resolve().parents[4] / "research" / "02_universe.csv"


def _coerce_float(raw: str) -> float | None:
    """Parse a CSV cell as a float. Returns None for empty / unparseable.

    Raises `ValueError` on garbage (e.g. `"n/a"`) so the caller can
    decide between None (semantic: "missing") and 0.0 (semantic:
    "explicit zero"). The list endpoints log a warning and set
    `None`; the M2 spec is that exposure_pct is a percent so a
    missing value should be visibly missing, not silently zero.
    """
    stripped = raw.strip()
    if not stripped:
        return None
    try:
        return float(Decimal(stripped.replace(",", "").replace("$", "")))
    except (InvalidOperation, ValueError) as e:
        raise ValueError(f"could not parse {raw!r} as float") from e


def _pick_eta(
    segment_map: dict[str, dict],
    static_eta: dict[str, tuple[str, str]],
) -> dict | None:
    """Pick the ETA for a multi-segment ticker.

    The M2 ETA table has one entry per segment; when a ticker spans
    several, the highest-exposure segment is the one whose
    bottleneck trajectory the user most cares about. Ties go to
    the first-seen segment (insertion order in the CSV, which is
    Python dict insertion order — deterministic).
    """
    if not segment_map:
        return None
    candidates = [(seg, info.get("exposure_pct")) for seg, info in segment_map.items()]
    # Highest exposure first; None treated as -inf so it loses to
    # any real value. Ties broken by first-seen (stable sort).
    candidates.sort(key=lambda x: (x[1] is None, -(x[1] or 0.0)))
    for seg, _ in candidates:
        if seg in static_eta:
            eta_band, conf = static_eta[seg]
            return {"eta": eta_band, "confidence": conf, "segment": seg}
    return None


def _parse_exposure_pct(row: dict[str, str], *, ticker: str, segment: str) -> float | None:
    """Parse exposure_pct from a CSV row, logging a warning on garbage.

    Centralizes the "log + return None" pattern so both ticker
    endpoints behave identically.
    """
    raw = row.get("exposure_pct") or ""
    try:
        return _coerce_float(raw)
    except ValueError:
        _LOGGER.warning(
            "ticker=%s segment=%s: unparseable exposure_pct=%r; emitting null",
            ticker,
            segment,
            raw,
        )
        return None


def _load_universe_rows() -> list[dict[str, str]]:
    """Read the universe CSV into a list of dicts.

    Returns [] if the file is missing (e.g. running from an installed
    wheel). The endpoint then returns an empty list rather than 500.
    """
    if not _UNIVERSE_CSV.exists():
        _LOGGER.warning("universe CSV not found at %s", _UNIVERSE_CSV)
        return []
    with _UNIVERSE_CSV.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _score_index(factory: sessionmaker) -> dict[str, tuple[str | None, str | None]]:
    """Build a {segment: (regime, regime_confidence)} index for the near horizon.

    The ticker endpoint annotates each row with the *near-horizon*
    regime of the ticker’s segment. The full 3-horizon regime data is
    available at /api/v1/scores/regime for the quadrant.
    """
    with factory() as session:
        rows = session.execute(
            select(Score.segment, Score.regime, Score.regime_confidence).where(Score.horizon == "near")
        ).all()
    return {seg: (regime, conf) for seg, regime, conf in rows}


@router.get("/tickers", response_model=list[TickerRow])
def list_tickers(
    request: Request,
    segment: str | None = Query(
        default=None,
        description="Filter to one segment slug.",
    ),
) -> list[TickerRow]:
    factory: sessionmaker = request.app.state.session_factory
    universe = _load_universe_rows()
    if not universe:
        return []
    regimes = _score_index(factory)

    out: list[TickerRow] = []
    for row in universe:
        seg = (row.get("segment") or "").strip()
        if not seg:
            continue
        if segment is not None and seg != segment:
            continue
        regime, conf = regimes.get(seg, (None, None))
        ticker = (row.get("ticker") or "").strip()
        out.append(
            TickerRow(
                ticker=ticker,
                exchange=(row.get("exchange") or "").strip(),
                name=(row.get("name") or "").strip(),
                segment=seg,
                subsegment=(row.get("subsegment") or "").strip() or None,
                exposure_pct=_parse_exposure_pct(row, ticker=ticker, segment=seg),
                market_cap_bucket=(row.get("market_cap_bucket") or "").strip(),
                mcap_usd=_coerce_float(row.get("mcap_usd") or ""),
                currency_hedge=(row.get("currency_hedge") or "").strip(),
                notes=(row.get("notes") or "").strip(),
                regime=regime,
                regime_confidence=conf,
            )
        )
    return out


class TickerDetailSegment(BaseModel):
    segment: str
    name: str
    subsegment: str | None
    exposure_pct: float | None
    regime_near: str | None
    score_near: float | None
    momentum_near: float | None
    thesis_count: int


class TickerDetail(BaseModel):
    ticker: str
    exchange: str
    name: str
    segments: list[TickerDetailSegment]
    companies: list[str]
    thesis: list[dict]
    eta: dict | None
    thesis_count: int


@router.get("/tickers/{ticker}", response_model=TickerDetail)
def get_ticker(request: Request, ticker: str) -> TickerDetail:
    from bottlewatch.app.db import Score, Thesis
    from sqlalchemy import select, func

    factory = request.app.state.session_factory
    universe = _load_universe_rows()
    regimes = _score_index(factory)

    # Find all rows in the CSV for this ticker.
    ticker_rows = [r for r in universe if (r.get("ticker") or "").strip() == ticker]
    if not ticker_rows:
        raise HTTPException(status_code=404, detail=f"ticker not found: {ticker!r}")

    # Deduplicate segments (a ticker can have multiple rows in the CSV
    # for different subsegments of the same segment).
    segment_map: dict[str, dict] = {}
    for row in ticker_rows:
        seg = (row.get("segment") or "").strip()
        if not seg:
            continue
        if seg not in segment_map:
            segment_map[seg] = {
                "subsegment": (row.get("subsegment") or "").strip() or None,
                "exposure_pct": _parse_exposure_pct(row, ticker=ticker, segment=seg),
            }

    # Get near-horizon scores for each segment.
    segments_out: list[dict] = []
    with factory() as session:
        thesis_counts = dict(
            session.execute(
                select(Thesis.ticker, func.count(Thesis.id)).where(Thesis.ticker == ticker).group_by(Thesis.ticker)
            ).all()
        )
        # Near-horizon score/momentum for all of the ticker's segments in one
        # query (was a SELECT per segment — an N+1).
        score_rows = session.execute(
            select(Score.segment, Score.score, Score.momentum).where(
                Score.segment.in_(list(segment_map)), Score.horizon == "near"
            )
        ).all()
        score_by_segment = {seg: (score, momentum) for seg, score, momentum in score_rows}
        for seg, info in segment_map.items():
            regime, conf = regimes.get(seg, (None, None))
            score_near, momentum_near = score_by_segment.get(seg, (None, None))
            segments_out.append(
                {
                    "segment": seg,
                    "name": segments_meta.display_name(seg),
                    "subsegment": info["subsegment"],
                    "exposure_pct": info["exposure_pct"],
                    "regime_near": regime,
                    "score_near": score_near,
                    "momentum_near": momentum_near,
                    "thesis_count": thesis_counts.get(ticker, 0),
                }
            )

    # Companies: collect unique companies from the value chain for each segment.
    # The value-chain JSON's node id (e.g. `transformers_switchgear`) may
    # differ from the scoring segment slug (e.g. `transformers_tnd`); the
    # shared `SEGMENT_TO_NODE_ID` map in `app.value_chain` is the only
    # place that translation lives.
    companies: set[str] = set()
    chain = load_value_chain_json()
    if chain:
        seg_to_node = {n["id"]: n for n in chain.get("nodes", [])}
        for seg in segment_map:
            node_id = SEGMENT_TO_NODE_ID.get(seg, seg)
            node = seg_to_node.get(node_id)
            if node:
                companies.update(node.get("companies", []))

    # Thesis notes for this ticker.
    thesis_notes: list[dict] = []
    with factory() as session:
        rows = (
            session.execute(select(Thesis).where(Thesis.ticker == ticker).order_by(Thesis.updated_at.desc()))
            .scalars()
            .all()
        )
        for r in rows:
            thesis_notes.append(
                {
                    "id": r.id,
                    "side": r.side,
                    "body_md": r.body_md,
                    "updated_at": r.updated_at,
                }
            )

    # ETA: from the highest-exposure segment. If the ticker spans
    # multiple segments, the segment with the largest exposure_pct
    # is the one whose bottleneck trajectory the user most cares
    # about; ties go to the first-seen segment (CSV row order).
    # The ETA endpoint has a static table; read it directly.
    from bottlewatch.app.api.eta import _STATIC_ETA

    eta = _pick_eta(segment_map, _STATIC_ETA)

    first_row = ticker_rows[0]
    return TickerDetail(
        ticker=ticker,
        exchange=(first_row.get("exchange") or "").strip(),
        name=(first_row.get("name") or "").strip(),
        segments=[TickerDetailSegment(**s) for s in segments_out],
        companies=sorted(companies),
        thesis=thesis_notes,
        eta=eta,
        thesis_count=len(thesis_notes),
    )
