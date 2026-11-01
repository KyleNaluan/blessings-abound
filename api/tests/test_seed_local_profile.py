from uuid import uuid4

import pytest
from sqlmodel import Session, delete

from app import seed_local_profile
from app.db import get_engine
from app.models import Profile, Role
from app.settings import Settings


def test_it_refuses_a_hosted_database(monkeypatch: pytest.MonkeyPatch) -> None:
    hosted = Settings(database_url="postgresql+psycopg://user:secret@db.example.supabase.co/db")
    monkeypatch.setattr(seed_local_profile, "get_settings", lambda: hosted)
    assert seed_local_profile.main([str(uuid4()), "person"]) == 1


def test_it_needs_an_id_and_a_username() -> None:
    assert seed_local_profile.main([]) == 1


def test_it_creates_the_profile_and_is_safe_to_run_again() -> None:
    auth_user_id = uuid4()
    username = f"seed-{auth_user_id.hex}"
    try:
        for _ in range(2):
            assert seed_local_profile.main([str(auth_user_id), username, "manager"]) == 0
        with Session(get_engine()) as session:
            profile = session.get(Profile, auth_user_id)
            assert profile is not None
            assert (profile.username, profile.role) == (username, Role.MANAGER)
    finally:
        with Session(get_engine()) as session:
            session.exec(delete(Profile).where(Profile.auth_user_id == auth_user_id))  # type: ignore[arg-type]
            session.commit()
