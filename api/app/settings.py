from datetime import date
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.models import Confidence

# The single .env file lives at the repository root and is shared with docker compose and web/.
ROOT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class PricingRules(BaseModel):
    """The numbers behind the pricing pipeline in docs/architecture.md, each with its reason.

    The worth-listing threshold, the fees and both ask-to-sale factors are the starting values of
    the Settings page, and an appraisal reads them from there through `pricing_rules` in
    app/store_settings.py.
    """

    model_config = ConfigDict(frozen=True)

    ask_to_sale_factor: float = Field(
        default=0.645,
        description="Assumption, for apparel: comps are asking prices, and this came from Poshmark "
        "ratios of 1.21 to 2.93, not from eBay sales.",
    )
    games_ask_to_sale_factor: float = Field(
        default=0.94,
        description="Assumption, for games and hardware: one over the median 1.06 asking price per "
        "sold price on 18 tuning items, see docs/evaluation.md.",
    )
    games_low_percentile: float = Field(
        default=0.15,
        description="The low end of the range for games and hardware, because sold prices often "
        "fell outside the middle half of asking prices on the tuning items.",
    )
    games_high_percentile: float = Field(
        default=0.85, description="The high end of that range, at the same distance from the top."
    )
    tukey_fence_multiplier: float = Field(
        default=1.5, description="The standard Tukey fence width, applied to log price."
    )
    tukey_min_comps: int = Field(
        default=4, description="Below this, quartiles are too thin to call any listing an outlier."
    )
    high_confidence_min_comps: int = Field(
        default=10, description="Enough listings that one odd price barely moves the range."
    )
    high_confidence_max_spread: float = Field(
        default=2.0, description="A high price within twice the low means one market level."
    )
    medium_confidence_min_comps: int = Field(
        default=5, description="The fewest listings that still show a range, not a few anecdotes."
    )
    medium_confidence_max_spread: float = Field(
        default=3.0, description="Past three times the low, the comps likely mix different items."
    )
    worth_listing_threshold_cents: int = Field(
        default=3000, description="The client's stated bar for a typical sale price worth listing."
    )
    fee_rate: float = Field(
        default=0.136, description="eBay's final value fee for most categories."
    )
    per_order_fee_cents: int = Field(default=40, description="eBay's fixed fee on each order.")
    supplies_cents: int = Field(
        default=150, description="Assumption: the packaging cost of shipping one item."
    )


class PhotoChecks(BaseModel):
    """The numbers behind the blur and brightness check at intake, each with its reason.

    They were measured on 53 evaluation photos, as the photo check section of docs/architecture.md
    describes, and a photo that fails one is a prompt to take it again, never a refusal.
    """

    model_config = ConfigDict(frozen=True)

    long_side: int = Field(
        default=640,
        description="Photos are scaled to this size first, so a full-size phone photo and a small "
        "upload score alike.",
    )
    grid: int = Field(
        default=8,
        description="The photo is cut into this many columns and rows and only the sharpest piece "
        "counts, so a plain backdrop can't make a sharp item look blurry.",
    )
    min_sharpness: float = Field(
        default=100.0,
        description="Every sharp evaluation photo scored at least 129 and every one blurred by 2 "
        "pixels at most 55, so 100 sits between them.",
    )
    tail_share: float = Field(
        default=0.05,
        description="The share of the brightest and darkest pixels read for brightness, so a few "
        "glints or shadows don't decide it.",
    )
    min_bright_end: int = Field(
        default=100,
        description="Too dark when even the brightest 5% is below this out of 255, where every "
        "evaluation photo was at least 163 and every one at 35% of its light at most 89.",
    )
    max_dark_end: int = Field(
        default=210,
        description="Washed out when even the darkest 5% is above this out of 255, where every "
        "evaluation photo, white items on white included, was at most 183.",
    )


Shares = tuple[float, float, float]
MonthlyIndex = tuple[
    float, float, float, float, float, float, float, float, float, float, float, float
]


class SyntheticSales(BaseModel):
    """The numbers behind the synthetic sales history in app/synthetic_sales.py, with sources.

    Each description starts with where the number comes from: a published figure it is calibrated
    to, a choice about the history itself, or "Assumed" when nothing published backs it. They are
    read from code rather than the environment, so the history in the database and the calibration
    report in docs/synthetic-sales.md always describe the same numbers.
    """

    model_config = ConfigDict(frozen=True)

    seed: int = Field(
        default=2026,
        description="Choice: the fixed seed, so every load gives the same history, and any other "
        "whole number gives a different one.",
    )
    first_day: date = Field(
        default=date(2025, 7, 1),
        description="Choice: intake starts here and runs for 12 months, so every listing's 90 "
        "days are over before November 2026.",
    )
    months: int = Field(default=12, description="Choice: a year of history, for the seasonality.")
    monthly_items: float = Field(
        default=50.0,
        description="Choice: the average number of items forwarded to Ecommerce each month, for "
        "about 600 items in a year, with the count each month drawn around it.",
    )
    max_days: int = Field(
        default=90,
        description="Choice: how long a listing runs before it ends unsold, the window of Closo's "
        "sell-through figures.",
    )
    clothing_share: float = Field(
        default=0.7,
        description="Assumed: the share of forwarded items that come from the clothing department, "
        "with the rest from electronics and games.",
    )
    apparel_department_shares: Shares = Field(
        default=(0.3, 0.55, 0.15),
        description="Assumed: the share of apparel that is men's, women's and kids'.",
    )
    apparel_condition_shares: Shares = Field(
        default=(0.08, 0.07, 0.85),
        description="Assumed: the share of apparel that is new with tags, new without tags and "
        "pre-owned.",
    )
    electronics_games_condition_shares: Shares = Field(
        default=(0.04, 0.04, 0.92),
        description="Assumed: the same shares for electronics and games.",
    )
    apparel_median_price_cents: int = Field(
        default=3400, description="Assumed: the middle typical price of an apparel item."
    )
    apparel_price_spread: float = Field(
        default=0.8,
        description="Assumed: the spread of apparel prices on a log scale, which puts about one "
        "in seven under $15.",
    )
    electronics_games_median_price_cents: int = Field(
        default=4000, description="Assumed: the middle typical price of a games or hardware item."
    )
    electronics_games_price_spread: float = Field(
        default=0.95,
        description="Assumed: the spread of games and hardware prices on a log scale, which puts "
        "about one in six at $100 or more.",
    )
    check_share: float = Field(
        default=0.1,
        description='Assumed: the share of appraisals that come back "check", with low '
        "confidence or no comps.",
    )
    clothing_accept_if_yes: float = Field(
        default=0.9, description="Assumed: how often clothing staff accept an item rated yes."
    )
    clothing_accept_if_no: float = Field(
        default=0.15,
        description="Assumed: how often clothing staff accept an item rated no, overriding it.",
    )
    clothing_accept_if_check: float = Field(
        default=0.5, description="Assumed: how often clothing staff accept an item rated check."
    )
    electronics_games_accept_if_yes: float = Field(
        default=0.92,
        description="Assumed: how often electronics and games staff accept an item rated yes.",
    )
    electronics_games_accept_if_no: float = Field(
        default=0.1,
        description="Assumed: how often electronics and games staff accept an item rated no, "
        "overriding it.",
    )
    electronics_games_accept_if_check: float = Field(
        default=0.55,
        description="Assumed: how often electronics and games staff accept an item rated check.",
    )
    max_listing_lag_days: int = Field(
        default=7,
        description="Assumed: an accepted item is listed 1 to this many days after the staff "
        "call, for the manager approval and shelving.",
    )
    channel_b_share: float = Field(
        default=0.45,
        description="Assumed: the share of accepted apparel listed on Channel B rather than "
        "Channel A, with games and hardware always on Channel A.",
    )
    channel_a_scale_days: float = Field(
        default=2600.0,
        description="Calibrated to FlowLister's eBay figures: the scale of Channel A's baseline, "
        "where a larger value means fewer sales.",
    )
    channel_a_shape: float = Field(
        default=0.55,
        description="Calibrated to FlowLister's eBay figures: below 1, the daily chance falls as a "
        "listing ages, so sales come early and a few take much longer.",
    )
    channel_b_scale_days: float = Field(
        default=150.0,
        description="Calibrated to Closo's Poshmark figures for women's tops: the scale of "
        "Channel B's baseline.",
    )
    channel_b_shape: float = Field(
        default=2.0,
        description="Calibrated to Closo's Poshmark figures: above 1, the daily chance rises as a "
        "listing ages, which a 59-day average inside 90 days needs.",
    )
    price_band_edges_cents: tuple[int, int, int, int, int] = Field(
        default=(1500, 3000, 5000, 10000, 25000),
        description="Choice: the price bands start at these prices, with FlowLister's under $15 "
        "and $100 to $249.99 among them and the $30 worth-listing bar as an edge.",
    )
    price_band_factors: tuple[float, float, float, float, float, float] = Field(
        default=(0.9, 0.95, 1.0, 1.4, 3.4, 3.4),
        description="Calibrated to FlowLister's sell-through under $15 and at $100 to $249.99 for "
        "the first and fifth bands, and assumed to rise evenly between them and stay level above.",
    )
    apparel_factor: float = Field(
        default=1.0,
        description="Assumed: no published figure we use compares categories, so both start equal.",
    )
    electronics_games_factor: float = Field(
        default=1.0, description="Assumed: the same as apparel, for the same reason."
    )
    condition_factors: Shares = Field(
        default=(1.15, 1.1, 1.0),
        description="Assumed: new with tags, new without tags and pre-owned, with new items "
        "selling a little more often.",
    )
    apparel_seasonal_index: MonthlyIndex = Field(
        default=(0.85, 0.9, 1.15, 1.1, 1.0, 0.9, 0.85, 1.0, 1.2, 1.15, 1.0, 0.9),
        description="Assumed: January to December, peaking as spring and fall start and falling "
        "off after, which a thrift practitioner's article supports only in words.",
    )
    electronics_games_seasonal_index: MonthlyIndex = Field(
        default=(0.9, 0.85, 0.9, 0.9, 0.9, 0.95, 0.95, 0.95, 1.0, 1.05, 1.3, 1.35),
        description="Assumed: January to December, peaking with holiday gift buying in November "
        "and December.",
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_ENV_FILE,
        env_ignore_empty=True,
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://thrift:thrift@localhost:5432/thrift"
    cors_origins: list[str] = ["http://localhost:5173"]
    # Where the web app lives, so an invite email can link back to it.
    web_app_url: str = "http://localhost:5173"

    local_storage_dir: Path = Path("storage")
    supabase_url: str | None = None
    supabase_anon_key: str | None = None
    supabase_service_role_key: str | None = None
    supabase_storage_bucket: str = "photos"

    ai_base_url: str | None = None
    ai_model: str | None = None
    ai_api_key: str | None = None
    # Second provider, used when the first one fails twice or cannot be reached.
    ai_fallback_base_url: str | None = None
    ai_fallback_model: str | None = None
    ai_fallback_api_key: str | None = None
    # Below this, staff confirm the card before a search, because a search costs from a small quota.
    item_card_min_confidence: Confidence = Confidence.MEDIUM

    serpapi_api_key: str | None = None
    serpapi_search_url: str = "https://serpapi.com/search.json"
    # The free plan allows 250 searches a month, so the default leaves a small margin.
    serpapi_monthly_budget: int = 240

    pricing: PricingRules = PricingRules()
    photo_checks: PhotoChecks = PhotoChecks()

    # The mock sales channels in mock_channel/. A channel with no URL or key is left out.
    channel_a_url: str | None = None
    channel_a_key: str | None = None
    channel_b_url: str | None = None
    channel_b_key: str | None = None
    # The background sync: how often to look for due jobs, and how often to poll each channel
    # for sales whose webhook never arrived. Tests turn it off and drive the sync by hand.
    sync_enabled: bool = True
    sync_job_seconds: float = 2.0
    sync_poll_seconds: float = 30.0

    # Render sets this to the deployed commit, and it is empty anywhere else.
    render_git_commit: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
