"""Read-only HTTP smoke test for Portal Inmobiliario result pages.

Fetches one real results page over HTTP, parses the result cards, and stores a
sanitized fixture for regression tests. It does not use Chrome, visit details,
write to the database, or touch the pipeline.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infrastructure.scrapers.portalinmobiliario import (  # noqa: E402
    PortalInmobiliarioScraper,
    classify_portal_page_state,
    extract_portal_detail_urls,
)
DEFAULT_SEARCH_URL = "https://www.portalinmobiliario.com/venta/departamento/santiago-metropolitana"
DEFAULT_FIXTURE_PATH = ROOT / "tests" / "fixtures" / "portal_results_real_sanitized.html"
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
}


@dataclass(frozen=True)
class SmokeSummary:
    status: str
    search_state: str
    http_status: int | None
    cards_detected: int
    parsed_items: int
    discarded_items: int
    discarded_reasons: str
    detail_links_found: int
    fixture_path: str


def _print_summary(summary: SmokeSummary) -> None:
    print("status=" + summary.status)
    print("search_state=" + summary.search_state)
    print("http_status=" + (str(summary.http_status) if summary.http_status is not None else "unknown"))
    print("cards_detected=" + str(summary.cards_detected))
    print("parsed_items=" + str(summary.parsed_items))
    print("discarded_items=" + str(summary.discarded_items))
    print("discarded_reasons=" + summary.discarded_reasons)
    print("detail_links_found=" + str(summary.detail_links_found))
    print("fixture_path=" + summary.fixture_path)


def _fetch_results(url: str, *, timeout_s: float) -> httpx.Response:
    with httpx.Client(headers=DEFAULT_HEADERS, follow_redirects=True, timeout=timeout_s) as client:
        return client.get(url)


def _sanitize_html(html: str) -> str:
    soup = BeautifulSoup(html or "", "lxml")
    for tag in soup.select("script, style, noscript, template"):
        tag.decompose()
    for tag in soup.find_all(["meta", "link"]):
        values = " ".join(str(value) for value in tag.attrs.values()).lower()
        if any(marker in values for marker in ("csrf", "nonce", "traceparent", "maps.googleapis.com")):
            tag.decompose()
    for tag in soup.select("[nonce]"):
        del tag["nonce"]
    for tag in soup.select("input"):
        if tag.has_attr("value"):
            tag["value"] = ""
    for tag in soup.select("a[href]"):
        href = str(tag.get("href") or "")
        if "#" in href:
            tag["href"] = href.split("#", 1)[0]
    text = str(soup)
    text = re.sub(r"[\w.\-+]+@[\w.\-]+\.\w+", "<redacted-email>", text)
    text = re.sub(r"(?:\+?56\s*)?(?:\(?\d{1,2}\)?[\s.-]*)?\d{3,4}[\s.-]\d{4}", "<redacted-phone>", text)
    return "<!DOCTYPE html>\n" + text


def _relative_to_root(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _reason_summary(reasons: Counter[str]) -> str:
    if not reasons:
        return "none"
    return ",".join(f"{reason}:{count}" for reason, count in sorted(reasons.items()))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a read-only Portal Inmobiliario HTTP results smoke test.")
    parser.add_argument("--search-url", default="")
    parser.add_argument("--timeout-s", type=float, default=30.0)
    parser.add_argument("--fixture-path", default=str(DEFAULT_FIXTURE_PATH))
    args = parser.parse_args()

    search_url = args.search_url.strip() or DEFAULT_SEARCH_URL
    fixture_path = Path(args.fixture_path)
    if not fixture_path.is_absolute():
        fixture_path = ROOT / fixture_path

    try:
        response = _fetch_results(search_url, timeout_s=args.timeout_s)
    except httpx.HTTPError as exc:
        _print_summary(
            SmokeSummary(
                status="http_error",
                search_state="not_run",
                http_status=None,
                cards_detected=0,
                parsed_items=0,
                discarded_items=0,
                discarded_reasons=str(exc.__class__.__name__),
                detail_links_found=0,
                fixture_path=_relative_to_root(fixture_path),
            )
        )
        return 1

    html = response.text
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_path.write_text(_sanitize_html(html), encoding="utf-8")

    state = classify_portal_page_state(html, status_code=response.status_code)
    report = PortalInmobiliarioScraper.parse_listings_detailed(html, uf_to_clp=None)
    reasons = Counter(discard["reason"] for discard in report["discarded"])
    detail_urls = extract_portal_detail_urls(html, base_url=str(response.url), limit=2)

    ok = response.status_code == 200 and state == "authenticated" and len(report["items"]) > 0
    _print_summary(
        SmokeSummary(
            status="ok" if ok else "unexpected_content",
            search_state=state,
            http_status=response.status_code,
            cards_detected=report["cards_detected"],
            parsed_items=len(report["items"]),
            discarded_items=len(report["discarded"]),
            discarded_reasons=_reason_summary(reasons),
            detail_links_found=len(detail_urls),
            fixture_path=_relative_to_root(fixture_path),
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
