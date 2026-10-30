from collections.abc import Callable
from uuid import UUID, uuid4

import httpx2
import pytest
from sqlalchemy import text
from sqlmodel import Session, select

from app.create_first_manager import (
    SetupError,
    SupabaseAuthAdmin,
    check_same_environment,
    ensure_first_manager,
    main,
)
from app.db import get_engine
from app.models import Profile, Role
from app.settings import get_settings

USERNAME = "test-manager"
EMAIL = "test-manager@example.com"
PASSWORD = "not-a-real-password"
SERVICE_KEY = "not-a-real-service-key"


class FakeAuth:
    """Stands in for the Supabase Auth admin API, so tests never reach a real project."""

    def __init__(self) -> None:
        self.users: list[dict] = []
        self.created = 0

    def add_user(self, email: str, confirmed: bool = True) -> str:
        user_id = str(uuid4())
        confirmed_at = "2026-10-30T00:00:00Z" if confirmed else None
        self.users.append({"id": user_id, "email": email, "email_confirmed_at": confirmed_at})
        return user_id

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        assert request.headers["apikey"] == SERVICE_KEY
        assert request.url.path == "/auth/v1/admin/users"
        if request.method == "GET":
            page = int(request.url.params["page"])
            per_page = int(request.url.params["per_page"])
            start = (page - 1) * per_page
            return httpx2.Response(200, json={"users": self.users[start : start + per_page]})
        self.created += 1
        user_id = self.add_user(EMAIL)
        return httpx2.Response(200, json={"id": user_id, "email": EMAIL})

    def client(self) -> SupabaseAuthAdmin:
        return SupabaseAuthAdmin(
            "http://localhost:54321", SERVICE_KEY, httpx2.MockTransport(self.handler)
        )


@pytest.fixture
def auth() -> FakeAuth:
    return FakeAuth()


def run(session: Session, auth: FakeAuth, password: str | None = PASSWORD) -> str:
    return ensure_first_manager(session, auth.client(), USERNAME, EMAIL, password)


def test_creates_the_auth_user_and_a_manager_profile(session: Session, auth: FakeAuth) -> None:
    message = run(session, auth)

    profile = session.exec(select(Profile).where(Profile.username == USERNAME)).one()
    assert profile.role == Role.MANAGER
    assert profile.email == EMAIL
    assert profile.is_active
    assert profile.display_name == USERNAME
    assert profile.auth_user_id == UUID(auth.users[0]["id"])
    assert auth.created == 1
    assert "Created" in message


def test_running_again_changes_nothing(session: Session, auth: FakeAuth) -> None:
    run(session, auth)
    message = run(session, auth, password=None)

    assert "nothing was changed" in message
    assert auth.created == 1
    assert len(session.exec(select(Profile)).all()) == 1


def test_finishes_a_run_that_stopped_before_the_profile(session: Session, auth: FakeAuth) -> None:
    user_id = auth.add_user(EMAIL)

    message = run(session, auth, password=None)

    assert auth.created == 0
    assert "Kept the existing Auth user" in message
    assert session.exec(select(Profile)).one().auth_user_id == UUID(user_id)


def test_finds_an_auth_user_past_the_first_page(session: Session, auth: FakeAuth) -> None:
    for number in range(200):
        auth.add_user(f"someone{number}@example.com")
    user_id = auth.add_user(EMAIL)

    run(session, auth)

    assert auth.created == 0
    assert session.exec(select(Profile)).one().auth_user_id == UUID(user_id)


def test_refuses_to_promote_an_unconfirmed_auth_user(session: Session, auth: FakeAuth) -> None:
    auth.add_user(EMAIL, confirmed=False)

    with pytest.raises(SetupError, match="unconfirmed"):
        run(session, auth)

    assert session.exec(select(Profile)).all() == []


@pytest.mark.parametrize(
    ("username", "email", "role"),
    [
        (USERNAME, "someone-else@example.com", Role.MANAGER),
        ("someone-else", EMAIL, Role.MANAGER),
        (USERNAME, EMAIL, Role.STAFF),
    ],
)
def test_leaves_a_conflicting_profile_alone(
    session: Session, auth: FakeAuth, username: str, email: str, role: Role
) -> None:
    session.add(
        Profile(
            auth_user_id=uuid4(),
            username=username,
            display_name=username,
            email=email,
            role=role,
        )
    )
    session.commit()

    with pytest.raises(SetupError, match="nothing was changed"):
        run(session, auth)

    assert auth.created == 0
    assert session.exec(select(Profile)).one().role == role


def test_needs_a_password_only_to_create_a_user(session: Session, auth: FakeAuth) -> None:
    with pytest.raises(SetupError, match="FIRST_MANAGER_PASSWORD"):
        run(session, auth, password=None)
    assert auth.created == 0


def test_refuses_a_bad_username(session: Session, auth: FakeAuth) -> None:
    with pytest.raises(SetupError, match="FIRST_MANAGER_USERNAME"):
        ensure_first_manager(session, auth.client(), "Not Valid", EMAIL, PASSWORD)
    assert auth.users == []


@pytest.mark.parametrize(
    ("database_host", "auth_url"),
    [("localhost", "https://abc.supabase.co"), ("db.abc.supabase.co", "http://localhost:54321")],
)
def test_refuses_mixed_environments(database_host: str, auth_url: str) -> None:
    with pytest.raises(SetupError, match="different environments"):
        check_same_environment(f"postgresql+psycopg://u:p@{database_host}:5432/x", auth_url)


@pytest.fixture
def manager_env(monkeypatch: pytest.MonkeyPatch) -> Callable[[], None]:
    def clean_up() -> None:
        with get_engine().begin() as connection:
            connection.execute(
                text("DELETE FROM profiles WHERE username = :name"), {"name": USERNAME}
            )

    monkeypatch.setenv("DATABASE_URL", get_settings().database_url)
    monkeypatch.setenv("SUPABASE_URL", "http://localhost:54321")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", SERVICE_KEY)
    monkeypatch.setenv("FIRST_MANAGER_USERNAME", USERNAME)
    monkeypatch.setenv("FIRST_MANAGER_EMAIL", EMAIL)
    monkeypatch.setenv("FIRST_MANAGER_PASSWORD", PASSWORD)
    return clean_up


def test_main_reads_the_environment_and_prints_no_secrets(
    manager_env: Callable[[], None], auth: FakeAuth, capsys: pytest.CaptureFixture[str]
) -> None:
    try:
        assert main(httpx2.MockTransport(auth.handler)) == 0
        assert main(httpx2.MockTransport(auth.handler)) == 0
    finally:
        manager_env()

    output = capsys.readouterr()
    assert auth.created == 1
    assert "already exists" in output.out
    for secret in (PASSWORD, SERVICE_KEY):
        assert secret not in output.out + output.err


def test_main_reports_an_auth_error_without_secrets(
    manager_env: Callable[[], None], capsys: pytest.CaptureFixture[str]
) -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        if request.method == "GET":
            return httpx2.Response(200, json={"users": []})
        return httpx2.Response(422, json={"error_code": "weak_password", "msg": PASSWORD})

    try:
        assert main(httpx2.MockTransport(refuse)) == 1
    finally:
        manager_env()

    output = capsys.readouterr()
    assert "status 422" in output.err
    assert PASSWORD not in output.out + output.err
