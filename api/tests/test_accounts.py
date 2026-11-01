"""Accounts and roles through the API, against real Postgres and a stand-in for Supabase Auth."""

import json
from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import httpx2
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session

from app.accounts import SignInThrottle, get_sign_in_throttle
from app.auth import get_token_verifier
from app.db import get_session
from app.main import app
from app.models import Appraisal, Decision, DecisionChoice, Item, Profile, Recommendation, Role
from app.settings import get_settings
from app.supabase_auth import (
    BAN_DURATION,
    NO_BAN,
    NO_SUCH_ACCOUNT_EMAIL,
    PLACEHOLDER_DOMAIN,
    SupabaseAuthAdmin,
    get_auth_admin,
)
from app.team import _refuse_removing_last_manager

MANAGER_TOKEN = "manager-token"
STAFF_TOKEN = "staff-token"
PASSWORD = "the right password"
SERVICE_KEY = "not-a-real-service-key"


def auth_error(status: int, code: str) -> httpx2.Response:
    return httpx2.Response(status, json={"code": status, "error_code": code, "msg": code})


class FakeSupabaseAuth:
    """Behaves like the Auth routes the API uses, and refuses a sign-up as the setting does."""

    def __init__(self) -> None:
        self.users: dict[UUID, dict[str, Any]] = {}
        self.requests: list[httpx2.Request] = []
        self.fail_with: httpx2.Response | None = None
        self.sign_ups_on = False
        self.tokens: dict[str, UUID] = {}

    def add(self, email: str, password: str = PASSWORD, user_id: UUID | None = None) -> UUID:
        user_id = user_id or uuid4()
        self.users[user_id] = {
            "id": str(user_id),
            "email": email,
            "password": password,
            "banned": False,
            "email_confirm": True,
        }
        return user_id

    def _by_email(self, email: str) -> dict[str, Any] | None:
        return next((user for user in self.users.values() if user["email"] == email), None)

    def _body(self, request: httpx2.Request) -> dict[str, Any]:
        return json.loads(request.content or b"{}")

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        path = request.url.path.removeprefix("/auth/v1")
        if self.fail_with is not None:
            return self.fail_with
        method = request.method
        if method == "POST" and path == "/token":
            return self._token(self._body(request))
        if method == "PUT" and path == "/user":
            return self._change_own_password(request)
        assert request.headers["Authorization"] == f"Bearer {SERVICE_KEY}"
        if method == "GET" and path == "/settings":
            return httpx2.Response(200, json={"disable_signup": not self.sign_ups_on})
        if method == "POST" and path == "/invite":
            return self._create(self._body(request) | {"password": None, "email_confirm": False})
        if method == "POST" and path == "/admin/users":
            return self._create(self._body(request))
        if method == "GET" and path == "/admin/users":
            return httpx2.Response(200, json={"users": list(self.users.values())})
        user_id = UUID(path.rsplit("/", 1)[1])
        if user_id not in self.users:
            return auth_error(404, "user_not_found")
        if method == "GET":
            return httpx2.Response(200, json=self.users[user_id])
        if method == "DELETE":
            del self.users[user_id]
            return httpx2.Response(200, json={})
        changes = self._body(request)
        if "ban_duration" in changes:
            self.users[user_id]["banned"] = changes["ban_duration"] != NO_BAN
        for field in ("password", "email_confirm"):
            if field in changes:
                self.users[user_id][field] = changes[field]
        return httpx2.Response(200, json=self.users[user_id])

    def _token(self, body: dict[str, Any]) -> httpx2.Response:
        user = self._by_email(body["email"])
        if user is not None and user["banned"]:
            return auth_error(400, "user_banned")
        if user is None or user["password"] != body["password"]:
            return auth_error(400, "invalid_credentials")
        token = f"token-for-{user['id']}"
        self.tokens[token] = UUID(user["id"])
        return httpx2.Response(200, json={"access_token": token, "refresh_token": "refresh"})

    def _create(self, body: dict[str, Any]) -> httpx2.Response:
        if self._by_email(body["email"]) is not None:
            return auth_error(422, "email_exists")
        user_id = self.add(body["email"], body["password"])
        self.users[user_id]["email_confirm"] = body["email_confirm"]
        return httpx2.Response(200, json=self.users[user_id])

    def _change_own_password(self, request: httpx2.Request) -> httpx2.Response:
        token = request.headers["Authorization"].removeprefix("Bearer ")
        user = self.users[self.tokens[token]]
        password = self._body(request)["password"]
        if password == user["password"]:
            return auth_error(422, "same_password")
        if password == "weak weak weak":
            return auth_error(422, "weak_password")
        user["password"] = password
        return httpx2.Response(200, json=user)


class FakeVerifier:
    def __init__(self, auth: FakeSupabaseAuth) -> None:
        self.auth = auth

    def user_id(self, token: str) -> UUID | None:
        return self.auth.tokens.get(token)


def add_person(
    session: Session, auth: FakeSupabaseAuth, username: str, role: Role = Role.STAFF, **values: Any
) -> Profile:
    profile = Profile(
        auth_user_id=auth.add(f"{username}@{PLACEHOLDER_DOMAIN}"),
        username=username,
        display_name=username.title(),
        role=role,
        **values,
    )
    session.add(profile)
    session.commit()
    return profile


@pytest.fixture
def auth() -> FakeSupabaseAuth:
    return FakeSupabaseAuth()


@pytest.fixture
def manager(session: Session, auth: FakeSupabaseAuth) -> Profile:
    profile = add_person(session, auth, "boss", Role.MANAGER)
    auth.tokens[MANAGER_TOKEN] = profile.auth_user_id
    return profile


@pytest.fixture
def staff(session: Session, auth: FakeSupabaseAuth) -> Profile:
    profile = add_person(session, auth, "helper")
    auth.tokens[STAFF_TOKEN] = profile.auth_user_id
    return profile


@pytest.fixture
def client(
    session: Session, auth: FakeSupabaseAuth, manager: Profile, staff: Profile
) -> Iterator[TestClient]:
    admin = SupabaseAuthAdmin(
        "http://localhost:54321", SERVICE_KEY, httpx2.MockTransport(auth.handler)
    )
    throttle = SignInThrottle()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_auth_admin] = lambda: admin
    app.dependency_overrides[get_token_verifier] = lambda: FakeVerifier(auth)
    app.dependency_overrides[get_sign_in_throttle] = lambda: throttle
    yield TestClient(app, headers={"Authorization": f"Bearer {MANAGER_TOKEN}"})
    app.dependency_overrides.clear()


def as_token(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


AS_STAFF = as_token(STAFF_TOKEN)
NEW_PERSON = {"username": "new.person", "display_name": "New Person", "role": "staff"}


def sign_in(client: TestClient, username: str, password: str = PASSWORD) -> httpx2.Response:
    return client.post(
        "/auth/sign-in", json={"username": username, "password": password}, headers={}
    )


def test_a_username_signs_in_and_the_tokens_are_not_cached(client: TestClient) -> None:
    response = sign_in(client, " Helper ")
    assert response.status_code == 200
    assert response.json()["refresh_token"] == "refresh"
    assert response.headers["Cache-Control"] == "no-store"
    assert "@" not in response.text


def test_a_profile_from_the_setup_scripts_signs_in_with_its_own_auth_address(
    client: TestClient, session: Session, auth: FakeSupabaseAuth
) -> None:
    # What seed_local_profile leaves behind: no email on the profile, any address in Auth.
    user_id = auth.add("someone@teammate.example")
    session.add(Profile(auth_user_id=user_id, username="teammate", display_name="Teammate"))
    session.commit()
    assert sign_in(client, "teammate").status_code == 200


@pytest.mark.parametrize(
    ("username", "password"),
    [("helper", "the wrong password"), ("nobody", PASSWORD), ("not a username!", PASSWORD)],
)
def test_a_wrong_password_and_an_unknown_username_answer_the_same(
    client: TestClient, username: str, password: str
) -> None:
    response = sign_in(client, username, password)
    assert response.status_code == 401
    assert response.json() == {"detail": "Your username, email or password is wrong"}


def test_an_unknown_username_still_asks_auth_with_an_address_nobody_can_have(
    client: TestClient, auth: FakeSupabaseAuth
) -> None:
    sign_in(client, "nobody")
    assert json.loads(auth.requests[-1].content)["email"] == NO_SUCH_ACCOUNT_EMAIL


def test_repeated_wrong_passwords_are_slowed_down_for_that_username_only(
    client: TestClient, auth: FakeSupabaseAuth
) -> None:
    for _ in range(SignInThrottle.MAX_FAILURES):
        assert sign_in(client, "helper", "wrong guess").status_code == 401
    asked = len(auth.requests)
    assert sign_in(client, "helper").status_code == 429
    assert len(auth.requests) == asked
    assert sign_in(client, "boss").status_code == 200


def test_auth_being_down_is_not_a_wrong_password(
    client: TestClient, auth: FakeSupabaseAuth
) -> None:
    auth.fail_with = httpx2.Response(500)
    assert sign_in(client, "helper").status_code == 503


def test_username_sign_in_says_so_when_the_service_key_is_missing(client: TestClient) -> None:
    get_auth_admin.cache_clear()
    settings = get_settings()
    app.dependency_overrides.pop(get_auth_admin)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(settings, "supabase_service_role_key", None)
        assert sign_in(client, "helper").status_code == 503
    get_auth_admin.cache_clear()


def test_every_route_needs_a_sign_in_except_the_public_ones() -> None:
    public = {
        ("get", "/health"),
        ("get", "/health/db"),
        ("post", "/auth/sign-in"),
    }
    guarded = {
        (method, path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    } - public
    anonymous = TestClient(app)
    for method, path in sorted(guarded):
        url = path.replace("{item_id}", str(uuid4())).replace("{auth_user_id}", str(uuid4()))
        assert anonymous.request(method, url).status_code == 401, (method, path)


def team_routes() -> list[tuple[str, str]]:
    return [
        (method, path)
        for path, operations in app.openapi()["paths"].items()
        if path.startswith("/team")
        for method in operations
    ]


def test_the_team_routes_are_all_listed_here() -> None:
    assert len(team_routes()) == 7


@pytest.mark.parametrize(("method", "path"), team_routes())
def test_staff_are_refused_every_team_route_with_nothing_changed(
    client: TestClient, auth: FakeSupabaseAuth, manager: Profile, method: str, path: str
) -> None:
    url = path.replace("{auth_user_id}", str(manager.auth_user_id))
    body = NEW_PERSON | {"email": "new@store.example"} if "/{" not in path else {"role": "staff"}
    asked = len(auth.requests)
    json_body = None if method == "get" else body
    response = client.request(method, url, headers=AS_STAFF, json=json_body)
    assert response.status_code == 403
    assert response.json() == {"detail": "Only a manager can do this."}
    assert len(auth.requests) == asked


def test_a_manager_lists_people_with_their_status(
    client: TestClient, session: Session, auth: FakeSupabaseAuth
) -> None:
    add_person(session, auth, "gone", is_active=False)
    add_person(session, auth, "temp", must_change_password=True)
    response = client.get("/team/people")
    assert response.status_code == 200
    assert {person["username"]: person["status"] for person in response.json()} == {
        "boss": "active",
        "gone": "deactivated",
        "helper": "active",
        "temp": "temporary_password",
    }


def test_an_invite_emails_a_link_back_to_choosing_a_password(
    client: TestClient, session: Session, auth: FakeSupabaseAuth
) -> None:
    response = client.post(
        "/team/people/invite", json=NEW_PERSON | {"email": " New@Store.example "}
    )
    assert response.status_code == 201
    person = response.json()
    assert person["status"] == "invited"
    assert person["email"] == "new@store.example"
    assert "temporary_password" not in person
    invite = auth.requests[-1]
    assert invite.url.path == "/auth/v1/invite"
    assert invite.url.params["redirect_to"] == (
        f"{get_settings().web_app_url.rstrip('/')}/choose-password"
    )
    profile = session.get(Profile, UUID(person["auth_user_id"]))
    assert profile is not None and profile.must_change_password


def test_an_invite_needs_an_email(client: TestClient) -> None:
    assert client.post("/team/people/invite", json=NEW_PERSON).status_code == 422


@pytest.mark.parametrize(
    "email", ["not-an-address", f"someone@{PLACEHOLDER_DOMAIN}", "two@at@signs.example"]
)
def test_a_bad_or_placeholder_address_is_refused(
    client: TestClient, auth: FakeSupabaseAuth, email: str
) -> None:
    before = len(auth.users)
    response = client.post("/team/people/invite", json=NEW_PERSON | {"email": email})
    assert response.status_code == 422
    assert len(auth.users) == before


@pytest.mark.parametrize(
    ("status", "code", "answer"),
    [
        (429, "over_email_send_rate_limit", 429),
        (400, "email_address_not_authorized", 422),
        (422, "email_exists", 409),
        (500, "unexpected_failure", 503),
    ],
)
def test_a_failed_invite_leaves_no_profile_and_says_why(
    client: TestClient,
    session: Session,
    auth: FakeSupabaseAuth,
    status: int,
    code: str,
    answer: int,
) -> None:
    auth.fail_with = auth_error(status, code)
    response = client.post("/team/people/invite", json=NEW_PERSON | {"email": "new@store.example"})
    assert response.status_code == answer
    assert session.exec(text("SELECT count(*) FROM profiles")).one()[0] == 2  # pyright: ignore[reportCallIssue, reportArgumentType]


def test_a_person_without_email_gets_a_hidden_address_and_a_temporary_password(
    client: TestClient, auth: FakeSupabaseAuth
) -> None:
    response = client.post("/team/people/temporary-password", json=NEW_PERSON)
    assert response.status_code == 201
    assert response.headers["Cache-Control"] == "no-store"
    body = response.json()
    assert body["person"]["status"] == "temporary_password"
    assert body["person"]["email"] is None
    user = auth.users[UUID(body["person"]["auth_user_id"])]
    assert user["email"] == f"new.person@{PLACEHOLDER_DOMAIN}"
    assert user["password"] == body["temporary_password"]
    assert PLACEHOLDER_DOMAIN not in response.text
    listed = client.get("/team/people").text
    assert PLACEHOLDER_DOMAIN not in listed
    assert body["temporary_password"] not in listed


def test_a_temporary_password_can_be_given_with_an_email_too(
    client: TestClient, auth: FakeSupabaseAuth
) -> None:
    response = client.post(
        "/team/people/temporary-password", json=NEW_PERSON | {"email": "new@store.example"}
    )
    assert response.json()["person"]["email"] == "new@store.example"
    assert auth.users[UUID(response.json()["person"]["auth_user_id"])]["email_confirm"] is True


def test_the_temporary_passwords_differ(client: TestClient) -> None:
    first = client.post("/team/people/temporary-password", json=NEW_PERSON)
    second = client.post(
        "/team/people/temporary-password", json=NEW_PERSON | {"username": "second.person"}
    )
    assert first.json()["temporary_password"] != second.json()["temporary_password"]


@pytest.mark.parametrize(
    "username",
    ["", "UPPER CASE", "has space", ".starts-with-dot", "ends-with-dot.", "two..dots", "a@b", "é"],
)
def test_a_username_that_cannot_make_an_address_is_refused(
    client: TestClient, username: str
) -> None:
    response = client.post(
        "/team/people/temporary-password", json=NEW_PERSON | {"username": username}
    )
    assert response.status_code == 422


def test_a_blank_name_is_refused(client: TestClient) -> None:
    response = client.post(
        "/team/people/temporary-password", json=NEW_PERSON | {"display_name": "   "}
    )
    assert response.status_code == 422


def test_a_taken_username_or_email_is_refused_before_auth_is_asked(
    client: TestClient, session: Session, auth: FakeSupabaseAuth
) -> None:
    add_person(session, auth, "has.mail", email="taken@store.example")
    asked = len(auth.requests)
    for path, body in (
        ("temporary-password", NEW_PERSON | {"username": "helper"}),
        ("invite", NEW_PERSON | {"email": "taken@store.example"}),
    ):
        assert client.post(f"/team/people/{path}", json=body).status_code == 409
    assert len(auth.requests) == asked


def test_a_save_that_loses_a_race_takes_the_new_auth_user_back_out(
    client: TestClient, session: Session, auth: FakeSupabaseAuth, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_person(session, auth, "racer")
    monkeypatch.setattr("app.team._refuse_if_taken", lambda *_: None)
    before = len(auth.users)
    response = client.post(
        "/team/people/temporary-password", json=NEW_PERSON | {"username": "racer"}
    )
    assert response.status_code == 409
    assert len(auth.users) == before


def test_someone_on_a_temporary_password_can_do_nothing_until_they_choose_one(
    client: TestClient, session: Session, auth: FakeSupabaseAuth
) -> None:
    created = client.post("/team/people/temporary-password", json=NEW_PERSON).json()
    signed_in = sign_in(client, "new.person", created["temporary_password"]).json()
    headers = as_token(signed_in["access_token"])

    assert client.get("/decisions", headers=headers).status_code == 403
    assert client.post("/items", headers=headers).status_code == 403
    assert client.get("/me", headers=headers).json()["status"] == "temporary_password"

    same = client.post(
        "/me/password", headers=headers, json={"password": created["temporary_password"]}
    )
    assert same.status_code == 422
    assert "different" in same.json()["detail"]
    assert client.get("/decisions", headers=headers).status_code == 403

    chosen = client.post("/me/password", headers=headers, json={"password": "my own password"})
    assert chosen.status_code == 200
    assert chosen.json()["status"] == "active"
    assert client.get("/decisions", headers=headers).status_code == 200
    assert sign_in(client, "new.person", "my own password").status_code == 200
    assert sign_in(client, "new.person", created["temporary_password"]).status_code == 401


def test_changing_only_the_session_metadata_does_not_lift_the_block(
    client: TestClient, session: Session, auth: FakeSupabaseAuth, staff: Profile
) -> None:
    # The block is a column the browser has no way to write, unlike Supabase's user metadata.
    staff.must_change_password = True
    session.add(staff)
    session.commit()
    auth.users[staff.auth_user_id]["user_metadata"] = {"temporary_password": False}
    assert client.get("/decisions", headers=AS_STAFF).status_code == 403


def test_a_password_auth_calls_weak_is_refused_and_keeps_the_block(
    client: TestClient, session: Session, staff: Profile
) -> None:
    staff.must_change_password = True
    session.add(staff)
    session.commit()
    response = client.post("/me/password", headers=AS_STAFF, json={"password": "weak weak weak"})
    assert response.status_code == 422
    assert "stronger" in response.json()["detail"]
    assert client.get("/me", headers=AS_STAFF).json()["status"] == "temporary_password"


@pytest.mark.parametrize("password", ["too short", "x" * 73])
def test_a_password_of_the_wrong_length_never_reaches_auth(
    client: TestClient, auth: FakeSupabaseAuth, password: str
) -> None:
    asked = len(auth.requests)
    response = client.post("/me/password", headers=AS_STAFF, json={"password": password})
    assert response.status_code == 422
    assert len(auth.requests) == asked


def test_accepting_an_invite_ends_at_active(client: TestClient, auth: FakeSupabaseAuth) -> None:
    invited = client.post(
        "/team/people/invite", json=NEW_PERSON | {"email": "new@store.example"}
    ).json()
    auth.tokens["invite-session"] = UUID(invited["auth_user_id"])
    headers = as_token("invite-session")
    assert client.get("/decisions", headers=headers).status_code == 403
    assert client.get("/me", headers=headers).json()["status"] == "invited"
    chosen = client.post("/me/password", headers=headers, json={"password": "my own password"})
    assert chosen.json()["status"] == "active"
    assert auth.users[UUID(invited["auth_user_id"])]["password"] == "my own password"


def test_a_manager_issues_a_new_temporary_password(
    client: TestClient, auth: FakeSupabaseAuth, staff: Profile
) -> None:
    response = client.post(f"/team/people/{staff.auth_user_id}/temporary-password")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["person"]["status"] == "temporary_password"
    assert auth.users[staff.auth_user_id]["password"] == response.json()["temporary_password"]
    assert sign_in(client, "helper").status_code == 401


def test_a_temporary_password_for_someone_who_never_opened_their_invite_works(
    client: TestClient, auth: FakeSupabaseAuth
) -> None:
    invited = client.post(
        "/team/people/invite", json=NEW_PERSON | {"email": "new@store.example"}
    ).json()
    response = client.post(f"/team/people/{invited['auth_user_id']}/temporary-password")
    assert response.json()["person"]["status"] == "temporary_password"
    assert auth.users[UUID(invited["auth_user_id"])]["email_confirm"] is True


def test_a_failed_new_temporary_password_changes_nothing(
    client: TestClient, session: Session, auth: FakeSupabaseAuth, staff: Profile
) -> None:
    auth.fail_with = httpx2.Response(500)
    response = client.post(f"/team/people/{staff.auth_user_id}/temporary-password")
    assert response.status_code == 503
    session.refresh(staff)
    assert not staff.must_change_password


def test_a_deactivated_person_gets_no_new_temporary_password(
    client: TestClient, staff: Profile
) -> None:
    client.post(f"/team/people/{staff.auth_user_id}/deactivate")
    response = client.post(f"/team/people/{staff.auth_user_id}/temporary-password")
    assert response.status_code == 409


def test_unknown_people_answer_404(client: TestClient) -> None:
    missing = uuid4()
    for method, url in (
        ("post", f"/team/people/{missing}/deactivate"),
        ("post", f"/team/people/{missing}/temporary-password"),
    ):
        assert client.request(method, url).status_code == 404
    assert client.patch(f"/team/people/{missing}", json={"role": "staff"}).status_code == 404


def test_a_manager_changes_a_role_and_it_takes_effect_at_once(
    client: TestClient, staff: Profile
) -> None:
    assert client.get("/team/people", headers=AS_STAFF).status_code == 403
    response = client.patch(f"/team/people/{staff.auth_user_id}", json={"role": "manager"})
    assert response.json()["role"] == "manager"
    assert client.get("/team/people", headers=AS_STAFF).status_code == 200


def test_the_last_active_manager_keeps_the_role(
    client: TestClient, session: Session, auth: FakeSupabaseAuth, manager: Profile
) -> None:
    add_person(session, auth, "former", Role.MANAGER, is_active=False)
    response = client.patch(f"/team/people/{manager.auth_user_id}", json={"role": "staff"})
    assert response.status_code == 409
    session.refresh(manager)
    assert manager.role == Role.MANAGER


def test_a_manager_can_step_down_when_another_is_active(
    client: TestClient, session: Session, auth: FakeSupabaseAuth, manager: Profile
) -> None:
    add_person(session, auth, "other", Role.MANAGER)
    response = client.patch(f"/team/people/{manager.auth_user_id}", json={"role": "staff"})
    assert response.json()["role"] == "staff"


def test_nobody_can_deactivate_themselves(
    client: TestClient, session: Session, auth: FakeSupabaseAuth, manager: Profile
) -> None:
    add_person(session, auth, "other", Role.MANAGER)
    response = client.post(f"/team/people/{manager.auth_user_id}/deactivate")
    assert response.status_code == 409
    assert auth.users[manager.auth_user_id]["banned"] is False


def test_the_last_active_manager_is_refused_by_the_check_a_race_would_reach(
    client: TestClient, session: Session, manager: Profile
) -> None:
    # Over HTTP the caller is itself an active manager, so only a concurrent request gets here.
    with pytest.raises(HTTPException, match="409"):
        _refuse_removing_last_manager(session, manager)


def test_two_managers_can_deactivate_down_to_one_and_no_further(
    client: TestClient, session: Session, auth: FakeSupabaseAuth, manager: Profile
) -> None:
    other = add_person(session, auth, "other", Role.MANAGER)
    auth.tokens["other-token"] = other.auth_user_id
    assert client.post(f"/team/people/{other.auth_user_id}/deactivate").status_code == 200
    # The deactivated manager's own session no longer works, so it can't remove the last one.
    response = client.post(
        f"/team/people/{manager.auth_user_id}/deactivate", headers=as_token("other-token")
    )
    assert response.status_code == 403


def test_deactivating_stops_sign_in_and_the_open_session_and_keeps_decisions(
    client: TestClient, session: Session, auth: FakeSupabaseAuth, staff: Profile
) -> None:
    item = Item(sku="SKU-1", lister_id=staff.auth_user_id, photo_keys=["key"], photo_hash="hash")
    appraisal = Appraisal(
        item_id=item.id,
        confidence="low",  # pyright: ignore[reportArgumentType]
        recommendation=Recommendation.CHECK,
        rules_config={},
    )
    decision = Decision(
        item_id=item.id,
        appraisal_id=appraisal.id,
        decision=DecisionChoice.NO,
        decided_by=staff.auth_user_id,
    )
    session.add(item)
    session.flush()
    session.add(appraisal)
    session.flush()
    session.add(decision)
    session.commit()

    response = client.post(f"/team/people/{staff.auth_user_id}/deactivate")

    assert response.status_code == 200
    assert response.json()["status"] == "deactivated"
    ban = json.loads(auth.requests[-1].content)
    assert ban == {"ban_duration": BAN_DURATION}
    assert client.get("/decisions", headers=AS_STAFF).status_code == 403
    answer = sign_in(client, "helper")
    assert answer.status_code == 403
    assert "turned off" in answer.json()["detail"]
    session.refresh(decision)
    assert decision.decided_by == staff.auth_user_id
    assert session.get(Profile, staff.auth_user_id) is not None


def test_a_profile_turned_off_without_a_ban_gets_no_tokens_either(
    client: TestClient, session: Session, auth: FakeSupabaseAuth, staff: Profile
) -> None:
    staff.is_active = False
    session.add(staff)
    session.commit()
    response = sign_in(client, "helper")
    assert response.status_code == 403
    assert "access_token" not in response.text


def test_a_failed_ban_leaves_the_person_active(
    client: TestClient, session: Session, auth: FakeSupabaseAuth, staff: Profile
) -> None:
    auth.fail_with = httpx2.Response(500)
    assert client.post(f"/team/people/{staff.auth_user_id}/deactivate").status_code == 503
    session.refresh(staff)
    assert staff.is_active


def test_reactivating_lifts_the_ban(
    client: TestClient, auth: FakeSupabaseAuth, staff: Profile
) -> None:
    client.post(f"/team/people/{staff.auth_user_id}/deactivate")
    response = client.post(f"/team/people/{staff.auth_user_id}/reactivate")
    assert response.json()["status"] == "active"
    assert auth.users[staff.auth_user_id]["banned"] is False
    assert sign_in(client, "helper").status_code == 200
    assert client.get("/decisions", headers=AS_STAFF).status_code == 200


def test_a_stranger_with_an_auth_user_but_no_profile_gets_nothing(
    client: TestClient, auth: FakeSupabaseAuth
) -> None:
    # What a sign-up would leave behind if that setting were ever turned back on.
    auth.tokens["stranger"] = auth.add("stranger@example.com")
    headers = as_token("stranger")
    for method, url in (("get", "/me"), ("get", "/decisions"), ("get", "/team/people")):
        assert client.request(method, url, headers=headers).status_code == 403


def test_no_route_offers_sign_up() -> None:
    paths = app.openapi()["paths"]
    assert not [path for path in paths if "sign-up" in path or "signup" in path]


def test_no_response_model_carries_the_service_key() -> None:
    schema = json.dumps(app.openapi()).lower()
    assert "service_role" not in schema
