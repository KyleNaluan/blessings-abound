import json
from uuid import UUID

import httpx2
import pytest
from sqlalchemy import text
from sqlmodel import Session, select

from app.create_first_manager import SetupError
from app.db import get_engine
from app.models import Profile, Role
from app.seed_demo_accounts import ensure_demo_account, main
from app.settings import get_settings
from app.supabase_auth import NO_BAN, PLACEHOLDER_DOMAIN, SupabaseAuthAdmin
from tests.test_accounts import SERVICE_KEY, FakeSupabaseAuth

STAFF_PASSWORD = "not-a-real-staff-password"
MANAGER_PASSWORD = "not-a-real-manager-password"
# Not the real demo usernames, so seeding the demo on this database doesn't clash with these tests.
TEST_STAFF_USERNAME = "seed.test.staff"
TEST_MANAGER_USERNAME = "seed.test.manager"


@pytest.fixture
def auth() -> FakeSupabaseAuth:
    return FakeSupabaseAuth()


def admin(auth: FakeSupabaseAuth) -> SupabaseAuthAdmin:
    return SupabaseAuthAdmin(
        "http://localhost:54321", SERVICE_KEY, httpx2.MockTransport(auth.handler)
    )


def seed(
    session: Session, auth: FakeSupabaseAuth, role: Role = Role.STAFF, password: str = "password-1"
) -> str:
    return ensure_demo_account(session, admin(auth), "demo.staff", "Demo Staff", role, password)


def test_creates_an_account_with_a_hidden_address_and_no_password_change(
    session: Session, auth: FakeSupabaseAuth
) -> None:
    assert "Created" in seed(session, auth)
    profile = session.exec(select(Profile)).one()
    assert profile.email is None
    assert not profile.must_change_password
    assert auth.users[profile.auth_user_id]["email"] == f"demo.staff@{PLACEHOLDER_DOMAIN}"


def test_running_again_restores_the_password_and_turns_the_account_back_on(
    session: Session, auth: FakeSupabaseAuth
) -> None:
    seed(session, auth)
    profile = session.exec(select(Profile)).one()
    profile.is_active = False
    profile.must_change_password = True
    session.add(profile)
    session.commit()

    assert "Restored" in seed(session, auth, password="password-2")

    session.refresh(profile)
    assert profile.is_active
    assert not profile.must_change_password
    assert auth.users[profile.auth_user_id]["password"] == "password-2"
    assert json.loads(auth.requests[-1].content)["ban_duration"] == NO_BAN
    assert len(session.exec(select(Profile)).all()) == 1


def test_finishes_a_run_that_stopped_before_the_profile(
    session: Session, auth: FakeSupabaseAuth
) -> None:
    user_id = auth.add(f"demo.staff@{PLACEHOLDER_DOMAIN}", "old password")
    seed(session, auth)
    profile = session.exec(select(Profile)).one()
    assert profile.auth_user_id == user_id
    assert auth.users[user_id]["password"] == "password-1"


def test_leaves_a_profile_with_another_role_alone(session: Session, auth: FakeSupabaseAuth) -> None:
    seed(session, auth)
    profile = session.exec(select(Profile)).one()
    before = auth.users[profile.auth_user_id]["password"]
    with pytest.raises(SetupError, match="nothing was changed"):
        seed(session, auth, role=Role.MANAGER, password="password-2")
    assert auth.users[profile.auth_user_id]["password"] == before


@pytest.fixture
def demo_env(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DATABASE_URL", get_settings().database_url)
    monkeypatch.setenv("SUPABASE_URL", "http://localhost:54321")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", SERVICE_KEY)
    monkeypatch.setenv("DEMO_STAFF_PASSWORD", STAFF_PASSWORD)
    monkeypatch.setenv("DEMO_MANAGER_PASSWORD", MANAGER_PASSWORD)
    monkeypatch.setenv("DEMO_STAFF_USERNAME", TEST_STAFF_USERNAME)
    monkeypatch.setenv("DEMO_MANAGER_USERNAME", TEST_MANAGER_USERNAME)
    yield monkeypatch
    with get_engine().begin() as connection:
        connection.execute(text("DELETE FROM profiles WHERE username LIKE 'seed.test.%'"))


def test_main_creates_both_accounts_from_the_environment_and_prints_no_secrets(
    demo_env: pytest.MonkeyPatch, auth: FakeSupabaseAuth, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(httpx2.MockTransport(auth.handler)) == 0
    with Session(get_engine()) as session:
        people = {
            profile.username: profile
            for profile in session.exec(
                select(Profile).where(Profile.username.startswith("seed.test."))  # pyright: ignore[reportAttributeAccessIssue]
            )
        }
    assert people[TEST_STAFF_USERNAME].role == Role.STAFF
    assert people[TEST_MANAGER_USERNAME].role == Role.MANAGER
    passwords = {user["password"] for user in auth.users.values()}
    assert passwords == {STAFF_PASSWORD, MANAGER_PASSWORD}
    assert isinstance(people[TEST_STAFF_USERNAME].auth_user_id, UUID)

    output = capsys.readouterr()
    assert "Warning" not in output.err
    for secret in (STAFF_PASSWORD, MANAGER_PASSWORD, SERVICE_KEY):
        assert secret not in output.out + output.err


def test_main_warns_when_sign_ups_are_on(
    demo_env: pytest.MonkeyPatch, auth: FakeSupabaseAuth, capsys: pytest.CaptureFixture[str]
) -> None:
    auth.sign_ups_on = True
    assert main(httpx2.MockTransport(auth.handler)) == 0
    assert "public sign-up is on" in capsys.readouterr().err


def test_main_needs_both_passwords_and_says_which(
    demo_env: pytest.MonkeyPatch, auth: FakeSupabaseAuth, capsys: pytest.CaptureFixture[str]
) -> None:
    demo_env.delenv("DEMO_MANAGER_PASSWORD")
    demo_env.setenv("DEMO_MANAGER_PASSWORD", "")
    assert main(httpx2.MockTransport(auth.handler)) == 1
    assert "DEMO_MANAGER_PASSWORD" in capsys.readouterr().err
    assert auth.users == {}


def test_main_refuses_a_hosted_auth_server_with_a_local_database(
    demo_env: pytest.MonkeyPatch, auth: FakeSupabaseAuth, capsys: pytest.CaptureFixture[str]
) -> None:
    demo_env.setenv("SUPABASE_URL", "https://abc.supabase.co")
    assert main(httpx2.MockTransport(auth.handler)) == 1
    assert "different environments" in capsys.readouterr().err
    assert auth.requests == []
