import json
from typing import List, Optional, Any
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator

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
    proxies: Any = Field(
        default_factory=list,
        description="Proxy URLs: JSON list, comma-separated string, or empty",
    )
    
    # Example: SCRAPER_PROXIES="http://p1,http://p2" will be parsed automatically

    vueling_bearer_token: Optional[str] = Field(
        default=None,
        description="Bearer token for Vueling FlightCalendar partner API (optional)",
    )
    vueling_culture: str = Field(default="en-GB", description="Vueling culture / language tag")
    vueling_currency: str = Field(default="EUR", description="Vueling currency code")
    vueling_product_class: str = Field(
        default="BA",
        description="Vueling FlightCalendar product class: BA (Basic) or OP (Optima)",
    )
    vueling_seed_airports: List[str] = Field(
        default_factory=list,
        description="Comma-separated or JSON list of IATA seeds for Vueling route graph (optional)",
    )
    vueling_calendar_prices_path: str = Field(
        default="/api/FlightCalendarPrices",
        description="Path for Vueling FlightCalendar prices (override if your environment uses a different route)",
    )
    vueling_calendar_routes_path: str = Field(
        default="/api/FlightCalendarRoutes",
        description="Path for Vueling FlightCalendar routes (override if your environment uses a different route)",
    )

    @field_validator("proxies", mode="before")
    @classmethod
    def _split_proxy_list(cls, v: Any) -> List[str]:
        if v is None:
            return []
        if isinstance(v, list):
            return [str(p).strip() for p in v if str(p).strip()]
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return []
            if s.startswith("["):
                parsed = json.loads(s)
                if isinstance(parsed, list):
                    return [str(p).strip() for p in parsed if str(p).strip()]
                return []
            return [p.strip() for p in s.split(",") if p.strip()]
        return []

    @field_validator("vueling_seed_airports", mode="before")
    @classmethod
    def _split_seed_airports(cls, v: Any) -> Any:
        if v is None or v == "":
            return []
        if isinstance(v, str):
            s = v.strip()
            if s.startswith("["):
                parsed = json.loads(s)
                if isinstance(parsed, list):
                    return [str(p).strip().upper() for p in parsed if str(p).strip()]
                return []
            return [p.strip().upper() for p in s.split(",") if p.strip()]
        return v

# Global settings instance
settings = ScraperSettings()
