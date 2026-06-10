"""Adapter contract + RawSignal model.

The contract is a `Protocol`, not an ABC, so adapters can be plain
classes (or even module-level callables wrapped in a class) and the
type-checker still gets the structure for free.

Adapters are PURE network: they take a period window, hit the source,
and return a list of `RawSignal`. They do NOT touch the database; the
orchestrator owns the DB write path. This keeps adapters testable in
isolation and lets us swap a cache layer in later without touching
the network code.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Callable, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

# Signature for the optional progress callback adapters can
# accept. `current` and `total` are 0-based (0, total) when the
# adapter is about to start; (i, total) per step; (total, total)
# on completion. `label` is a short human-readable string
# ("AAPL", "series_id", etc.) so the user can see what the
# adapter is currently working on. Adapters that don't have a
# known total (EIA v2's open-ended series list) can ignore the
# callback.
ProgressCallback = Callable[[int, int, str], None]


class Cadence(Enum):
    """How often the orchestrator should re-run this source.

    `min_interval` is the minimum gap between successful runs before
    the orchestrator re-fetches. The orchestrator consults this AND
    the source's last successful run; the more conservative wins.
    """

    DAILY = ("daily", 1)  # 1 day
    WEEKLY = ("weekly", 7)
    MONTHLY = ("monthly", 30)

    def __init__(self, label: str, min_interval_days: int) -> None:
        self.label = label
        self.min_interval_days = min_interval_days


class RawSignal(BaseModel):
    """One raw observation, normalized to the signals table schema.

    `id` and `ingested_at` are assigned by the orchestrator at write
    time; adapters never set them. `tickers` is JSON-encoded and is
    an empty list for M1 (the universe-to-signal mapping is M3).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    segment: str
    subsegment: str | None = None
    signal_name: str
    value_num: float | None = None
    value_text: str | None = None
    unit: str | None = None
    geography: str | None = None
    source: str
    source_id: str | None = None
    observed_at: date
    tickers: str = "[]"  # JSON array; defaults to "[]"


@runtime_checkable
class Adapter(Protocol):
    """The contract every ingest source implements.

    `name` is the stable identifier (e.g. "eia_v2") used in the
    `ingest_runs` table, the refresh log, and the CLI `--source`
    flag. `cadence` is the orchestrator's hint for watermark checks.
    """

    name: str
    cadence: Cadence

    def is_configured(self) -> tuple[bool, str]:
        """Return (ok, reason). When ok is False, `fetch()` MUST return []. The
        orchestrator surfaces the reason in the refresh log.
        """
        ...

    def fetch(
        self,
        period_start: date,
        period_end: date,
        progress: ProgressCallback | None = None,
    ) -> list[RawSignal]:
        """Fetch raw signals for the period. Network only; no DB.

        `progress` is an optional `(current, total, label) -> None`
        callback the adapter may invoke per step. The orchestrator
        wires this up to a stderr progress bar; adapters that
        don't have a meaningful inner loop (most of them) can
        accept the param and ignore it.
        """
        ...


@dataclass(frozen=True)
class AdapterSpec:
    """A registered adapter + its constructor args.

    The registry (in `app/ingest/__init__.py`) is a list of
    `AdapterSpec`s so we can build adapters with config injected
    at runtime (e.g. `Settings`) rather than at import time.
    """

    name: str
    cadence: Cadence
    factory: "type[Adapter]"


# EIA v2 mandates the API key in the URL query string; httpx logs the
# full URL at INFO before sending. The request hooks that try to mutate
# `request.url` in place also mutate the outgoing request, so the
# approach is to drop httpx's per-request log line to WARNING. Adapters
# that want finer-grained per-call logging should attach a custom
# request hook that captures the *response* (where the URL is not a
# secret anymore) and emits a structured log line.
def quiet_httpx_request_log() -> None:
    """Silence httpx's per-request INFO log line; WARNING+ still fires.

    EIA v2 mandates the API key in the URL query string, and httpx logs
    the full URL at INFO. A request hook that mutates `request.url` in
    place would also mutate the outgoing request and the API would see
    the scrubbed value (caught this in test). Dropping the log level is
    the cleanest fix: the orchestrator's structured log line still
    records source + status + rows_written, and adapters that need
    finer-grained per-call info can attach a custom hook.
    """
    import logging

    logging.getLogger("httpx").setLevel(logging.WARNING)
