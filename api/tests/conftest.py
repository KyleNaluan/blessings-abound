from collections.abc import Iterator
from urllib.parse import urlsplit

import pytest
from sqlalchemy import Connection
from sqlmodel import Session, SQLModel

from app import models  # noqa: F401, so SQLModel.metadata lists every table
from app.db import get_engine
from app.settings import get_settings

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "db"}


@pytest.fixture(scope="session", autouse=True)
def refuse_hosted_database() -> None:
    # Test runs and test data stay out of the shared demo database, whatever .env says.
    host = urlsplit(get_settings().database_url).hostname
    if host not in LOCAL_HOSTS:
        pytest.exit(f"Tests only run against a local database, not {host}.", returncode=2)


@pytest.fixture
def connection() -> Iterator[Connection]:
    """A connection on empty tables whose work is rolled back at the end of the test.

    Tests see no rows from a developer's own local data, and that data is back afterwards.
    """
    with get_engine().connect() as connection:
        transaction = connection.begin()
        for table in reversed(SQLModel.metadata.sorted_tables):
            connection.execute(table.delete())
        yield connection
        if transaction.is_active:
            transaction.rollback()


@pytest.fixture
def session(connection: Connection) -> Iterator[Session]:
    """A session on that connection, where commit only releases a savepoint."""
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        yield session
