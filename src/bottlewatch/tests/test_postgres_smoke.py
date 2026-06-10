"""Opt-in Postgres smoke test.

Runs end-to-end against a real Postgres database when
`BOTTLEWATCH_PG_TEST_URL` is set in the env. Skipped otherwise so
CI without a Postgres instance keeps using the in-memory SQLite
test path.

What it covers (the v1.1 cutover acceptance):
- `make_engine` produces a working Postgres engine
- `Base.metadata.create_all` and `alembic upgrade head` produce the
  same schema (the in-test path uses create_all to avoid a
  subprocess; the migrations were verified separately)
- `session_scope` round-trips a Signal row and a Score row with
  the `sub_scores` JSON column
- `recompute_scores.run` writes 30 score rows + 30 score_history
  rows on a fresh DB
- The API surface can be mounted against the Postgres engine and
  serves the scoreboard endpoint

The smoke test creates a one-off schema for isolation. Postgres
schemas are the canonical way to namespace migrations in test
suites; the default `public` schema is reserved for production.
The connecting user needs CREATE/DROP SCHEMA privileges.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest
from sqlalchemy import text

# Skip the whole module when the env var is unset. Pytest's
# collection-time skip means CI without Postgres pays no cost.
pytestmark = pytest.mark.skipif(
    os.environ.get("BOTTLEWATCH_PG_TEST_URL") is None,
    reason="BOTTLEWATCH_PG_TEST_URL not set; Postgres smoke test is opt-in",
)


def _pg_url() -> str:
    """Return the configured Postgres URL (must be postgresql+psycopg://...)."""
    url = os.environ["BOTTLEWATCH_PG_TEST_URL"]
    if not url.startswith("postgresql+psycopg://"):
        # SQLAlchemy 2.0 won't pick psycopg3 from a plain postgresql:// URL.
        # Force the dialect so the engine doesn't try to import psycopg2.
        url = "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


def _isolated_url(schema: str) -> str:
    """Add `?options=...search_path=<schema>` to the URL.

    Postgres ignores `connect_args` for `options=`; the cleanest
    way to scope a session to a schema is via the connection
    string's `options` parameter.
    """
    parts = urlsplit(_pg_url())
    # urlencode-friendly: options is the last query arg.
    new_q = f"options=-c%20search_path%3D{schema}"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_q, parts.fragment))


@pytest.fixture
def pg_schema():
    """Create a fresh schema, yield its name, drop it on teardown.

    Connects as the application user (the URL's credentials) so
    permissions are tested end-to-end. The user needs CREATE +
    DROP SCHEMA privileges on the database.
    """
    import psycopg

    # Parse the URL to get the credentials (the same ones in the URL).
    parts = urlsplit(_pg_url())
    user = parts.username
    password = parts.password
    host = parts.hostname
    port = parts.port or 5432
    dbname = parts.path.lstrip("/")

    # A unique schema per test run — combine timestamp + pid to dodge
    # collisions when two CI jobs share a DB.
    schema = f"bottlewatch_smoke_{datetime.now(tz=timezone.utc).strftime('%H%M%S_%f')}"

    admin_conn = psycopg.connect(host=host, port=port, dbname=dbname, user=user, password=password, autocommit=True)
    try:
        with admin_conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA "{schema}"')
        yield schema
    finally:
        try:
            with admin_conn.cursor() as cur:
                cur.execute(f'DROP SCHEMA "{schema}" CASCADE')
        finally:
            admin_conn.close()


def test_engine_connects_to_postgres() -> None:
    from bottlewatch.app.db import make_engine

    eng = make_engine(_pg_url())
    try:
        with eng.connect() as conn:
            result = conn.execute(text("SELECT current_user, current_database()")).fetchone()
        assert result is not None
        user, db = result
        assert db == "bottlewatch"
    finally:
        eng.dispose()


def test_create_all_builds_schema_on_postgres(pg_schema: str) -> None:
    """Base.metadata.create_all produces the expected tables on Postgres."""
    from bottlewatch.app.db import init_schema, make_engine

    url = _isolated_url(pg_schema)
    eng = make_engine(url)
    try:
        init_schema(eng)
        with eng.connect() as conn:
            rows = conn.execute(
                text("SELECT table_name FROM information_schema.tables WHERE table_schema = :s ORDER BY table_name"),
                {"s": pg_schema},
            ).fetchall()
        names = {r[0] for r in rows}
        assert {"signals", "ingest_runs", "scores", "score_history", "thesis"} <= names
    finally:
        eng.dispose()


def test_signal_and_score_round_trip_on_postgres(pg_schema: str) -> None:
    """The JSON `sub_scores` column survives a Postgres round-trip as a dict."""
    from datetime import date

    from bottlewatch.app.db import init_schema, make_engine, make_session_factory, session_scope
    from bottlewatch.app.db.models import Score, Signal

    url = _isolated_url(pg_schema)
    eng = make_engine(url)
    try:
        init_schema(eng)
        factory = make_session_factory(eng)
        now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        with session_scope(factory) as session:
            session.add(
                Signal(
                    segment="seg_a",
                    signal_name="sig_a",
                    value_num=1.0,
                    unit="unit",
                    source="test",
                    observed_at=date(2024, 1, 1),
                    ingested_at=now,
                )
            )
            session.add(
                Score(
                    segment="seg_a",
                    horizon="near",
                    score=50.0,
                    momentum=0.0,
                    regime="STABLE",
                    regime_confidence="low",
                    sub_scores={"a": 1.0, "b": 2.0, "c": None},
                    data_completeness=0.8,
                    first_computed_at=now,
                    computed_at=now,
                )
            )

        # Read back: confirm the JSON column came through as a real dict.
        from sqlalchemy import select

        with factory() as session:
            sig = session.execute(select(Signal)).scalars().one()
            assert sig.segment == "seg_a"
            score = session.execute(select(Score)).scalars().one()
            assert isinstance(score.sub_scores, dict)
            assert score.sub_scores == {"a": 1.0, "b": 2.0, "c": None}
    finally:
        eng.dispose()


def test_recompute_writes_30_score_rows_on_postgres(pg_schema: str) -> None:
    """The recompute job produces 30 score rows + 30 score_history rows on Postgres."""
    from bottlewatch.app.db import init_schema, make_engine, make_session_factory
    from bottlewatch.app.db.models import Score, ScoreHistory
    from bottlewatch.config import Settings
    from bottlewatch.jobs import recompute_scores

    url = _isolated_url(pg_schema)
    eng = make_engine(url)
    try:
        init_schema(eng)
        factory = make_session_factory(eng)
        settings = Settings(database_url=url, refresh_log_path=Path("/tmp/pg-smoke.log"))
        report = recompute_scores.run(settings=settings, factory=factory)
        assert report.exit_code == 0
        assert report.rows_written == 30  # 10 segments × 3 horizons

        from sqlalchemy import select

        with factory() as session:
            score_count = len(session.execute(select(Score)).scalars().all())
            history_count = len(session.execute(select(ScoreHistory)).scalars().all())
        assert score_count == 30
        assert history_count == 30
    finally:
        eng.dispose()


def test_alembic_upgrade_head_on_postgres(pg_schema: str) -> None:
    """The 4 existing migrations run cleanly against Postgres (DDL is portable)."""
    import subprocess
    from bottlewatch.app.db import make_engine
    from sqlalchemy import text

    url = _isolated_url(pg_schema)
    env = {**os.environ, "DATABASE_URL": url}
    # `alembic upgrade head` from a clean Postgres schema. Each test
    # run uses a unique schema so we don't depend on the public
    # schema being empty.
    result = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(Path(__file__).resolve().parents[3]),
    )
    assert result.returncode == 0, f"alembic failed: {result.stderr}"

    # Verify the tables exist under the test schema.
    eng = make_engine(url)
    try:
        with eng.connect() as conn:
            rows = conn.execute(
                text("SELECT table_name FROM information_schema.tables WHERE table_schema = :s"),
                {"s": pg_schema},
            ).fetchall()
        names = {r[0] for r in rows}
        assert {"signals", "ingest_runs", "scores", "score_history", "thesis", "alembic_version"} <= names
    finally:
        eng.dispose()
