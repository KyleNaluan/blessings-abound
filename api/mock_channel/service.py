"""One mock sales channel as a FastAPI app, built twice by channel_a.py and channel_b.py.

Each channel has three faces:

- A seller API under `/api`, which the main app calls with the channel key to publish, end and
  read listings and to read orders. It answers 503 while the channel is switched offline.
- A storefront at `/`, where anyone can buy a listing, which is how the demo simulates a sale.
- A sale webhook to the main app, signed with the channel key, sent right after each purchase.
  The storefront can leave it out, to show polling catching a missed webhook.

`/admin`, behind the channel key, switches the channel offline and back for the demo.
"""

import hashlib
import hmac
import json
import logging
import secrets
from collections.abc import Callable, Iterator
from datetime import datetime
from functools import lru_cache
from html import escape
from typing import Annotated, Any
from uuid import UUID, uuid4

import httpx2
import sqlalchemy as sa
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    FastAPI,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBasic,
    HTTPBasicCredentials,
    HTTPBearer,
)
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from mock_channel.tables import TABLES, ChannelTables

logger = logging.getLogger(__name__)

SIGNATURE_HEADER = "X-Channel-Signature"
WEBHOOK_TIMEOUT_SECONDS = 5.0


class ChannelSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_name: str
    label: str
    tagline: str
    # The channel's own categories, which Turnstone's listing drafts choose from.
    categories: tuple[str, ...]
    # Listing fields that must be filled, on top of the ones every listing needs.
    required: tuple[str, ...] = ()
    title_limit: int = 80


class ChannelSettings(BaseSettings):
    """Read from CHANNEL_ variables set for each service, not from the app's .env."""

    model_config = SettingsConfigDict(env_prefix="CHANNEL_", env_ignore_empty=True, extra="ignore")

    # Empty means the local compose database, as this channel's own role.
    database_url: str | None = None
    # The seller API key, which also signs the sale webhooks. With none, the seller API is off.
    key: str | None = None
    # Where sale webhooks go, the app's /channels/<schema>/sales. With none, polling finds sales.
    webhook_url: str | None = None


def default_database_url(schema_name: str) -> str:
    return f"postgresql+psycopg://{schema_name}:{schema_name}@localhost:5432/thrift"


class ListingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_ref: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    category: str
    condition: str
    price_cents: int = Field(gt=0)
    brand: str | None = None
    size: str | None = None
    color: str | None = None
    specifics: dict[str, str] = {}


class ListingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    external_ref: str
    title: str
    description: str
    category: str
    condition: str
    price_cents: int
    brand: str | None
    size: str | None
    color: str | None
    specifics: dict[str, str]
    status: str
    created_at: datetime
    ended_at: datetime | None


class OrderOut(BaseModel):
    id: UUID
    listing_id: UUID
    external_ref: str
    price_cents: int
    status: str
    sold_at: datetime
    acknowledged_at: datetime | None


class PurchaseIn(BaseModel):
    listing_id: UUID
    # False leaves the webhook out, the way a dropped one would, so only polling can find the sale.
    send_webhook: bool = True


@lru_cache
def get_channel_settings() -> ChannelSettings:
    return ChannelSettings()


def get_spec(request: Request) -> ChannelSpec:
    return request.app.state.spec


SpecDep = Annotated[ChannelSpec, Depends(get_spec)]
SettingsDep = Annotated[ChannelSettings, Depends(get_channel_settings)]


@lru_cache
def _engine(url: str) -> sa.Engine:
    return sa.create_engine(url, pool_pre_ping=True)


def get_session_factory(spec: SpecDep, settings: SettingsDep) -> Callable[[], Session]:
    engine = _engine(settings.database_url or default_database_url(spec.schema_name))
    return lambda: Session(engine)


SessionFactoryDep = Annotated[Callable[[], Session], Depends(get_session_factory)]


def get_session(factory: SessionFactoryDep) -> Iterator[Session]:
    with factory() as session:
        yield session


# Closed when the route returns, so no connection is held while the sale webhook goes out.
SessionDep = Annotated[Session, Depends(get_session, scope="function")]


@lru_cache
def get_webhook_client() -> httpx2.Client:
    return httpx2.Client(timeout=WEBHOOK_TIMEOUT_SECONDS)


WebhookClientDep = Annotated[httpx2.Client, Depends(get_webhook_client)]


def get_tables(spec: SpecDep) -> ChannelTables:
    return TABLES[spec.schema_name]


TablesDep = Annotated[ChannelTables, Depends(get_tables)]


def sign(key: str, body: bytes) -> str:
    """The signature header value for a webhook body."""
    return "sha256=" + hmac.new(key.encode(), body, hashlib.sha256).hexdigest()


def is_offline(session: Session, tables: ChannelTables) -> bool:
    return bool(session.execute(sa.select(tables.controls.c.offline)).scalar())


def require_online(spec: SpecDep, session: SessionDep, tables: TablesDep) -> None:
    if is_offline(session, tables):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"{spec.label} is offline.")


bearer = HTTPBearer(auto_error=False)


def require_seller(
    spec: SpecDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> None:
    if not settings.key:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"{spec.label} has no seller key set."
        )
    if credentials is None or not secrets.compare_digest(credentials.credentials, settings.key):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "That seller key isn't right.",
            headers={"WWW-Authenticate": "Bearer"},
        )


basic = HTTPBasic(auto_error=False)


def require_admin(
    spec: SpecDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPBasicCredentials | None, Depends(basic)],
) -> None:
    """The demo switches, behind the channel key as the password, with any username."""
    if settings.key and credentials and secrets.compare_digest(credentials.password, settings.key):
        return
    raise HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        f"Sign in with the {spec.label} key as the password.",
        headers={"WWW-Authenticate": f'Basic realm="{spec.label}"'},
    )


def _listing(session: Session, tables: ChannelTables, listing_id: UUID, *, lock: bool = False):
    query = sa.select(tables.listings).where(tables.listings.c.id == listing_id)
    row = session.execute(query.with_for_update() if lock else query).mappings().first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That listing doesn't exist.")
    return row


def _orders_query(tables: ChannelTables) -> sa.Select[*tuple[Any, ...]]:
    orders, listings = tables.orders, tables.listings
    return (
        sa.select(
            orders.c.id,
            orders.c.listing_id,
            listings.c.external_ref,
            orders.c.price_cents,
            orders.c.status,
            orders.c.created_at.label("sold_at"),
            orders.c.acknowledged_at,
        )
        .join(listings, orders.c.listing_id == listings.c.id)
        .order_by(orders.c.created_at, orders.c.id)
    )


def _order(session: Session, tables: ChannelTables, order_id: UUID) -> OrderOut:
    row = session.execute(_orders_query(tables).where(tables.orders.c.id == order_id)).mappings()
    found = row.first()
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That order doesn't exist.")
    return OrderOut.model_validate(dict(found))


def check_listing(spec: ChannelSpec, listing: ListingIn) -> None:
    """This channel's own rules, which is where platform fit is enforced."""
    if listing.category not in spec.categories:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"{spec.label} has no {listing.category} category.",
        )
    if len(listing.title) > spec.title_limit:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"{spec.label} titles are at most {spec.title_limit} characters.",
        )
    for name in spec.required:
        if not getattr(listing, name):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"{spec.label} needs a {name}."
            )


seller_api = APIRouter(prefix="/api", dependencies=[Depends(require_seller)])


@seller_api.post(
    "/listings",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_online)],
)
def publish_listing(
    listing: ListingIn, response: Response, spec: SpecDep, session: SessionDep, tables: TablesDep
) -> ListingOut:
    """Create a listing, or return the one already made for this external_ref."""
    check_listing(spec, listing)
    inserted = session.execute(
        pg_insert(tables.listings)
        .values(id=uuid4(), **listing.model_dump())
        .on_conflict_do_nothing(index_elements=["external_ref"])
        .returning(tables.listings.c.id)
    ).scalar()
    session.commit()
    if inserted is None:
        response.status_code = status.HTTP_200_OK
    row = (
        session.execute(
            sa.select(tables.listings).where(tables.listings.c.external_ref == listing.external_ref)
        )
        .mappings()
        .one()
    )
    return ListingOut.model_validate(dict(row))


@seller_api.get("/listings", dependencies=[Depends(require_online)])
def list_listings(
    session: SessionDep,
    tables: TablesDep,
    listing_status: Annotated[str | None, Query(alias="status")] = None,
) -> list[ListingOut]:
    query = sa.select(tables.listings).order_by(tables.listings.c.created_at, tables.listings.c.id)
    if listing_status is not None:
        query = query.where(tables.listings.c.status == listing_status)
    return [ListingOut.model_validate(dict(row)) for row in session.execute(query).mappings()]


@seller_api.get("/listings/{listing_id}", dependencies=[Depends(require_online)])
def get_listing(listing_id: UUID, session: SessionDep, tables: TablesDep) -> ListingOut:
    return ListingOut.model_validate(dict(_listing(session, tables, listing_id)))


@seller_api.post("/listings/{listing_id}/end", dependencies=[Depends(require_online)])
def end_listing(listing_id: UUID, session: SessionDep, tables: TablesDep) -> ListingOut:
    """Take a listing down. Ending one twice is fine, and a sold one can't be ended."""
    row = _listing(session, tables, listing_id, lock=True)
    if row["status"] == "sold":
        raise HTTPException(status.HTTP_409_CONFLICT, "This listing has already sold.")
    if row["status"] == "active":
        session.execute(
            sa.update(tables.listings)
            .where(tables.listings.c.id == listing_id)
            .values(status="ended", ended_at=sa.func.now(), updated_at=sa.func.now())
        )
    session.commit()
    return ListingOut.model_validate(dict(_listing(session, tables, listing_id)))


@seller_api.get("/orders", dependencies=[Depends(require_online)])
def list_orders(
    session: SessionDep, tables: TablesDep, acknowledged: bool | None = None
) -> list[OrderOut]:
    """Every order, or only those the seller hasn't acknowledged, which is what polling asks for."""
    query = _orders_query(tables)
    if acknowledged is not None:
        column = tables.orders.c.acknowledged_at
        query = query.where(column.is_not(None) if acknowledged else column.is_(None))
    return [OrderOut.model_validate(dict(row)) for row in session.execute(query).mappings()]


@seller_api.post(
    "/orders/{order_id}/acknowledge",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_online)],
)
def acknowledge_order(order_id: UUID, session: SessionDep, tables: TablesDep) -> None:
    _order(session, tables, order_id)
    session.execute(
        sa.update(tables.orders)
        .where(tables.orders.c.id == order_id, tables.orders.c.acknowledged_at.is_(None))
        .values(acknowledged_at=sa.func.now())
    )
    session.commit()


def deliver_sale_webhook(
    order_id: UUID,
    spec: ChannelSpec,
    settings: ChannelSettings,
    factory: Callable[[], Session],
    client: httpx2.Client,
) -> None:
    """Send one signed sale webhook, once. A failure is left for the app's polling to find."""
    if not (settings.webhook_url and settings.key):
        return
    tables = TABLES[spec.schema_name]
    with factory() as session:
        order = _order(session, tables, order_id)
    body = json.dumps(
        {
            "id": str(order.id),
            "listing_id": str(order.listing_id),
            "external_ref": order.external_ref,
            "price_cents": order.price_cents,
            "sold_at": order.sold_at.isoformat(),
        }
    ).encode()
    try:
        response = client.post(
            settings.webhook_url,
            content=body,
            headers={
                "Content-Type": "application/json",
                SIGNATURE_HEADER: sign(settings.key, body),
            },
        )
    except httpx2.HTTPError as error:
        logger.warning("%s: sale webhook for order %s failed: %s", spec.label, order_id, error)
        return
    if not response.is_success:
        logger.warning(
            "%s: sale webhook for order %s got %s", spec.label, order_id, response.status_code
        )
        return
    with factory() as session:
        session.execute(
            sa.update(tables.orders)
            .where(tables.orders.c.id == order_id, tables.orders.c.acknowledged_at.is_(None))
            .values(acknowledged_at=sa.func.now())
        )
        session.commit()


def purchase(
    listing_id: UUID,
    spec: ChannelSpec,
    session: Session,
    tables: ChannelTables,
) -> OrderOut:
    if is_offline(session, tables):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"{spec.label} is offline.")
    listing = _listing(session, tables, listing_id, lock=True)
    if listing["status"] != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "This item is no longer available.")
    order_id = uuid4()
    session.execute(
        sa.insert(tables.orders).values(
            id=order_id, listing_id=listing_id, price_cents=listing["price_cents"]
        )
    )
    session.execute(
        sa.update(tables.listings)
        .where(tables.listings.c.id == listing_id)
        .values(status="sold", updated_at=sa.func.now())
    )
    session.commit()
    return _order(session, tables, order_id)


storefront = APIRouter()


@storefront.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@storefront.post("/purchases", status_code=status.HTTP_201_CREATED)
def create_purchase(
    request: PurchaseIn,
    background: BackgroundTasks,
    spec: SpecDep,
    settings: SettingsDep,
    session: SessionDep,
    factory: SessionFactoryDep,
    client: WebhookClientDep,
    tables: TablesDep,
) -> OrderOut:
    """Buy a listing as a shopper would, for scripts and tests. The storefront posts to /buy."""
    order = purchase(request.listing_id, spec, session, tables)
    if request.send_webhook:
        background.add_task(deliver_sale_webhook, order.id, spec, settings, factory, client)
    return order


@storefront.get("/", response_class=HTMLResponse)
def storefront_page(
    spec: SpecDep,
    session: SessionDep,
    tables: TablesDep,
    order: UUID | None = None,
    told: bool = True,
) -> HTMLResponse:
    listings = session.execute(
        sa.select(tables.listings)
        .where(tables.listings.c.status == "active")
        .order_by(tables.listings.c.created_at.desc(), tables.listings.c.id)
    ).mappings()
    notice = ""
    if is_offline(session, tables):
        notice = _notice(f"{spec.label} is offline right now, so nothing can be bought.")
    elif order is not None and told:
        notice = _notice("Thanks, your order is in. The seller has been told.", tone="good")
    elif order is not None:
        notice = _notice(
            "Thanks, your order is in. No webhook went out, so the seller finds this sale on "
            "their next poll.",
            tone="good",
        )
    return HTMLResponse(_page(spec, spec.label, notice + _listing_grid(list(listings))))


@storefront.post("/buy/{listing_id}")
def buy_from_page(
    listing_id: UUID,
    background: BackgroundTasks,
    spec: SpecDep,
    settings: SettingsDep,
    session: SessionDep,
    factory: SessionFactoryDep,
    client: WebhookClientDep,
    tables: TablesDep,
    send_webhook: Annotated[bool, Form()] = False,
) -> Response:
    try:
        order = purchase(listing_id, spec, session, tables)
    except HTTPException as error:
        body = _notice(str(error.detail)) + '<p><a href="/">Back to the shop</a></p>'
        return HTMLResponse(_page(spec, "Not bought", body), status_code=error.status_code)
    if send_webhook:
        background.add_task(deliver_sale_webhook, order.id, spec, settings, factory, client)
    told = "" if send_webhook else "&told=false"
    return RedirectResponse(f"/?order={order.id}{told}", status_code=status.HTTP_303_SEE_OTHER)


@storefront.get("/admin", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
def admin_page(spec: SpecDep, session: SessionDep, tables: TablesDep) -> HTMLResponse:
    offline = is_offline(session, tables)
    if offline:
        state = (
            "offline</strong>. Its seller API answers 503, so Turnstone retries what it sends, "
            "and nothing can be bought."
        )
    else:
        state = "online</strong>."
    action = "Bring it back online" if offline else "Take it offline"
    body = (
        f"<p>{escape(spec.label)} is <strong>{state}</p>"
        '<form method="post" action="/admin/offline">'
        f'<input type="hidden" name="offline" value="{"false" if offline else "true"}">'
        f'<button type="submit">{action}</button></form>'
        '<p><a href="/">Back to the shop</a></p>'
    )
    return HTMLResponse(_page(spec, f"{spec.label} switches", body))


def set_offline(session: Session, tables: ChannelTables, offline: bool) -> None:
    session.execute(
        pg_insert(tables.controls)
        .values(id=True, offline=offline)
        .on_conflict_do_update(index_elements=["id"], set_={"offline": offline})
    )
    session.commit()


@storefront.post("/admin/offline", dependencies=[Depends(require_admin)])
def switch_offline(
    session: SessionDep, tables: TablesDep, offline: Annotated[bool, Form()]
) -> RedirectResponse:
    set_offline(session, tables, offline)
    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)


def _money(cents: int) -> str:
    return f"${cents / 100:,.2f}"


CONDITION_LABELS = {
    "new_with_tags": "New with tags",
    "new_without_tags": "New without tags",
    "pre_owned": "Pre-owned",
}


def _condition(value: str) -> str:
    return CONDITION_LABELS.get(value, value.replace("_", " ").capitalize())


def _notice(text: str, tone: str = "warn") -> str:
    return f'<p class="notice {tone}" role="status">{escape(text)}</p>'


def _listing_grid(listings: list[Any]) -> str:
    if not listings:
        return '<p class="empty">Nothing is for sale right now.</p>'
    cards = []
    for row in listings:
        facts = " · ".join(
            escape(part)
            for part in (
                row["brand"],
                row["size"] and f"Size {row['size']}",
                _condition(row["condition"]),
            )
            if part
        )
        cards.append(
            "<li>"
            f"<h2>{escape(row['title'])}</h2>"
            f'<p class="price">{_money(row["price_cents"])}</p>'
            f'<p class="facts">{facts}</p>'
            f'<p class="description">{escape(row["description"])}</p>'
            f'<form method="post" action="/buy/{row["id"]}">'
            '<label><input type="checkbox" name="send_webhook" value="true" checked>'
            "<span>Tell the seller right away, by sale webhook</span></label>"
            '<button type="submit">Buy now</button></form>'
            "</li>"
        )
    return f'<ul class="listings">{"".join(cards)}</ul>'


def _page(spec: ChannelSpec, title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<style>
  :root {{ color-scheme: light; --ink: #1b1b1b; --muted: #565c65; --rule: #dfe1e2;
    --accent: {"#162e51" if spec.schema_name == "channel_a" else "#5c1111"}; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font: 16px/1.5 system-ui, sans-serif; color: var(--ink); background: #fff; }}
  header {{ background: var(--accent); color: #fff; }}
  header div, main {{ max-width: 960px; margin: 0 auto; padding: 16px; }}
  header p {{ margin: 0; opacity: 0.85; }}
  header a {{ color: inherit; text-decoration: none; font-size: 1.5rem; font-weight: 700; }}
  .mock {{ font-size: 0.875rem; color: var(--muted); border-bottom: 1px solid var(--rule);
    padding-bottom: 12px; margin: 0 0 16px; }}
  .notice {{ padding: 12px 16px; border-left: 4px solid #e5a000; background: #faf3d1; }}
  .notice.good {{ border-color: #00a91c; background: #ecf3ec; }}
  .listings {{ list-style: none; margin: 0; padding: 0; display: grid; gap: 16px;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); }}
  .listings li {{ border: 1px solid var(--rule); padding: 16px; display: flex;
    flex-direction: column; }}
  h2 {{ font-size: 1.125rem; margin: 0 0 4px; }}
  .price {{ font-size: 1.25rem; font-weight: 700; margin: 0; }}
  .facts {{ color: var(--muted); margin: 0 0 8px; }}
  .description {{ margin: 0 0 12px; flex: 1; }}
  label {{ display: flex; gap: 8px; align-items: flex-start; font-size: 0.875rem;
    color: var(--muted); margin-bottom: 12px; }}
  label input {{ margin: 3px 0 0; accent-color: var(--accent); }}
  button {{ font: inherit; font-weight: 600; color: #fff; background: var(--accent);
    border: 0; padding: 10px 16px; cursor: pointer; }}
  .listings button {{ width: 100%; }}
  main a {{ color: var(--accent); }}
  button:hover {{ filter: brightness(1.15); }}
  :focus-visible {{ outline: 3px solid #2491ff; outline-offset: 2px; }}
  .empty {{ color: var(--muted); }}
</style>
</head>
<body>
<header><div><a href="/">{escape(spec.label)}</a><p>{escape(spec.tagline)}</p></div></header>
<main>
<p class="mock">A mock storefront for the Turnstone demo. Nothing here is real, and buying
costs nothing.</p>
{body}
</main>
</body>
</html>
"""


def create_app(spec: ChannelSpec) -> FastAPI:
    app = FastAPI(title=f"{spec.label} (mock channel)", version="0.1.0")
    app.state.spec = spec
    app.include_router(seller_api)
    app.include_router(storefront)
    return app
