"""The sales insight dashboards for managers, over the synthetic history and the live mock channels.

The store has no sales history, so time to sell, seasonality and the triage funnel are read from
`synthetic_items` and `synthetic_listings`, which app/synthetic_sales.py loads. The live side comes
from what the mock channels actually did, in `items`, `listings`, `sale_events`, `triage_log` and
`sync_log`, and the two are never added together, so the page can label each one. Every function
here reads one view and changes nothing, so the insight chat can call the same ones.
"""

import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

import sqlalchemy as sa
from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import distinct_on
from sqlmodel import Session, col, select

from app.appraisal import SessionDep
from app.auth import ManagerProfile
from app.models import (
    Appraisal,
    Category,
    ConflictKind,
    Decision,
    DecisionChoice,
    Item,
    ItemCard,
    Job,
    JobStatus,
    Listing,
    ListingStatus,
    Recommendation,
    SaleEvent,
    SaleSource,
    SyncEvent,
    SyncLogEntry,
    SyntheticItem,
    SyntheticListing,
    TriageEntry,
    TriageOutcome,
)
from app.settings import SyntheticSales
from app.synthetic_sales import price_band

router = APIRouter(prefix="/dashboards")

# A rate per listing-day reads as "out of 100 live listings, this many sell in a week".
LISTINGS_PER_RATE = 100
DAYS_PER_RATE = 7


class PriceBandRead(BaseModel):
    """One price band, from its low price up to but not including its high one."""

    band: int
    low_cents: int | None
    high_cents: int | None


class HistorySpan(BaseModel):
    """What the synthetic history covers, so the page can say which dates it is."""

    first_forwarded_on: date
    last_forwarded_on: date
    items: int
    listings: int
    sales: int
    run_days: int


class SyntheticTimeToSell(BaseModel):
    category: Category
    band: int
    listed: int
    sold: int
    # The middle of the days from listing to sale, over the listings that sold in their run.
    median_days: float | None


class LiveTimeToSell(BaseModel):
    category: Category
    band: int
    # Listings a channel confirmed, and those of them that sold.
    listed: int
    sold: int
    # Hours rather than days, because a demo sale can come minutes after the listing went up.
    median_hours: float | None


class TimeToSell(BaseModel):
    synthetic: list[SyntheticTimeToSell]
    # Only the categories and bands that have a confirmed listing.
    live: list[LiveTimeToSell]


class SeasonMonth(BaseModel):
    category: Category
    # The calendar month, 1 for January, gathered across every year of the history.
    month: int
    sales: int
    # Days that listings of this category were up in this month, including the day one sold.
    listing_days: int
    # Sales for every 100 listings up for a week, or None with no listing up that month.
    sales_per_100_weekly: float | None


class FunnelCounts(BaseModel):
    forwarded: int
    accepted: int
    listed: int
    sold: int
    # Staff calls on a yes or a no, and how many of them went against it.
    called: int
    against_recommendation: int


class SyntheticFunnel(FunnelCounts):
    category: Category


class TriageFunnel(BaseModel):
    synthetic: list[SyntheticFunnel]
    live: FunnelCounts


class FlagCount(BaseModel):
    conflict: ConflictKind
    open: int
    resolved: int


class SyncHealth(BaseModel):
    """What sync did on the mock channels, and where Turnstone and a channel disagreed."""

    first_event_at: datetime | None
    last_event_at: datetime | None
    published: int
    publish_rejected: int
    # Tries that failed, often several for one listing while its channel was down.
    publish_failed: int
    publish_gave_up: int
    sales_by_webhook: int
    sales_by_polling: int
    delisted: int
    delist_failed: int
    delist_gave_up: int
    delist_found_sold: int
    flags: list[FlagCount]
    # Items with more than one order that hasn't been cancelled, which should always be 0.
    oversold_items: int
    jobs_waiting: int
    jobs_given_up: int


class Dashboards(BaseModel):
    price_bands: list[PriceBandRead]
    # None when no synthetic history is loaded, and then every synthetic list is empty.
    history: HistorySpan | None
    time_to_sell: TimeToSell
    seasonality: list[SeasonMonth]
    triage_funnel: TriageFunnel
    sync_health: SyncHealth


def price_bands(params: SyntheticSales) -> list[PriceBandRead]:
    edges = params.price_band_edges_cents
    lows: list[int | None] = [None, *edges]
    highs: list[int | None] = [*edges, None]
    return [
        PriceBandRead(band=band, low_cents=low, high_cents=high)
        for band, (low, high) in enumerate(zip(lows, highs, strict=True))
    ]


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _synthetic_rows(session: Session) -> list[tuple[SyntheticListing, SyntheticItem]]:
    rows = session.exec(
        select(SyntheticListing, SyntheticItem)
        .join(SyntheticItem, col(SyntheticItem.id) == col(SyntheticListing.item_id))
        .order_by(col(SyntheticListing.id))
    ).all()
    return [(listing, item) for listing, item in rows]


def history_span(session: Session, params: SyntheticSales) -> HistorySpan | None:
    first, last, items = session.exec(
        select(
            sa.func.min(SyntheticItem.forwarded_on),
            sa.func.max(SyntheticItem.forwarded_on),
            sa.func.count(),
        ).select_from(SyntheticItem)
    ).one()
    if first is None or last is None:
        return None
    listings, sales = session.exec(
        select(sa.func.count(), sa.func.count(col(SyntheticListing.sold_on))).select_from(
            SyntheticListing
        )
    ).one()
    return HistorySpan(
        first_forwarded_on=first,
        last_forwarded_on=last,
        items=items,
        listings=listings,
        sales=sales,
        run_days=params.max_days,
    )


def synthetic_time_to_sell(session: Session, params: SyntheticSales) -> list[SyntheticTimeToSell]:
    """Every category and band, with the days each sold listing took, from the synthetic history."""
    if history_span(session, params) is None:
        return []
    listed: Counter[tuple[Category, int]] = Counter()
    days: defaultdict[tuple[Category, int], list[float]] = defaultdict(list)
    for listing, item in _synthetic_rows(session):
        key = (item.category, price_band(params, listing.price_cents))
        listed[key] += 1
        if listing.sold_on is not None:
            days[key].append((listing.sold_on - listing.listed_on).days)
    return [
        SyntheticTimeToSell(
            category=category,
            band=band.band,
            listed=listed[(category, band.band)],
            sold=len(days[(category, band.band)]),
            median_days=_median(days[(category, band.band)]),
        )
        for category in Category
        for band in price_bands(params)
    ]


def live_time_to_sell(session: Session, params: SyntheticSales) -> list[LiveTimeToSell]:
    """The listings a mock channel confirmed, by the item card's category and the listing price.

    A listing counts as sold while it is marked sold, from its confirmed listing to the time the
    channel took its order, so a double sale's cancelled order isn't counted.
    """
    first_sale = (
        sa.select(col(SaleEvent.listing_id), sa.func.min(SaleEvent.sold_at).label("sold_at"))
        .where(col(SaleEvent.cancelled_at).is_(None))
        .group_by(col(SaleEvent.listing_id))
        .subquery()
    )
    query = (
        sa.select(
            col(ItemCard.category),
            col(Listing.price_cents),
            col(Listing.status),
            col(Listing.published_at),
            first_sale.c.sold_at,
        )
        .join(ItemCard, col(ItemCard.item_id) == col(Listing.item_id))
        .outerjoin(first_sale, first_sale.c.listing_id == col(Listing.id))
        .where(col(Listing.published_at).is_not(None))
    )
    rows = session.connection().execute(query).all()
    listed: Counter[tuple[Category, int]] = Counter()
    hours: defaultdict[tuple[Category, int], list[float]] = defaultdict(list)
    for category, price_cents, status, published_at, sold_at in rows:
        key = (category, price_band(params, price_cents))
        listed[key] += 1
        if status is ListingStatus.SOLD and published_at is not None and sold_at is not None:
            elapsed = max(sold_at - published_at, timedelta(0))
            hours[key].append(elapsed.total_seconds() / 3600)
    order = list(Category)
    return [
        LiveTimeToSell(
            category=category,
            band=band,
            listed=count,
            sold=len(hours[(category, band)]),
            median_hours=_median(hours[(category, band)]),
        )
        for (category, band), count in sorted(
            listed.items(), key=lambda entry: (order.index(entry[0][0]), entry[0][1])
        )
    ]


def seasonality(session: Session, params: SyntheticSales) -> list[SeasonMonth]:
    """Each category's sales against the listings up, by calendar month, from the history.

    Counting sales alone would show the history filling up and running out at its two ends, so
    each month's sales are taken over the days listings were up in it.
    """
    if history_span(session, params) is None:
        return []
    sales: Counter[tuple[Category, int]] = Counter()
    listing_days: Counter[tuple[Category, int]] = Counter()
    for listing, item in _synthetic_rows(session):
        # Up from the day it was listed through the day it sold, or until the day it ended.
        last = listing.sold_on or (listing.ended_on or listing.listed_on) - timedelta(days=1)
        day = listing.listed_on
        while day <= last:
            listing_days[(item.category, day.month)] += 1
            day += timedelta(days=1)
        if listing.sold_on is not None:
            sales[(item.category, listing.sold_on.month)] += 1
    rows: list[SeasonMonth] = []
    for category in Category:
        for month in range(1, 13):
            up = listing_days[(category, month)]
            sold = sales[(category, month)]
            rate = sold / up * LISTINGS_PER_RATE * DAYS_PER_RATE if up else None
            rows.append(
                SeasonMonth(
                    category=category,
                    month=month,
                    sales=sold,
                    listing_days=up,
                    sales_per_100_weekly=rate,
                )
            )
    return rows


def synthetic_funnel(session: Session) -> list[SyntheticFunnel]:
    items = session.exec(select(SyntheticItem)).all()
    if not items:
        return []
    rows = _synthetic_rows(session)
    listed = Counter(item.category for _, item in rows)
    sold = Counter(item.category for listing, item in rows if listing.sold_on is not None)
    funnels: list[SyntheticFunnel] = []
    for category in Category:
        mine = [item for item in items if item.category is category]
        funnels.append(
            SyntheticFunnel(
                category=category,
                forwarded=len(mine),
                accepted=sum(item.outcome is TriageOutcome.ACCEPTED for item in mine),
                listed=listed[category],
                sold=sold[category],
                called=sum(item.recommendation is not Recommendation.CHECK for item in mine),
                against_recommendation=sum(item.overridden for item in mine),
            )
        )
    return funnels


def live_funnel(session: Session) -> FunnelCounts:
    """The real items so far, each counted by the call that stands on it, the newest one."""
    forwarded = session.exec(select(sa.func.count()).select_from(Item)).one()
    latest_triage = (
        sa.select(col(TriageEntry.item_id), col(TriageEntry.outcome))
        .ext(distinct_on(col(TriageEntry.item_id)))
        .order_by(
            col(TriageEntry.item_id), col(TriageEntry.recorded_at).desc(), col(TriageEntry.id)
        )
        .subquery()
    )
    accepted = session.exec(
        select(sa.func.count())
        .select_from(latest_triage)
        .where(latest_triage.c.outcome == TriageOutcome.ACCEPTED)
    ).one()
    listed = session.exec(
        select(sa.func.count(sa.distinct(col(Listing.item_id)))).where(
            col(Listing.published_at).is_not(None)
        )
    ).one()
    sold = session.exec(
        select(sa.func.count(sa.distinct(col(SaleEvent.item_id)))).where(
            col(SaleEvent.cancelled_at).is_(None)
        )
    ).one()
    latest_decision = (
        sa.select(col(Decision.decision), col(Appraisal.recommendation))
        .join(Appraisal, col(Appraisal.id) == col(Decision.appraisal_id))
        .ext(distinct_on(col(Decision.item_id)))
        .order_by(col(Decision.item_id), col(Decision.decided_at).desc(), col(Decision.id))
        .subquery()
    )
    calls = session.exec(
        select(latest_decision.c.decision, latest_decision.c.recommendation).where(
            latest_decision.c.recommendation != Recommendation.CHECK
        )
    ).all()
    against = sum(
        (recommendation == Recommendation.YES) != (decision == DecisionChoice.YES)
        for decision, recommendation in calls
    )
    return FunnelCounts(
        forwarded=forwarded,
        accepted=accepted,
        listed=listed,
        sold=sold,
        called=len(calls),
        against_recommendation=against,
    )


def sync_health(session: Session) -> SyncHealth:
    events = Counter(
        dict(
            session.exec(
                select(SyncLogEntry.event, sa.func.count()).group_by(col(SyncLogEntry.event))
            ).all()
        )
    )
    first, last = session.exec(
        select(sa.func.min(SyncLogEntry.created_at), sa.func.max(SyncLogEntry.created_at))
    ).one()
    sources = Counter(
        dict(
            session.exec(
                select(SaleEvent.source, sa.func.count()).group_by(col(SaleEvent.source))
            ).all()
        )
    )
    open_flags = Counter(
        dict(
            session.exec(
                select(SyncLogEntry.conflict, sa.func.count())
                .where(col(SyncLogEntry.conflict).is_not(None))
                .where(col(SyncLogEntry.resolved_at).is_(None))
                .group_by(col(SyncLogEntry.conflict))
            ).all()
        )
    )
    resolved_flags = Counter(
        dict(
            session.exec(
                select(SyncLogEntry.conflict, sa.func.count())
                .where(col(SyncLogEntry.conflict).is_not(None))
                .where(col(SyncLogEntry.resolved_at).is_not(None))
                .group_by(col(SyncLogEntry.conflict))
            ).all()
        )
    )
    live_orders = (
        sa.select(col(SaleEvent.item_id))
        .where(col(SaleEvent.cancelled_at).is_(None))
        .group_by(col(SaleEvent.item_id))
        .having(sa.func.count() > 1)
        .subquery()
    )
    oversold = session.exec(select(sa.func.count()).select_from(live_orders)).one()
    jobs = Counter(
        dict(session.exec(select(Job.status, sa.func.count()).group_by(col(Job.status))).all())
    )
    return SyncHealth(
        first_event_at=first,
        last_event_at=last,
        published=events[SyncEvent.PUBLISHED],
        publish_rejected=events[SyncEvent.PUBLISH_REJECTED],
        publish_failed=events[SyncEvent.PUBLISH_FAILED],
        publish_gave_up=events[SyncEvent.PUBLISH_GAVE_UP],
        sales_by_webhook=sources[SaleSource.WEBHOOK],
        sales_by_polling=sources[SaleSource.POLLING],
        delisted=events[SyncEvent.DELISTED],
        delist_failed=events[SyncEvent.DELIST_FAILED],
        delist_gave_up=events[SyncEvent.DELIST_GAVE_UP],
        delist_found_sold=events[SyncEvent.DELIST_FOUND_SOLD],
        flags=[
            FlagCount(conflict=kind, open=open_flags[kind], resolved=resolved_flags[kind])
            for kind in ConflictKind
        ],
        oversold_items=oversold,
        jobs_waiting=jobs[JobStatus.PENDING],
        jobs_given_up=jobs[JobStatus.FAILED],
    )


def dashboards(session: Session, params: SyntheticSales) -> Dashboards:
    return Dashboards(
        price_bands=price_bands(params),
        history=history_span(session, params),
        time_to_sell=TimeToSell(
            synthetic=synthetic_time_to_sell(session, params),
            live=live_time_to_sell(session, params),
        ),
        seasonality=seasonality(session, params),
        triage_funnel=TriageFunnel(synthetic=synthetic_funnel(session), live=live_funnel(session)),
        sync_health=sync_health(session),
    )


@router.get("", operation_id="get_dashboards")
def get_dashboards(manager: ManagerProfile, session: SessionDep) -> Dashboards:
    """The four views, with the synthetic history and the live mock channels kept apart."""
    return dashboards(session, SyntheticSales())
