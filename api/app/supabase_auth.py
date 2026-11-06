"""Talks to Supabase Auth from the server with the service role key, which never leaves the API."""

from functools import lru_cache
from typing import Any
from uuid import UUID

import httpx2
from fastapi import HTTPException, status

from app.settings import get_settings

AUTH_PAGE_SIZE = 200
# Supabase Auth has no permanent ban, so a deactivated account is banned for about 100 years.
BAN_DURATION = "876000h"
NO_BAN = "none"
# A person with no email gets an address here. `.invalid` is reserved, so it can never be delivered.
PLACEHOLDER_DOMAIN = "accounts.turnstone.invalid"
# Sign-in with an unknown username still asks Supabase Auth, using this address nobody can have,
# so the answer is the same as for a wrong password.
NO_SUCH_ACCOUNT_EMAIL = "no-such-account@unknown.turnstone.invalid"


def placeholder_email(username: str) -> str:
    return f"{username}@{PLACEHOLDER_DOMAIN}"


def error_code(error: httpx2.HTTPStatusError) -> str | None:
    """The reason Supabase Auth gave, such as `invalid_credentials`."""
    try:
        body = error.response.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    for key in ("error_code", "code", "error"):
        if isinstance(body.get(key), str):
            return body[key]
    return None


class SupabaseAuthAdmin:
    def __init__(
        self, url: str, service_role_key: str, transport: httpx2.BaseTransport | None = None
    ) -> None:
        self.client = httpx2.Client(
            base_url=f"{url.rstrip('/')}/auth/v1",
            headers={"Authorization": f"Bearer {service_role_key}", "apikey": service_role_key},
            transport=transport,
            timeout=10.0,
        )

    def find_user(self, email: str) -> dict[str, Any] | None:
        page = 1
        while True:
            response = self.client.get(
                "/admin/users", params={"page": page, "per_page": AUTH_PAGE_SIZE}
            )
            response.raise_for_status()
            users = response.json()["users"]
            for user in users:
                if (user.get("email") or "").lower() == email:
                    return user
            if len(users) < AUTH_PAGE_SIZE:
                return None
            page += 1

    def get_user(self, user_id: UUID) -> dict[str, Any] | None:
        response = self.client.get(f"/admin/users/{user_id}")
        if response.status_code == status.HTTP_404_NOT_FOUND:
            return None
        response.raise_for_status()
        return response.json()

    def create_user(self, email: str, password: str) -> dict[str, Any]:
        """A user with a confirmed address, who can sign in straight away."""
        response = self.client.post(
            "/admin/users", json={"email": email, "password": password, "email_confirm": True}
        )
        response.raise_for_status()
        return response.json()

    def invite_user(self, email: str, redirect_to: str) -> dict[str, Any]:
        """Emails a link that signs the person in once, works with public sign-up turned off."""
        response = self.client.post(
            "/invite", params={"redirect_to": redirect_to}, json={"email": email}
        )
        response.raise_for_status()
        return response.json()

    def update_user(self, user_id: UUID, **attributes: Any) -> dict[str, Any]:
        response = self.client.put(f"/admin/users/{user_id}", json=attributes)
        response.raise_for_status()
        return response.json()

    def delete_user(self, user_id: UUID) -> None:
        response = self.client.delete(f"/admin/users/{user_id}")
        response.raise_for_status()

    def sign_ups_are_off(self) -> bool:
        response = self.client.get("/settings")
        response.raise_for_status()
        return response.json().get("disable_signup") is True

    def sign_in(self, email: str, password: str) -> dict[str, Any]:
        """The session for this address and password, or HTTPStatusError when Auth refuses them."""
        response = self.client.post(
            "/token", params={"grant_type": "password"}, json={"email": email, "password": password}
        )
        response.raise_for_status()
        return response.json()

    def send_password_reset(self, email: str, redirect_to: str) -> None:
        """Emails a link that signs the person in once to choose a new password."""
        response = self.client.post(
            "/recover", params={"redirect_to": redirect_to}, json={"email": email}
        )
        response.raise_for_status()

    def change_own_password(self, access_token: str, password: str) -> None:
        """Changes it as the person, so Auth still refuses a weak password or the same one."""
        response = self.client.put(
            "/user",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"password": password},
        )
        response.raise_for_status()


@lru_cache
def get_auth_admin() -> SupabaseAuthAdmin:
    settings = get_settings()
    if not (settings.supabase_url and settings.supabase_service_role_key):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Account management isn't set up on this copy of Turnstone.",
        )
    return SupabaseAuthAdmin(settings.supabase_url, settings.supabase_service_role_key)
