"""Migration tests: the migrations and the models must describe the same schema."""

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, inspect

from ms_db.models import Base
from ms_db.testing import alembic_config


def test_migrations_match_the_models(migrated_engine: Engine) -> None:
    # If someone changes models.py without generating a migration, this fails.
    with migrated_engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)

    assert diff == []


def test_migrations_downgrade_and_upgrade_cleanly(migrated_engine: Engine) -> None:
    cfg = alembic_config(migrated_engine.url.render_as_string(hide_password=False))

    command.downgrade(cfg, "base")
    assert set(inspect(migrated_engine).get_table_names()) == {"alembic_version"}

    command.upgrade(cfg, "head")
    assert {"instruments", "daily_closes", "price_snapshots"} <= set(
        inspect(migrated_engine).get_table_names()
    )
