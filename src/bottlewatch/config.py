"""Application settings loaded from environment + .env.

Pydantic-settings reads .env automatically (when the file exists) and
overlays process env. The Settings class is a singleton-by-convention:
importing it at the top of a module yields a fresh instance each time,
but the underlying `model_validate` is cheap. Tests pass a custom
`Settings(_env_file=None, eia_api_key="test-key")` rather than mutating
the real env.

We deliberately keep the surface small — only what M1 reads. v1
extensions (EIA-860M paths, FRED key, USITC creds) will append fields
here, not fork the class.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root: three levels up from this file (src/bottlewatch/config.py).
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DATA_DIR = _PROJECT_ROOT / "data"
_DEFAULT_DB_PATH = _DATA_DIR / "processed" / "bottlewatch.db"
_DEFAULT_LOG_PATH = _DATA_DIR / "cache" / "refresh.log"


class Settings(BaseSettings):
    """Typed application settings.

    The .env file lives at the project root (next to pyproject.toml).
    APP_ENV controls logging verbosity in v2; for M1 we just stash it.
    """

    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = Field(default="dev", description="dev | test | prod")
    eia_api_key: str | None = Field(default=None, description="EIA Open Data v2 API key")
    fred_api_key: str | None = Field(default=None, description="FRED API key")
    comtrade_api_key: str | None = Field(default=None, description="UN Comtrade API key")
    ollama_api_key: str | None = Field(default=None, description="Ollama Cloud API key for daily research reasoning")
    ollama_base_url: str = Field(
        default="https://ollama.com/v1",
        description="Ollama Cloud API base URL",
    )
    ollama_model: str = Field(default="llama3.2", description="Ollama model for daily research reasoning")

    # sqlite:///./relative is interpreted relative to CWD by SQLAlchemy
    # by default; using an absolute path keeps the orchestrator location-
    # independent. Override with DATABASE_URL=postgresql://... for v1.1.
    database_url: str = Field(
        default=f"sqlite:///{_DEFAULT_DB_PATH}",
        description="SQLAlchemy URL. sqlite:///:memory: is the test default.",
    )
    refresh_log_path: Path = Field(
        default=_DEFAULT_LOG_PATH,
        description="JSONL log written by the orchestrator.",
    )

    # Price ingest for the walk-forward backtest.
    price_data_source: Literal["csv", "yfinance", "alphavantage"] = Field(
        default="csv",
        description="Source for refreshing data/processed/prices.csv; 'csv' leaves the file untouched.",
    )
    price_api_key: str | None = Field(default=None, description="API key for Alpha Vantage price ingest.")
    prices_csv_path: Path = Field(
        default=_DATA_DIR / "processed" / "prices.csv",
        description="Destination CSV for price refresh; backtest reads this file by default.",
    )
    price_lookback_days: int = Field(
        default=730,
        description="Default calendar-days window to pull when refreshing prices.",
    )

    eia_base_url: str = Field(
        default="https://api.eia.gov/v2",
        description="EIA v2 base URL; pinned so v2 changes do not surprise us.",
    )
    eia_timeout_s: float = Field(default=30.0, description="httpx timeout per request")
    eia_max_retries: int = Field(default=3, description="tenacity stop_after_attempt")
    eia_isorto_regions: list[str] = Field(
        default_factory=lambda: ["ERCO", "CISO", "PJM"],
        description="EIA-930 respondents used for ISO/RTO capacity-tightness data.",
    )

    # M2 web surface. CORS default is the Next.js dev origin; override
    # in .env for prod. The API is read-only in M2 so methods are
    # restricted to GET at the middleware level (see app/main.py).
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000"],
        description="Origins allowed by CORS. The scoreboard runs at :3000 in dev.",
    )
    score_horizons: list[str] = Field(
        default_factory=lambda: ["near", "med", "long"],
        description="Horizon labels; the scoreboard renders one column per entry.",
    )

    # Phase 2 scoring-engine feature flags.
    geo_concentration_source: Literal["ontology", "universe_weighted"] = Field(
        default="universe_weighted",
        description="Source for the geo_concentration sub-score. universe_weighted uses 02_universe.csv; ontology uses the OWL ABox.",
    )
    score_normalization_mode: Literal["fixed", "rolling"] = Field(
        default="fixed",
        description="Sub-score normalization: fixed bands (current behavior) or 5-year rolling bands.",
    )
    score_bands_path: Path = Field(
        default=_PROJECT_ROOT / "research" / "config" / "score_bands.json",
        description="JSON calibration file for fixed sub-score bands.",
    )


def get_settings() -> Settings:
    """Build a fresh Settings. Cheap; do not memoize."""
    return Settings()
