"""Let each mock channel's database role sign in, with a password from the environment.

The migration creates the `channel_a` and `channel_b` roles with no login, so no password is ever
in the repo. Run this as the database owner after the migrations, with either password or both:

    CHANNEL_A_DB_PASSWORD=... CHANNEL_B_DB_PASSWORD=... uv run python -m app.channel_roles

A role whose password variable is empty is left as it is. Running it again sets the same
passwords, so it is safe to repeat, and docker compose runs it on every start.
"""

import os
import sys

from psycopg import sql
from sqlalchemy import Connection

from app.db import get_engine
from mock_channel.tables import SCHEMAS


def password_variable(role: str) -> str:
    return f"{role.upper()}_DB_PASSWORD"


def set_passwords(connection: Connection, passwords: dict[str, str]) -> list[str]:
    """Turn on login for each role given a password, and return the roles changed."""
    changed = []
    for role in SCHEMAS:
        password = passwords.get(role)
        if not password:
            continue
        statement = sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {}").format(
            sql.Identifier(role), sql.Literal(password)
        )
        # The password is quoted by psycopg, and the role name is one of ours.
        raw = connection.connection.dbapi_connection
        assert raw is not None
        connection.exec_driver_sql(statement.as_string(raw))  # pyright: ignore[reportArgumentType]
        changed.append(role)
    return changed


def main() -> int:
    passwords = {role: os.environ.get(password_variable(role), "") for role in SCHEMAS}
    with get_engine().begin() as connection:
        changed = set_passwords(connection, passwords)
    for role in SCHEMAS:
        state = (
            "can sign in" if role in changed else f"unchanged, {password_variable(role)} is empty"
        )
        print(f"{role}: {state}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
