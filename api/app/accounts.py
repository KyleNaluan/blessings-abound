"""Signing in with a username, who the caller is, and leaving a temporary password behind."""

import hashlib
from datetime import datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

import httpx2
import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict
from sqlmodel import Session, col, delete, select

from app.auth import SignedInProfile, bearer
from app.db import get_session
from app.models import AccountStatus, Profile, Role, SignInAttempt
from app.supabase_auth import NO_SUCH_ACCOUNT_EMAIL, SupabaseAuthAdmin, error_code, get_auth_admin

router = APIRouter()

SessionDep = Annotated[Session, Depends(get_session)]
AuthAdminDep = Annotated[SupabaseAuthAdmin, Depends(get_auth_admin)]

COULD_NOT_SIGN_IN = "We couldn't sign in. Check your details or ask your manager."
TOO_MANY_TRIES = "Too many tries. Wait a few minutes and try again."
UNREACHABLE = "We couldn't reach the sign-in service. Try again in a minute."
MAX_SIGN_IN_FAILURES = 10
SIGN_IN_WINDOW_SECONDS = 300
MIN_PASSWORD_LENGTH = 10
# Supabase Auth ignores anything past 72 bytes, so a longer password would be quietly cut short.
MAX_PASSWORD_BYTES = 72


def _username_hash(username: str) -> str:
    return hashlib.sha256(username.encode()).hexdigest()


def _attempts_expire_at() -> Any:
    return sa.func.now() - timedelta(seconds=SIGN_IN_WINDOW_SECONDS)


def _start_sign_in_attempt(session: Session, username: str) -> UUID | None:
    """Count this attempt, or return None when the username has used up its tries.

    Supabase Auth limits sign-ins by address, but here every attempt comes from the API's address,
    so it can't tell one person guessing from everyone signing in. The attempt is counted before
    Auth is asked, and the lock lasts until the commit, so requests arriving together at any number
    of API processes can't get past the limit.
    """
    username_hash = _username_hash(username)
    session.exec(
        select(sa.func.pg_advisory_xact_lock(sa.func.hashtextextended(username_hash, 0)))
    ).one()
    failures = session.exec(
        select(sa.func.count())
        .select_from(SignInAttempt)
        .where(
            SignInAttempt.username_hash == username_hash,
            col(SignInAttempt.attempted_at) > _attempts_expire_at(),
        )
    ).one()
    if failures >= MAX_SIGN_IN_FAILURES:
        session.commit()
        return None
    attempt = SignInAttempt(username_hash=username_hash)
    attempt_id = attempt.id
    session.add(attempt)
    # Clearing expired rows here keeps guessing at random usernames from growing the table.
    # SKIP LOCKED stops two requests clearing the same rows from deadlocking.
    expired = (
        select(SignInAttempt.id)
        .where(col(SignInAttempt.attempted_at) <= _attempts_expire_at())
        .with_for_update(skip_locked=True)
    )
    session.exec(delete(SignInAttempt).where(col(SignInAttempt.id).in_(expired)))
    session.commit()
    return attempt_id


def _forget_sign_in_attempt(session: Session, attempt_id: UUID) -> None:
    """For when Auth gave no answer about the password, which shouldn't use up a try."""
    session.exec(delete(SignInAttempt).where(col(SignInAttempt.id) == attempt_id))
    session.commit()


def _clear_sign_in_attempts(session: Session, username: str) -> None:
    username_hash = _username_hash(username)
    session.exec(delete(SignInAttempt).where(col(SignInAttempt.username_hash) == username_hash))
    session.commit()


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


def _sign_in_address(session: Session, auth: SupabaseAuthAdmin, username: str) -> str:
    """The address Auth knows this username by.

    Auth is asked rather than the profile, because a profile from the setup scripts may have no
    email while its Auth user has one, and the address must never reach the browser. A turned-off
    account gets the address nobody can have, so its answer is the same as a wrong password's,
    whether or not the password is right.
    """
    profile = session.exec(select(Profile).where(Profile.username == username)).first()
    if profile is None or not profile.is_active:
        return NO_SUCH_ACCOUNT_EMAIL
    user = auth.get_user(profile.auth_user_id)
    if user is None or not user.get("email"):
        return NO_SUCH_ACCOUNT_EMAIL
    return user["email"]


@router.post(
    "/auth/sign-in",
    operation_id="sign_in_with_username",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "The sign-in was refused"},
        status.HTTP_429_TOO_MANY_REQUESTS: {"description": "Too many wrong passwords"},
    },
)
def sign_in_with_username(
    request: SignInRequest, response: Response, session: SessionDep, auth: AuthAdminDep
) -> SignInSession:
    """Sign in by username here, because telling the browser the address would expose it.

    An address in the sign-in box goes from the browser straight to Supabase Auth instead.
    """
    attempt_id = _start_sign_in_attempt(session, request.username)
    if attempt_id is None:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, TOO_MANY_TRIES)
    try:
        email = _sign_in_address(session, auth, request.username)
        tokens = auth.sign_in(email, request.password)
    except httpx2.HTTPStatusError as error:
        # A ban left by a deactivation that stopped halfway is a 400 too, and answers the same.
        if error.response.status_code in (status.HTTP_400_BAD_REQUEST, 422):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, COULD_NOT_SIGN_IN) from error
        _forget_sign_in_attempt(session, attempt_id)
        if error.response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, TOO_MANY_TRIES) from error
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, UNREACHABLE) from error
    except httpx2.TransportError as error:
        _forget_sign_in_attempt(session, attempt_id)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, UNREACHABLE) from error
    _clear_sign_in_attempts(session, request.username)
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
