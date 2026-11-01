"""Give an existing Supabase Auth user a profile in a local database, for development only.

The API refuses anyone without a profile, and account management arrives with #31. Until then this
lets a developer who has an Auth user sign in to their own local copy. It refuses other databases.

Usage: uv run python -m app.seed_local_profile <auth user id> <username> [staff|manager]
"""

import sys
from urllib.parse import urlsplit
from uuid import UUID

from sqlmodel import Session, create_engine

from app.create_first_manager import LOCAL_HOSTS
from app.models import Profile, Role
from app.settings import get_settings


def main(arguments: list[str]) -> int:
    if len(arguments) not in (2, 3):
        print(__doc__, file=sys.stderr)
        return 1
    database_url = get_settings().database_url
    if urlsplit(database_url).hostname not in LOCAL_HOSTS:
        print("This only seeds a local database.", file=sys.stderr)
        return 1
    auth_user_id, username = UUID(arguments[0]), arguments[1]
    role = Role(arguments[2]) if len(arguments) == 3 else Role.STAFF

    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            if session.get(Profile, auth_user_id) is not None:
                print(f"Auth user {auth_user_id} already has a profile, so nothing was changed.")
                return 0
            session.add(
                Profile(
                    auth_user_id=auth_user_id, username=username, display_name=username, role=role
                )
            )
            session.commit()
    finally:
        engine.dispose()
    print(f"Created the {role.value} profile {username}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
