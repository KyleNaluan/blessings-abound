"""Create or restore the demo staff and demo manager accounts for judging. Safe to run again.

It reads DEMO_STAFF_PASSWORD and DEMO_MANAGER_PASSWORD, and optionally DEMO_STAFF_USERNAME and
DEMO_MANAGER_USERNAME, plus DATABASE_URL, SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY, from the
environment or the root .env file. Running it again puts the passwords from the environment back
and turns the accounts back on, so a judge's changes don't carry over to the next judge.

Usage: uv run python -m app.seed_demo_accounts
"""

import sys
from uuid import UUID

import httpx2
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlmodel import Session, create_engine, select

from app.create_first_manager import SetupError, check_same_environment
from app.models import Profile, Role
from app.settings import ROOT_ENV_FILE
from app.supabase_auth import NO_BAN, SupabaseAuthAdmin, placeholder_email


class DemoAccountSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_ENV_FILE, env_ignore_empty=True, extra="ignore")

    database_url: str = "postgresql+psycopg://thrift:thrift@localhost:5432/thrift"
    supabase_url: str | None = None
    supabase_service_role_key: SecretStr | None = None
    demo_staff_username: str = "demo.staff"
    demo_staff_password: SecretStr | None = None
    demo_manager_username: str = "demo.manager"
    demo_manager_password: SecretStr | None = None


def ensure_demo_account(
    session: Session,
    auth: SupabaseAuthAdmin,
    username: str,
    display_name: str,
    role: Role,
    password: str,
) -> str:
    """Make sure the account exists and works with this password, and say what happened."""
    profile = session.exec(select(Profile).where(Profile.username == username)).first()
    if profile is not None:
        if profile.role != role:
            raise SetupError(
                f"The profile {username} has role {profile.role}, not {role}, so nothing was "
                "changed for it."
            )
        auth.update_user(
            profile.auth_user_id, password=password, ban_duration=NO_BAN, email_confirm=True
        )
        profile.is_active = True
        profile.must_change_password = False
        profile.invited_at = None
        session.add(profile)
        session.commit()
        return f"Restored the {role.value} account {username}."

    email = placeholder_email(username)
    user = auth.find_user(email)
    if user is None:
        user = auth.create_user(email, password)
    else:
        # An earlier run stopped before the profile.
        auth.update_user(UUID(user["id"]), password=password, ban_duration=NO_BAN)
    session.add(
        Profile(
            auth_user_id=UUID(user["id"]), username=username, display_name=display_name, role=role
        )
    )
    session.commit()
    return f"Created the {role.value} account {username}."


def main(transport: httpx2.BaseTransport | None = None) -> int:
    settings = DemoAccountSettings()
    required = {
        "SUPABASE_URL": settings.supabase_url,
        "SUPABASE_SERVICE_ROLE_KEY": settings.supabase_service_role_key,
        "DEMO_STAFF_PASSWORD": settings.demo_staff_password,
        "DEMO_MANAGER_PASSWORD": settings.demo_manager_password,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        print(f"Missing settings: {', '.join(missing)}", file=sys.stderr)
        return 1
    assert settings.supabase_url and settings.supabase_service_role_key
    assert settings.demo_staff_password and settings.demo_manager_password

    auth = SupabaseAuthAdmin(
        settings.supabase_url, settings.supabase_service_role_key.get_secret_value(), transport
    )
    engine = create_engine(settings.database_url)
    try:
        check_same_environment(settings.database_url, settings.supabase_url)
        if not auth.sign_ups_are_off():
            print("Warning: public sign-up is on for this Auth server.", file=sys.stderr)
        with Session(engine) as session:
            for username, display_name, role, password in (
                (
                    settings.demo_staff_username,
                    "Demo Staff",
                    Role.STAFF,
                    settings.demo_staff_password,
                ),
                (
                    settings.demo_manager_username,
                    "Demo Manager",
                    Role.MANAGER,
                    settings.demo_manager_password,
                ),
            ):
                print(
                    ensure_demo_account(
                        session, auth, username, display_name, role, password.get_secret_value()
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
