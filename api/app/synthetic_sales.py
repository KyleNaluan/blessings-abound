"""A synthetic sales history for the dashboards, because the store has no real one to show.

Run `uv run python -m app.synthetic_sales` in api/ to replace the history in the database with the
one from the fixed seed in `SyntheticSales` in app/settings.py, or add `--seed N` for another one.
The same seed always gives the same rows, and it writes only `synthetic_items` and
`synthetic_listings`, never the real items, sales or sync log.

Each month a number of items is forwarded to Ecommerce, each gets a price, an appraisal and a staff
call, and each accepted item is listed on one channel. A listing then has a chance of selling on
each day of its run, which is the channel's baseline for that day of the run multiplied by factors
for the price band, the category, the condition and the month. The method, the parameters and how
well they match the published figures are in docs/synthetic-sales.md, which
`app.synthetic_calibration` writes.
"""

import argparse
import math
import random
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import date, timedelta

from sqlalchemy import delete, insert
from sqlmodel import Session

from app.db import get_engine
from app.models import (
    Category,
    Channel,
    Condition,
    Department,
    Recommendation,
    StoreDepartment,
    SyntheticItem,
    SyntheticListing,
    TriageOutcome,
)
from app.settings import PricingRules, SyntheticSales

DEPARTMENTS = (Department.MENS, Department.WOMENS, Department.KIDS)
CONDITIONS = (Condition.NEW_WITH_TAGS, Condition.NEW_WITHOUT_TAGS, Condition.PRE_OWNED)
# The pricing rule's bar, so the synthetic yes and no follow the same line the app draws.
WORTH_LISTING_CENTS = PricingRules().worth_listing_threshold_cents


@dataclass(frozen=True)
class Item:
    id: int
    forwarded_on: date
    store_department: StoreDepartment
    category: Category
    department: Department | None
    condition: Condition
    typical_price_cents: int
    recommendation: Recommendation
    outcome: TriageOutcome
    overridden: bool


@dataclass(frozen=True)
class Listing:
    id: int
    item_id: int
    channel: Channel
    price_cents: int
    listed_on: date
    sold_on: date | None
    ended_on: date | None

    @property
    def days_to_sell(self) -> int | None:
        """Days from listing to sale, 0 for a sale on the day it was listed."""
        return None if self.sold_on is None else (self.sold_on - self.listed_on).days


@dataclass(frozen=True)
class History:
    seed: int
    items: list[Item]
    listings: list[Listing]


def _poisson(rng: random.Random, mean: float) -> int:
    """A Poisson count by multiplying uniforms, which is exact and quick for a mean of about 50."""
    limit, count, product = math.exp(-mean), 0, rng.random()
    while product > limit:
        count += 1
        product *= rng.random()
    return count


def _add_months(day: date, months: int) -> date:
    total = day.month - 1 + months
    return date(day.year + total // 12, total % 12 + 1, 1)


def price_band(params: SyntheticSales, cents: int) -> int:
    """The index of the price band a price falls in, from 0 for the cheapest."""
    return sum(cents >= edge for edge in params.price_band_edges_cents)


def baseline(params: SyntheticSales, channel: Channel) -> list[float]:
    """The channel's baseline for each day of the run, before the factors.

    It is the rise in a Weibull curve's cumulative rate over that day, so with every factor at 1
    the share sold within d days is 1 - exp(-(d / scale) ** shape).
    """
    if channel is Channel.CHANNEL_A:
        scale, shape = params.channel_a_scale_days, params.channel_a_shape
    else:
        scale, shape = params.channel_b_scale_days, params.channel_b_shape
    return [((day + 1) / scale) ** shape - (day / scale) ** shape for day in range(params.max_days)]


def item_factor(params: SyntheticSales, item: Item, price_cents: int) -> float:
    """The price band, category and condition factors multiplied together."""
    category = (
        params.apparel_factor
        if item.category is Category.APPAREL
        else params.electronics_games_factor
    )
    return (
        params.price_band_factors[price_band(params, price_cents)]
        * category
        * params.condition_factors[CONDITIONS.index(item.condition)]
    )


def _seasonal(params: SyntheticSales, category: Category) -> Sequence[float]:
    if category is Category.APPAREL:
        return params.apparel_seasonal_index
    return params.electronics_games_seasonal_index


def _staff_call(
    params: SyntheticSales, rng: random.Random, department: StoreDepartment, price_cents: int
) -> tuple[Recommendation, TriageOutcome]:
    if rng.random() < params.check_share:
        recommendation = Recommendation.CHECK
    elif price_cents >= WORTH_LISTING_CENTS:
        recommendation = Recommendation.YES
    else:
        recommendation = Recommendation.NO
    prefix = "clothing" if department is StoreDepartment.CLOTHING else "electronics_games"
    accept = getattr(params, f"{prefix}_accept_if_{recommendation.value}")
    outcome = TriageOutcome.ACCEPTED if rng.random() < accept else TriageOutcome.REJECTED
    return recommendation, outcome


def _overridden(recommendation: Recommendation, outcome: TriageOutcome) -> bool:
    if recommendation is Recommendation.YES:
        return outcome is TriageOutcome.REJECTED
    return recommendation is Recommendation.NO and outcome is TriageOutcome.ACCEPTED


def _forwarded_days(params: SyntheticSales, rng: random.Random) -> list[date]:
    days: list[date] = []
    for month in range(params.months):
        start = _add_months(params.first_day.replace(day=1), month)
        length = (_add_months(start, 1) - start).days
        days.extend(
            sorted(
                start + timedelta(days=rng.randrange(length))
                for _ in range(_poisson(rng, params.monthly_items))
            )
        )
    return days


def _new_item(params: SyntheticSales, rng: random.Random, number: int, day: date) -> Item:
    if rng.random() < params.clothing_share:
        store_department, category = StoreDepartment.CLOTHING, Category.APPAREL
        department = rng.choices(DEPARTMENTS, weights=params.apparel_department_shares)[0]
        conditions = params.apparel_condition_shares
        median, spread = params.apparel_median_price_cents, params.apparel_price_spread
    else:
        store_department, category = StoreDepartment.ELECTRONICS_GAMES, Category.ELECTRONICS_GAMES
        department = None
        conditions = params.electronics_games_condition_shares
        median = params.electronics_games_median_price_cents
        spread = params.electronics_games_price_spread
    condition = rng.choices(CONDITIONS, weights=conditions)[0]
    price = max(100, round(rng.lognormvariate(math.log(median), spread)))
    recommendation, outcome = _staff_call(params, rng, store_department, price)
    return Item(
        id=number,
        forwarded_on=day,
        store_department=store_department,
        category=category,
        department=department,
        condition=condition,
        typical_price_cents=price,
        recommendation=recommendation,
        outcome=outcome,
        overridden=_overridden(recommendation, outcome),
    )


def _run(
    params: SyntheticSales,
    rng: random.Random,
    item: Item,
    number: int,
    baselines: dict[Channel, list[float]],
) -> Listing:
    """List an accepted item and run it day by day until it sells or its run ends."""
    listed_on = item.forwarded_on + timedelta(days=rng.randint(1, params.max_listing_lag_days))
    channel = Channel.CHANNEL_A
    if item.category is Category.APPAREL and rng.random() < params.channel_b_share:
        channel = Channel.CHANNEL_B
    price = item.typical_price_cents
    factor = item_factor(params, item, price)
    seasonal = _seasonal(params, item.category)
    sold_on = None
    for offset, rate in enumerate(baselines[channel]):
        day = listed_on + timedelta(days=offset)
        if rng.random() < 1 - math.exp(-rate * factor * seasonal[day.month - 1]):
            sold_on = day
            break
    ended_on = None if sold_on else listed_on + timedelta(days=params.max_days)
    return Listing(
        id=number,
        item_id=item.id,
        channel=channel,
        price_cents=price,
        listed_on=listed_on,
        sold_on=sold_on,
        ended_on=ended_on,
    )


def generate(params: SyntheticSales, seed: int | None = None) -> History:
    """The history for one seed, which is the configured seed unless another is given."""
    seed = params.seed if seed is None else seed
    rng = random.Random(seed)
    baselines = {channel: baseline(params, channel) for channel in Channel}
    items: list[Item] = []
    listings: list[Listing] = []
    for number, day in enumerate(_forwarded_days(params, rng), start=1):
        item = _new_item(params, rng, number, day)
        items.append(item)
        if item.outcome is TriageOutcome.ACCEPTED:
            listings.append(_run(params, rng, item, len(listings) + 1, baselines))
    return History(seed=seed, items=items, listings=listings)


def _rows(records: Iterable[Item | Listing]) -> list[dict[str, object]]:
    return [asdict(record) for record in records]


def load(session: Session, history: History) -> None:
    """Replace the synthetic tables with this history, in the session's transaction."""
    session.execute(delete(SyntheticListing))
    session.execute(delete(SyntheticItem))
    if history.items:
        session.execute(insert(SyntheticItem), _rows(history.items))
    if history.listings:
        session.execute(insert(SyntheticListing), _rows(history.listings))


def main(arguments: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Load the synthetic sales history.")
    parser.add_argument("--seed", type=int, help="another seed instead of the configured one")
    options = parser.parse_args(arguments)
    history = generate(SyntheticSales(), options.seed)
    with Session(get_engine()) as session:
        load(session, history)
        session.commit()
    sold = sum(listing.sold_on is not None for listing in history.listings)
    print(
        f"Loaded the synthetic history from seed {history.seed}: {len(history.items)} items, "
        f"{len(history.listings)} listings and {sold} sales, replacing any history before it."
    )


if __name__ == "__main__":
    main()
