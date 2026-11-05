"""Check the synthetic sales history against the published figures it is calibrated to.

Run `uv run python -m app.synthetic_calibration` in api/ to generate the history from many seeds,
print each calibration target beside the simulated mean and spread, then the hold-out and the shape
check, and rewrite api/eval/synthetic_sales_results.json and docs/synthetic-sales.md. It needs no
database, keys or network.
"""

import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from app.models import Category, Channel, Department
from app.settings import SyntheticSales
from app.synthetic_sales import History, Listing, generate, price_band

ROOT = Path(__file__).resolve().parents[2]
RESULTS_FILE = ROOT / "api" / "eval" / "synthetic_sales_results.json"
REPORT_FILE = ROOT / "docs" / "synthetic-sales.md"

SEEDS = range(1, 201)
# A target passes when the mean over the seeds is within this share of the published figure.
TOLERANCE = 0.25
# The slowest tenth of sales must take at least this many times the median, for a long tail.
TAIL_RATIO = 3.0


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TargetResult(_Strict):
    key: str
    measure: str
    source: str
    target: float
    unit: str
    # Over the seeds where the measure had any listings to count.
    mean: float
    low: float
    high: float
    seeds_measured: int
    off_by: float
    passed: bool


class ShapeResult(_Strict):
    sales: int
    mean_days: float
    median_days: float
    sd_days: float
    skewness: float
    p90_days: float
    max_days: int
    within_week_share: float
    passed: bool


class HistorySize(_Strict):
    seed: int
    items: int
    accepted: int
    listings: int
    sales: int


class CalibrationResults(_Strict):
    seeds: int
    tolerance: float
    history: HistorySize
    targets: list[TargetResult]
    holdout: TargetResult
    # Judged on Channel A, the general marketplace like the Mercari study's, see the report.
    shape: ShapeResult
    # Both channels together, which is what the time to sell chart shows, reported and not judged.
    shape_both_channels: ShapeResult
    parameters: dict[str, object]


Measure = Callable[[History], float | None]


@dataclass(frozen=True)
class Target:
    key: str
    measure: str
    source: str
    target: float
    unit: str
    compute: Measure


def _on(history: History, channel: Channel) -> list[Listing]:
    return [listing for listing in history.listings if listing.channel is channel]


def _womens_apparel(history: History, channel: Channel) -> list[Listing]:
    womens = {
        item.id
        for item in history.items
        if item.category is Category.APPAREL and item.department is Department.WOMENS
    }
    return [listing for listing in _on(history, channel) if listing.item_id in womens]


def sold_within(listings: Sequence[Listing], days: int) -> float | None:
    """The share of listings that sold within their first `days` days, or none with no listings."""
    if not listings:
        return None
    sold = sum(
        listing.days_to_sell is not None and listing.days_to_sell < days for listing in listings
    )
    return sold / len(listings)


def _days(listings: Sequence[Listing], within: int | None = None) -> list[int]:
    return [
        days
        for listing in listings
        if (days := listing.days_to_sell) is not None and (within is None or days < within)
    ]


def _median_or_none(values: Sequence[int]) -> float | None:
    return statistics.median(values) if values else None


def _mean_or_none(values: Sequence[int]) -> float | None:
    return statistics.fmean(values) if values else None


def _in_band(history: History, band: int) -> list[Listing]:
    params = SyntheticSales()
    return [
        listing
        for listing in _on(history, Channel.CHANNEL_A)
        if price_band(params, listing.price_cents) == band
    ]


FLOWLISTER = "FlowLister, 33,638 eBay listings"
CLOSO = "Closo, women's tops on Poshmark"

TARGETS = [
    Target(
        "a_sold_30",
        "Channel A, sold within 30 days",
        FLOWLISTER,
        0.122,
        "share",
        lambda history: sold_within(_on(history, Channel.CHANNEL_A), 30),
    ),
    Target(
        "a_sold_7",
        "Channel A, sold within 7 days",
        FLOWLISTER,
        0.058,
        "share",
        lambda history: sold_within(_on(history, Channel.CHANNEL_A), 7),
    ),
    Target(
        "a_median_30",
        "Channel A, median days to sale of those sold within 30 days",
        FLOWLISTER,
        7.5,
        "days",
        lambda history: _median_or_none(_days(_on(history, Channel.CHANNEL_A), within=30)),
    ),
    Target(
        "a_under_15",
        "Channel A under $15, sold within 30 days",
        FLOWLISTER,
        0.086,
        "share",
        lambda history: sold_within(_in_band(history, 0), 30),
    ),
    Target(
        "a_100_to_250",
        "Channel A at $100 to $249.99, sold within 30 days",
        FLOWLISTER,
        0.276,
        "share",
        lambda history: sold_within(_in_band(history, 4), 30),
    ),
    Target(
        "b_womens_mean_days",
        "Channel B women's apparel, average days to sale",
        CLOSO,
        59.0,
        "days",
        lambda history: _mean_or_none(_days(_womens_apparel(history, Channel.CHANNEL_B))),
    ),
    Target(
        "b_womens_sold_90",
        "Channel B women's apparel, sold within 90 days",
        CLOSO,
        0.37,
        "share",
        lambda history: sold_within(_womens_apparel(history, Channel.CHANNEL_B), 90),
    ),
]

HOLDOUT = Target(
    "a_womens_sold_90",
    "Channel A women's apparel, sold within 90 days",
    "Closo, tops on eBay, held out of calibration",
    0.28,
    "share",
    lambda history: sold_within(_womens_apparel(history, Channel.CHANNEL_A), 90),
)


def within_tolerance(target: float, mean: float, tolerance: float = TOLERANCE) -> bool:
    return abs(mean - target) <= tolerance * target


def _round(value: float, unit: str) -> float:
    return round(value, 2 if unit == "days" else 4)


def score(target: Target, histories: Sequence[History]) -> TargetResult:
    """The target beside the mean and the 5th to 95th percentile spread over the histories."""
    values = [value for history in histories if (value := target.compute(history)) is not None]
    if not values:
        raise ValueError(f"No history had any listings to measure {target.key}.")
    mean = statistics.fmean(values)
    if len(values) > 1:
        cuts = statistics.quantiles(values, n=20, method="inclusive")
        low, high = cuts[0], cuts[-1]
    else:
        low = high = values[0]
    return TargetResult(
        key=target.key,
        measure=target.measure,
        source=target.source,
        target=target.target,
        unit=target.unit,
        mean=_round(mean, target.unit),
        low=_round(low, target.unit),
        high=_round(high, target.unit),
        seeds_measured=len(values),
        off_by=round((mean - target.target) / target.target, 4),
        passed=within_tolerance(target.target, mean),
    )


def skewness(values: Sequence[float]) -> float:
    """The Fisher-Pearson skewness, above 0 when the values trail off to the right."""
    mean = statistics.fmean(values)
    spread = statistics.pstdev(values, mean)
    if spread == 0:
        return 0.0
    return statistics.fmean(((value - mean) / spread) ** 3 for value in values)


def shape_passes(mean: float, median: float, skew: float, p90: float) -> bool:
    """Skewed with a long tail: the mean above the median, a right skew and a slow last tenth."""
    return mean > median and skew > 0 and p90 >= TAIL_RATIO * median


def shape(histories: Sequence[History], channel: Channel | None = None) -> ShapeResult:
    """The days to sale of every sale in every history, on one channel or both."""
    days = [
        days
        for history in histories
        for days in _days(_on(history, channel) if channel else history.listings)
    ]
    mean, median = statistics.fmean(days), statistics.median(days)
    skew = skewness(days)
    p90 = statistics.quantiles(days, n=10, method="inclusive")[-1]
    return ShapeResult(
        sales=len(days),
        mean_days=round(mean, 2),
        median_days=median,
        sd_days=round(statistics.pstdev(days, mean), 2),
        skewness=round(skew, 3),
        p90_days=p90,
        max_days=max(days),
        within_week_share=round(sum(day < 7 for day in days) / len(days), 4),
        passed=shape_passes(mean, median, skew, p90),
    )


def history_size(history: History) -> HistorySize:
    return HistorySize(
        seed=history.seed,
        items=len(history.items),
        accepted=sum(item.outcome == "accepted" for item in history.items),
        listings=len(history.listings),
        sales=sum(listing.sold_on is not None for listing in history.listings),
    )


def run(seeds: Sequence[int] = SEEDS) -> CalibrationResults:
    params = SyntheticSales()
    histories = [generate(params, seed) for seed in seeds]
    return CalibrationResults(
        seeds=len(histories),
        tolerance=TOLERANCE,
        history=history_size(generate(params)),
        targets=[score(target, histories) for target in TARGETS],
        holdout=score(HOLDOUT, histories),
        shape=shape(histories, Channel.CHANNEL_A),
        shape_both_channels=shape(histories),
        parameters=params.model_dump(mode="json"),
    )


def results_json(results: CalibrationResults) -> str:
    return results.model_dump_json(indent=2) + "\n"


def _value(value: float, unit: str) -> str:
    return f"{value * 100:.1f}%" if unit == "share" else f"{value:.1f} days"


def _off(result: TargetResult) -> str:
    return f"{result.off_by * 100:+.1f}%"


def _target_row(result: TargetResult) -> str:
    return (
        f"| {result.measure} | {result.source} | {_value(result.target, result.unit)} "
        f"| {_value(result.mean, result.unit)} "
        f"| {_value(result.low, result.unit)} to {_value(result.high, result.unit)} "
        f"| {_off(result)} | {'yes' if result.passed else 'no'} |"
    )


TARGET_HEAD = [
    "| Measure | Source | Published | Simulated mean | 5th to 95th percentile | Off by "
    "| Within 25% |",
    "| --- | --- | --- | --- | --- | --- | --- |",
]


def _shape_row(name: str, result: ShapeResult) -> str:
    return (
        f"| {name} | {result.sales:,} | {result.mean_days:.1f} | {result.median_days:.1f} "
        f"| {result.sd_days:.1f} | {result.skewness:.2f} | {result.p90_days:.1f} "
        f"| {result.max_days} | {result.within_week_share * 100:.1f}% |"
    )


def _parameter(value: object) -> str:
    if isinstance(value, list | tuple):
        return ", ".join(str(part) for part in value)
    return str(value)


METHOD_LINES = [
    "Each month a number of items is forwarded to Ecommerce, drawn around an average of "
    "`monthly_items`, on days spread through the month.",
    "Each item comes from the clothing or the electronics and games department, and gets the "
    "category, apparel department and condition the app already uses, with the shares below.",
    "Its typical price is drawn from a log-normal spread around each category's middle price.",
    'The appraisal says "check" for a share of items, and otherwise yes at or above the $30 '
    "worth-listing bar in app/settings.py and no below it.",
    "Staff accept or reject each item at a rate for its department and recommendation, and a call "
    "against a yes or a no counts as an override.",
    "An accepted item is listed a few days later on one channel, Channel A for games and hardware "
    "and either channel for apparel, at its typical price.",
    "",
    "Each listing then runs day by day for up to 90 days.",
    "Its chance of selling on a day is 1 - exp(-r), where r is the channel's baseline for that day "
    "of the run multiplied by the factors for the item's price band, category and condition and "
    "the seasonal index for that day's month.",
    "The baseline is the rise over that day in a Weibull curve's cumulative rate, (d / scale) ** "
    "shape, so with every factor at 1 the share sold within d days is 1 - exp(-(d / scale) ** "
    "shape).",
    "Channel A's eBay baseline has a shape below 1, so its daily chance falls as a listing ages, "
    "with most sales early and a few much later.",
    "Channel B's Poshmark baseline has a shape above 1, so its daily chance rises as a listing "
    "ages.",
    "A listing that hasn't sold by the end of its run ends on its 90th day.",
    "",
    "One random number stream from the seed drives every draw in a fixed order, so the same seed "
    "always gives the same rows, and `uv run python -m app.synthetic_sales` replaces both tables "
    "with them in one transaction.",
    "The history lives in `synthetic_items` and `synthetic_listings`, apart from the real `items`, "
    "`sale_events` and `sync_log`, as [database.md](database.md#synthetic-sales-history) "
    "describes.",
]


def render_report(results: CalibrationResults) -> str:
    """The results as Markdown, generated so that a change shows up in review."""
    params = SyntheticSales()
    holdout = results.holdout
    size = results.history
    verdict = "within" if holdout.passed else "outside"
    lines = [
        "# Synthetic sales history",
        "",
        "This page is generated by `uv run python -m app.synthetic_calibration` in `api/`, so edit "
        "the script or `SyntheticSales` in `api/app/settings.py` instead of this page.",
        "",
        "**Every number here, and every chart drawn from this history, is synthetic.**",
        "The store has no sales history to show, so the dashboards run on one made by a model "
        "calibrated to published figures.",
        "Any seasonal pattern in the charts was put there by the seasonal index below, so the "
        "dashboards show what the app can do, not a finding about the store.",
        "",
        "## Result",
        "",
        f"The configured seed, {size.seed}, gives {size.items} items forwarded to Ecommerce, "
        f"{size.accepted} accepted, {size.listings} listings and {size.sales} sales.",
        f"The check generates the history from {results.seeds} other seeds and compares the mean "
        f"of each measure with its published figure, which passes within "
        f"{results.tolerance * 100:.0f}%.",
        "The spread is the 5th to 95th percentile of the measure across those seeds, so it shows "
        "how far one history, like the one in the database, can land from the mean.",
        "",
        *TARGET_HEAD,
        *(_target_row(result) for result in results.targets),
        "",
        "### Hold-out",
        "",
        "One published figure was kept out of the calibration and is checked only afterward.",
        "",
        *TARGET_HEAD,
        _target_row(holdout),
        "",
        f"The hold-out comes out at {_value(holdout.mean, holdout.unit)} against "
        f"{_value(holdout.target, holdout.unit)}, {abs(holdout.off_by) * 100:.1f}% "
        f"{'low' if holdout.off_by < 0 else 'high'}, which is {verdict} the "
        f"{results.tolerance * 100:.0f}% band.",
        "No parameter was changed to move it, because a hold-out that is tuned to stops being a "
        "check.",
        "",
        "### Shape of the time to sell",
        "",
        "A study of Mercari Japan reports a mean time to sell of 19.4 days with a standard "
        "deviation of 50 and a maximum of more than 1,400 days, which is many quick sales and a "
        "long tail.",
        "The figure is used only to check the shape, so the check passes when the mean is above "
        "the median, the skewness is above 0, and the slowest tenth of sales take at least "
        f"{TAIL_RATIO:.0f} times the median.",
        "It is judged on Channel A, because Mercari is a general marketplace like eBay, and "
        "Channel B's rising curve puts its sales late in the run by design.",
        "",
        "| Sales on | Sales | Mean days | Median days | Standard deviation | Skewness "
        "| 90th percentile | Longest | Sold in the first week |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        _shape_row("Channel A", results.shape),
        _shape_row("Both channels, not judged", results.shape_both_channels),
        "",
        f"Channel A {'passes' if results.shape.passed else 'fails'} the shape check.",
        "No sale can take longer than the 90-day run, so the tail stops far short of Mercari's "
        "1,400 days.",
        "",
        "## How the history is made",
        "",
        *METHOD_LINES,
        "",
        "## Parameters",
        "",
        "Each parameter says where it comes from: a published figure it is calibrated to, a "
        'choice about the history itself, or "Assumed" when nothing published backs it.',
        "The shares and factors in threes are in the order given in their source line.",
        "",
        "| Parameter | Value | Source |",
        "| --- | --- | --- |",
    ]
    for name, field in SyntheticSales.model_fields.items():
        lines.append(f"| `{name}` | {_parameter(getattr(params, name))} | {field.description} |")
    lines += [
        "",
        "## Sources",
        "",
        "- FlowLister's [eBay listing data study](https://flowlister.com/ebay-listing-data-study/) "
        "of 33,638 single-unit eBay US listings: 12.2% sold within 30 days, 5.8% within a week, a "
        "median of 7.5 days to sale among those sold within 30 days, and 30-day sell-through of "
        "8.6% under $15 against 27.6% at $100 to $249.99.",
        "- Closo's [comparison of clothing marketplaces](https://closo.co/blogs/inventory-"
        "liquidation/top-clothing-marketplaces-for-resale): women's tops on Poshmark averaged 59 "
        "days to sale with 37% sell-through, and tops on eBay had 28% sell-through over 90 days, "
        "which is the hold-out.",
        "- A study of Mercari Japan with a mean time to sell of 19.4 days, a standard deviation of "
        "50 and a maximum of more than 1,400 days, used only for the shape check.",
        "- A thrift retail practitioner's article saying seasonal clothing sales peak at the start "
        "of the season and fall off after, which is the only support for the seasonal index, so "
        "its values are assumed.",
        "- Nothing published backs the intake and funnel rates, which are the share forwarded, "
        "accepted, rejected and overridden in each department, so they are assumed.",
        "",
        "## Limits",
        "",
        "- FlowLister and Closo sell tools to resellers, so their figures are samples they report "
        "about their own users, not audited data.",
        "- The app has no category for tops, so the Closo figures are compared with women's "
        "apparel on each channel.",
        "- Closo's Poshmark figures cover a trailing year rather than a 90-day run, so matching a "
        "59-day average inside 90 days needs Channel B's chance to rise with age.",
        "  That rise is a fit to the figure, not evidence about how Poshmark sells.",
        "- Each item is listed on one channel, while the app lists an item on every channel that "
        "takes it, because the published figures are for one marketplace each and a sale on one "
        "channel would cut the other's sell-through.",
        "- Groups with few listings, such as items under $15, move a lot from one seed to the "
        "next, as the spread shows, so one history can be far from the published figure even "
        "when the mean is close.",
        "- The sale price is the asking price, because the history has no offers or price drops.",
    ]
    return "\n".join(lines) + "\n"


def _line(result: TargetResult) -> str:
    return (
        f"{result.measure}: published {_value(result.target, result.unit)}, simulated "
        f"{_value(result.mean, result.unit)} ({_value(result.low, result.unit)} to "
        f"{_value(result.high, result.unit)}), off by {_off(result)}, "
        f"{'within' if result.passed else 'outside'} {TOLERANCE * 100:.0f}%"
    )


def main() -> None:
    results = run()
    RESULTS_FILE.write_text(results_json(results), encoding="utf-8", newline="\n")
    REPORT_FILE.write_text(render_report(results), encoding="utf-8", newline="\n")
    print(f"Calibration over {results.seeds} seeds, mean and 5th to 95th percentile:")
    for result in results.targets:
        print(f"- {_line(result)}")
    print(f"Hold-out, not used in calibration: {_line(results.holdout)}")
    shape_a = results.shape
    print(
        f"Shape on Channel A: mean {shape_a.mean_days:.1f} days, median {shape_a.median_days:.1f}, "
        f"skewness {shape_a.skewness:.2f}, 90th percentile {shape_a.p90_days:.1f}, "
        f"{'passes' if shape_a.passed else 'fails'}"
    )
    passed = sum(result.passed for result in results.targets)
    print(
        f"{passed} of {len(results.targets)} targets pass. Wrote {RESULTS_FILE} and {REPORT_FILE}."
    )


if __name__ == "__main__":
    main()
