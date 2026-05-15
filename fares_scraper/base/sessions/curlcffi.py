import asyncio
import logging
from itertools import cycle
from typing import List, Dict, Optional

from curl_cffi import requests

from .base import BaseSessionManager

logger = logging.getLogger("scraper.session_manager.curlcffi")

class CurlCffiSessionManager(BaseSessionManager):
    """
    Manages the lifecycle of curl_cffi AsyncSession and proxy rotation.
    Designed to bypass TLS fingerprinting blocks (e.g. Akamai).
    """
    def __init__(
        self, 
        timeout: int, 
        base_url: Optional[str] = None, 
        warm_up_url: Optional[str] = None,
        default_headers: Optional[Dict[str, str]] = None,
        proxies: Optional[List[str]] = None
    ):
        self._session: Optional[requests.AsyncSession] = None
        self._stateless_session: Optional[requests.AsyncSession] = None
        self._warm_up_cookies: Dict[str, str] = {}
        self._timeout = timeout
        self._base_url = base_url
        self._warm_up_url = warm_up_url
        self._default_headers = default_headers
        
        self._proxies = proxies if proxies else [None]
        self._proxies_loop = cycle(self._proxies)
        self._lock = asyncio.Lock()

    def _get_proxy_dict(self, proxy_str: Optional[str]) -> Optional[Dict[str, str]]:
        if not proxy_str:
            return None
        return {"http": proxy_str, "https": proxy_str}

    async def get_session(self, stateless: bool = False) -> requests.AsyncSession:
        async with self._lock:
            if self._session is None:
                logger.debug("Initializing new curl_cffi AsyncSession")
                self._session = requests.AsyncSession(
                    impersonate="chrome",
                    headers=self._default_headers,
                    timeout=self._timeout,
                    verify=False  # Typically needed for proxies
                )
                
                target_warm_up = self._warm_up_url or (self._base_url if self._base_url else None)
                if target_warm_up:
                    try:
                        url = target_warm_up if "://" in target_warm_up else f"{self._base_url}{target_warm_up}"
                        proxy = self.get_next_proxy()
                        proxy_dict = self._get_proxy_dict(proxy)
                        
                        response = await self._session.get(url, proxies=proxy_dict)
                        response.raise_for_status()
                        
                        # capture cookies
                        self._warm_up_cookies = {k: v for k, v in self._session.cookies.items()}
                        logger.debug(f"Session warmed up via {url}. Captured {len(self._warm_up_cookies)} cookies.")
                    except Exception as e:
                        logger.warning(f"Session warm-up failed: {e}")

            if stateless:
                if self._stateless_session is None:
                    self._stateless_session = requests.AsyncSession(
                        impersonate="chrome",
                        headers=self._default_headers,
                        timeout=self._timeout,
                        verify=False
                    )
                return self._stateless_session
            
            return self._session

    def get_warm_up_cookies(self) -> Dict[str, str]:
        return self._warm_up_cookies

    def get_next_proxy(self) -> Optional[str]:
        return next(self._proxies_loop)

    async def close(self):
        async with self._lock:
            if self._session:
                await self._session.close()
                self._session = None
            if self._stateless_session:
                await self._stateless_session.close()
                self._stateless_session = None
            logger.debug("All curl_cffi AsyncSessions closed")

    @property
    def timeout(self) -> int:
        return self._timeout
