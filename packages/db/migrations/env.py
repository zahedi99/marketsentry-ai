"""Alembic environment: connects migrations to our models and database."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from ms_db.models import Base
from ms_db.session import database_url

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# What autogenerate compares the live database against.
target_metadata = Base.metadata


def url() -> str:
    """An explicit URL passed by tests wins; otherwise $DATABASE_URL / the local default."""
    configured = config.get_main_option("sqlalchemy.url")
    return configured or database_url()


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it (`alembic upgrade head --sql`)."""
    context.configure(
        url=url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect to the database and apply migrations."""
    engine = create_engine(url())
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
