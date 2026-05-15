import logging
import asyncio
import aiohttp
import re

from abc import ABC, abstractmethod
from typing import Optional, Dict, List, Any, Iterable, Tuple
from datetime import date, time

from ..sessions.aiohttp import AiohttpSessionManager
from ..sessions.curlcffi import CurlCffiSessionManager
from ..config import settings, ScraperSettings
from ..exceptions import ScraperError, ProxyError, RateLimitError
from ..types.common import Airport, OneWayFare, RoundTripFare, ConcurrentResults
from ...utils.timer import Timer

logger = logging.getLogger("scraper.base")


class BaseScraper(ABC):
    """
    The core of the framework. Defines the interface and provides high-level 
    utilities for concurrent requests, retries, and error handling.
    """
    def __init__(
        self,
        config: ScraperSettings = settings,
        base_url: Optional[str] = None,
        warm_up_url: Optional[str] = None,
        default_headers: Optional[Dict[str, str]] = None
    ):
        self.config = config
        self._semaphore = asyncio.Semaphore(config.pool_size)
        self.active_airports: Tuple[Airport, ...] = tuple()
        self.sm = None # To be initialized by subclasses

    @staticmethod
    def parse_flight_number(flight_num_raw: str, carrier_code: str = "") -> int:
        if not flight_num_raw:
            return 0
            
        cleaned = flight_num_raw.replace(' ', '').upper()
        carrier_code = carrier_code.replace(' ', '').upper()
        
        if carrier_code and cleaned.startswith(carrier_code):
            cleaned = cleaned[len(carrier_code):]
            
        digits = re.sub(r'\D', '', cleaned)
        return int(digits) if digits else 0

    def get_airport(self, iata_code: str) -> Optional[Airport]:
        airports = self.get_active_airports() 
        for airport in airports:
            if airport.iata_code == iata_code:
                return airport
        return None

    def get_active_airports(self) -> Tuple[Airport, ...]:
        if self.active_airports is None:
            raise RuntimeError("Scraper not initialized. Use within an 'async with' block.")
        return self.active_airports
    
    @abstractmethod
    async def update_active_airports(self) -> None:
        pass

    @abstractmethod
    async def get_destination_codes(self, origin: str) -> Tuple[str, ...]:
        pass

    @abstractmethod
    async def get_available_dates(self, origin: str, destination: str) -> Tuple[str, ...]:
        pass

    @abstractmethod
    async def search_one_way_fares(
        self,
        origin: str,
        from_date: date,
        to_date: Optional[date] = None,
        destinations: Iterable[str] = []
    ) -> List[OneWayFare]:
        pass

    @abstractmethod
    async def search_round_trip_fares(
        self,
        origin: str,
        min_days: int,
        max_days: int,
        from_date: date,
        to_date: Optional[date] = None,
        destinations: Iterable[str] = []
    ) -> List[RoundTripFare]:
        pass

    @staticmethod
    def _sanitize_params(params: Optional[Dict[str, Any]]) -> Optional[Dict[str, str]]:
        if not params:
            return None
        
        sanitized = {}
        for k, v in params.items():
            if v is None: continue
            if isinstance(v, date):
                sanitized[k] = v.isoformat()
            elif isinstance(v, bool):
                sanitized[k] = str(v).lower()
            elif isinstance(v, list):
                sanitized[k] = ",".join(map(str, v))
            elif isinstance(v, time):
                sanitized[k] = v.strftime('%H:%M')
            else:
                sanitized[k] = str(v)
        return sanitized

    @abstractmethod
    async def request(self, method: str, url: str, params: Optional[Dict] = None, stateless: bool = False, **kwargs) -> Any:
        pass

    @abstractmethod
    async def get(self, url: str, stateless: bool = False, **kwargs) -> Any:
        pass

    @abstractmethod
    async def post(self, url: str, stateless: bool = False, **kwargs) -> Any:
        pass

    async def run_concurrently(self, tasks: Iterable[Any]) -> ConcurrentResults:
        async def wrap_task(task):
            async with self._semaphore:
                try:
                    if asyncio.iscoroutine(task):
                        return await task
                    return task
                except Exception as e:
                    logger.error(f"Concurrent task failed: {e}")
                    return e
        
        timer = Timer(start=True)
        results = await asyncio.gather(*(wrap_task(t) for t in tasks), return_exceptions=True)
        timer.stop()
        
        execution_time = timer.seconds_elapsed
        logger.debug(f"Concurrent tasks completed in {execution_time:.2f}s")
        return ConcurrentResults(results=results, execution_time=execution_time)

    async def __aenter__(self):
        await self.update_active_airports()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.sm:
            await self.sm.close()


class AiohttpScraper(BaseScraper):
    def __init__(
        self,
        config: ScraperSettings = settings,
        base_url: Optional[str] = None,
        warm_up_url: Optional[str] = None,
        default_headers: Optional[Dict[str, str]] = None
    ):
        super().__init__(config, base_url, warm_up_url, default_headers)
        
        headers = {
            "User-Agent": config.user_agent,
            "Accept": "application/json",
            **(default_headers or {})
        }
        
        self.sm = AiohttpSessionManager(
            timeout=config.timeout,
            base_url=base_url,
            warm_up_url=warm_up_url,
            default_headers=headers,
            proxies=config.proxies
        )

    async def request(
        self, 
        method: str, 
        url: str, 
        params: Optional[Dict] = None, 
        stateless: bool = False,
        **kwargs
    ) -> aiohttp.ClientResponse:
        last_exception = None
        clean_params = self._sanitize_params(params)

        for attempt in range(1, self.config.max_retries + 1):
            session = await self.sm.get_session(stateless=stateless)
            proxy = self.sm.get_next_proxy()
            timeout = aiohttp.ClientTimeout(total=self.config.timeout)
            
            if stateless:
                initial_cookies = self.sm.get_warm_up_cookies()
                provided_cookies = kwargs.get("cookies") or {}
                kwargs["cookies"] = {**initial_cookies, **provided_cookies}

            try:
                request_kwargs = {
                    "method": method,
                    "url": url,
                    "params": clean_params,
                    "timeout": timeout,
                    **kwargs
                }
                if proxy:
                    request_kwargs["proxy"] = proxy

                response = await session.request(**request_kwargs)
                
                if response.status == 429:
                    raise RateLimitError(f"Rate limited (429) on {url}")
                if response.status == 403:
                    raise ProxyError(f"Forbidden (403) for {url}")
                if response.status == 401:
                    raise ProxyError(f"Unauthorized (401) for {url}")
                
                if response.status >= 400:
                    body = await response.text()
                    logger.warning(f"Request to {url} failed with status {response.status}. Body: {body[:200]}")
                
                response.raise_for_status()
                return response
            
            except (asyncio.TimeoutError, aiohttp.ClientError, ScraperError) as e:
                logger.warning(f"Attempt {attempt}/{self.config.max_retries} failed for {url}: {e}")
                last_exception = e
                if 'response' in locals() and response is not None:
                    await response.release()
                
                if attempt < self.config.max_retries:
                    await asyncio.sleep(2 ** (attempt - 1))

        if isinstance(last_exception, ScraperError):
            raise last_exception
        raise ScraperError(f"Failed {method} {url} after {self.config.max_retries} attempts. Last error: {last_exception}")

    async def get(self, url: str, stateless: bool = False, **kwargs) -> aiohttp.ClientResponse:
        return await self.request("GET", url, stateless=stateless, **kwargs)

    async def post(self, url: str, stateless: bool = False, **kwargs) -> aiohttp.ClientResponse:
        return await self.request("POST", url, stateless=stateless, **kwargs)


class CurlCffiResponseAdapter:
    def __init__(self, r):
        self._r = r

    @property
    def status(self):
        return self._r.status_code

    @property
    def url(self):
        return self._r.url

    async def json(self):
        return self._r.json()

    async def text(self):
        return self._r.text

    def raise_for_status(self):
        self._r.raise_for_status()

    async def release(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass


class CurlCffiScraper(BaseScraper):
    def __init__(
        self,
        config: ScraperSettings = settings,
        base_url: Optional[str] = None,
        warm_up_url: Optional[str] = None,
        default_headers: Optional[Dict[str, str]] = None
    ):
        super().__init__(config, base_url, warm_up_url, default_headers)
        
        headers = {
            "Accept": "application/json",
            **(default_headers or {})
        }
        
        self.sm = CurlCffiSessionManager(
            timeout=config.timeout,
            base_url=base_url,
            warm_up_url=warm_up_url,
            default_headers=headers,
            proxies=config.proxies
        )

    async def request(
        self, 
        method: str, 
        url: str, 
        params: Optional[Dict] = None, 
        stateless: bool = False,
        **kwargs
    ) -> CurlCffiResponseAdapter:
        last_exception = None
        clean_params = self._sanitize_params(params)

        for attempt in range(1, self.config.max_retries + 1):
            session = await self.sm.get_session(stateless=stateless)
            proxy = self.sm.get_next_proxy()
            
            if stateless:
                initial_cookies = self.sm.get_warm_up_cookies()
                provided_cookies = kwargs.get("cookies") or {}
                kwargs["cookies"] = {**initial_cookies, **provided_cookies}

            try:
                full_url = url if "://" in url else f"{self.sm._base_url}{url}"
                request_kwargs = {
                    "method": method,
                    "url": full_url,
                    "params": clean_params,
                    "timeout": self.config.timeout,
                    **kwargs
                }
                if proxy:
                    request_kwargs["proxies"] = {"http": proxy, "https": proxy}

                response = await session.request(**request_kwargs)
                
                if response.status_code == 429:
                    raise RateLimitError(f"Rate limited (429) on {url}")
                if response.status_code == 403:
                    raise ProxyError(f"Forbidden (403) for {url}")
                if response.status_code == 401:
                    raise ProxyError(f"Unauthorized (401) for {url}")
                
                if response.status_code >= 400:
                    body = response.text
                    logger.warning(f"Request to {url} failed with status {response.status_code}. Body: {body[:200]}")
                
                response.raise_for_status()
                return CurlCffiResponseAdapter(response)
            
            except Exception as e:
                if isinstance(e, ScraperError):
                    logger.warning(f"Attempt {attempt}/{self.config.max_retries} failed for {url}: {e}")
                    last_exception = e
                else:
                    logger.warning(f"Attempt {attempt}/{self.config.max_retries} failed for {url}: {e}")
                    last_exception = ScraperError(str(e))
                
                if attempt < self.config.max_retries:
                    await asyncio.sleep(2 ** (attempt - 1))

        if isinstance(last_exception, ScraperError):
            raise last_exception
        raise ScraperError(f"Failed {method} {url} after {self.config.max_retries} attempts. Last error: {last_exception}")

    async def get(self, url: str, stateless: bool = False, **kwargs) -> CurlCffiResponseAdapter:
        return await self.request("GET", url, stateless=stateless, **kwargs)

    async def post(self, url: str, stateless: bool = False, **kwargs) -> CurlCffiResponseAdapter:
        return await self.request("POST", url, stateless=stateless, **kwargs)
