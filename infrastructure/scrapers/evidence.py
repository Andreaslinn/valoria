"""Additive, internal source evidence. Never used by valuation or identity matching."""

from __future__ import annotations

import copy
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from domain.ingestion.raw_safety import sanitize, POLICY_VERSION

VERSION = "source_evidence_v2"


def parser_identity(path: str) -> dict:
    # Hash the actual parser file, not a date-derived version assumption.
    return {
        "version": VERSION,
        "module": Path(path).name,
        "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        "evidence_helper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }


def capture(
    source: str,
    *,
    raw: dict,
    parser_file: str,
    stage: str,
    observed_at: datetime | None = None,
    original_url: str | None = None,
    canonical_url: str | None = None,
) -> dict:
    result = {
        "schema_version": VERSION,
        "source": source,
        "stage": stage,
        "observed_at": (observed_at or datetime.now(UTC)).isoformat(),
        "parser": parser_identity(parser_file),
        "original_url": original_url,
        "canonical_url": canonical_url,
        "raw": copy.deepcopy(raw),
        "coordinate_precision": "source_pin_unverified",
        "canonical_url_origin": "derived_absolute_url"
        if source == "yapo"
        else "source_canonical_or_offer_url"
        if canonical_url
        else "not_observed",
    }
    payload = raw.get("payload") or {}
    gallery = (raw.get("components") or {}).get("gallery") or {}
    gallery = gallery if isinstance(gallery, dict) else {}
    pictures = gallery.get("pictures") or []
    pictures = pictures if isinstance(pictures, list) else []
    images = payload.get("images")
    urls = list(images) if isinstance(images, list) else []
    if isinstance(payload.get("principalImage"), str) and payload["principalImage"] not in urls:
        urls.insert(0, payload["principalImage"])
    for image in raw.get("images_raw") or []:
        if isinstance(image, dict):
            urls.extend([image.get("data_src"), image.get("src")])
    urls.extend(x.get("url") for x in pictures if isinstance(x, dict))
    schema = raw.get("schema_raw") or []
    if isinstance(schema, dict):
        schema = [schema]
    for obj in schema:
        if isinstance(obj, dict):
            image = obj.get("image")
            if isinstance(image, str):
                urls.append(image)
            elif isinstance(image, list):
                urls.extend(x for x in image if isinstance(x, str))

    def valid_url(value):
        try:
            return isinstance(value, str) and urlsplit(value).scheme in {"http", "https"}
        except ValueError:
            return False

    urls = list(dict.fromkeys(x for x in urls if valid_url(x)))
    ids = [x["id"] for x in pictures if isinstance(x, dict) and x.get("id")]
    if source == "yapo":
        ids = [urlsplit(x).path.rsplit("/", 1)[-1] for x in urls]
    publication_date = payload.get("publishedAt") or payload.get("datePublished")
    update_date = payload.get("updatedAt") or payload.get("dateModified")
    for obj in schema:
        if isinstance(obj, dict):
            publication_date = publication_date or obj.get("datePublished")
            update_date = update_date or obj.get("dateModified")
    result["parsed_signals"] = {
        "image_urls": urls,
        "image_ids": ids,
        "image_identifier_kind": "url_path_suffix"
        if source == "yapo"
        else "source_remote_picture_id",
        "image_order_preserved": True,
        "platform_listing_id": payload.get("id") or raw.get("platform_id"),
        "physical_unit_id": None,
        "publication_date": publication_date,
        "source_updated_at": update_date,
        "source_date_precision": "not_inferred",
        "source_surfaces_raw": {k: payload.get(k) for k in ("square", "lotSize", "usableArea")},
        "seller_raw": {
            k: payload[k]
            for k in ("seller", "sellerId", "brokerId", "agencyId", "userId")
            if k in payload
        },
    }
    result["signal_provenance"] = {
        k: {
            "source": source,
            "observed_at": result["observed_at"],
            "parser": result["parser"],
            "origin": "observed_source_fields",
            "inferred_physical_identity": False,
        }
        for k in result["parsed_signals"]
    }
    result['safety_policy'] = POLICY_VERSION
    return sanitize(result)


def portal_card_raw(item) -> dict:
    # Bind images/text to this card, never to all page images.
    return {
        "title_raw": item.select_one("a.poly-component__title").get_text()
        if item.select_one("a.poly-component__title")
        else None,
        "attributes_raw": [
            x.get_text(" ", strip=True) for x in item.select(".poly-attributes_list__item")
        ],
        "images_raw": [
            {"src": x.get("src"), "data_src": x.get("data-src"), "alt": x.get("alt")}
            for x in item.select("img")
        ],
        "location_raw": item.select_one(".poly-component__location").get_text()
        if item.select_one(".poly-component__location")
        else None,
        "seller_raw": item.select_one(".poly-component__seller").get_text()
        if item.select_one(".poly-component__seller")
        else None,
        "price_raw": item.select_one(".poly-component__price").get_text()
        if item.select_one(".poly-component__price")
        else None,
    }


def public_component(value):
    """Keep listing signals, exclude session/telemetry and contact action payloads."""
    excluded = {
        "track",
        "tracking",
        "actions",
        "action",
        "cookies",
        "cookie",
        "access_token",
        "token",
        "authorization",
        "password",
        "session",
    }
    if isinstance(value, dict):
        return {k: public_component(v) for k, v in value.items() if k.lower() not in excluded}
    if isinstance(value, list):
        return [public_component(v) for v in value]
    return copy.deepcopy(value)


def portal_detail_raw(soup, state: dict | None, components: dict) -> dict:
    allowed = (
        "header",
        "price",
        "gallery",
        "location",
        "location_and_points",
        "technical_specifications",
        "highlighted_specs_res",
        "quotable_models",
        "seller_profile",
        "description",
        "bookmark",
    )
    return {
        "platform_id": (state or {}).get("id"),
        "components": {k: public_component(components[k]) for k in allowed if k in components},
        "json_ld_raw": [
            x.string or x.get_text() for x in soup.select("script[type='application/ld+json']")
        ],
        "schema_raw": public_component((state or {}).get("schema")),
        "meta_raw": [
            {"name": x.get("name"), "property": x.get("property"), "content": x.get("content")}
            for x in soup.select(
                "meta[name='description'], meta[property='og:description'], meta[property='og:image']"
            )
        ],
    }


def yapo_detail_extra(soup) -> dict:
    return {
        "meta_raw": [
            {"name": x.get("name"), "property": x.get("property"), "content": x.get("content")}
            for x in soup.select(
                "meta[name='description'], meta[property='og:description'], meta[property='og:image'], meta[property='og:title']"
            )
        ],
        "h1_raw": [x.get_text() for x in soup.select("h1")],
        "property_maps_raw": [x.get("src") for x in soup.select("iframe[src*='maps']")],
        "detail_attributes_raw": [
            x.get_text(" ", strip=True)
            for x in soup.select(".details-item, .property-details li, .info-details li")
        ],
    }
