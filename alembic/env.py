"""Alembic env: wires up the project's SQLAlchemy metadata and pulls the DB URL from
bottlewatch.config.Settings. The actual migration DDL lives in
alembic/versions/0001_initial_signals.py (hand-checked; no autogenerate in M1).
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Importing the package brings in the Base + the two model classes, so
# autogenerate (if we ever turn it on) can see them. The cost is one
# cheap import; the win is consistency with the orchestrator's
# create_all path.
from bottlewatch.app.db.models import Base  # noqa: F401
from bottlewatch.config import get_settings

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Override sqlalchemy.url with the project's settings. We escape `%`
# to `%%` because configparser's interpolation treats `%` as a
# token; raw URLs with `?options=-c%20...` would otherwise raise
# `ValueError: invalid interpolation syntax`.
config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
