"""Stands in for Supabase, the vision model and SerpApi in the offline demo, on this machine only.

docker-compose.offline.yml points the API and the web app here, so the app's own code runs unchanged
with no keys and no network. It answers with one fixed item card and the committed SerpApi fixtures,
and it reads no photo. A Needs Attention prompt gets its own fixed sentences back. Its passwords
are public, so it must never serve anything but that demo.

Usage: uvicorn app.offline_standin:app --port 9999
"""

import base64
import json
import os
import re
import time
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.supabase_auth import placeholder_email

PASSWORD = "offline-demo"
USERS = {
    "demo.staff": UUID("00000000-0000-4000-8000-000000000001"),
    "demo.manager": UUID("00000000-0000-4000-8000-000000000002"),
}
TOKEN_SECONDS = 3600
FIXTURES = Path(__file__).parents[1] / "tests" / "fixtures" / "serpapi"
DEFAULT_FIXTURE = "levis-501-jeans"
ITEM_CARD = {
    "category": "apparel",
    "brand": "Levi's",
    "product": "501 jeans",
    "visible_text": "Levi's 501",
    "search_query": "Levi's 501 jeans",
    "model_confidence": "high",
    "color": "blue",
    "material": "denim",
    "exact_model": "501",
    "platform": None,
}

app = FastAPI(title="Turnstone offline stand-in")
# supabase-js calls Auth straight from the browser, on another port than the page.
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"], max_age=600
)


def _photo_dir() -> Path:
    return Path(os.environ.get("OFFLINE_PHOTO_DIR", "/tmp/turnstone-offline-photos"))


def _user(user_id: UUID) -> dict[str, Any]:
    username = next(name for name, known in USERS.items() if known == user_id)
    return {
        "id": str(user_id),
        "aud": "authenticated",
        "role": "authenticated",
        "email": placeholder_email(username),
        "app_metadata": {},
        "user_metadata": {},
        "created_at": "2026-11-13T00:00:00Z",
    }


def _encode(part: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(part).encode()).rstrip(b"=").decode()


def _session(user_id: UUID) -> dict[str, Any]:
    expires_at = int(time.time()) + TOKEN_SECONDS
    claims = {"sub": str(user_id), "exp": expires_at, "aud": "authenticated"}
    token = f"{_encode({'alg': 'none', 'typ': 'JWT'})}.{_encode(claims)}.offline"
    return {
        "access_token": token,
        "refresh_token": str(user_id),
        "token_type": "bearer",
        "expires_in": TOKEN_SECONDS,
        "expires_at": expires_at,
        "user": _user(user_id),
    }


def _user_from_token(authorization: str | None) -> UUID:
    try:
        payload = (authorization or "").removeprefix("Bearer ").split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        user_id = UUID(claims["sub"])
    except (IndexError, KeyError, ValueError) as error:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad token") from error
    if user_id not in USERS.values():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad token")
    return user_id


class TokenRequest(BaseModel):
    email: str | None = None
    password: str | None = None
    refresh_token: str | None = None


def _wrong_details() -> JSONResponse:
    return JSONResponse(
        {"code": 400, "error_code": "invalid_credentials", "msg": "Invalid login credentials"},
        status.HTTP_400_BAD_REQUEST,
    )


@app.post("/auth/v1/token", response_model=None)
def token(request: TokenRequest, grant_type: str) -> dict[str, Any] | JSONResponse:
    if grant_type == "refresh_token":
        try:
            user_id = UUID(request.refresh_token or "")
        except ValueError:
            return _wrong_details()
        return _session(user_id) if user_id in USERS.values() else _wrong_details()
    for username, user_id in USERS.items():
        if request.email == placeholder_email(username) and request.password == PASSWORD:
            return _session(user_id)
    return _wrong_details()


@app.get("/auth/v1/user")
def current_user(authorization: Annotated[str | None, Header()] = None) -> dict[str, Any]:
    return _user(_user_from_token(authorization))


@app.post("/auth/v1/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout() -> None:
    return None


@app.get("/auth/v1/admin/users/{user_id}")
def admin_user(user_id: UUID) -> dict[str, Any]:
    if user_id not in USERS.values():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such user")
    return _user(user_id)


@app.post("/storage/v1/object/{bucket}/{key:path}")
async def save_photo(bucket: str, key: str, request: Request) -> dict[str, str]:
    path = _photo_path(bucket, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(await request.body())
    return {"Key": f"{bucket}/{key}"}


@app.get("/storage/v1/object/{bucket}/{key:path}")
def read_photo(bucket: str, key: str) -> Response:
    path = _photo_path(bucket, key)
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such photo")
    return Response(path.read_bytes(), media_type="application/octet-stream")


def _photo_path(bucket: str, key: str) -> Path:
    root = _photo_dir().resolve()
    path = (root / bucket / key).resolve()
    if not path.is_relative_to(root):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "bad key")
    return path


# The listing for the fixed card, which only restates it, so the claim checker passes it.
LISTING_DRAFT = {
    "title": "Levi's 501 jeans, blue denim - Pre-owned",
    "description": "Blue Levi's 501 jeans in denim, pre-owned. See the photos for the exact item.",
}


def _prompt_text(body: dict[str, Any]) -> str:
    messages = body.get("messages") or [{}]
    content = messages[0].get("content")
    return content if isinstance(content, str) else ""


def _fact(prompt: str, label: str) -> str:
    found = re.search(rf"^- {label}: (.*)$", prompt, re.MULTILINE)
    return found.group(1) if found else ""


@app.post("/v1/chat/completions")
async def chat_completion(request: Request) -> dict[str, Any]:
    """The fixed card for a photo, the fixed listing for a listing prompt, and a flag's own
    fixed sentences back for a Needs Attention prompt."""
    body = await request.body()
    prompt = _prompt_text(json.loads(body)) if body else ""
    if prompt.startswith("You write a listing"):
        category = "Unisex" if "Channel B" in prompt else "Unisex Clothing"
        content = json.dumps(LISTING_DRAFT | {"category": category})
    elif prompt.startswith("You explain"):
        content = json.dumps(
            {"explanation": _fact(prompt, "Problem"), "suggested_fix": _fact(prompt, "Fix")}
        )
    else:
        content = json.dumps(ITEM_CARD)
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def closest_fixture(query: str, condition: str) -> dict[str, Any]:
    """The committed response whose search shares the most words with this one."""
    fixtures = {
        path.stem: json.loads(path.read_text(encoding="utf-8")) for path in FIXTURES.glob("*.json")
    }

    def score(name: str) -> tuple[int, bool, bool]:
        parameters = fixtures[name]["search_parameters"]
        return (
            len(_words(query) & _words(parameters["_nkw"])),
            parameters["LH_ItemCondition"] == condition,
            name == DEFAULT_FIXTURE,
        )

    return fixtures[max(fixtures, key=score)]


@app.get("/search.json")
def ebay_search(
    query: Annotated[str, Query(alias="_nkw")],
    condition: Annotated[str, Query(alias="LH_ItemCondition")],
) -> dict[str, Any]:
    return closest_fixture(query, condition)
