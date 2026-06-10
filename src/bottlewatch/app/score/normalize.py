"""5y rolling-band normalization (methodology §1).

The methodology prescribes three edge cases:
1. <2 years of history → return 0.5 (universe median, methodology
   calls for the median of the universe — we use 0.5 as the
   conservative midpoint until a real median is wired in v1.1)
2. flat history (min == max) → return 0.5 (no signal)
3. normal case → map linearly to [0, 1] using the band

Direction note: for sub-scores where higher raw = tighter (the
default in the methodology), we map directly. For inverted
sub-scores (none in v1), flip the band.
"""

from __future__ import annotations

_HISTORY_MIN_DAYS = 730  # 2y
_UNINFORMED_VALUE = 0.5


def normalize_5y(value: float, history: list[float]) -> float:
    """Map a raw value to [0, 1] using the 5y min/max band.

    `history` should be the trailing 5y of values, oldest first.
    The band is min(history) → max(history). The function is
    pure and side-effect-free.
    """
    if not history or value is None:
        return _UNINFORMED_VALUE
    band_min, band_max = min(history), max(history)
    if band_min == band_max:
        return _UNINFORMED_VALUE
    # If the value is outside the band, clamp to [0, 1]. This
    # happens when the most recent reading sets a new high/low;
    # we don't want a "101" reading to overflow the score.
    if value <= band_min:
        return 0.0
    if value >= band_max:
        return 1.0
    return (value - band_min) / (band_max - band_min)


def history_is_mature_dated(history: list[tuple[float, float]]) -> bool:
    """True if the (timestamp, value) pairs span >= 2 years.

    Used to gate the <2y edge case in `normalize_5y`. Caller passes
    the trailing 5y of (unix_ts, value) pairs.
    """
    if len(history) < 2:
        return False
    timestamps = [t for t, _ in history]
    span_seconds = max(timestamps) - min(timestamps)
    return span_seconds >= _HISTORY_MIN_DAYS * 86_400
