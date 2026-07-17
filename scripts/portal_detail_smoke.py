"""HTTP smoke test for two Portal Inmobiliario detail pages.

Discovers two listing URLs from a real results page, fetches those detail pages
over HTTP, parses them with the dedicated detail parser, and writes sanitized
fixtures. It does not use Chrome, visit additional details, write to the
database, or activate Portal in production.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infrastructure.scrapers.portalinmobiliario import (  # noqa: E402
    extract_portal_detail_urls,
    parse_listing_detail_portal,
)
from infrastructure.scrapers.portalinmobiliario import _extract_first_json_object  # noqa: E402
from scripts.portal_smoke import DEFAULT_HEADERS, DEFAULT_SEARCH_URL  # noqa: E402

DEFAULT_FIXTURE_DIR = ROOT / "tests" / "fixtures"
SENSITIVE_KEYS = {
    "csrfToken",
    "d2id",
    "recaptchaSiteKey",
    "userConsentCookie",
    "currentUser",
    "deviceInfo",
    "networkState",
    "cookies",
    "headers",
}


def _fetch(client: httpx.Client, url: str) -> httpx.Response:
    return client.get(url)


def _sanitize_html(html: str) -> str:
    soup = BeautifulSoup(html or "", "lxml")
    for tag in soup.select("script"):
        script_type = str(tag.get("type") or "").lower()
        script_id = str(tag.get("id") or "")
        if script_type == "application/ld+json":
            continue
        if script_id == "__NORDIC_RENDERING_CTX__":
            sanitized = _sanitized_nordic_script(tag.get_text())
            if sanitized:
                tag.string = sanitized
                continue
        tag.decompose()
    for tag in soup.select("style, noscript, template"):
        tag.decompose()
    for tag in soup.find_all(["meta", "link"]):
        values = " ".join(str(value) for value in tag.attrs.values()).lower()
        if any(marker in values for marker in ("csrf", "nonce", "traceparent", "maps.googleapis.com")):
            tag.decompose()
    for tag in soup.find_all():
        if "maps.googleapis.com" in " ".join(str(value) for value in tag.attrs.values()).lower():
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


def _sanitized_nordic_script(raw: str) -> str | None:
    try:
        data = json.loads(_extract_first_json_object(raw))
    except (ValueError, json.JSONDecodeError):
        return None
    cleaned = _drop_sensitive(data)
    return "_n.ctx.r=" + json.dumps(cleaned, ensure_ascii=False, separators=(",", ":")) + ";"


def _drop_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, child in value.items():
            if key in SENSITIVE_KEYS:
                continue
            if key == "src" and isinstance(child, str) and "maps.googleapis.com" in child:
                out[key] = "<redacted-map-url>"
                continue
            out[key] = _drop_sensitive(child)
        return out
    if isinstance(value, list):
        return [_drop_sensitive(child) for child in value]
    if isinstance(value, str):
        if "maps.googleapis.com" in value:
            return "<redacted-map-url>"
        value = re.sub(r"[\w.\-+]+@[\w.\-]+\.\w+", "<redacted-email>", value)
    return value


def _fields_available(detail: dict[str, Any]) -> list[str]:
    fields = [
        "external_id",
        "canonical_url",
        "title",
        "price_uf",
        "price_clp",
        "usable_area_m2",
        "built_area_m2",
        "total_area_m2",
        "land_area_m2",
        "bedrooms",
        "bathrooms",
        "parking",
        "common_expenses_clp",
        "description",
        "comuna",
        "location",
        "seller",
    ]
    return [field for field in fields if detail.get(field) not in (None, "", [])]


def _fixture_path(index: int) -> Path:
    return DEFAULT_FIXTURE_DIR / f"portal_detail_real_{index}_sanitized.html"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a Portal Inmobiliario HTTP detail smoke test.")
    parser.add_argument("--search-url", default="")
    parser.add_argument("--timeout-s", type=float, default=30.0)
    args = parser.parse_args()

    search_url = args.search_url.strip() or DEFAULT_SEARCH_URL
    with httpx.Client(headers=DEFAULT_HEADERS, follow_redirects=True, timeout=args.timeout_s) as client:
        search_response = _fetch(client, search_url)
        detail_urls = extract_portal_detail_urls(search_response.text, base_url=str(search_response.url), limit=2)
        print(f"search_http_status={search_response.status_code}")
        print(f"detail_urls_found={len(detail_urls)}")
        ok = search_response.status_code == 200 and len(detail_urls) == 2

        for index, detail_url in enumerate(detail_urls, start=1):
            response = _fetch(client, detail_url)
            parsed = parse_listing_detail_portal(response.text, str(response.url))
            fixture = _fixture_path(index)
            fixture.parent.mkdir(parents=True, exist_ok=True)
            fixture.write_text(_sanitize_html(response.text), encoding="utf-8")
            fields = _fields_available(parsed)
            ok = ok and response.status_code == 200
            ok = ok and parsed.get("state") == "detail"
            ok = ok and all(parsed.get(field) for field in ("external_id", "canonical_url", "title"))
            ok = ok and (parsed.get("price_uf") is not None or parsed.get("price_clp") is not None)
            ok = ok and (
                parsed.get("usable_area_m2") is not None
                or parsed.get("built_area_m2") is not None
                or parsed.get("total_area_m2") is not None
                or parsed.get("land_area_m2") is not None
            )
            ok = ok and (parsed.get("bedrooms") is not None or parsed.get("bathrooms") is not None)
            print(f"detail_{index}_http_status={response.status_code}")
            print(f"detail_{index}_state={parsed.get('state')}")
            print(f"detail_{index}_external_id={parsed.get('external_id')}")
            print(f"detail_{index}_title={parsed.get('title')}")
            print(f"detail_{index}_price_uf={parsed.get('price_uf')}")
            print(f"detail_{index}_price_clp={parsed.get('price_clp')}")
            print(f"detail_{index}_fields={','.join(fields)}")
            print(f"detail_{index}_fixture={fixture.relative_to(ROOT)}")

    print("status=" + ("ok" if ok else "unexpected_content"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
