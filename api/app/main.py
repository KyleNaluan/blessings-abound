from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from app.accounts import router as accounts_router
from app.appraisal import router as appraisal_router
from app.db import get_session
from app.settings import get_settings
from app.team import router as team_router

app = FastAPI(title="Turnstone API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(appraisal_router)
app.include_router(accounts_router)
app.include_router(team_router)


class HealthStatus(BaseModel):
    status: Literal["ok", "unavailable"]


class ApiHealth(HealthStatus):
    commit: str | None


@app.get("/health", operation_id="get_health")
def health() -> ApiHealth:
    return ApiHealth(status="ok", commit=get_settings().render_git_commit)


@app.get(
    "/health/db",
    operation_id="get_health_db",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthStatus}},
)
def health_db(
    session: Annotated[Session, Depends(get_session)], response: Response
) -> HealthStatus:
    try:
        session.connection().execute(text("SELECT 1"))
    except SQLAlchemyError:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthStatus(status="unavailable")
    return HealthStatus(status="ok")
