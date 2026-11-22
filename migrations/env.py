from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool
from sqlmodel import SQLModel

import ask_ai.models  # noqa: F401  Registers the tables on SQLModel.metadata.
from ask_ai.config import settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata

# DATABASE_URL by default. Tests point Alembic at their own database with
# config.set_main_option("sqlalchemy.url", ...).
db_url = config.get_main_option("sqlalchemy.url") or settings.database_url


def run_migrations_offline() -> None:
    """Emit the migrations as SQL to stdout instead of running them."""
    context.configure(
        url=db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(db_url, poolclass=pool.NullPool)

    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
