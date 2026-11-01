from uuid import uuid4

import httpx2
import pytest

from app.auth import AuthUnavailableError, SupabaseTokenVerifier

URL = "https://project.supabase.example"


def verifier(handler) -> SupabaseTokenVerifier:  # type: ignore[no-untyped-def]
    return SupabaseTokenVerifier(URL, "project-key", httpx2.MockTransport(handler))


def test_a_good_token_gives_the_user_id_and_sends_both_credentials() -> None:
    user_id = uuid4()
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json={"id": str(user_id)})

    assert verifier(handler).user_id("the-token") == user_id
    assert str(seen[0].url) == f"{URL}/auth/v1/user"
    assert seen[0].headers["Authorization"] == "Bearer the-token"
    assert seen[0].headers["apikey"] == "project-key"


@pytest.mark.parametrize("status_code", [400, 401, 403, 404])
def test_a_rejected_token_gives_no_user(status_code: int) -> None:
    assert verifier(lambda _: httpx2.Response(status_code)).user_id("bad") is None


def test_an_auth_server_error_is_not_a_rejected_token() -> None:
    with pytest.raises(AuthUnavailableError):
        verifier(lambda _: httpx2.Response(500)).user_id("token")


def test_an_unreachable_auth_server_is_not_a_rejected_token() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("no route", request=request)

    with pytest.raises(AuthUnavailableError):
        verifier(handler).user_id("token")
