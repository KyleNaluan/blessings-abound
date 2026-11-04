from logging.config import fileConfig

from sqlalchemy import create_engine, pool
from sqlmodel import SQLModel

import app.models  # noqa: F401
from alembic import context
from app.settings import get_settings
from mock_channel.tables import SCHEMAS as CHANNEL_SCHEMAS
from mock_channel.tables import metadata as channel_metadata

# Import every table module above so autogenerate can see it.

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = [SQLModel.metadata, channel_metadata]
database_url = get_settings().database_url
# The app's tables are in the default schema and each mock channel's are in its own.
SCHEMAS = {None, *CHANNEL_SCHEMAS}


def include_name(name: str | None, type_: str, parent_names: object) -> bool:
    # Leave out every other schema, such as the ones Supabase adds for itself.
    return name in SCHEMAS if type_ == "schema" else True


def run_migrations_offline() -> None:
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        include_schemas=True,
        include_name=include_name,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(database_url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_name=include_name,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
