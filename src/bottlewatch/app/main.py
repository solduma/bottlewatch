"""FastAPI app factory (M2).

`make api` runs `uvicorn bottlewatch.app.main:app`; that
`app` is the module-level singleton built by `create_app()`.
Tests call `create_app()` directly with a `Settings` that
points at the in-memory engine from `conftest.py`.

The app's `state.session_factory` is the bridge between the
async routers and the sync SQLAlchemy engine. Routers pull it
out of `request.app.state` and pass it to the service layer.

CORS: methods are `GET` plus `POST` in M2. `POST` is only
needed for the thesis endpoint (`POST /api/v1/thesis`); the
rest of the API is read-only. The default
`cors_origins=["http://localhost:3000"]` covers the Next.js
dev server. Override in .env for prod.

Test seam: `create_app` accepts an optional `session_factory`
so the test fixture can pass one bound to a pre-seeded
in-memory engine. Without it, `create_app` builds its own
engine from `settings.database_url`.
"""

from __future__ import annotations


from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import sessionmaker

from bottlewatch.app.api import eta, health, map, scores, screener, segments, signals, thesis, tickers
from bottlewatch.app.db import make_engine, make_session_factory
from bottlewatch.config import Settings, get_settings


def create_app(
    settings: Settings | None = None,
    *,
    session_factory: sessionmaker | None = None,
) -> FastAPI:
    """Build a FastAPI app. Tests pass a Settings with the
    in-memory engine; `make api` passes get_settings() default.
    """
    settings = settings or get_settings()
    app = FastAPI(title="Bottlewatch API", version="0.2.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    if session_factory is None:
        engine = make_engine(settings.database_url)
        session_factory = make_session_factory(engine)
    app.state.session_factory = session_factory

    app.include_router(health.router, prefix="/api/v1")
    app.include_router(segments.router, prefix="/api/v1")
    app.include_router(signals.router, prefix="/api/v1")
    app.include_router(scores.router, prefix="/api/v1")
    app.include_router(tickers.router, prefix="/api/v1")
    app.include_router(screener.router, prefix="/api/v1")
    app.include_router(map.router, prefix="/api/v1")
    app.include_router(eta.router, prefix="/api/v1")
    app.include_router(thesis.router, prefix="/api/v1")
    return app


# Module-level singleton for `uvicorn bottlewatch.app.main:app`.
app = create_app()
