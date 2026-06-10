"""SQLAlchemy engine + session factory.

A single `make_engine(url)` is the public entry point. M1 callers
either pass a real sqlite file path (the production case) or
`sqlite:///:memory:` (tests). Postgres is one URL swap away —
`postgresql+psycopg://...` for v1.1.

URL-scheme-aware connect_args: SQLite needs `check_same_thread=False`
when used across threads (FastAPI sync handlers run in anyio's
threadpool); Postgres rejects that option, so we only apply it
when the URL scheme is sqlite. This is the only Postgres-vs-sqlite
divergence at the engine level — the models and migrations are
already portable.

We do NOT enable SQLAlchemy's connection pool echo by default —
pass `echo=True` for debugging in a notebook.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from bottlewatch.app.db.models import Base

_IN_MEMORY_URL = "sqlite:///:memory:"


def _scheme(url: str) -> str:
    """Return the URL scheme (`sqlite`, `postgresql`, ...). Empty if unparseable."""
    if "://" in url:
        return url.split("://", 1)[0].lower()
    return ""


def _normalize_url(url: str) -> str:
    """Rewrite a plain `postgresql://` URL to `postgresql+psycopg://`.

    SQLAlchemy's `postgresql://` dialect defaults to `psycopg2`,
    which is a separate (and unmaintained-as-of-2024) dependency.
    We ship `psycopg3` (`psycopg[binary]`), so we transparently
    pick the psycopg3 driver for any user that writes the
    short-form URL. The user can still opt into `psycopg2` by
    writing `postgresql+psycopg2://` explicitly.
    """
    if _scheme(url) == "postgresql":
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def _connect_args_for(url: str) -> dict[str, object]:
    """Per-scheme connect_args.

    SQLite needs `check_same_thread=False` when the engine will be
    used across threads (the FastAPI threadpool, the recompute
    job's worker thread). Postgres doesn't accept that key.
    """
    if _scheme(url).startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


def make_engine(url: str, *, echo: bool = False) -> Engine:
    """Construct an engine. For sqlite file URLs, ensure the parent dir exists.
    For sqlite:///:memory:, use StaticPool so the test engine's schema is
    visible to every connection (FastAPI's threadpool opens one per worker).

    For Postgres, the engine gets default pool sizing (5 + 10 overflow)
    plus `pool_pre_ping=True` so stale connections after a server
    restart are recycled silently.
    """
    url = _normalize_url(url)
    if _scheme(url).startswith("sqlite") and url != _IN_MEMORY_URL:
        path = Path(url.removeprefix("sqlite:///"))
        if not path.is_absolute():
            path = Path.cwd() / path
        path.parent.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, object] = {
        "echo": echo,
        "connect_args": _connect_args_for(url),
        "future": True,
    }
    if url == _IN_MEMORY_URL:
        kwargs["poolclass"] = StaticPool
    if _scheme(url).startswith("postgresql"):
        # Reasonable defaults for a single-user dashboard. Tune later
        # when the QPS justifies it.
        kwargs["pool_size"] = 5
        kwargs["max_overflow"] = 10
        kwargs["pool_pre_ping"] = True
    return create_engine(url, **kwargs)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Transactional scope. Commits on success, rolls back on exception."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_schema(engine: Engine) -> None:
    """Create all tables. Used by the orchestrator's fallback path
    when the alembic head is missing, and by tests.
    """
    Base.metadata.create_all(engine)
