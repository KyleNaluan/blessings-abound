from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.accounts import router as accounts_router
from app.appraisal import get_draft_providers
from app.appraisal import router as appraisal_router
from app.approval import router as approval_router
from app.attention import router as attention_router
from app.channels import get_channels
from app.dashboards import router as dashboards_router
from app.db import get_session, get_session_factory
from app.insight import router as insight_router
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
            get_session_factory(),
            channels,
            settings.sync_job_seconds,
            settings.sync_poll_seconds,
            get_draft_providers,
        )
        scheduler.start()
    yield
    if scheduler is not None:
        scheduler.stop()


class ServerErrorResponse:
    """Answer an unhandled error with a 500 that the CORS middleware around it can label.

    Starlette's own 500 comes from outside every middleware, so it reaches the browser without CORS
    headers, and the web app can only say it couldn't reach the API. The error is raised again
    afterwards, so it is still logged and still fails a test.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracked_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracked_send)
        except Exception:
            if not started:
                response = JSONResponse(
                    {"detail": "Something went wrong on the server. Try again."},
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
                await response(scope, receive, send)
            raise


app = FastAPI(title="Turnstone API", version="0.1.0", lifespan=lifespan)

# Added first, so it sits inside the CORS middleware.
app.add_middleware(ServerErrorResponse)
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
app.include_router(attention_router)
app.include_router(dashboards_router)
app.include_router(insight_router)
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
