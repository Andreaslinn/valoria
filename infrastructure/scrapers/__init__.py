from infrastructure.scrapers.base import (
    Currency,
    RateLimiter,
    ScraperBase,
    ScraperResult,
    parse_price_text,
    parse_spanish_number,
    to_clp,
    with_retry,
)
from infrastructure.scrapers.portalinmobiliario import PortalInmobiliarioScraper
from infrastructure.scrapers.yapo import YapoScraper

SCRAPER_STATUS = {
    "yapo": {
        "status": "active",
        "reason": "Parser y scraper HTTP implementados.",
    },
    "portalinmobiliario": {
        "status": "experimental",
        "reason": (
            "Parser cubierto por tests; scraping real puede quedar blocked por "
            "login, account-verification, captcha o 403."
        ),
    },
}

__all__ = [
    "Currency",
    "PortalInmobiliarioScraper",
    "RateLimiter",
    "SCRAPER_STATUS",
    "ScraperBase",
    "ScraperResult",
    "YapoScraper",
    "parse_price_text",
    "parse_spanish_number",
    "to_clp",
    "with_retry",
]
