from collections.abc import Iterator

from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine

from app.db import get_session
from app.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_db_reaches_postgres() -> None:
    response = client.get("/health/db")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_db_reports_unavailable_database() -> None:
    engine = create_engine("postgresql+psycopg://nobody:nothing@127.0.0.1:1/none")

    def unreachable_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = unreachable_session
    try:
        response = client.get("/health/db")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
