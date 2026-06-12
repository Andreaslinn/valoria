"""Probe aislado de Mercado Libre API para inmuebles Chile.

No escribe DB ni toca el pipeline. Genera reportes para evaluar si la API
oficial/publica de Mercado Libre puede complementar Portal Inmobiliario.

Uso:
    python scripts/probes/mercadolibre_realestate_probe.py
    python scripts/probes/mercadolibre_realestate_probe.py --limit 10 --commune providencia --commune nunoa
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

API_BASE = "https://api.mercadolibre.com"
SITE_ID = "MLC"
DEFAULT_OUTPUT_DIR = Path("reports")
DEFAULT_LIMIT = 5
DEFAULT_COMMUNES = ("providencia", "nunoa", "las_condes", "santiago", "la_reina")
PROPERTY_QUERIES = {
    "apartment": "departamento venta {commune}",
    "house": "casa venta {commune}",
}
DETAIL_FIELDS = (
    "external_id",
    "title",
    "price",
    "currency",
    "permalink",
    "seller_id",
    "location",
    "comuna",
    "address",
    "latitude",
    "longitude",
    "attributes",
    "m2",
    "bedrooms",
    "bathrooms",
    "operation_type",
    "property_type",
    "listing_date",
)
ATTRIBUTE_ALIASES = {
    "m2": {
        "COVERED_AREA",
        "TOTAL_AREA",
        "PROPERTY_SIZE",
        "SURFACE_TOTAL",
        "SURFACE_COVERED",
        "AREA",
    },
    "bedrooms": {"BEDROOMS", "ROOMS", "BEDROOM_AMOUNT", "ROOM_AMOUNT"},
    "bathrooms": {"FULL_BATHROOMS", "BATHROOMS", "BATHROOM_AMOUNT"},
    "operation_type": {"OPERATION", "OPERATION_TYPE"},
    "property_type": {"PROPERTY_TYPE", "REAL_ESTATE_TYPE"},
}
DOC_REFERENCES = [
    {
        "title": "Mercado Libre Items & Searches",
        "url": "https://developers.mercadolibre.com.ar/en_us/en_us/items-and-searches",
        "note": "Documenta /sites/{SITE_ID}/search y /items.",
    },
    {
        "title": "Mercado Libre Real Estate categories",
        "url": "https://developers.mercadolibre.com.ar/productos-recibe-notificaciones/categorias-inmuebles",
        "note": "Documenta category tree/attributes para inmuebles por site, incluido MLC.",
    },
    {
        "title": "Mercado Libre List properties",
        "url": "https://developers.mercadolibre.com.ar/en_us/list-properties",
        "note": "Describe campos de item inmobiliario vía /items/{ITEM_ID}.",
    },
]


def main() -> int:
    args = parse_args()
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"mercadolibre_api_probe_{timestamp}.json"
    md_path = output_dir / f"mercadolibre_api_probe_{timestamp}.md"

    with httpx.Client(
        base_url=API_BASE,
        timeout=httpx.Timeout(args.timeout),
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 "
                "AVM-Chile-MercadoLibre-API-Probe/1.0"
            ),
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
        },
        follow_redirects=True,
    ) as client:
        report = run_probe(
            client,
            communes=tuple(args.commune),
            limit=args.limit,
            sleep_seconds=args.sleep_seconds,
        )

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    md_path.write_text(markdown_report(report), encoding="utf-8")
    print(f"JSON\t{json_path}")
    print(f"Markdown\t{md_path}")
    print(f"items\t{report['summary']['unique_items']}")
    print(f"coords_pct\t{report['summary']['coordinate_presence_pct']}")
    print(f"decision_primary\t{report['decision']['serves_as_primary_source']}")
    print(f"decision_secondary\t{report['decision']['serves_as_secondary_source']}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe read-only de Mercado Libre API para real estate MLC.")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Resultados por query.")
    parser.add_argument("--commune", action="append", default=None, help="Comuna a buscar. Repetible.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directorio de reportes.")
    parser.add_argument("--timeout", type=float, default=20.0, help="Timeout HTTP por request.")
    parser.add_argument("--sleep-seconds", type=float, default=0.2, help="Pausa conservadora entre detalles.")
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be >= 1")
    if args.commune is None:
        args.commune = list(DEFAULT_COMMUNES)
    args.commune = [normalize_commune_arg(value) for value in args.commune]
    return args


def run_probe(
    client: httpx.Client,
    *,
    communes: tuple[str, ...],
    limit: int,
    sleep_seconds: float,
) -> dict[str, Any]:
    generated_at = datetime.now(UTC).isoformat()
    category_errors: list[dict[str, Any]] = []
    try:
        site_categories = fetch_json(client, f"/sites/{SITE_ID}/categories")
    except httpx.HTTPError as exc:
        site_categories = []
        category_errors.append({"endpoint": f"/sites/{SITE_ID}/categories", "error": str(exc)})
    realestate_category = discover_realestate_category(client, site_categories, errors=category_errors)
    category_tree = fetch_category_tree(client, realestate_category["id"]) if realestate_category else None
    leaf_categories = flatten_categories(category_tree) if category_tree else []
    search_category_id = realestate_category["id"] if realestate_category else None

    searches: list[dict[str, Any]] = []
    detail_by_id: dict[str, dict[str, Any]] = {}
    duplicate_counter: Counter[str] = Counter()
    errors: list[dict[str, Any]] = []

    query_specs = [{"scope": "general", "property_type": "all", "query": "propiedades venta region metropolitana"}]
    for commune in communes:
        for property_type, template in PROPERTY_QUERIES.items():
            query_specs.append(
                {
                    "scope": "commune",
                    "property_type": property_type,
                    "commune": commune,
                    "query": template.format(commune=commune.replace("_", " ")),
                }
            )

    for spec in query_specs:
        try:
            search_payload = search_items(
                client,
                query=spec["query"],
                category_id=search_category_id,
                limit=limit,
            )
            search_error = None
        except httpx.HTTPError as exc:
            search_payload = {"results": [], "paging": {}}
            search_error = str(exc)
            errors.append(
                {
                    "stage": "search",
                    "query": spec["query"],
                    "category_id": search_category_id,
                    "error": search_error,
                }
            )
        results = search_payload.get("results") if isinstance(search_payload, dict) else []
        paging = search_payload.get("paging") if isinstance(search_payload, dict) else {}
        ids = [str(item.get("id")) for item in results if item.get("id")]
        duplicate_counter.update(ids)
        searches.append(
            {
                **spec,
                "category_id": search_category_id,
                "result_count": len(ids),
                "paging": {
                    "total": paging.get("total"),
                    "primary_results": paging.get("primary_results"),
                    "offset": paging.get("offset"),
                    "limit": paging.get("limit"),
                },
                "error": search_error,
                "item_ids": ids,
                "sample_titles": [item.get("title") for item in results[:3]],
            }
        )
        for item_id in ids:
            if item_id in detail_by_id:
                continue
            try:
                detail = fetch_json(client, f"/items/{item_id}")
                detail_by_id[item_id] = extract_item(detail)
                if sleep_seconds > 0:
                    time.sleep(sleep_seconds)
            except httpx.HTTPError as exc:
                errors.append({"stage": "item_detail", "item_id": item_id, "error": str(exc)})

    items = list(detail_by_id.values())
    field_stats = summarize_fields(items)
    location_quality = summarize_location_quality(items)
    duplicates = {item_id: count for item_id, count in duplicate_counter.items() if count > 1}
    decision = build_decision(
        items=items,
        searches=searches,
        field_stats=field_stats,
        location_quality=location_quality,
        errors=errors,
    )

    return {
        "generated_at": generated_at,
        "site_id": SITE_ID,
        "docs": DOC_REFERENCES,
        "category_discovery": {
            "realestate_category": realestate_category,
            "errors": category_errors,
            "leaf_categories_sample": leaf_categories[:40],
            "leaf_category_count": len(leaf_categories),
        },
        "summary": {
            "queries": len(searches),
            "unique_items": len(items),
            "duplicate_item_ids": len(duplicates),
            "coordinate_presence_pct": field_stats["presence_pct"].get("latitude", 0.0),
            "address_presence_pct": field_stats["presence_pct"].get("address", 0.0),
            "m2_presence_pct": field_stats["presence_pct"].get("m2", 0.0),
            "bedrooms_presence_pct": field_stats["presence_pct"].get("bedrooms", 0.0),
            "bathrooms_presence_pct": field_stats["presence_pct"].get("bathrooms", 0.0),
            "errors": len(errors),
        },
        "searches": searches,
        "field_stats": field_stats,
        "location_quality": location_quality,
        "duplicates": duplicates,
        "pagination_limitations": analyze_pagination(searches),
        "items": items,
        "errors": errors,
        "decision": decision,
    }


def fetch_json(client: httpx.Client, path: str, *, params: dict[str, Any] | None = None) -> Any:
    response = client.get(path, params=params)
    response.raise_for_status()
    return response.json()


def discover_realestate_category(
    client: httpx.Client,
    categories: Any,
    *,
    errors: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not isinstance(categories, list):
        return None
    candidates = [
        category
        for category in categories
        if "inmueble" in normalize_text(str(category.get("name", "")))
        or "propiedad" in normalize_text(str(category.get("name", "")))
    ]
    if not candidates:
        # Fallback historico observado para MLC real estate.
        try:
            category = fetch_json(client, "/categories/MLC1459")
            return {
                "id": category.get("id", "MLC1459"),
                "name": category.get("name", "MLC1459"),
                "source": "fallback_MLC1459",
            }
        except httpx.HTTPError as exc:
            errors.append({"endpoint": "/categories/MLC1459", "error": str(exc)})
            return {"id": "MLC1459", "name": "Inmuebles", "source": "hardcoded_MLC1459_after_category_error"}
    selected = candidates[0]
    return {
        "id": selected.get("id"),
        "name": selected.get("name"),
        "total_items_in_this_category": selected.get("total_items_in_this_category"),
        "source": "sites_categories",
    }


def fetch_category_tree(client: httpx.Client, category_id: str) -> dict[str, Any] | None:
    try:
        return fetch_json(client, f"/categories/{category_id}")
    except httpx.HTTPError:
        return None


def flatten_categories(category: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not category:
        return []
    rows: list[dict[str, Any]] = []

    def walk(node: dict[str, Any], path: list[str]) -> None:
        name = str(node.get("name") or "")
        current_path = [*path, name]
        children = node.get("children_categories") or []
        if not children:
            rows.append(
                {
                    "id": node.get("id"),
                    "name": name,
                    "path": " > ".join(part for part in current_path if part),
                    "total_items_in_this_category": node.get("total_items_in_this_category"),
                }
            )
            return
        for child in children:
            walk(child, current_path)

    walk(category, [])
    return rows


def search_items(client: httpx.Client, *, query: str, category_id: str | None, limit: int) -> dict[str, Any]:
    params: dict[str, Any] = {"q": query, "limit": limit, "offset": 0}
    if category_id:
        params["category"] = category_id
    return fetch_json(client, f"/sites/{SITE_ID}/search", params=params)


def extract_item(item: dict[str, Any]) -> dict[str, Any]:
    attributes = item.get("attributes") or []
    attr_map = attribute_map(attributes)
    location = item.get("location") or {}
    latitude = first_non_empty(
        location.get("latitude"),
        item.get("latitude"),
        item.get("seller_address", {}).get("latitude") if isinstance(item.get("seller_address"), dict) else None,
    )
    longitude = first_non_empty(
        location.get("longitude"),
        item.get("longitude"),
        item.get("seller_address", {}).get("longitude") if isinstance(item.get("seller_address"), dict) else None,
    )
    address = first_non_empty(
        location.get("address_line"),
        location.get("address"),
        item.get("address"),
        nested_name(location.get("neighborhood")),
    )
    comuna = extract_comuna(location)
    return {
        "external_id": item.get("id"),
        "title": item.get("title"),
        "price": item.get("price"),
        "currency": item.get("currency_id"),
        "permalink": item.get("permalink"),
        "seller_id": item.get("seller_id"),
        "location": location,
        "comuna": comuna,
        "address": address,
        "latitude": latitude,
        "longitude": longitude,
        "attributes": attributes,
        "attributes_compact": compact_attributes(attributes),
        "m2": first_attribute_value(attr_map, "m2"),
        "bedrooms": first_attribute_value(attr_map, "bedrooms"),
        "bathrooms": first_attribute_value(attr_map, "bathrooms"),
        "operation_type": first_attribute_value(attr_map, "operation_type"),
        "property_type": first_attribute_value(attr_map, "property_type"),
        "listing_date": first_non_empty(item.get("date_created"), item.get("start_time"), item.get("last_updated")),
        "category_id": item.get("category_id"),
        "status": item.get("status"),
        "condition": item.get("condition"),
    }


def attribute_map(attributes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(attr.get("id")): attr for attr in attributes if attr.get("id")}


def compact_attributes(attributes: list[dict[str, Any]]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for attr in attributes:
        key = attr.get("id") or attr.get("name")
        if key:
            compact[str(key)] = display_attribute_value(attr)
    return compact


def first_attribute_value(attr_map: dict[str, dict[str, Any]], semantic: str) -> Any:
    for attr_id in ATTRIBUTE_ALIASES[semantic]:
        attr = attr_map.get(attr_id)
        if attr is not None:
            return display_attribute_value(attr)
    return None


def display_attribute_value(attr: dict[str, Any]) -> Any:
    if attr.get("value_name") not in (None, ""):
        return attr.get("value_name")
    if attr.get("value_id") not in (None, ""):
        return attr.get("value_id")
    if isinstance(attr.get("values"), list) and attr["values"]:
        return ", ".join(str(value.get("name") or value.get("id")) for value in attr["values"])
    value_struct = attr.get("value_struct")
    if isinstance(value_struct, dict):
        number = value_struct.get("number")
        unit = value_struct.get("unit")
        if number is not None and unit:
            return f"{number} {unit}"
        if number is not None:
            return number
    return None


def extract_comuna(location: dict[str, Any]) -> str | None:
    for key in ("city", "neighborhood", "municipality"):
        value = nested_name(location.get(key))
        if value:
            return value
    return None


def nested_name(value: Any) -> str | None:
    if isinstance(value, dict):
        return first_non_empty(value.get("name"), value.get("id"))
    if isinstance(value, str):
        return value
    return None


def first_non_empty(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def summarize_fields(items: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(items)
    present: Counter[str] = Counter()
    missing: dict[str, list[str]] = defaultdict(list)
    attribute_ids: Counter[str] = Counter()
    category_ids: Counter[str] = Counter()
    currencies: Counter[str] = Counter()

    for item in items:
        external_id = str(item.get("external_id"))
        for field in DETAIL_FIELDS:
            value = item.get(field)
            has_value = value not in (None, "", [], {})
            if has_value:
                present[field] += 1
            else:
                missing[field].append(external_id)
        for attr in item.get("attributes") or []:
            if attr.get("id"):
                attribute_ids[str(attr["id"])] += 1
        if item.get("category_id"):
            category_ids[str(item["category_id"])] += 1
        if item.get("currency"):
            currencies[str(item["currency"])] += 1

    return {
        "total_items": total,
        "present_counts": {field: present[field] for field in DETAIL_FIELDS},
        "missing_counts": {field: total - present[field] for field in DETAIL_FIELDS},
        "presence_pct": {field: pct(present[field], total) for field in DETAIL_FIELDS},
        "missing_sample_ids": {field: ids[:10] for field, ids in missing.items()},
        "attribute_id_counts": dict(attribute_ids.most_common(50)),
        "category_id_counts": dict(category_ids.most_common()),
        "currency_counts": dict(currencies.most_common()),
    }


def summarize_location_quality(items: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(items)
    both_coords = [item for item in items if item.get("latitude") is not None and item.get("longitude") is not None]
    address = [item for item in items if item.get("address")]
    comuna = [item for item in items if item.get("comuna")]
    quality_counts = Counter(location_quality(item) for item in items)
    by_comuna = Counter(str(item.get("comuna") or "unknown") for item in items)
    return {
        "with_coordinates": len(both_coords),
        "with_coordinates_pct": pct(len(both_coords), total),
        "with_address": len(address),
        "with_address_pct": pct(len(address), total),
        "with_comuna": len(comuna),
        "with_comuna_pct": pct(len(comuna), total),
        "quality_counts": dict(quality_counts.most_common()),
        "by_comuna": dict(by_comuna.most_common()),
        "coordinate_sample": [
            {
                "external_id": item.get("external_id"),
                "title": item.get("title"),
                "comuna": item.get("comuna"),
                "lat": item.get("latitude"),
                "lon": item.get("longitude"),
                "address": item.get("address"),
            }
            for item in both_coords[:10]
        ],
    }


def location_quality(item: dict[str, Any]) -> str:
    has_coords = item.get("latitude") is not None and item.get("longitude") is not None
    has_address = bool(item.get("address"))
    has_comuna = bool(item.get("comuna"))
    if has_coords and has_address:
        return "coordinates_and_address"
    if has_coords:
        return "coordinates_only"
    if has_address and has_comuna:
        return "address_and_comuna"
    if has_comuna:
        return "comuna_only"
    return "missing_location"


def analyze_pagination(searches: list[dict[str, Any]]) -> dict[str, Any]:
    totals = [search["paging"].get("total") for search in searches if isinstance(search.get("paging"), dict)]
    primary_results = [
        search["paging"].get("primary_results")
        for search in searches
        if isinstance(search.get("paging"), dict) and search["paging"].get("primary_results") is not None
    ]
    return {
        "max_reported_total": max([value for value in totals if isinstance(value, int)], default=None),
        "max_primary_results": max([value for value in primary_results if isinstance(value, int)], default=None),
        "note": (
            "El probe usa limit bajo y offset 0. Para producción habría que validar límites de offset, "
            "ordenamiento, filtros disponibles y estabilidad/duplicados por refresh incremental."
        ),
    }


def build_decision(
    *,
    items: list[dict[str, Any]],
    searches: list[dict[str, Any]],
    field_stats: dict[str, Any],
    location_quality: dict[str, Any],
    errors: list[dict[str, Any]],
) -> dict[str, Any]:
    unique_items = len(items)
    coord_pct = field_stats["presence_pct"].get("latitude", 0.0)
    m2_pct = field_stats["presence_pct"].get("m2", 0.0)
    bedrooms_pct = field_stats["presence_pct"].get("bedrooms", 0.0)
    bathrooms_pct = field_stats["presence_pct"].get("bathrooms", 0.0)
    address_pct = field_stats["presence_pct"].get("address", 0.0)
    enough_items = unique_items >= max(10, len(searches))
    critical_missing = [
        name
        for name, value in {
            "m2": m2_pct,
            "bedrooms": bedrooms_pct,
            "bathrooms": bathrooms_pct,
            "coordinates": coord_pct,
            "address": address_pct,
        }.items()
        if value < 70.0
    ]
    serves_secondary = unique_items > 0 and m2_pct >= 50.0
    serves_primary = serves_secondary and coord_pct >= 60.0 and address_pct >= 50.0 and enough_items
    enrichment = unique_items > 0 and (coord_pct < 70.0 or address_pct < 70.0)
    return {
        "serves_as_primary_source": "yes" if serves_primary else "no",
        "serves_as_secondary_source": "yes" if serves_secondary else "no",
        "critical_missing_fields": critical_missing,
        "keep_trying_portal_scraper": "yes",
        "use_api_plus_enrichment_scraper": "yes" if enrichment else "optional",
        "estimated_integration_effort": estimate_effort(unique_items, critical_missing, errors),
        "rationale": [
            f"Items únicos observados: {unique_items}.",
            f"Coordenadas: {coord_pct}%; address: {address_pct}%; m2: {m2_pct}%; dormitorios: {bedrooms_pct}%; baños: {bathrooms_pct}%.",
            f"Calidad ubicación: {location_quality.get('quality_counts', {})}.",
            "La API reduce bloqueo/Akamai del scraper, pero hay que validar cobertura, filtros, paginación e identidad incremental.",
        ],
    }


def estimate_effort(unique_items: int, critical_missing: list[str], errors: list[dict[str, Any]]) -> str:
    if unique_items == 0:
        return "alto: primero resolver acceso/categoría/query."
    if "coordinates" in critical_missing or "address" in critical_missing:
        return "medio-alto: adapter + enrichment de ubicación + paginación incremental."
    if errors:
        return "medio: adapter + manejo robusto de errores/paginación."
    return "medio: adapter de API, normalización y deduplicación contra source/external_id."


def markdown_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    decision = report["decision"]
    lines = [
        "# Mercado Libre API Real Estate Probe",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Site: `{report['site_id']}`",
        f"- Unique items: {summary['unique_items']}",
        f"- Queries: {summary['queries']}",
        f"- Duplicate item IDs: {summary['duplicate_item_ids']}",
        "",
        "## Official API References",
        "",
    ]
    for doc in report["docs"]:
        lines.append(f"- [{doc['title']}]({doc['url']}): {doc['note']}")
    lines.extend(
        [
            "",
            "## Category Discovery",
            "",
            f"- Real estate category: `{json.dumps(report['category_discovery']['realestate_category'], ensure_ascii=False)}`",
            f"- Leaf category count observed: {report['category_discovery']['leaf_category_count']}",
            "",
            "## Search Results",
            "",
            table(
                ["scope", "property_type", "commune", "query", "result_count", "total", "primary_results", "error"],
                [
                    [
                        row.get("scope", ""),
                        row.get("property_type", ""),
                        row.get("commune", ""),
                        row.get("query", ""),
                        row.get("result_count", 0),
                        row.get("paging", {}).get("total"),
                        row.get("paging", {}).get("primary_results"),
                        truncate(str(row.get("error") or ""), 90),
                    ]
                    for row in report["searches"]
                ],
            ),
            "",
            "## API Errors",
            "",
            table(
                ["stage", "query/item", "category_id", "error"],
                [
                    [
                        error.get("stage", "category"),
                        error.get("query") or error.get("item_id") or error.get("endpoint"),
                        error.get("category_id", ""),
                        truncate(str(error.get("error") or ""), 120),
                    ]
                    for error in [
                        *report["category_discovery"].get("errors", []),
                        *report.get("errors", []),
                    ]
                ],
            ),
            "",
            "## Field Availability",
            "",
            table(
                ["field", "present", "missing", "presence_pct"],
                [
                    [
                        field,
                        report["field_stats"]["present_counts"].get(field, 0),
                        report["field_stats"]["missing_counts"].get(field, 0),
                        report["field_stats"]["presence_pct"].get(field, 0.0),
                    ]
                    for field in DETAIL_FIELDS
                ],
            ),
            "",
            "## Location Quality",
            "",
            f"- With coordinates: {report['location_quality']['with_coordinates']} ({report['location_quality']['with_coordinates_pct']}%)",
            f"- With address: {report['location_quality']['with_address']} ({report['location_quality']['with_address_pct']}%)",
            f"- With comuna: {report['location_quality']['with_comuna']} ({report['location_quality']['with_comuna_pct']}%)",
            f"- Quality counts: `{json.dumps(report['location_quality']['quality_counts'], ensure_ascii=False)}`",
            "",
            "## Duplicates",
            "",
            f"- Duplicate IDs across queries: {len(report['duplicates'])}",
            f"- Sample: `{json.dumps(dict(list(report['duplicates'].items())[:10]), ensure_ascii=False)}`",
            "",
            "## Pagination Limitations",
            "",
            f"- Max reported total: {report['pagination_limitations']['max_reported_total']}",
            f"- Max primary results: {report['pagination_limitations']['max_primary_results']}",
            f"- Note: {report['pagination_limitations']['note']}",
            "",
            "## Decision",
            "",
            f"1. API sirve como fuente principal: **{decision['serves_as_primary_source']}**",
            f"2. API sirve como fuente secundaria: **{decision['serves_as_secondary_source']}**",
            f"3. Campos críticos faltantes: `{', '.join(decision['critical_missing_fields']) or 'none'}`",
            f"4. Conviene seguir intentando scraper Portal: **{decision['keep_trying_portal_scraper']}**",
            f"5. Conviene usar API + enrichment scraper: **{decision['use_api_plus_enrichment_scraper']}**",
            f"6. Esfuerzo estimado: **{decision['estimated_integration_effort']}**",
            "",
            "### Rationale",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in decision["rationale"])
    lines.extend(
        [
            "",
            "## Sample Items",
            "",
            table(
                ["external_id", "title", "price", "currency", "comuna", "address", "lat", "lon", "m2", "bedrooms", "bathrooms"],
                [
                    [
                        item.get("external_id"),
                        truncate(str(item.get("title") or ""), 70),
                        item.get("price"),
                        item.get("currency"),
                        item.get("comuna"),
                        truncate(str(item.get("address") or ""), 50),
                        item.get("latitude"),
                        item.get("longitude"),
                        item.get("m2"),
                        item.get("bedrooms"),
                        item.get("bathrooms"),
                    ]
                    for item in report["items"][:20]
                ],
            ),
            "",
        ]
    )
    return "\n".join(lines)


def table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return "_No data._"
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(escape_md(value) for value in row) + " |")
    return "\n".join(lines)


def escape_md(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ")


def truncate(value: str, length: int) -> str:
    return value if len(value) <= length else value[: length - 1] + "..."


def normalize_commune_arg(value: str) -> str:
    return normalize_text(value).replace(" ", "_")


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    without_marks = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(without_marks.lower().replace("_", " ").split())


def pct(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round((numerator / denominator) * 100, 2)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
