"""Create the first manager in Supabase Auth and their profile. Safe to run again.

It reads FIRST_MANAGER_USERNAME, FIRST_MANAGER_EMAIL and FIRST_MANAGER_PASSWORD, plus DATABASE_URL,
SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY, from the environment or the root .env file. It never
changes the password or role of an account that already exists, and it refuses to guess when the
existing accounts disagree with those settings.

Usage: uv run python -m app.create_first_manager
"""

import re
import sys
from urllib.parse import urlsplit
from uuid import UUID

import httpx2
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlmodel import Session, create_engine, select

from app.models import USERNAME_PATTERN, Profile, Role
from app.settings import ROOT_ENV_FILE
from app.supabase_auth import SupabaseAuthAdmin

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "db"}


class SetupError(Exception):
    """A problem the person running the script has to fix. The message never holds a secret."""


class FirstManagerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_ENV_FILE, env_ignore_empty=True, extra="ignore")

    database_url: str = "postgresql+psycopg://thrift:thrift@localhost:5432/thrift"
    supabase_url: str | None = None
    supabase_service_role_key: SecretStr | None = None
    first_manager_username: str | None = None
    first_manager_email: str | None = None
    first_manager_password: SecretStr | None = None


def check_same_environment(database_url: str, supabase_url: str) -> None:
    """Refuse to pair a local database with a hosted Auth project, or the other way around."""
    database_is_local = urlsplit(database_url).hostname in LOCAL_HOSTS
    auth_is_local = urlsplit(supabase_url).hostname in LOCAL_HOSTS
    if database_is_local != auth_is_local:
        raise SetupError(
            "DATABASE_URL and SUPABASE_URL point at different environments, "
            "so the login and the profile would end up in different places."
        )


def _existing_manager_message(profile: Profile, username: str, email: str) -> str:
    if profile.username != username or profile.email != email or profile.role != Role.MANAGER:
        raise SetupError(
            f"A profile already uses username {profile.username} or email {profile.email} with "
            f"role {profile.role}, which does not match these settings, so nothing was changed."
        )
    return f"Manager {username} already exists, so nothing was changed."


def ensure_first_manager(
    session: Session,
    auth: SupabaseAuthAdmin,
    username: str,
    email: str,
    password: str | None,
) -> str:
    """Make sure the manager exists and return a line saying what happened."""
    if not re.fullmatch(USERNAME_PATTERN, username):
        raise SetupError(
            "FIRST_MANAGER_USERNAME may only use lowercase letters, digits, '.', '_' and '-'."
        )
    email = email.lower()

    for match in (
        session.exec(select(Profile).where(Profile.username == username)).first(),
        session.exec(select(Profile).where(Profile.email == email)).first(),
    ):
        if match is not None:
            return _existing_manager_message(match, username, email)

    user = auth.find_user(email)
    if user is None:
        if not password:
            raise SetupError("FIRST_MANAGER_PASSWORD is required to create a new Auth user.")
        user = auth.create_user(email, password)
        action = "Created the Auth user and profile"
    else:
        # A confirmed address means this script made the user on an earlier run that stopped
        # before the profile. An unconfirmed one could be a stranger's sign-up for that address.
        if not user.get("email_confirmed_at"):
            raise SetupError(
                f"An unconfirmed Auth user already has the email {email}, so it was not made a "
                "manager. Delete that user in Supabase if it is not yours, then run this again."
            )
        action = "Kept the existing Auth user and its password, and created the profile"

    auth_user_id = UUID(user["id"])
    if session.get(Profile, auth_user_id) is not None:
        raise SetupError(f"The Auth user for {email} already has a different profile.")

    session.add(
        Profile(
            auth_user_id=auth_user_id,
            username=username,
            display_name=username,
            email=email,
            role=Role.MANAGER,
        )
    )
    session.commit()
    return f"{action} for manager {username}."


def main(transport: httpx2.BaseTransport | None = None) -> int:
    settings = FirstManagerSettings()
    required = {
        "SUPABASE_URL": settings.supabase_url,
        "SUPABASE_SERVICE_ROLE_KEY": settings.supabase_service_role_key,
        "FIRST_MANAGER_USERNAME": settings.first_manager_username,
        "FIRST_MANAGER_EMAIL": settings.first_manager_email,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        print(f"Missing settings: {', '.join(missing)}", file=sys.stderr)
        return 1
    assert settings.supabase_url and settings.supabase_service_role_key
    assert settings.first_manager_username and settings.first_manager_email

    password = (
        settings.first_manager_password.get_secret_value()
        if settings.first_manager_password
        else None
    )
    auth = SupabaseAuthAdmin(
        settings.supabase_url, settings.supabase_service_role_key.get_secret_value(), transport
    )
    engine = create_engine(settings.database_url)
    try:
        check_same_environment(settings.database_url, settings.supabase_url)
        with Session(engine) as session:
            print(
                ensure_first_manager(
                    session,
                    auth,
                    settings.first_manager_username,
                    settings.first_manager_email,
                    password,
                )
            )
    except SetupError as error:
        print(error, file=sys.stderr)
        return 1
    except httpx2.HTTPStatusError as error:
        # Only the status, never the request that carried the password.
        print(f"Supabase Auth returned status {error.response.status_code}.", file=sys.stderr)
        return 1
    except httpx2.TransportError as error:
        print(f"Could not reach Supabase Auth: {type(error).__name__}.", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
