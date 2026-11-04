from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from app.accounts import router as accounts_router
from app.appraisal import router as appraisal_router
from app.approval import router as approval_router
from app.channels import get_channels
from app.db import get_session, get_session_factory
from app.listings import router as listings_router
from app.scheduler import SyncScheduler
from app.settings import get_settings
from app.store_settings import router as store_settings_router
from app.team import router as team_router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    channels = get_channels()
    scheduler = None
    if settings.sync_enabled and channels:
        scheduler = SyncScheduler(
            get_session_factory(), channels, settings.sync_job_seconds, settings.sync_poll_seconds
        )
        scheduler.start()
    yield
    if scheduler is not None:
        scheduler.stop()


app = FastAPI(title="Turnstone API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(appraisal_router)
app.include_router(approval_router)
app.include_router(accounts_router)
app.include_router(team_router)
app.include_router(listings_router)
app.include_router(store_settings_router)


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
