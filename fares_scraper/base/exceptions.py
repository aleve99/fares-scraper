class ScraperError(Exception):
    """Base exception for all scraper-related errors."""
    pass

class ProxyError(ScraperError):
    """Raised when there is an issue with the proxy (e.g., connection failed)."""
    pass

class ProxyBlockedError(ProxyError):
    """Raised when the proxy is blocked or throttled by the server."""
    pass

class RateLimitError(ScraperError):
    """Raised when the server returns a 429 Too Many Requests."""
    pass

class SessionError(ScraperError):
    """Raised when there is an issue maintaining or creating a session."""
    pass

class ParsingError(ScraperError):
    """Raised when the response data cannot be parsed correctly."""
    pass

class FlightNotFoundError(ScraperError):
    """Raised when no flights are found for the requested route/date."""
    pass

