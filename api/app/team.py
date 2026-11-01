"""What managers do to accounts. Every route here needs a signed-in manager."""

import re
import secrets
import string
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

import httpx2
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import AfterValidator, BaseModel, BeforeValidator, StringConstraints
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.accounts import PersonRead
from app.auth import ManagerProfile
from app.db import get_session
from app.models import Profile, Role
from app.settings import get_settings
from app.supabase_auth import (
    BAN_DURATION,
    NO_BAN,
    PLACEHOLDER_DOMAIN,
    SupabaseAuthAdmin,
    error_code,
    get_auth_admin,
    placeholder_email,
)

router = APIRouter(prefix="/team")

SessionDep = Annotated[Session, Depends(get_session)]
AuthAdminDep = Annotated[SupabaseAuthAdmin, Depends(get_auth_admin)]

USERNAME_RULES = (
    "A username needs lowercase letters or digits at both ends, may also use '.', '_' and '-' "
    "between them, and can't have two dots in a row."
)
# Stricter than the database's pattern, because the username also becomes the start of an address.
_USERNAME = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?")
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_TEMPORARY_PASSWORD_LETTERS = "".join(
    letter for letter in string.ascii_letters + string.digits if letter not in "0O1lI"
)
ACCOUNT_TAKEN = "That username or email already has an account."
UNREACHABLE = "We couldn't reach the sign-in service. Try again in a minute."


def _check_username(username: str) -> str:
    if not _USERNAME.fullmatch(username) or ".." in username:
        raise ValueError(USERNAME_RULES)
    return username


def _check_email(email: str) -> str:
    if not _EMAIL.fullmatch(email) or email.endswith(f"@{PLACEHOLDER_DOMAIN}"):
        raise ValueError("That doesn't look like an email address.")
    return email


def _clean_text(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


def _clean_lowercase(value: Any) -> Any:
    return value.strip().lower() if isinstance(value, str) else value


Username = Annotated[str, BeforeValidator(_clean_lowercase), AfterValidator(_check_username)]
Email = Annotated[str, BeforeValidator(_clean_lowercase), AfterValidator(_check_email)]
DisplayName = Annotated[
    str, BeforeValidator(_clean_text), StringConstraints(min_length=1, max_length=200)
]


class InviteRequest(BaseModel):
    username: Username
    display_name: DisplayName
    email: Email
    role: Role = Role.STAFF


class CreateWithTemporaryPasswordRequest(BaseModel):
    username: Username
    display_name: DisplayName
    email: Email | None = None
    role: Role = Role.STAFF


class ChangeRoleRequest(BaseModel):
    role: Role


class PersonWithTemporaryPassword(BaseModel):
    """The only time the temporary password is shown, because it is stored nowhere."""

    person: PersonRead
    temporary_password: str


def _new_temporary_password() -> str:
    """Four groups of four, with look-alike characters left out so it can be read out loud."""
    while True:
        password = "-".join(
            "".join(secrets.choice(_TEMPORARY_PASSWORD_LETTERS) for _ in range(4)) for _ in range(4)
        )
        checks: tuple[Any, ...] = (str.islower, str.isupper, str.isdigit)
        if all(any(check(letter) for letter in password) for check in checks):
            return password


def _auth_failure(error: httpx2.HTTPError) -> HTTPException:
    if isinstance(error, httpx2.HTTPStatusError):
        code = error_code(error)
        if code in ("email_exists", "user_already_exists", "phone_exists"):
            return HTTPException(status.HTTP_409_CONFLICT, ACCOUNT_TAKEN)
        if code == "over_email_send_rate_limit" or error.response.status_code == 429:
            return HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Too many emails were sent. Try again in an hour, or create a username with a "
                "temporary password instead.",
            )
        if code in ("email_address_invalid", "email_address_not_authorized"):
            return HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "We couldn't send an email to that address. Create a username with a temporary "
                "password instead.",
            )
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, UNREACHABLE)


def _refuse_if_taken(session: Session, username: str, email: str | None) -> None:
    query = select(Profile).where(Profile.username == username)
    if email is not None:
        query = select(Profile).where((Profile.username == username) | (Profile.email == email))
    if session.exec(query).first() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, ACCOUNT_TAKEN)


def _save_new_person(session: Session, auth: SupabaseAuthAdmin, profile: Profile) -> PersonRead:
    """Save the profile, and take the new Auth user back out if that fails."""
    session.add(profile)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        auth.delete_user(profile.auth_user_id)
        raise HTTPException(status.HTTP_409_CONFLICT, ACCOUNT_TAKEN) from error
    session.refresh(profile)
    return PersonRead.model_validate(profile)


def _get_person(session: Session, auth_user_id: UUID) -> Profile:
    profile = session.get(Profile, auth_user_id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That person doesn't exist.")
    return profile


def _refuse_removing_last_manager(session: Session, target: Profile) -> None:
    """Holds the active managers' rows until commit, so two requests can't each remove one."""
    active_managers = session.exec(
        select(Profile)
        .where(Profile.role == Role.MANAGER, col(Profile.is_active))
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    session.refresh(target)
    if target.is_active and target.role == Role.MANAGER and len(active_managers) <= 1:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This is the last active manager, so it has to stay."
        )


@router.get("/people", operation_id="list_people")
def list_people(_: ManagerProfile, session: SessionDep) -> list[PersonRead]:
    people = session.exec(select(Profile).order_by(col(Profile.username))).all()
    return [PersonRead.model_validate(person) for person in people]


@router.post("/people/invite", operation_id="invite_person", status_code=status.HTTP_201_CREATED)
def invite_person(
    request: InviteRequest, _: ManagerProfile, session: SessionDep, auth: AuthAdminDep
) -> PersonRead:
    """Email a link that signs the person in once to choose a password."""
    _refuse_if_taken(session, request.username, request.email)
    redirect_to = f"{get_settings().web_app_url.rstrip('/')}/choose-password"
    try:
        user = auth.invite_user(request.email, redirect_to)
    except httpx2.HTTPError as error:
        raise _auth_failure(error) from error
    return _save_new_person(
        session,
        auth,
        Profile(
            auth_user_id=UUID(user["id"]),
            username=request.username,
            display_name=request.display_name,
            email=request.email,
            role=request.role,
            must_change_password=True,
            invited_at=datetime.now(UTC),
        ),
    )


@router.post(
    "/people/temporary-password",
    operation_id="create_person_with_temporary_password",
    status_code=status.HTTP_201_CREATED,
)
def create_person_with_temporary_password(
    request: CreateWithTemporaryPasswordRequest,
    response: Response,
    _: ManagerProfile,
    session: SessionDep,
    auth: AuthAdminDep,
) -> PersonWithTemporaryPassword:
    """Create a username whose temporary password must be changed at first sign-in."""
    _refuse_if_taken(session, request.username, request.email)
    password = _new_temporary_password()
    try:
        user = auth.create_user(request.email or placeholder_email(request.username), password)
    except httpx2.HTTPError as error:
        raise _auth_failure(error) from error
    person = _save_new_person(
        session,
        auth,
        Profile(
            auth_user_id=UUID(user["id"]),
            username=request.username,
            display_name=request.display_name,
            email=request.email,
            role=request.role,
            must_change_password=True,
        ),
    )
    response.headers["Cache-Control"] = "no-store"
    return PersonWithTemporaryPassword(person=person, temporary_password=password)


@router.post("/people/{auth_user_id}/temporary-password", operation_id="issue_temporary_password")
def issue_temporary_password(
    auth_user_id: UUID,
    response: Response,
    _: ManagerProfile,
    session: SessionDep,
    auth: AuthAdminDep,
) -> PersonWithTemporaryPassword:
    """Replace the person's password, which is how someone with no email gets back in."""
    person = _get_person(session, auth_user_id)
    if not person.is_active:
        raise HTTPException(status.HTTP_409_CONFLICT, "Reactivate this person first.")
    password = _new_temporary_password()
    try:
        # Confirmed too, because someone who never opened their invite couldn't sign in otherwise.
        auth.update_user(auth_user_id, password=password, email_confirm=True)
    except httpx2.HTTPError as error:
        raise _auth_failure(error) from error
    person.must_change_password = True
    person.invited_at = None
    session.add(person)
    session.commit()
    session.refresh(person)
    response.headers["Cache-Control"] = "no-store"
    return PersonWithTemporaryPassword(
        person=PersonRead.model_validate(person), temporary_password=password
    )


@router.patch("/people/{auth_user_id}", operation_id="change_role")
def change_role(
    auth_user_id: UUID, request: ChangeRoleRequest, _: ManagerProfile, session: SessionDep
) -> PersonRead:
    person = _get_person(session, auth_user_id)
    if request.role != Role.MANAGER:
        _refuse_removing_last_manager(session, person)
    person.role = request.role
    session.add(person)
    session.commit()
    session.refresh(person)
    return PersonRead.model_validate(person)


@router.post("/people/{auth_user_id}/deactivate", operation_id="deactivate_person")
def deactivate_person(
    auth_user_id: UUID, manager: ManagerProfile, session: SessionDep, auth: AuthAdminDep
) -> PersonRead:
    """Stop the person signing in. The row stays, so their past decisions stay too."""
    if auth_user_id == manager.auth_user_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "You can't deactivate yourself.")
    person = _get_person(session, auth_user_id)
    _refuse_removing_last_manager(session, person)
    try:
        # Auth first, so a failure here leaves the person as they were.
        auth.update_user(auth_user_id, ban_duration=BAN_DURATION)
    except httpx2.HTTPError as error:
        raise _auth_failure(error) from error
    person.is_active = False
    session.add(person)
    session.commit()
    session.refresh(person)
    return PersonRead.model_validate(person)


@router.post("/people/{auth_user_id}/reactivate", operation_id="reactivate_person")
def reactivate_person(
    auth_user_id: UUID, _: ManagerProfile, session: SessionDep, auth: AuthAdminDep
) -> PersonRead:
    person = _get_person(session, auth_user_id)
    try:
        auth.update_user(auth_user_id, ban_duration=NO_BAN)
    except httpx2.HTTPError as error:
        raise _auth_failure(error) from error
    person.is_active = True
    session.add(person)
    session.commit()
    session.refresh(person)
    return PersonRead.model_validate(person)
