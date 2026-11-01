"""Who is calling the API: checks the Supabase Auth token and finds the person's profile."""

from functools import lru_cache
from typing import Annotated, Protocol
from uuid import UUID

import httpx2
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session

from app.db import get_session
from app.models import Profile
from app.settings import get_settings

# Supabase Auth answers these for a token that is expired, malformed or for a deleted user.
_REJECTED_TOKEN_STATUSES = {
    status.HTTP_400_BAD_REQUEST,
    status.HTTP_401_UNAUTHORIZED,
    status.HTTP_403_FORBIDDEN,
    status.HTTP_404_NOT_FOUND,
}


class AuthUnavailableError(Exception):
    """The token could not be checked, which says nothing about whether it is good."""


class TokenVerifier(Protocol):
    def user_id(self, token: str) -> UUID | None:
        """The Auth user id the token belongs to, or None when the token is not valid."""
        ...


class SupabaseTokenVerifier:
    """Asks Supabase Auth about each token, so a banned or deleted user stops working at once."""

    def __init__(
        self, url: str, api_key: str, transport: httpx2.BaseTransport | None = None
    ) -> None:
        self.client = httpx2.Client(
            base_url=f"{url.rstrip('/')}/auth/v1",
            headers={"apikey": api_key},
            transport=transport,
            timeout=10.0,
        )

    def user_id(self, token: str) -> UUID | None:
        try:
            response = self.client.get("/user", headers={"Authorization": f"Bearer {token}"})
        except httpx2.TransportError as error:
            raise AuthUnavailableError from error
        if response.status_code in _REJECTED_TOKEN_STATUSES:
            return None
        if response.status_code != status.HTTP_200_OK:
            raise AuthUnavailableError
        return UUID(response.json()["id"])


class AuthNotConfiguredVerifier:
    def user_id(self, token: str) -> UUID | None:
        raise AuthUnavailableError


@lru_cache
def get_token_verifier() -> TokenVerifier:
    settings = get_settings()
    # Any of the project's keys identifies the project here, because the token is what gets checked.
    api_key = settings.supabase_anon_key or settings.supabase_service_role_key
    if not (settings.supabase_url and api_key):
        return AuthNotConfiguredVerifier()
    return SupabaseTokenVerifier(settings.supabase_url, api_key)


_bearer = HTTPBearer(auto_error=False)


def get_current_profile(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    verifier: Annotated[TokenVerifier, Depends(get_token_verifier)],
    session: Annotated[Session, Depends(get_session)],
) -> Profile:
    """The active person making this request. Both roles pass, and a route checks any more."""
    not_signed_in = HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "You need to sign in again.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise not_signed_in
    try:
        user_id = verifier.user_id(credentials.credentials)
    except AuthUnavailableError as error:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "The API couldn't check your sign-in."
        ) from error
    if user_id is None:
        raise not_signed_in
    profile = session.get(Profile, user_id)
    if profile is None or not profile.is_active:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "This account has no active Turnstone profile."
        )
    return profile


CurrentProfile = Annotated[Profile, Depends(get_current_profile)]
