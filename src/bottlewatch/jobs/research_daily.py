"""Daily research reasoning job.

Runs after `bottlewatch-recompute`. For each segment it audits the
latest score against the research seed, detects divergences, and
produces a short rationale explaining the current regime and any
meaningful day-over-day changes.

Outputs:
- `research/daily/YYYY-MM-DD/reasoning.md` — human-readable per-segment summary.
- `research/daily/YYYY-MM-DD/divergences.json` — structured divergence flags.
- `research_snapshots` table — same content, queryable by the API.

The job is cost-conscious: it only calls the LLM for segments with
non-trivial changes (score delta > 5, momentum magnitude > 5, or a
seed-vs-dynamic divergence > 0.2). Otherwise it writes a short
machine-generated rationale and carries forward any prior LLM prose.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from bottlewatch.app.db import ResearchSnapshot, Score, Signal, make_engine, make_session_factory, session_scope
from bottlewatch.app.score.research_values import SeedEntry, for_segment, known_segments, load_seed
from bottlewatch.config import Settings, get_settings

_LOGGER = logging.getLogger(__name__)

# Thresholds that make a segment "interesting" enough to call the LLM.
_SCORE_DELTA_THRESHOLD = 5.0
_MOMENTUM_THRESHOLD = 5.0
_DIVERGENCE_THRESHOLD = 0.2

# Numeric-claim validation: a number in the LLM rationale is considered
# grounded if it matches some context value within these tolerances
# (absolute OR relative, to allow rounding like "B=64.8" cited as "65").
_ABS_TOL = 0.05
_REL_TOL = 0.02
# Policy knob: max ungrounded numbers tolerated before the rationale is
# rejected. 0 = strict. Tunable once the rejection logs show the real
# false-positive rate; the fallback is a safe machine rationale, not data loss.
_MAX_UNVERIFIED_CLAIMS = 0

# ISO date tokens (2026-06, 2026-06-15) are stripped before number
# extraction: dates are not quantitative claims, and their inter-component
# hyphens would otherwise parse as spurious negative numbers (e.g.
# "2026-06-15" -> 2026, -6, -15).
_DATE_RE = re.compile(r"\b\d{4}-\d{1,2}(?:-\d{1,2})?\b")

# A standalone integer/decimal, optionally signed, optionally a percent.
# Leading (?<![\w.]) keeps digits inside identifiers (co2, A35SNO, tickers
# like 034020.KS) and inter-digit hyphens from being read as numbers/negatives.
# Trailing (?![\w]|\.\w) blocks a word char or a dot-then-word-char (so
# "034020.KS" and "1.5x"-style tokens aren't matched as bare numbers) while
# still allowing sentence-ending punctuation like "50%." or "65.". Group 1 =
# number, group 2 = "%" or "".
_NUMBER_RE = re.compile(r"(?<![\w.])(-?\d+(?:\.\d+)?)(%?)(?![\w]|\.\w)")

# Project root: src/bottlewatch/jobs/research_daily.py -> ../../../..
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DAILY_OUTPUT_DIR = _PROJECT_ROOT / "research" / "daily"


@dataclass(frozen=True)
class SegmentContext:
    """Inputs needed to reason about one segment."""

    segment: str
    seed: SeedEntry
    scores: dict[str, dict[str, Any]]  # horizon -> score row dict
    prev_scores: dict[str, dict[str, Any]] | None
    signals: list[dict[str, Any]]
    divergences: list[dict[str, Any]]


@dataclass
class RationaleResult:
    """Output of one rationale generation."""

    segment: str
    horizon: str
    rationale_md: str
    divergences: list[dict[str, Any]]
    generated_by: str


def _today(now: datetime | None = None) -> date:
    """Return the logical date for the daily snapshot."""
    if now is None:
        now = datetime.now(tz=timezone.utc)
    return now.date()


def _load_scores_for_date(
    factory: sessionmaker,
    segment: str,
    snapshot_date: date,
) -> dict[str, dict[str, Any]]:
    """Load the 3 horizon score rows for a segment on a given date.

    `computed_at` is compared against the day boundary (00:00 to 23:59).
    """
    start = datetime.combine(snapshot_date, datetime.min.time())
    end = start + timedelta(days=1)
    with factory() as session:
        rows = (
            session.execute(
                select(Score)
                .where(Score.segment == segment)
                .where(Score.computed_at >= start)
                .where(Score.computed_at < end)
                .order_by(Score.horizon.asc())
            )
            .scalars()
            .all()
        )
    return {r.horizon: _score_to_dict(r) for r in rows}


def _load_latest_scores_before(
    factory: sessionmaker,
    segment: str,
    before: datetime,
) -> dict[str, dict[str, Any]]:
    """Load the most recent 3 horizon score rows for a segment before
    the given cutoff (used for day-over-day delta).
    """
    out: dict[str, dict[str, Any]] = {}
    with factory() as session:
        for horizon in ("near", "med", "long"):
            row = session.execute(
                select(Score)
                .where(Score.segment == segment)
                .where(Score.horizon == horizon)
                .where(Score.computed_at < before)
                .order_by(Score.computed_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            if row is not None:
                out[horizon] = _score_to_dict(row)
    return out


def _score_to_dict(s: Score) -> dict[str, Any]:
    return {
        "segment": s.segment,
        "horizon": s.horizon,
        "score": s.score,
        "momentum": s.momentum,
        "regime": s.regime,
        "regime_confidence": s.regime_confidence,
        "data_completeness": s.data_completeness,
        "sub_scores": s.sub_scores,
        "computed_at": s.computed_at.isoformat() if s.computed_at else None,
    }


def _load_recent_signals(
    factory: sessionmaker,
    segment: str,
    since: datetime,
) -> list[dict[str, Any]]:
    """Load the most recent 30 signals for a segment since `since`."""
    with factory() as session:
        rows = (
            session.execute(
                select(Signal)
                .where(Signal.segment == segment)
                .where(Signal.observed_at >= since.date())
                .order_by(Signal.observed_at.desc())
                .limit(30)
            )
            .scalars()
            .all()
        )
    return [
        {
            "signal_name": r.signal_name,
            "value_num": r.value_num,
            "unit": r.unit,
            "source": r.source,
            "observed_at": r.observed_at.isoformat() if r.observed_at else None,
        }
        for r in rows
    ]


def _detect_divergences(score_row: dict[str, Any], seed: SeedEntry) -> list[dict[str, Any]]:
    """Compare the score row's actual sub-scores to research seeds.

    Only sub-scores that are backed by a seed value can diverge:
    `lead_time_growth`, `geo_concentration`, and `demand_signal`.
    `regulatory_friction` is seed-only and `capacity_tightness` is
    always dynamic, so neither is compared.
    """
    divergences: list[dict[str, Any]] = []
    sub_scores = score_row.get("sub_scores") or {}
    for name in ("lead_time_growth", "geo_concentration", "demand_signal"):
        dynamic = sub_scores.get(name)
        static = seed.get(name)
        if dynamic is None or static is None:
            continue
        gap = dynamic - static
        if abs(gap) > _DIVERGENCE_THRESHOLD:
            divergences.append(
                {
                    "sub_score": name,
                    "seed": static,
                    "dynamic": dynamic,
                    "gap": gap,
                }
            )
    return divergences


def _is_interesting(
    score_row: dict[str, Any],
    prev_row: dict[str, Any] | None,
    divergences: list[dict[str, Any]],
) -> bool:
    """True if the segment merits an LLM call today."""
    if divergences:
        return True
    momentum = score_row.get("momentum")
    if momentum is not None and abs(momentum) > _MOMENTUM_THRESHOLD:
        return True
    if prev_row is None:
        return True
    prev_score = prev_row.get("score")
    score = score_row.get("score")
    if prev_score is not None and score is not None and abs(score - prev_score) > _SCORE_DELTA_THRESHOLD:
        return True
    return False


def _build_prompt(context: SegmentContext, horizon: str, score_row: dict[str, Any]) -> str:
    """Build a concise prompt for the LLM."""
    prev = (context.prev_scores or {}).get(horizon)
    prev_score = prev.get("score") if prev else None
    prev_regime = prev.get("regime") if prev else None

    divergences_text = "None"
    if context.divergences:
        divergences_text = "\n".join(
            f"- {d['sub_score']}: seed={d['seed']:.2f}, dynamic={d['dynamic']:.2f}, gap={d['gap']:+.2f}"
            for d in context.divergences
        )

    signals_text = "None"
    if context.signals:
        signals_text = "\n".join(
            f"- {s['signal_name']}={s['value_num']} ({s['source']}, {s['observed_at']})" for s in context.signals[:10]
        )

    return f"""You are a research analyst for Bottlewatch, a dashboard that scores AI-supply-chain bottlenecks on a 0-100 scale. Given the segment, today's score, yesterday's score, the research seed values, and the latest raw signals, write a concise 3-sentence Markdown rationale.

Segment: {context.segment}
Horizon: {horizon}
Today's score (B): {score_row.get("score")}
Today's momentum (B'): {score_row.get("momentum")}
Today's regime: {score_row.get("regime")}
Yesterday's score: {prev_score if prev_score is not None else "N/A"}
Yesterday's regime: {prev_regime if prev_regime is not None else "N/A"}

Research seed sub-scores:
- lead_time_growth: {context.seed.get("lead_time_growth")}
- geo_concentration: {context.seed.get("geo_concentration")}
- regulatory_friction: {context.seed.get("regulatory_friction")}
- demand_signal: {context.seed.get("demand_signal")}

Actual sub-scores used today:
- lead_time_growth: {score_row.get("sub_scores", {}).get("lead_time_growth")}
- capacity_tightness: {score_row.get("sub_scores", {}).get("capacity_tightness")}
- geo_concentration: {score_row.get("sub_scores", {}).get("geo_concentration")}
- regulatory_friction: {score_row.get("sub_scores", {}).get("regulatory_friction")}
- demand_signal: {score_row.get("sub_scores", {}).get("demand_signal")}

Seed-vs-dynamic divergences (>0.2):
{divergences_text}

Recent signals:
{signals_text}

Instructions:
1. First sentence: state the current regime and the single biggest reason for it.
2. Second sentence: identify any meaningful day-over-day change or divergence from the research seed.
3. Third sentence: note the key signal or data gap an investor should watch next.

Be concise. Cite specific signal names and values. Do not invent data. If there are no recent signals, say so explicitly."""


def _call_llm(prompt: str, api_key: str | None, base_url: str, model: str) -> str:
    """Call the Ollama Cloud API and return the generated text.

    Uses the OpenAI-compatible chat completions endpoint.
    Raises if the API key is missing or the call fails.
    """
    if not api_key:
        raise RuntimeError("OLLAMA_API_KEY is not configured")

    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are a concise financial research analyst. Use only the data provided in the prompt.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
        "max_tokens": 512,
    }

    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        response = client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("LLM returned no choices")
    message = choices[0].get("message", {})
    content = message.get("content") or ""
    # Some Ollama models (e.g. qwen3.5:cloud) return the final answer in
    # a `reasoning` field and leave `content` empty. Fall back to
    # reasoning text, but warn so the operator can switch models.
    if not content:
        reasoning = message.get("reasoning") or ""
        if reasoning:
            _LOGGER.warning("LLM model %r returned empty content; using reasoning field", model)
            return str(reasoning).strip()
        raise RuntimeError("LLM returned empty content and no reasoning")
    return str(content).strip()


def _machine_rationale(context: SegmentContext, horizon: str, score_row: dict[str, Any]) -> str:
    """Generate a minimal rationale without an LLM call.

    Used when the LLM is unavailable or when the segment is not
    interesting enough to justify an API call.
    """
    prev = (context.prev_scores or {}).get(horizon)
    prev_score = prev.get("score") if prev else None
    score_delta = ""
    if prev_score is not None and score_row.get("score") is not None:
        delta = score_row["score"] - prev_score
        score_delta = f" Score changed by {delta:+.1f} from yesterday."

    div_text = ""
    if context.divergences:
        div_names = ", ".join(d["sub_score"] for d in context.divergences)
        div_text = f" Divergences vs seed: {div_names}."

    signal_names = ", ".join(sorted({s["signal_name"] for s in context.signals[:5]}))
    signal_text = f" Recent signals: {signal_names}." if signal_names else " No recent signals."

    return (
        f"{context.segment} ({horizon}) is in {score_row.get('regime')} regime with B={score_row.get('score')} "
        f"and B'={score_row.get('momentum')}.{score_delta}{div_text}{signal_text}"
    )


def _date_year_month_parts(iso_date: str | None) -> list[float]:
    """Return the integer year and month of an ISO date as floats.

    Included in the grounding set so legitimate date citations (e.g. the
    year "2026") don't read as hallucinated numbers.
    """
    if not iso_date:
        return []
    try:
        d = date.fromisoformat(iso_date[:10])
    except ValueError:
        return []
    return [float(d.year), float(d.month)]


def _build_grounding_set(context: SegmentContext, score_row: dict[str, Any]) -> list[float]:
    """Collect every numeric value the prompt showed the model.

    These are the only numbers a rationale may legitimately cite: signal
    values, score B, momentum B', prev score, sub-scores, seed values,
    divergence seed/dynamic/gap, and the year/month parts of shown dates.
    """
    values: list[float] = []

    def add(v: Any) -> None:
        if isinstance(v, bool):
            return
        if isinstance(v, (int, float)):
            values.append(float(v))

    # Today's score, momentum, sub-scores.
    add(score_row.get("score"))
    add(score_row.get("momentum"))
    for v in (score_row.get("sub_scores") or {}).values():
        add(v)

    # Yesterday's score for this horizon.
    prev = (context.prev_scores or {}).get(score_row.get("horizon", ""))
    if prev:
        add(prev.get("score"))

    # Research seed sub-scores.
    for v in context.seed.values():
        add(v)

    # Divergence seed / dynamic / gap.
    for d in context.divergences:
        add(d.get("seed"))
        add(d.get("dynamic"))
        add(d.get("gap"))

    # Signal values and the year/month of their observation dates.
    for s in context.signals:
        add(s.get("value_num"))
        values.extend(_date_year_month_parts(s.get("observed_at")))

    return values


def _validate_numeric_claims(
    rationale: str,
    context: SegmentContext,
    score_row: dict[str, Any],
) -> list[float]:
    """Return the numbers in `rationale` not grounded in the prompt context.

    Pure and deterministic. ISO dates are stripped first (not quantitative
    claims). Each remaining number is grounded if it matches some context
    value within tolerance (`abs(a-b) <= max(_ABS_TOL, _REL_TOL*|b|)`). A
    percent ("50%") is matched against BOTH its literal value (50.0) and its
    fraction form (0.50), since sub-scores live on a 0-1 scale but the prompt
    also frames B on 0-100 — so analyst phrasings either way are accepted.
    An empty result means the rationale's numeric claims are all grounded.
    """
    grounding = _build_grounding_set(context, score_row)
    text = _DATE_RE.sub(" ", rationale)
    unverified: list[float] = []
    for number, percent in _NUMBER_RE.findall(text):
        a = float(number)
        candidates = [a, a / 100.0] if percent else [a]
        if not any(abs(cand - b) <= max(_ABS_TOL, _REL_TOL * abs(b)) for cand in candidates for b in grounding):
            unverified.append(a)
    return unverified


def _generate_for_segment_horizon(
    context: SegmentContext,
    horizon: str,
    api_key: str | None,
    base_url: str,
    model: str,
) -> RationaleResult:
    """Generate a rationale for one (segment, horizon).

    If the segment is interesting and an API key is available, call
    the LLM. Otherwise use the machine fallback.
    """
    score_row = context.scores[horizon]
    prev_row = (context.prev_scores or {}).get(horizon)

    generated_by = "machine"
    if api_key and _is_interesting(score_row, prev_row, context.divergences):
        try:
            prompt = _build_prompt(context, horizon, score_row)
            rationale = _call_llm(prompt, api_key, base_url, model)
            unverified = _validate_numeric_claims(rationale, context, score_row)
            if len(unverified) > _MAX_UNVERIFIED_CLAIMS:
                _LOGGER.warning(
                    "LLM rationale rejected for %s/%s: %d ungrounded number(s) %s; using machine fallback",
                    context.segment,
                    horizon,
                    len(unverified),
                    unverified,
                )
                generated_by = "machine_rejected"
            else:
                return RationaleResult(
                    segment=context.segment,
                    horizon=horizon,
                    rationale_md=rationale,
                    divergences=list(context.divergences),
                    generated_by="llm",
                )
        except Exception as e:
            _LOGGER.warning("LLM rationale failed for %s/%s: %s; using fallback", context.segment, horizon, e)
            generated_by = "machine_llm_error"

    return RationaleResult(
        segment=context.segment,
        horizon=horizon,
        rationale_md=_machine_rationale(context, horizon, score_row),
        divergences=list(context.divergences),
        generated_by=generated_by,
    )


def _write_artifacts(
    snapshot_date: date,
    results: list[RationaleResult],
) -> Path:
    """Write the daily markdown + JSON artifacts and return the directory."""
    out_dir = _DAILY_OUTPUT_DIR / snapshot_date.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)

    md_path = out_dir / "reasoning.md"
    json_path = out_dir / "divergences.json"

    md_lines = [f"# Daily Research Reasoning — {snapshot_date}\n"]
    for r in results:
        md_lines.append(f"\n## {r.segment} ({r.horizon}) — generated by {r.generated_by}\n")
        md_lines.append(r.rationale_md)
        md_lines.append("")

    md_path.write_text("\n".join(md_lines), encoding="utf-8")

    divergences_by_segment_horizon: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        if r.divergences:
            key = f"{r.segment}:{r.horizon}"
            divergences_by_segment_horizon[key] = r.divergences
    json_path.write_text(json.dumps(divergences_by_segment_horizon, indent=2), encoding="utf-8")

    return out_dir


def run(
    *,
    settings: Settings | None = None,
    factory: sessionmaker | None = None,
    now: datetime | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Generate daily research rationales for all segments.

    Args:
        settings: application settings. Defaults to `get_settings()`.
        factory: SQLAlchemy sessionmaker. Defaults to a factory built
            from `settings.database_url`.
        now: reference timestamp. Defaults to UTC now.
        api_key: Ollama Cloud API key. Defaults to `settings.ollama_api_key`.

    Returns:
        A report dict with counts and the output directory.
    """
    settings = settings or get_settings()
    now = now or datetime.now(tz=timezone.utc)
    api_key = api_key if api_key is not None else settings.ollama_api_key
    base_url = settings.ollama_base_url
    model = settings.ollama_model

    if factory is None:
        engine = make_engine(settings.database_url)
        factory = make_session_factory(engine)

    snapshot_date = _today(now)
    snapshot_dt = datetime.combine(snapshot_date, datetime.min.time())
    signal_since = snapshot_dt - timedelta(days=90)

    seed = load_seed()
    results: list[RationaleResult] = []

    for segment in known_segments(seed):
        scores = _load_scores_for_date(factory, segment, snapshot_date)
        if not scores:
            _LOGGER.info("no scores for %s on %s; skipping", segment, snapshot_date)
            continue

        prev_scores = _load_latest_scores_before(factory, segment, snapshot_dt)
        segment_seed = for_segment(segment, seed)
        # Divergences are computed from the near-horizon score because it has
        # the most dynamic inputs; the same seed applies to all horizons.
        near_row = scores.get("near")
        divergences = _detect_divergences(near_row, segment_seed) if near_row else []
        signals = _load_recent_signals(factory, segment, signal_since)

        context = SegmentContext(
            segment=segment,
            seed=segment_seed,
            scores=scores,
            prev_scores=prev_scores if prev_scores else None,
            signals=signals,
            divergences=divergences,
        )

        for horizon in ("near", "med", "long"):
            if horizon not in scores:
                continue
            result = _generate_for_segment_horizon(context, horizon, api_key, base_url, model)
            results.append(result)

    # Upsert all results into the DB.
    with session_scope(factory) as session:
        for r in results:
            existing = session.execute(
                select(ResearchSnapshot).where(
                    ResearchSnapshot.segment == r.segment,
                    ResearchSnapshot.horizon == r.horizon,
                    ResearchSnapshot.date == snapshot_date,
                )
            ).scalar_one_or_none()
            if existing is not None:
                existing.rationale_md = r.rationale_md
                existing.divergences = r.divergences
                existing.generated_by = r.generated_by
                existing.created_at = now
            else:
                session.add(
                    ResearchSnapshot(
                        segment=r.segment,
                        horizon=r.horizon,
                        date=snapshot_date,
                        rationale_md=r.rationale_md,
                        divergences=r.divergences,
                        generated_by=r.generated_by,
                        created_at=now,
                    )
                )

    out_dir = _write_artifacts(snapshot_date, results)
    llm_count = sum(1 for r in results if r.generated_by == "llm")
    llm_error_count = sum(1 for r in results if r.generated_by == "machine_llm_error")
    rejected_count = sum(1 for r in results if r.generated_by == "machine_rejected")
    # "machine" = no LLM attempted (no key / not interesting). The four
    # counts partition `total`.
    machine_count = len(results) - llm_count - llm_error_count - rejected_count

    _LOGGER.info(
        "research_daily: %d rationales written (%d LLM, %d machine, %d llm_error, %d rejected) to %s",
        len(results),
        llm_count,
        machine_count,
        llm_error_count,
        rejected_count,
        out_dir,
    )
    return {
        "date": snapshot_date.isoformat(),
        "total": len(results),
        "llm": llm_count,
        "machine": machine_count,
        "llm_error": llm_error_count,
        "rejected": rejected_count,
        "output_dir": str(out_dir),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="bottlewatch-research",
        description="Generate daily research rationales and divergence audit.",
    )
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        default=None,
        help="Snapshot date (YYYY-MM-DD). Default: today.",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Ollama Cloud API key (overrides OLLAMA_API_KEY env).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Use a temporary DB and do not touch production data.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        settings = get_settings()
        if args.dry_run:
            settings = settings.model_copy(
                update={"database_url": f"sqlite:///{Path('/tmp/bottlewatch-research-dry.db')}"}
            )
        now = datetime.combine(args.date, datetime.min.time(), tzinfo=timezone.utc) if args.date else None
        report = run(settings=settings, now=now, api_key=args.api_key)
    except Exception as e:
        print(f"fatal: {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    print(f"bottlewatch-research: {report['total']} rationales ({report['llm']} LLM, {report['machine']} machine)")
    print(f"  output: {report['output_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
