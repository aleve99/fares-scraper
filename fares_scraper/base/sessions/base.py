from abc import ABC, abstractmethod
from typing import Dict, Optional, Any

class BaseSessionManager(ABC):
    @abstractmethod
    async def get_session(self, stateless: bool = False) -> Any:
        pass

    @abstractmethod
    def get_warm_up_cookies(self) -> Dict[str, str]:
        pass

    @abstractmethod
    def get_next_proxy(self) -> Optional[str]:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass

    @property
    @abstractmethod
    def timeout(self) -> int:
        pass
