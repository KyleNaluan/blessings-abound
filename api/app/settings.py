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
