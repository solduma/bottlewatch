"""Ingest adapters.

Public surface:
- `RawSignal`, `Adapter`, `Cadence`, `AdapterSpec` (re-exported from base.py)
- `EIAV2Adapter` (re-exported from eia.py)
- `get_registry()` — the orchestrator iterates this. Adding a new
  source is a one-liner: define a class, append an `AdapterSpec` to
  `_build_registry()`.

Why a registry instead of `importlib.metadata` entry points? The
project has one deployment; the explicit list is grep-friendly and
keeps the test for "is the EIA adapter registered" in this file.
"""

from bottlewatch.app.ingest.base import Adapter, AdapterSpec, Cadence, RawSignal
from bottlewatch.app.ingest.eia import EIAV2Adapter
from bottlewatch.app.ingest.eia_860m import EIA860MAdapter
from bottlewatch.app.ingest.eia_capacity import EIAV2CapacityAdapter
from bottlewatch.app.ingest.fred import FredAdapter
from bottlewatch.app.ingest.comtrade import ComtradeAdapter
from bottlewatch.app.ingest.epa_egrid import EPAEGridAdapter
from bottlewatch.app.ingest.eia_electric import EIAElectricAdapter
from bottlewatch.app.ingest.sec_edgar import SECEdgarAdapter
from bottlewatch.app.ingest.sec_insider import SECInsiderAdapter
from bottlewatch.app.ingest.semi_book_to_bill import SemiBookToBillAdapter

__all__ = [
    "Adapter",
    "AdapterSpec",
    "Cadence",
    "EIA860MAdapter",
    "EIAV2Adapter",
    "EIAV2CapacityAdapter",
    "FredAdapter",
    "ComtradeAdapter",
    "EPAEGridAdapter",
    "EIAElectricAdapter",
    "SECEdgarAdapter",
    "SECInsiderAdapter",
    "SemiBookToBillAdapter",
    "RawSignal",
    "get_registry",
]


def _build_registry() -> list[AdapterSpec]:
    """Import the bundled adapters and produce their specs.

    The factories take a `Settings` and return a configured Adapter.
    Importing the adapter modules here (rather than at module load)
    keeps `bottlewatch.app.ingest` importable without httpx/tenacity
    installed — e.g. for type checking in a clean env.
    """
    from bottlewatch.app.ingest.eia import build_eia_v2_adapter
    from bottlewatch.app.ingest.eia_860m import build_eia_860m_adapter
    from bottlewatch.app.ingest.eia_capacity import build_eia_v2_capacity_adapter
    from bottlewatch.app.ingest.fred import build_fred_adapter
    from bottlewatch.app.ingest.comtrade import build_comtrade_adapter
    from bottlewatch.app.ingest.epa_egrid import build_epa_egrid_adapter
    from bottlewatch.app.ingest.eia_electric import build_eia_electric_adapter
    from bottlewatch.app.ingest.sec_edgar import build_sec_edgar_adapter
    from bottlewatch.app.ingest.sec_insider import build_sec_insider_adapter
    from bottlewatch.app.ingest.semi_book_to_bill import build_semi_book_to_bill_adapter

    return [
        AdapterSpec(
            name="eia_v2",
            cadence=Cadence.DAILY,
            factory=build_eia_v2_adapter,  # type: ignore[arg-type]
        ),
        AdapterSpec(
            name="eia_v2_capacity",
            cadence=Cadence.WEEKLY,
            factory=build_eia_v2_capacity_adapter,  # type: ignore[arg-type]
        ),
        AdapterSpec(
            name="eia_860m",
            cadence=Cadence.MONTHLY,
            factory=build_eia_860m_adapter,  # type: ignore[arg-type]
        ),
        AdapterSpec(
            name="fred",
            cadence=Cadence.WEEKLY,
            factory=build_fred_adapter,  # type: ignore[arg-type]
        ),
        AdapterSpec(
            name="comtrade",
            cadence=Cadence.MONTHLY,
            factory=build_comtrade_adapter,  # type: ignore[arg-type]
        ),
        AdapterSpec(
            name="epa_egrid",
            cadence=Cadence.MONTHLY,
            factory=build_epa_egrid_adapter,  # type: ignore[arg-type]
        ),
        AdapterSpec(
            name="eia_electric",
            cadence=Cadence.MONTHLY,
            factory=build_eia_electric_adapter,  # type: ignore[arg-type]
        ),
        AdapterSpec(
            name="sec_edgar",
            cadence=Cadence.MONTHLY,
            factory=build_sec_edgar_adapter,  # type: ignore[arg-type]
        ),
        AdapterSpec(
            name="sec_insider",
            cadence=Cadence.DAILY,
            factory=build_sec_insider_adapter,  # type: ignore[arg-type]
        ),
        AdapterSpec(
            name="semi_book_to_bill",
            cadence=Cadence.MONTHLY,
            factory=build_semi_book_to_bill_adapter,  # type: ignore[arg-type]
        ),
    ]


# Built lazily so adapter construction is deferred until the
# orchestrator is ready to inject Settings.
_REGISTRY: list[AdapterSpec] | None = None


def get_registry() -> list[AdapterSpec]:
    """Return the registered adapters, building on first call."""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _build_registry()
    return list(_REGISTRY)
