"""Signing in with a username, who the caller is, and leaving a temporary password behind."""

import threading
import time
from datetime import datetime
from functools import lru_cache
from typing import Annotated
from uuid import UUID

import httpx2
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict
from sqlmodel import Session, select

from app.auth import SignedInProfile, bearer
from app.db import get_session
from app.models import AccountStatus, Profile, Role
from app.supabase_auth import NO_SUCH_ACCOUNT_EMAIL, SupabaseAuthAdmin, error_code, get_auth_admin

router = APIRouter()

SessionDep = Annotated[Session, Depends(get_session)]
AuthAdminDep = Annotated[SupabaseAuthAdmin, Depends(get_auth_admin)]

WRONG_DETAILS = "Your username, email or password is wrong"
TURNED_OFF = "This account is turned off. Ask a store manager to turn it back on."
TOO_MANY_TRIES = "Too many tries. Wait a few minutes and try again."
UNREACHABLE = "We couldn't reach the sign-in service. Try again in a minute."
MIN_PASSWORD_LENGTH = 10
# Supabase Auth ignores anything past 72 bytes, so a longer password would be quietly cut short.
MAX_PASSWORD_BYTES = 72


class SignInThrottle:
    """Counts wrong passwords for each username.

    Supabase Auth limits sign-ins by address, but here every attempt comes from the API's address,
    so it can't tell one person guessing from everyone signing in. Counts are per process.
    """

    MAX_FAILURES = 10
    WINDOW_SECONDS = 300
    # Guessing at random usernames can't grow this without limit.
    MAX_TRACKED = 10_000

    def __init__(self) -> None:
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def is_blocked(self, username: str) -> bool:
        cutoff = time.monotonic() - self.WINDOW_SECONDS
        with self._lock:
            recent = [at for at in self._failures.get(username, []) if at > cutoff]
            if recent:
                self._failures[username] = recent
            else:
                self._failures.pop(username, None)
            return len(recent) >= self.MAX_FAILURES

    def record_failure(self, username: str) -> None:
        with self._lock:
            if username not in self._failures and len(self._failures) >= self.MAX_TRACKED:
                self._failures.clear()
            self._failures.setdefault(username, []).append(time.monotonic())

    def clear(self, username: str) -> None:
        with self._lock:
            self._failures.pop(username, None)


@lru_cache
def get_sign_in_throttle() -> SignInThrottle:
    return SignInThrottle()


class SignInRequest(BaseModel):
    username: Annotated[str, BeforeValidator(lambda value: str(value).strip().lower())]
    password: str


class SignInSession(BaseModel):
    """The Supabase Auth tokens, which the web app hands to its Supabase client."""

    access_token: str
    refresh_token: str


class PersonRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    auth_user_id: UUID
    username: str
    display_name: str
    email: str | None
    role: Role
    status: AccountStatus
    created_at: datetime


def _check_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Your password must be at least {MIN_PASSWORD_LENGTH} characters")
    if len(password.encode()) > MAX_PASSWORD_BYTES:
        raise ValueError(f"Your password must be {MAX_PASSWORD_BYTES} characters or fewer")
    return password


class ChoosePasswordRequest(BaseModel):
    password: Annotated[str, AfterValidator(_check_password)]


def _sign_in_address(session: Session, auth: SupabaseAuthAdmin, username: str) -> tuple[str, bool]:
    """The address Auth knows this username by, and whether the profile may sign in.

    Auth is asked rather than the profile, because a profile from the setup scripts may have no
    email while its Auth user has one, and the address must never reach the browser.
    """
    profile = session.exec(select(Profile).where(Profile.username == username)).first()
    if profile is None:
        return NO_SUCH_ACCOUNT_EMAIL, False
    user = auth.get_user(profile.auth_user_id)
    if user is None or not user.get("email"):
        return NO_SUCH_ACCOUNT_EMAIL, False
    return user["email"], profile.is_active


@router.post(
    "/auth/sign-in",
    operation_id="sign_in_with_username",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "The username or password is wrong"},
        status.HTTP_403_FORBIDDEN: {"description": "The account is deactivated"},
        status.HTTP_429_TOO_MANY_REQUESTS: {"description": "Too many wrong passwords"},
    },
)
def sign_in_with_username(
    request: SignInRequest,
    response: Response,
    session: SessionDep,
    auth: AuthAdminDep,
    throttle: Annotated[SignInThrottle, Depends(get_sign_in_throttle)],
) -> SignInSession:
    """Sign in by username here, because telling the browser the address would expose it.

    An address in the sign-in box goes from the browser straight to Supabase Auth instead.
    """
    if throttle.is_blocked(request.username):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, TOO_MANY_TRIES)
    try:
        email, may_sign_in = _sign_in_address(session, auth, request.username)
        tokens = auth.sign_in(email, request.password)
    except httpx2.HTTPStatusError as error:
        code = error_code(error)
        if code == "user_banned":
            raise HTTPException(status.HTTP_403_FORBIDDEN, TURNED_OFF) from error
        if error.response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, TOO_MANY_TRIES) from error
        if error.response.status_code in (status.HTTP_400_BAD_REQUEST, 422):
            throttle.record_failure(request.username)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, WRONG_DETAILS) from error
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, UNREACHABLE) from error
    except httpx2.TransportError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, UNREACHABLE) from error
    throttle.clear(request.username)
    if not may_sign_in:
        raise HTTPException(status.HTTP_403_FORBIDDEN, TURNED_OFF)
    response.headers["Cache-Control"] = "no-store"
    return SignInSession(access_token=tokens["access_token"], refresh_token=tokens["refresh_token"])


@router.get("/me", operation_id="get_me")
def get_me(profile: SignedInProfile) -> PersonRead:
    """Who is signed in. Someone who still has to choose a password can read this too."""
    return PersonRead.model_validate(profile)


@router.post("/me/password", operation_id="choose_my_password")
def choose_my_password(
    request: ChoosePasswordRequest,
    profile: SignedInProfile,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer)],
    session: SessionDep,
    auth: AuthAdminDep,
) -> PersonRead:
    """Set the person's own password and lift the block a temporary password or invite puts on.

    The block lives here rather than in anything the browser can write, so it can't be skipped.
    """
    try:
        auth.change_own_password(credentials.credentials, request.password)
    except httpx2.HTTPStatusError as error:
        code = error_code(error)
        if code == "same_password":
            detail = "Choose a password that is different from your current one"
        elif code == "weak_password":
            detail = "Choose a stronger password, such as a few words in a row"
        else:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, UNREACHABLE) from error
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail) from error
    except httpx2.TransportError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, UNREACHABLE) from error
    profile.must_change_password = False
    profile.invited_at = None
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return PersonRead.model_validate(profile)
