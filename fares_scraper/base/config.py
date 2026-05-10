from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AliasChoices, Field, model_validator

class ScraperSettings(BaseSettings):
    """
    Centralized configuration for the scraper framework using Pydantic Settings.
    This allows loading from environment variables automatically.
    """
    model_config = SettingsConfigDict(env_prefix="SCRAPER_", env_file=".env", extra="ignore")

    timeout: int = Field(default=15, description="Timeout for network requests in seconds")
    pool_size: int = Field(default=10, description="Max concurrent requests allowed")
    max_retries: int = Field(default=5, description="Number of retries for failed requests")
    user_agent: str = Field(
        default="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
        description="Default User-Agent header"
    )
    proxies: List[str] = Field(default_factory=list, description="List of proxy URLs")

    proxy: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("PROXY", "SCRAPER_PROXY"),
        description="Single proxy URL (prepended to SCRAPER_PROXIES rotation; useful for manual tests)",
    )

    vueling_profile_id: str = Field(
        default="e8ffa738-cb67-4a02-b501-9bfd975a4b65",
        description="SPA profileId for POST https://ams.vueling.com/asm/v1/Auth (from site config)",
    )
    vueling_ams_base: str = Field(default="https://ams.vueling.com")
    vueling_apiw_base: str = Field(default="https://apiw.vueling.com")
    vueling_seed_origins: str = Field(
        default="BCN,MAD,PMI,AGP,VLC",
        description="Comma-separated IATA codes to bootstrap Markets discovery",
    )
    vueling_routes_path: str = Field(
        default="/api/v1/flightCalendarRoutes",
        description="GET path on apiw for FlightCalendarRoutes (startDate, numDays)",
    )
    vueling_prices_path: str = Field(
        default="/api/v1/flightCalendarPrices",
        description="GET path on FlightCalendarPrices (startDate, numDays, productClass)",
    )
    vueling_culture: str = Field(default="en-GB")

    @model_validator(mode="after")
    def _prepend_proxy(self) -> "ScraperSettings":
        if self.proxy:
            merged = [self.proxy] + [p for p in self.proxies if p != self.proxy]
            object.__setattr__(self, "proxies", merged)
        return self

# Global settings instance
settings = ScraperSettings()
