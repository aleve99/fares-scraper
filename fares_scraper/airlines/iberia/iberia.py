import logging
import asyncio
from datetime import datetime, timedelta
from typing import Tuple, Dict, Any, Optional

from ...base.scrapers.gf_scraper import GoogleFlightsScraper
from ...base.exceptions import ScraperError

logger = logging.getLogger("scraper.iberia")


class IberiaScraper(GoogleFlightsScraper):
    """
    Iberia scraper leveraging Google Flights for the actual fare search.
    It overrides get_destination_codes by dynamically fetching routes
    from a Smartvel JSON endpoint.
    """

    CARRIER_CODES = ["IB"]
    
    # Base URL for the routes JSON. Format: https://cdn.smartvel.com/accounts/639/flights/ib_routes_51_YYYYMMDD.json
    ROUTES_URL_TEMPLATE = "https://cdn.smartvel.com/accounts/639/flights/ib_routes_51_{date_str}.json"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._routes_cache: Optional[Dict[str, Any]] = None
        self._routes_lock = asyncio.Lock()

    async def _fetch_routes(self) -> Dict[str, Any]:
        """
        Fetches the Iberia routes JSON. Uses the current date, and falls back to
        yesterday if the current date fails. Caches the result to avoid redundant
        network requests.
        """
        if self._routes_cache is not None:
            return self._routes_cache

        async with self._routes_lock:
            # Double-check inside the lock
            if self._routes_cache is not None:
                return self._routes_cache

            now = datetime.now()
            today_str = now.strftime("%Y%m%d")
            yesterday_str = (now - timedelta(days=1)).strftime("%Y%m%d")

            url_today = self.ROUTES_URL_TEMPLATE.format(date_str=today_str)
            url_yesterday = self.ROUTES_URL_TEMPLATE.format(date_str=yesterday_str)

            # Try today
            try:
                # Need to use a generic user-agent to bypass basic static blocks, but base scraper's get handles this.
                async with await self.get(url_today, stateless=True) as response:
                    data = await response.json()
                    self._routes_cache = data
                    logger.debug(f"Successfully fetched routes from {url_today}")
                    return data
            except Exception as e:
                logger.warning(f"Failed to fetch routes from {url_today}: {e}. Trying yesterday's date.")

            # Try yesterday
            try:
                async with await self.get(url_yesterday, stateless=True) as response:
                    data = await response.json()
                    self._routes_cache = data
                    logger.debug(f"Successfully fetched routes from {url_yesterday}")
                    return data
            except Exception as e:
                logger.error(f"Failed to fetch routes from {url_yesterday}: {e}")
                raise ScraperError(f"Could not fetch Iberia routes JSON for today or yesterday. Last error: {e}")

    async def get_destination_codes(self, origin: str) -> Tuple[str, ...]:
        """
        Overrides GoogleFlightsScraper's get_destination_codes to provide the
        actual direct routes for Iberia.
        """
        routes_data = await self._fetch_routes()
        
        origin = origin.upper()
        if origin not in routes_data:
            logger.debug(f"Origin {origin} not found in Iberia routes data.")
            return tuple()

        origin_data = routes_data[origin]
        direct_str = origin_data.get("direct", "")
        
        if not direct_str:
            return tuple()
            
        # The direct destinations are a comma-separated string
        destinations = [d.strip() for d in direct_str.split(",") if d.strip()]
        return tuple(destinations)
