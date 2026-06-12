"""Read-only dataset coverage and diversity audit for AVM-v2.

Usage:
    python scripts/dataset_coverage_audit.py --output-dir reports/dataset_coverage_audit
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any

from sqlalchemy import func, select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.assessment.beta_status import (  # noqa: E402
    DatasetBetaStatus,
    PropertyTypeCoverageStatus,
    dataset_beta_status_to_canonical,
)
from core.normalization.geocode_precision import normalize_geocode_precision  # noqa: E402
from core.normalization.property_type import normalize_property_type as _property_type  # noqa: E402
from domain.geocoding.geographic_microzones import (  # noqa: E402
    geographic_microzone_for,
)
from domain.geocoding.microzones import signals_from_value  # noqa: E402
from domain.valuation.price_surface import m2_bucket  # noqa: E402
from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.models import ListingORM, PriceHistoryORM  # noqa: E402

try:  # Optional runtime dependency already declared by the project.
    import pandas as pd
    import plotly.express as px
except ImportError:  # pragma: no cover - exercised only in lean envs.
    pd = None
    px = None


DEFAULT_OUTPUT_DIR = Path("reports/dataset_coverage_audit")
KNOWN_PROPERTY_TYPES = {"apartment", "house"}
BETA_MIN_USEFUL = 50
ROBUST_MIN_USEFUL = 150
MIN_BUCKET_COUNT = 10
MAX_BETA_DISPERSION_PCT = 85.0
MAX_HIDE_DISPERSION_PCT = 130.0
MAX_STALE_PCT = 70.0
RM_TARGET_COMUNAS = {
    "cerrillos",
    "cerro_navia",
    "conchali",
    "el_bosque",
    "estacion_central",
    "huechuraba",
    "independencia",
    "la_cisterna",
    "la_florida",
    "la_granja",
    "la_pintana",
    "la_reina",
    "las_condes",
    "lo_barnechea",
    "lo_espejo",
    "lo_prado",
    "macul",
    "maipu",
    "nunoa",
    "pedro_aguirre_cerda",
    "penalolen",
    "providencia",
    "pudahuel",
    "quilicura",
    "quinta_normal",
    "recoleta",
    "renca",
    "san_joaquin",
    "san_miguel",
    "san_ramon",
    "santiago",
    "vitacura",
}


@dataclass(frozen=True)
class AuditArtifacts:
    json_path: Path
    markdown_path: Path
    csv_dir: Path
    charts_dir: Path


def build_audit(
    listings: list[dict[str, Any]],
    price_history_counts: dict[int, int],
    *,
    stale_days: int = 45,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    now = generated_at or datetime.now(UTC)
    rows = [_listing_row(row, price_history_counts, now=now, stale_days=stale_days) for row in listings]
    active = [row for row in rows if row["status"] == "active"]
    useful = [row for row in active if _is_avm_useful(row)]

    by_comuna = _comuna_rows(active)
    by_comuna_property_type = _comuna_property_type_rows(active)
    by_property_type = _counter_rows(active, "property_type")
    by_m2_bucket = _counter_rows(useful, "m2_bucket")
    by_source = _counter_rows(rows, "source")
    by_geocode_precision = _counter_rows(active, "geocode_precision")
    temporal = _temporal_rows(active)
    duplicates = _duplicate_summary(rows)
    price_history = _price_history_summary(active)
    microzones = _microzone_summary(active)
    geographic_microzones = _geographic_microzone_summary(active)
    dispersion = _dispersion_rows(active)
    rm_coverage = _rm_coverage_rows(by_comuna)
    beta = _beta_readiness_rows(by_comuna_property_type, active)
    property_type_viability = _property_type_viability_rows(by_comuna_property_type, active)
    minimum_dataset = _minimum_dataset_estimate(by_comuna_property_type)

    source_total = sum(row["count"] for row in by_source)
    top_source = by_source[0] if by_source else {"value": "none", "count": 0, "pct": 0.0}
    stale_count = sum(1 for row in active if row["is_stale"])
    usable_coords = sum(1 for row in active if row["lat"] is not None and row["lon"] is not None)
    houses = [row for row in active if row["property_type"] == "house"]
    apartments = [row for row in active if row["property_type"] == "apartment"]
    beta_ready_segments = [row for row in beta if row["beta_status"] == DatasetBetaStatus.BETA_READY]
    hide_segments = [row for row in beta if row["beta_status"] == DatasetBetaStatus.HIDE_IN_BETA]

    return {
        "summary": {
            "generated_at": now.isoformat(),
            "stale_days": stale_days,
            "total_listings": len(rows),
            "active_listings": len(active),
            "avm_useful_listings": len(useful),
            "avm_useful_pct": _pct(len(useful), len(active)),
            "observed_comunas": len({row["comuna"] for row in active if row["comuna"] != "unknown"}),
            "rm_target_comunas": len(RM_TARGET_COMUNAS),
            "rm_target_coverage_pct": _pct(
                len({row["comuna"] for row in active if row["comuna"] in RM_TARGET_COMUNAS}),
                len(RM_TARGET_COMUNAS),
            ),
            "usable_coords_pct": _pct(usable_coords, len(active)),
            "stale_active_listings": stale_count,
            "stale_active_pct": _pct(stale_count, len(active)),
            "top_source": top_source["value"],
            "top_source_pct": top_source["pct"] if source_total else 0.0,
            "near_duplicate_groups": duplicates["near_duplicate_groups"],
            "price_history_usable_pct": price_history["listings_with_2plus_history_pct"],
            "useful_microzone_pct": microzones["useful_microzone_pct"],
            "geographic_microzone_pct": geographic_microzones["geographic_microzone_coverage_pct"],
            "geographic_microzone_count": geographic_microzones["geographic_microzone_count"],
            "geographic_microzone_sufficient_count": geographic_microzones["sufficient_microzone_count"],
            "house_land_area_coverage_pct": _pct(sum(row["has_land_area_m2"] for row in houses), len(houses)),
            "apartment_usable_area_coverage_pct": _pct(sum(row["has_usable_area_m2"] for row in apartments), len(apartments)),
            "area_parse_provenance_count": sum(row["has_area_parse_provenance"] for row in active),
            "area_parse_provenance_pct": _pct(sum(row["has_area_parse_provenance"] for row in active), len(active)),
            "beta_ready_segments": len(beta_ready_segments),
            "hide_in_beta_segments": len(hide_segments),
            "overfitting_risk": _overfitting_risk(
                active=active,
                duplicates=duplicates,
                microzones=microzones,
                by_source=by_source,
                beta=beta,
            ),
        },
        "by_comuna": by_comuna,
        "by_comuna_property_type": by_comuna_property_type,
        "by_property_type": by_property_type,
        "by_m2_bucket": by_m2_bucket,
        "by_source": by_source,
        "by_geocode_precision": by_geocode_precision,
        "area_quality": _area_quality_summary(active),
        "temporal_distribution": temporal,
        "duplicates": duplicates,
        "price_history": price_history,
        "microzones": microzones,
        "geographic_microzones": geographic_microzones,
        "dispersion_by_comuna": dispersion,
        "rm_coverage": rm_coverage,
        "beta_readiness": beta,
        "property_type_viability": property_type_viability,
        "minimum_dataset_estimate": minimum_dataset,
        "conclusion": _conclusion(beta, property_type_viability, active),
        "chart_data": _chart_data(active, by_comuna_property_type, dispersion),
    }


def write_audit(report: dict[str, Any], *, output_dir: Path = DEFAULT_OUTPUT_DIR) -> AuditArtifacts:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_dir = output_dir / "csv"
    charts_dir = output_dir / "charts"
    csv_dir.mkdir(parents=True, exist_ok=True)
    charts_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"dataset_coverage_audit_{stamp}.json"
    markdown_path = output_dir / f"dataset_coverage_audit_{stamp}.md"

    json_path.write_text(json.dumps(_json_safe(report), ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(_markdown_report(report), encoding="utf-8")
    _write_csvs(report, csv_dir, stamp)
    _write_charts(report, charts_dir, stamp)
    return AuditArtifacts(json_path=json_path, markdown_path=markdown_path, csv_dir=csv_dir, charts_dir=charts_dir)


def print_console_report(report: dict[str, Any], artifacts: AuditArtifacts | None = None) -> None:
    summary = report["summary"]
    print("== AVM Dataset Coverage Audit ==")
    print(f"active_listings\t{summary['active_listings']}")
    print(f"avm_useful_listings\t{summary['avm_useful_listings']}")
    print(f"avm_useful_pct\t{summary['avm_useful_pct']}")
    print(f"observed_comunas\t{summary['observed_comunas']}")
    print(f"usable_coords_pct\t{summary['usable_coords_pct']}")
    print(f"top_source\t{summary['top_source']}")
    print(f"top_source_pct\t{summary['top_source_pct']}")
    print(f"useful_microzone_pct\t{summary['useful_microzone_pct']}")
    print(f"geographic_microzone_pct\t{summary['geographic_microzone_pct']}")
    print(f"geographic_microzone_count\t{summary['geographic_microzone_count']}")
    print(f"geographic_microzone_sufficient_count\t{summary['geographic_microzone_sufficient_count']}")
    print(f"price_history_usable_pct\t{summary['price_history_usable_pct']}")
    print(f"house_land_area_coverage_pct\t{summary['house_land_area_coverage_pct']}")
    print(f"apartment_usable_area_coverage_pct\t{summary['apartment_usable_area_coverage_pct']}")
    print(f"area_parse_provenance_pct\t{summary['area_parse_provenance_pct']}")
    print(f"beta_ready_segments\t{summary['beta_ready_segments']}")
    print(f"hide_in_beta_segments\t{summary['hide_in_beta_segments']}")
    print(f"overfitting_risk\t{summary['overfitting_risk']}")

    print("\n== Property types ==")
    for row in report["by_property_type"]:
        print(f"{row['value']}\t{row['count']}\t{row['pct']}%")

    print("\n== Beta-ready segments ==")
    for row in [item for item in report["beta_readiness"] if item["beta_status"] == DatasetBetaStatus.BETA_READY][:20]:
        print(f"{row['comuna']}\t{row['property_type']}\tuseful={row['useful_listings']}\tdispersion={row['price_m2_iqr_pct']}")

    print("\n== Hide in beta ==")
    for row in [item for item in report["beta_readiness"] if item["beta_status"] == DatasetBetaStatus.HIDE_IN_BETA][:20]:
        print(f"{row['comuna']}\t{row['property_type']}\t{row['reason']}")

    if artifacts is not None:
        print("\n== Files ==")
        print(f"json\t{artifacts.json_path}")
        print(f"markdown\t{artifacts.markdown_path}")
        print(f"csv_dir\t{artifacts.csv_dir}")
        print(f"charts_dir\t{artifacts.charts_dir}")


def _listing_row(
    listing: dict[str, Any],
    price_history_counts: dict[int, int],
    *,
    now: datetime,
    stale_days: int,
) -> dict[str, Any]:
    scraped_at = _as_aware_datetime(listing.get("scraped_at"))
    area = _built_area(listing)
    price = _float_or_none(listing.get("price_clp")) or 0.0
    property_type = _property_type(listing.get("property_type"))
    raw_metadata = listing.get("raw_metadata") if isinstance(listing.get("raw_metadata"), dict) else {}
    lat = _float_or_none(listing.get("lat"))
    lon = _float_or_none(listing.get("lon"))
    geocode_precision = normalize_geocode_precision(
        listing.get("geocode_precision"),
        has_coords=lat is not None and lon is not None,
        raw_metadata=raw_metadata,
        comuna=listing.get("comuna"),
    )
    signals = _signals_for_listing(listing)
    microzone_tokens = _microzone_tokens(signals)
    age_days = (now - scraped_at).days if scraped_at is not None else None
    return {
        "id": listing.get("id"),
        "source": _norm_text(listing.get("source"), default="unknown"),
        "external_id": _norm_text(listing.get("external_id"), default=""),
        "fingerprint": _norm_text(listing.get("fingerprint"), default=""),
        "title": str(listing.get("title") or ""),
        "url": str(listing.get("url") or ""),
        "status": _norm_text(listing.get("status"), default="unknown"),
        "comuna": _norm_text(listing.get("comuna"), default="unknown"),
        "property_type": property_type,
        "m2": _float_or_none(listing.get("m2")),
        "built_area_m2": _float_or_none(listing.get("built_area_m2")),
        "usable_area_m2": _float_or_none(listing.get("usable_area_m2")),
        "land_area_m2": _float_or_none(listing.get("land_area_m2")),
        "has_built_area_m2": _has_positive(listing.get("built_area_m2")),
        "has_usable_area_m2": _has_positive(listing.get("usable_area_m2")),
        "has_land_area_m2": _has_positive(listing.get("land_area_m2")),
        "has_area_parse_provenance": bool(raw_metadata.get("area_parse_version")),
        "area_m2": area,
        "m2_bucket": m2_bucket(area),
        "bedrooms": listing.get("bedrooms"),
        "bathrooms": listing.get("bathrooms"),
        "parking": listing.get("parking"),
        "lat": lat,
        "lon": lon,
        "geocode_precision": geocode_precision,
        "price_clp": price,
        "price_m2": round(price / area, 2) if area and area > 0 and price > 0 else None,
        "raw_metadata": raw_metadata,
        "scraped_at": scraped_at,
        "age_days": age_days,
        "is_stale": age_days is None or age_days > stale_days,
        "price_history_count": price_history_counts.get(int(listing["id"]), 0) if listing.get("id") is not None else 0,
        "nearby_metro": signals.nearby_metro,
        "nearby_avenue": signals.nearby_avenue,
        "neighborhood_hint": signals.neighborhood_hint,
        "intersection_hint": signals.intersection_hint,
        "microzone_tokens": microzone_tokens,
        "microzone_confidence": signals.confidence,
        "microzone_reason": signals.reason,
        "has_useful_microzone": signals.confidence >= 0.55 and bool(microzone_tokens),
    }


def _comuna_rows(active: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in active:
        grouped[row["comuna"]].append(row)
    rows = []
    for comuna, items in sorted(grouped.items()):
        useful = [row for row in items if _is_avm_useful(row)]
        price_m2_values = [row["price_m2"] for row in useful if row["price_m2"] is not None]
        rows.append(
            {
                "comuna": comuna,
                "active_listings": len(items),
                "useful_listings": len(useful),
                "useful_pct": _pct(len(useful), len(items)),
                "property_types": sorted({row["property_type"] for row in items}),
                "stale_pct": _pct(sum(row["is_stale"] for row in items), len(items)),
                "usable_coords_pct": _pct(sum(row["lat"] is not None and row["lon"] is not None for row in items), len(items)),
                "useful_microzone_pct": _pct(sum(row["has_useful_microzone"] for row in items), len(items)),
                "built_area_m2_pct": _pct(sum(row["has_built_area_m2"] for row in items), len(items)),
                "usable_area_m2_pct": _pct(sum(row["has_usable_area_m2"] for row in items), len(items)),
                "land_area_m2_pct": _pct(sum(row["has_land_area_m2"] for row in items), len(items)),
                "area_parse_provenance_pct": _pct(sum(row["has_area_parse_provenance"] for row in items), len(items)),
                "median_price_m2": _round(_safe_median(price_m2_values)),
                "price_m2_iqr_pct": _round(_iqr_pct(price_m2_values)),
            }
        )
    return sorted(rows, key=lambda row: (-row["useful_listings"], row["comuna"]))


def _comuna_property_type_rows(active: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in active:
        grouped[(row["comuna"], row["property_type"])].append(row)
    rows = []
    for (comuna, property_type), items in sorted(grouped.items()):
        useful = [row for row in items if _is_avm_useful(row)]
        price_m2_values = [row["price_m2"] for row in useful if row["price_m2"] is not None]
        bucket_counts = Counter(row["m2_bucket"] for row in useful)
        rows.append(
            {
                "comuna": comuna,
                "property_type": property_type,
                "active_listings": len(items),
                "useful_listings": len(useful),
                "useful_pct": _pct(len(useful), len(items)),
                "m2_buckets_with_10plus": sum(1 for count in bucket_counts.values() if count >= MIN_BUCKET_COUNT),
                "top_m2_bucket": bucket_counts.most_common(1)[0][0] if bucket_counts else "unknown",
                "top_m2_bucket_count": bucket_counts.most_common(1)[0][1] if bucket_counts else 0,
                "stale_pct": _pct(sum(row["is_stale"] for row in items), len(items)),
                "usable_coords_pct": _pct(sum(row["lat"] is not None and row["lon"] is not None for row in items), len(items)),
                "useful_microzone_pct": _pct(sum(row["has_useful_microzone"] for row in items), len(items)),
                "built_area_m2_pct": _pct(sum(row["has_built_area_m2"] for row in items), len(items)),
                "usable_area_m2_pct": _pct(sum(row["has_usable_area_m2"] for row in items), len(items)),
                "land_area_m2_pct": _pct(sum(row["has_land_area_m2"] for row in items), len(items)),
                "area_parse_provenance_pct": _pct(sum(row["has_area_parse_provenance"] for row in items), len(items)),
                "median_price_m2": _round(_safe_median(price_m2_values)),
                "price_m2_iqr_pct": _round(_iqr_pct(price_m2_values)),
            }
        )
    return sorted(rows, key=lambda row: (-row["useful_listings"], row["comuna"], row["property_type"]))


def _counter_rows(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    counter = Counter(row.get(key) or "unknown" for row in rows)
    total = sum(counter.values())
    return [
        {"value": value, "count": count, "pct": _pct(count, total)}
        for value, count in counter.most_common()
    ]


def _temporal_rows(active: list[dict[str, Any]]) -> dict[str, Any]:
    age_buckets = Counter(_age_bucket(row["age_days"]) for row in active)
    by_month = Counter(
        row["scraped_at"].strftime("%Y-%m") if row["scraped_at"] is not None else "unknown"
        for row in active
    )
    scraped_dates = [row["scraped_at"] for row in active if row["scraped_at"] is not None]
    return {
        "oldest_scraped_at": min(scraped_dates).isoformat() if scraped_dates else None,
        "newest_scraped_at": max(scraped_dates).isoformat() if scraped_dates else None,
        "age_buckets": [{"bucket": key, "count": value} for key, value in sorted(age_buckets.items())],
        "by_month": [{"month": key, "count": value} for key, value in sorted(by_month.items())],
    }


def _duplicate_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    active = [row for row in rows if row["status"] == "active"]
    source_external = Counter(
        f"{row['source']}|{row['external_id']}" for row in rows if row["source"] and row["external_id"]
    )
    fingerprints = Counter(row["fingerprint"] for row in rows if row["fingerprint"])
    near_keys = Counter(_near_duplicate_key(row) for row in active if _near_duplicate_key(row))
    near_groups = [(key, count) for key, count in near_keys.items() if count > 1]
    duplicate_rows = sum(count - 1 for _, count in near_groups)
    return {
        "source_external_duplicate_groups": sum(1 for count in source_external.values() if count > 1),
        "fingerprint_duplicate_groups": sum(1 for count in fingerprints.values() if count > 1),
        "near_duplicate_groups": len(near_groups),
        "near_duplicate_rows": duplicate_rows,
        "near_duplicate_pct_active": _pct(duplicate_rows, len(active)),
        "top_near_duplicate_keys": [
            {"key": key, "count": count} for key, count in sorted(near_groups, key=lambda item: -item[1])[:20]
        ],
    }


def _price_history_summary(active: list[dict[str, Any]]) -> dict[str, Any]:
    with_history = [row for row in active if row["price_history_count"] >= 1]
    usable = [row for row in active if row["price_history_count"] >= 2]
    return {
        "active_listings": len(active),
        "listings_with_history": len(with_history),
        "listings_with_history_pct": _pct(len(with_history), len(active)),
        "listings_with_2plus_history": len(usable),
        "listings_with_2plus_history_pct": _pct(len(usable), len(active)),
        "total_price_history_rows": sum(row["price_history_count"] for row in active),
    }


def _area_quality_summary(active: list[dict[str, Any]]) -> dict[str, Any]:
    by_type = []
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in active:
        grouped[row["property_type"]].append(row)
    for property_type, items in sorted(grouped.items()):
        by_type.append(
            {
                "property_type": property_type,
                "active_listings": len(items),
                "built_area_m2_pct": _pct(sum(row["has_built_area_m2"] for row in items), len(items)),
                "usable_area_m2_pct": _pct(sum(row["has_usable_area_m2"] for row in items), len(items)),
                "land_area_m2_pct": _pct(sum(row["has_land_area_m2"] for row in items), len(items)),
                "area_parse_provenance_pct": _pct(sum(row["has_area_parse_provenance"] for row in items), len(items)),
            }
        )

    house_rows = [row for row in active if row["property_type"] == "house"]
    by_comuna: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in house_rows:
        by_comuna[row["comuna"]].append(row)
    worst_house_land_area_comunas = []
    for comuna, items in by_comuna.items():
        missing = sum(not row["has_land_area_m2"] for row in items)
        worst_house_land_area_comunas.append(
            {
                "comuna": comuna,
                "house_active_listings": len(items),
                "house_land_area_m2_pct": _pct(len(items) - missing, len(items)),
                "missing_land_area_m2": missing,
            }
        )

    return {
        "by_property_type": by_type,
        "worst_house_land_area_comunas": sorted(
            worst_house_land_area_comunas,
            key=lambda row: (-row["missing_land_area_m2"], row["house_land_area_m2_pct"], row["comuna"]),
        )[:20],
        "listings_with_area_parse_provenance": sum(row["has_area_parse_provenance"] for row in active),
        "listings_with_area_parse_provenance_pct": _pct(sum(row["has_area_parse_provenance"] for row in active), len(active)),
    }


def _microzone_summary(active: list[dict[str, Any]]) -> dict[str, Any]:
    useful = [row for row in active if row["has_useful_microzone"]]
    token_counter: Counter[str] = Counter()
    by_comuna: dict[str, Counter[str]] = defaultdict(Counter)
    rejected = Counter()
    for row in active:
        if str(row["microzone_reason"]).startswith("rejected:"):
            rejected[row["microzone_reason"]] += 1
        for token in row["microzone_tokens"]:
            token_counter[token] += 1
            by_comuna[row["comuna"]][token] += 1

    concentrated = []
    for comuna, counter in by_comuna.items():
        total = sum(counter.values())
        if total < 10:
            continue
        token, count = counter.most_common(1)[0]
        share = _pct(count, total)
        if share >= 45:
            concentrated.append({"comuna": comuna, "top_token": token, "count": count, "share_pct": share})

    return {
        "useful_microzone": len(useful),
        "useful_microzone_pct": _pct(len(useful), len(active)),
        "top_tokens": [{"token": token, "count": count} for token, count in token_counter.most_common(30)],
        "top_tokens_by_comuna": _top_tokens_by_comuna(by_comuna),
        "concentrated_microzones": sorted(concentrated, key=lambda row: -row["share_pct"]),
        "rejected_false_positives": [{"reason": key, "count": value} for key, value in rejected.most_common(20)],
    }


def _geographic_microzone_summary(active: list[dict[str, Any]]) -> dict[str, Any]:
    decisions = [(row, geographic_microzone_for(row)) for row in active]
    eligible = [(row, decision) for row, decision in decisions if decision.microzone is not None]
    microzones: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row, decision in eligible:
        assert decision.microzone is not None
        microzones[decision.microzone.microzone_id].append(row)
    by_comuna = Counter(row["comuna"] for row, _ in eligible)
    sufficient = []
    for microzone_id, rows in microzones.items():
        property_types = Counter(row["property_type"] for row in rows)
        if any(count >= 5 for count in property_types.values()):
            sufficient.append(
                {
                    "microzone_id": microzone_id,
                    "listing_count": len(rows),
                    "property_type_counts": dict(property_types),
                }
            )
    return {
        "geographic_microzone_listings": len(eligible),
        "geographic_microzone_coverage_pct": _pct(len(eligible), len(active)),
        "geographic_microzone_count": len(microzones),
        "sufficient_microzone_count": len(sufficient),
        "by_comuna": [
            {"comuna": comuna, "count": count}
            for comuna, count in by_comuna.most_common()
        ],
        "sufficient_microzones": sorted(sufficient, key=lambda row: -row["listing_count"])[:30],
        "exclusion_reasons": [
            {"reason": reason, "count": count}
            for reason, count in Counter(decision.reason for _, decision in decisions).most_common()
        ],
    }


def _dispersion_rows(active: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in active:
        if _is_avm_useful(row) and row["price_m2"] is not None:
            grouped[(row["comuna"], row["property_type"])].append(row["price_m2"])
    rows = []
    for (comuna, property_type), values in grouped.items():
        rows.append(
            {
                "comuna": comuna,
                "property_type": property_type,
                "sample_count": len(values),
                "median_price_m2": _round(_safe_median(values)),
                "p25_price_m2": _round(_percentile(values, 25)),
                "p75_price_m2": _round(_percentile(values, 75)),
                "price_m2_iqr_pct": _round(_iqr_pct(values)),
            }
        )
    return sorted(rows, key=lambda row: (-(row["price_m2_iqr_pct"] or 0), -row["sample_count"]))


def _rm_coverage_rows(by_comuna: list[dict[str, Any]]) -> list[dict[str, Any]]:
    observed = {row["comuna"]: row for row in by_comuna}
    rows = []
    for comuna in sorted(RM_TARGET_COMUNAS | set(observed)):
        source = observed.get(comuna)
        rows.append(
            {
                "comuna": comuna,
                "in_rm_target_set": comuna in RM_TARGET_COMUNAS,
                "active_listings": source["active_listings"] if source else 0,
                "useful_listings": source["useful_listings"] if source else 0,
                "coverage_status": "covered" if source and source["useful_listings"] > 0 else "missing",
            }
        )
    return rows


def _beta_readiness_rows(
    comuna_property_type_rows: list[dict[str, Any]],
    active: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    near_duplicate_by_segment = _near_duplicate_rows_by_segment(active)
    rows = []
    for row in comuna_property_type_rows:
        reason = _beta_reason(row, near_duplicate_by_segment.get((row["comuna"], row["property_type"]), 0))
        rows.append({**row, **reason, "canonical_beta_status": dataset_beta_status_to_canonical(reason["beta_status"])})
    return sorted(rows, key=lambda row: (row["beta_status"], -row["useful_listings"], row["comuna"]))


def _property_type_viability_rows(
    comuna_property_type_rows: list[dict[str, Any]],
    active: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for property_type in sorted({row["property_type"] for row in active}):
        items = [row for row in active if row["property_type"] == property_type]
        useful = [row for row in items if _is_avm_useful(row)]
        segments = [row for row in comuna_property_type_rows if row["property_type"] == property_type]
        beta_ready = sum(1 for row in segments if _beta_reason(row, 0)["beta_status"] == DatasetBetaStatus.BETA_READY)
        status = (
            PropertyTypeCoverageStatus.INVIABLE
            if len(useful) < 20 or beta_ready == 0
            else PropertyTypeCoverageStatus.BETA_CANDIDATE
        )
        if len(useful) >= 500 and beta_ready >= 5:
            status = PropertyTypeCoverageStatus.BROAD_BETA_CANDIDATE
        rows.append(
            {
                "property_type": property_type,
                "active_listings": len(items),
                "useful_listings": len(useful),
                "observed_comunas": len({row["comuna"] for row in items}),
                "beta_ready_comuna_segments": beta_ready,
                "status": status,
                "reason": _property_type_reason(status, len(useful), beta_ready),
            }
        )
    return rows


def _minimum_dataset_estimate(comuna_property_type_rows: list[dict[str, Any]]) -> dict[str, Any]:
    deficits = []
    for row in comuna_property_type_rows:
        useful = row["useful_listings"]
        deficits.append(
            {
                "comuna": row["comuna"],
                "property_type": row["property_type"],
                "current_useful": useful,
                "beta_min_50_deficit": max(0, BETA_MIN_USEFUL - useful),
                "robust_min_150_deficit": max(0, ROBUST_MIN_USEFUL - useful),
            }
        )
    return {
        "heuristics": {
            "exploratory_segment_min": 20,
            "beta_segment_min": BETA_MIN_USEFUL,
            "robust_segment_min": ROBUST_MIN_USEFUL,
            "m2_bucket_min_per_segment": MIN_BUCKET_COUNT,
            "recommended_price_history_points": 2,
            "recommended_independent_sources": 2,
        },
        "largest_beta_deficits": sorted(deficits, key=lambda row: -row["beta_min_50_deficit"])[:30],
        "largest_robust_deficits": sorted(deficits, key=lambda row: -row["robust_min_150_deficit"])[:30],
    }


def _overfitting_risk(
    *,
    active: list[dict[str, Any]],
    duplicates: dict[str, Any],
    microzones: dict[str, Any],
    by_source: list[dict[str, Any]],
    beta: list[dict[str, Any]],
) -> str:
    source_pct = by_source[0]["pct"] if by_source else 0.0
    hide_rate = _pct(sum(1 for row in beta if row["beta_status"] == DatasetBetaStatus.HIDE_IN_BETA), len(beta)) or 0.0
    near_dup_pct = duplicates["near_duplicate_pct_active"] or 0.0
    microzone_pct = microzones["useful_microzone_pct"] or 0.0
    if source_pct >= 95 or hide_rate >= 45 or near_dup_pct >= 15 or microzone_pct < 20:
        return "high"
    if source_pct >= 80 or hide_rate >= 25 or near_dup_pct >= 8 or microzone_pct < 35:
        return "medium"
    return "low"


def _conclusion(
    beta: list[dict[str, Any]],
    property_type_viability: list[dict[str, Any]],
    active: list[dict[str, Any]],
) -> dict[str, Any]:
    ready = [row for row in beta if row["beta_status"] == DatasetBetaStatus.BETA_READY]
    caution = [row for row in beta if row["beta_status"] == DatasetBetaStatus.CAUTION]
    hidden = [row for row in beta if row["beta_status"] == DatasetBetaStatus.HIDE_IN_BETA]
    return {
        "where_avm_serves": [
            f"{row['comuna']} / {row['property_type']}"
            for row in sorted(ready, key=lambda item: -item["useful_listings"])[:15]
        ],
        "where_avm_is_still_misleading": [
            f"{row['comuna']} / {row['property_type']}: {row['reason']}"
            for row in sorted(hidden, key=lambda item: item["useful_listings"])[:20]
        ],
        "beta_caution_segments": [
            f"{row['comuna']} / {row['property_type']}: {row['reason']}"
            for row in sorted(caution, key=lambda item: -item["useful_listings"])[:20]
        ],
        "property_type_assessment": property_type_viability,
        "overall": _overall_conclusion(ready, hidden, active),
    }


def _chart_data(
    active: list[dict[str, Any]],
    comuna_property_type_rows: list[dict[str, Any]],
    dispersion: list[dict[str, Any]],
) -> dict[str, Any]:
    heatmap_property_type = comuna_property_type_rows
    heatmap_m2 = []
    bucket_group: dict[tuple[str, str], int] = Counter()
    for row in active:
        if _is_avm_useful(row):
            bucket_group[(row["comuna"], row["m2_bucket"])] += 1
    for (comuna, bucket), count in bucket_group.items():
        heatmap_m2.append({"comuna": comuna, "m2_bucket": bucket, "count": count})
    coords = [
        {
            "id": row["id"],
            "comuna": row["comuna"],
            "property_type": row["property_type"],
            "lat": row["lat"],
            "lon": row["lon"],
            "geocode_precision": row["geocode_precision"],
        }
        for row in active
        if row["lat"] is not None and row["lon"] is not None
    ]
    return {
        "heatmap_property_type": heatmap_property_type,
        "heatmap_m2_bucket": heatmap_m2,
        "dispersion": dispersion,
        "active_rows": _chart_active_rows(active),
        "coordinates": coords,
    }


def _write_csvs(report: dict[str, Any], csv_dir: Path, stamp: str) -> None:
    csv_sections = {
        "by_comuna": report["by_comuna"],
        "by_comuna_property_type": report["by_comuna_property_type"],
        "beta_readiness": report["beta_readiness"],
        "dispersion_by_comuna": report["dispersion_by_comuna"],
        "rm_coverage": report["rm_coverage"],
        "property_type_viability": report["property_type_viability"],
        "area_quality_by_property_type": report["area_quality"]["by_property_type"],
        "area_quality_worst_house_land_area": report["area_quality"]["worst_house_land_area_comunas"],
    }
    for name, rows in csv_sections.items():
        _write_csv(rows, csv_dir / f"{name}_{stamp}.csv")


def _write_charts(report: dict[str, Any], charts_dir: Path, stamp: str) -> None:
    if pd is None or px is None:
        (charts_dir / f"charts_unavailable_{stamp}.txt").write_text(
            "pandas/plotly not available in this environment.\n",
            encoding="utf-8",
        )
        return
    chart_data = report["chart_data"]
    _write_heatmap(
        chart_data["heatmap_property_type"],
        index="comuna",
        columns="property_type",
        values="useful_listings",
        title="AVM useful listings by comuna and property_type",
        path=charts_dir / f"heatmap_comuna_property_type_{stamp}.html",
    )
    _write_heatmap(
        chart_data["heatmap_m2_bucket"],
        index="comuna",
        columns="m2_bucket",
        values="count",
        title="AVM useful listings by comuna and m2 bucket",
        path=charts_dir / f"heatmap_comuna_m2_bucket_{stamp}.html",
    )
    active_df = pd.DataFrame(chart_data["active_rows"])
    if not active_df.empty:
        fig = px.histogram(
            active_df[active_df["price_m2"].notna()],
            x="price_m2",
            color="property_type",
            nbins=60,
            title="Price per m2 distribution by property_type",
        )
        fig.write_html(charts_dir / f"hist_price_m2_by_property_type_{stamp}.html", include_plotlyjs="cdn")

        fig = px.histogram(active_df, x="age_days", color="property_type", nbins=40, title="Listing age distribution")
        fig.write_html(charts_dir / f"hist_listing_age_{stamp}.html", include_plotlyjs="cdn")

        source_df = pd.DataFrame(report["by_source"])
        fig = px.bar(source_df, x="value", y="count", title="Source dependency")
        fig.write_html(charts_dir / f"bar_source_dependency_{stamp}.html", include_plotlyjs="cdn")

    dispersion_df = pd.DataFrame(chart_data["dispersion"])
    if not dispersion_df.empty:
        fig = px.bar(
            dispersion_df.head(40),
            x="comuna",
            y="price_m2_iqr_pct",
            color="property_type",
            title="Highest price/m2 dispersion by comuna/property_type",
        )
        fig.write_html(charts_dir / f"bar_dispersion_by_comuna_{stamp}.html", include_plotlyjs="cdn")

    coords_df = pd.DataFrame(chart_data["coordinates"])
    if not coords_df.empty:
        fig = px.scatter_mapbox(
            coords_df,
            lat="lat",
            lon="lon",
            color="property_type",
            hover_data=["id", "comuna", "geocode_precision"],
            zoom=9,
            height=650,
            title="Geographic density for listings with coordinates",
        )
        fig.update_layout(mapbox_style="open-street-map")
        fig.write_html(charts_dir / f"map_coordinate_density_{stamp}.html", include_plotlyjs="cdn")


def _write_heatmap(rows: list[dict[str, Any]], *, index: str, columns: str, values: str, title: str, path: Path) -> None:
    if not rows:
        return
    df = pd.DataFrame(rows)
    if df.empty:
        return
    pivot = df.pivot_table(index=index, columns=columns, values=values, aggfunc="sum", fill_value=0)
    pivot = pivot.loc[pivot.sum(axis=1).sort_values(ascending=False).index]
    fig = px.imshow(pivot, aspect="auto", text_auto=True, title=title)
    fig.write_html(path, include_plotlyjs="cdn")


def _markdown_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# AVM Dataset Coverage Audit",
        "",
        "## Executive Summary",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Active listings: {summary['active_listings']}",
        f"- AVM useful listings: {summary['avm_useful_listings']} ({summary['avm_useful_pct']}%)",
        f"- Observed comunas: {summary['observed_comunas']}",
        f"- RM target coverage: {summary['rm_target_coverage_pct']}%",
        f"- Usable coordinates: {summary['usable_coords_pct']}%",
        f"- Stale active listings: {summary['stale_active_listings']} ({summary['stale_active_pct']}%)",
        f"- Top source dependency: {summary['top_source']} ({summary['top_source_pct']}%)",
        f"- Useful microzone signals: {summary['useful_microzone_pct']}%",
        f"- Geographic microzone coverage: {summary['geographic_microzone_pct']}%",
        f"- Geographic microzones: {summary['geographic_microzone_count']}",
        f"- Geographic microzones with enough same-type listings: {summary['geographic_microzone_sufficient_count']}",
        f"- Usable price history: {summary['price_history_usable_pct']}%",
        f"- Beta-ready comuna/property_type segments: {summary['beta_ready_segments']}",
        f"- Hidden-in-beta segments: {summary['hide_in_beta_segments']}",
        f"- Overfitting risk: `{summary['overfitting_risk']}`",
        "",
        "## Honest Conclusion",
        "",
        report["conclusion"]["overall"],
        "",
        "### Where the AVM already serves",
        "",
        _bullet_list(report["conclusion"]["where_avm_serves"]),
        "",
        "### Where it would still be misleading",
        "",
        _bullet_list(report["conclusion"]["where_avm_is_still_misleading"]),
        "",
        "### Beta caution segments",
        "",
        _bullet_list(report["conclusion"]["beta_caution_segments"]),
        "",
        "## Property Types",
        "",
        _markdown_table(report["property_type_viability"]),
        "",
        "## Coverage By Comuna",
        "",
        _markdown_table(report["by_comuna"][:40]),
        "",
        "## Coverage By Comuna And Property Type",
        "",
        _markdown_table(report["by_comuna_property_type"][:60]),
        "",
        "## Area Quality",
        "",
        "### By Property Type",
        "",
        _markdown_table(report["area_quality"]["by_property_type"]),
        "",
        "### Worst House Land Area Coverage",
        "",
        _markdown_table(report["area_quality"]["worst_house_land_area_comunas"]),
        "",
        "## Comunas To Hide In Beta",
        "",
        _markdown_table([row for row in report["beta_readiness"] if row["beta_status"] == DatasetBetaStatus.HIDE_IN_BETA][:60]),
        "",
        "## Price/M2 Dispersion Hotspots",
        "",
        _markdown_table(report["dispersion_by_comuna"][:30]),
        "",
        "## Dataset Minimum Estimate",
        "",
        _markdown_table(report["minimum_dataset_estimate"]["largest_beta_deficits"][:30]),
        "",
        "## Source Dependency",
        "",
        _markdown_table(report["by_source"]),
        "",
        "## Price History",
        "",
        _markdown_table([report["price_history"]]),
        "",
        "## Microzone Concentration",
        "",
        _markdown_table(report["microzones"]["concentrated_microzones"][:30]),
        "",
        "## Geographic Microzones Read-Only",
        "",
        "These are coordinate-grid audit groups only. They are not used by valuation, scoring, or comparables yet.",
        "",
        "### Geographic Microzone Coverage By Comuna",
        "",
        _markdown_table(report["geographic_microzones"]["by_comuna"][:30]),
        "",
        "### Geographic Microzones With Enough Same-Type Listings",
        "",
        _markdown_table(report["geographic_microzones"]["sufficient_microzones"][:30]),
        "",
        "### Geographic Microzone Exclusion Reasons",
        "",
        _markdown_table(report["geographic_microzones"]["exclusion_reasons"][:30]),
    ]
    return "\n".join(lines) + "\n"


async def _load_dataset() -> tuple[list[dict[str, Any]], dict[int, int]]:
    async with get_session_factory()() as session:
        result = await session.execute(select(ListingORM))
        listings = [_orm_to_dict(row) for row in result.scalars().all()]
        history_result = await session.execute(
            select(PriceHistoryORM.listing_id, func.count(PriceHistoryORM.id)).group_by(PriceHistoryORM.listing_id)
        )
        price_history_counts = {int(listing_id): int(count) for listing_id, count in history_result.all()}
    return listings, price_history_counts


def _orm_to_dict(row: ListingORM) -> dict[str, Any]:
    return {
        "id": row.id,
        "source": row.source,
        "external_id": row.external_id,
        "fingerprint": row.fingerprint,
        "title": row.title,
        "url": row.url,
        "comuna": row.comuna,
        "property_type": row.property_type,
        "m2": row.m2,
        "built_area_m2": row.built_area_m2,
        "usable_area_m2": row.usable_area_m2,
        "land_area_m2": row.land_area_m2,
        "bedrooms": row.bedrooms,
        "bathrooms": row.bathrooms,
        "parking": row.parking,
        "lat": row.lat,
        "lon": row.lon,
        "geocode_precision": row.geocode_precision,
        "price_clp": row.price_clp,
        "status": row.status,
        "raw_metadata": row.raw_metadata,
        "scraped_at": row.scraped_at,
    }


def _signals_for_listing(row: dict[str, Any]) -> Any:
    class Value:
        pass

    value = Value()
    value.title = row.get("title")
    value.raw_metadata = row.get("raw_metadata") if isinstance(row.get("raw_metadata"), dict) else {}
    return signals_from_value(value)


def _microzone_tokens(signals: Any) -> list[str]:
    tokens = list(signals.landmark_tokens)
    if signals.nearby_metro:
        tokens.append(f"metro:{signals.nearby_metro}")
    if signals.nearby_avenue:
        tokens.append(f"avenue:{signals.nearby_avenue}")
    if signals.neighborhood_hint:
        tokens.append(f"neighborhood:{signals.neighborhood_hint}")
    if signals.intersection_hint:
        tokens.append(f"intersection:{signals.intersection_hint}")
    return sorted(set(tokens))


def _is_avm_useful(row: dict[str, Any]) -> bool:
    return (
        row["status"] == "active"
        and row["property_type"] in KNOWN_PROPERTY_TYPES
        and row["area_m2"] is not None
        and row["area_m2"] > 0
        and row["price_clp"] > 0
    )


def _built_area(row: dict[str, Any]) -> float | None:
    for key in ("built_area_m2", "usable_area_m2", "m2"):
        value = _float_or_none(row.get(key))
        if value is not None and value > 0:
            return value
    return None


def _has_positive(value: Any) -> bool:
    parsed = _float_or_none(value)
    return parsed is not None and parsed > 0


def _beta_reason(row: dict[str, Any], near_duplicate_rows: int) -> dict[str, str]:
    useful = row["useful_listings"]
    dispersion = row["price_m2_iqr_pct"]
    stale_pct = row["stale_pct"] or 0.0
    if useful < 20:
        return {"beta_status": DatasetBetaStatus.HIDE_IN_BETA, "reason": "less_than_20_useful_listings"}
    if stale_pct >= MAX_STALE_PCT:
        return {"beta_status": DatasetBetaStatus.HIDE_IN_BETA, "reason": "stale_inventory_too_high"}
    if dispersion is not None and dispersion >= MAX_HIDE_DISPERSION_PCT:
        return {"beta_status": DatasetBetaStatus.HIDE_IN_BETA, "reason": "extreme_price_m2_dispersion"}
    if useful >= BETA_MIN_USEFUL and row["m2_buckets_with_10plus"] >= 2 and (
        dispersion is None or dispersion <= MAX_BETA_DISPERSION_PCT
    ):
        if near_duplicate_rows >= max(8, useful * 0.15):
            return {"beta_status": DatasetBetaStatus.CAUTION, "reason": "near_duplicate_concentration"}
        return {"beta_status": DatasetBetaStatus.BETA_READY, "reason": "enough_useful_data_and_m2_diversity"}
    if useful >= BETA_MIN_USEFUL:
        return {"beta_status": DatasetBetaStatus.CAUTION, "reason": "enough_data_but_weak_bucket_diversity_or_dispersion"}
    return {"beta_status": DatasetBetaStatus.CAUTION, "reason": "between_20_and_49_useful_listings"}


def _property_type_reason(status: str, useful: int, beta_ready: int) -> str:
    if status == PropertyTypeCoverageStatus.INVIABLE:
        return f"only {useful} useful listings and {beta_ready} beta-ready comuna segments"
    if status == PropertyTypeCoverageStatus.BROAD_BETA_CANDIDATE:
        return f"{useful} useful listings across {beta_ready} beta-ready comuna segments"
    return f"{useful} useful listings, but beta should be limited to {beta_ready} comuna segments"


def _near_duplicate_rows_by_segment(active: list[dict[str, Any]]) -> dict[tuple[str, str], int]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in active:
        key = _near_duplicate_key(row)
        if key:
            grouped[key].append(row)
    counts: Counter[tuple[str, str]] = Counter()
    for items in grouped.values():
        if len(items) <= 1:
            continue
        for row in items[1:]:
            counts[(row["comuna"], row["property_type"])] += 1
    return dict(counts)


def _near_duplicate_key(row: dict[str, Any]) -> str | None:
    title = _normalize_title(row.get("title"))
    if not title or row.get("price_clp", 0) <= 0:
        return None
    area = row.get("area_m2")
    area_bucket = str(round(area / 5) * 5) if area else "unknown"
    price_bucket = str(round(float(row["price_clp"]) / 500_000) * 500_000)
    return "|".join([row["source"], row["comuna"], row["property_type"], title[:80], area_bucket, price_bucket])


def _top_tokens_by_comuna(by_comuna: dict[str, Counter[str]]) -> list[dict[str, Any]]:
    rows = []
    for comuna, counter in by_comuna.items():
        for token, count in counter.most_common(5):
            rows.append({"comuna": comuna, "token": token, "count": count})
    return sorted(rows, key=lambda row: (-row["count"], row["comuna"], row["token"]))[:80]


def _chart_active_rows(active: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = ["id", "comuna", "property_type", "m2_bucket", "price_m2", "age_days", "source", "geocode_precision"]
    return [{key: row.get(key) for key in keys} for row in active]


def _age_bucket(age_days: int | None) -> str:
    if age_days is None:
        return "unknown"
    if age_days <= 7:
        return "0-7"
    if age_days <= 30:
        return "8-30"
    if age_days <= 60:
        return "31-60"
    if age_days <= 120:
        return "61-120"
    return "120+"


def _normalize_title(value: Any) -> str:
    text = re.sub(r"[^a-z0-9\s]", " ", str(value or "").lower())
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _safe_median(values: list[float]) -> float | None:
    clean = [float(value) for value in values if value is not None and float(value) > 0]
    return float(median(clean)) if clean else None


def _iqr_pct(values: list[float]) -> float | None:
    clean = [float(value) for value in values if value is not None and float(value) > 0]
    if len(clean) < 4:
        return None
    p25 = _percentile(clean, 25)
    p75 = _percentile(clean, 75)
    med = _safe_median(clean)
    if med is None or med <= 0:
        return None
    return (p75 - p25) / med * 100


def _percentile(values: list[float], percentile: int) -> float | None:
    clean = sorted(float(value) for value in values if value is not None and float(value) > 0)
    if not clean:
        return None
    if len(clean) == 1:
        return clean[0]
    position = (len(clean) - 1) * percentile / 100
    lower = int(position)
    upper = min(lower + 1, len(clean) - 1)
    weight = position - lower
    return clean[lower] * (1 - weight) + clean[upper] * weight


def _pct(part: int | float, total: int | float) -> float | None:
    if total == 0:
        return None
    return round(float(part) / float(total) * 100, 2)


def _round(value: float | None, digits: int = 2) -> float | None:
    return round(float(value), digits) if value is not None else None


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _norm_text(value: Any, *, default: str) -> str:
    text = str(value or "").strip().lower()
    return text or default


def _as_aware_datetime(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(_json_safe(row) for row in rows)


def _markdown_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "_No data._"
    columns = list(rows[0].keys())
    lines = ["| " + " | ".join(columns) + " |", "|" + "|".join("---" for _ in columns) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(_json_safe(row.get(column))) for column in columns) + " |")
    return "\n".join(lines)


def _bullet_list(items: list[str]) -> str:
    if not items:
        return "_No segments._"
    return "\n".join(f"- {item}" for item in items)


def _overall_conclusion(ready: list[dict[str, Any]], hidden: list[dict[str, Any]], active: list[dict[str, Any]]) -> str:
    if not active:
        return "No hay dataset activo; el AVM no deberia exponerse."
    if not ready:
        return (
            "El dataset todavia no tiene segmentos robustos para beta publica. "
            "Puede usarse solo como laboratorio interno y con baja confianza."
        )
    if len(hidden) > len(ready):
        return (
            "El AVM sirve en segmentos especificos, pero seria enganoso como producto amplio: "
            "hay mas segmentos que deberian ocultarse que segmentos listos para beta."
        )
    return (
        "El AVM tiene base para una beta acotada por comuna/property_type. "
        "No deberia presentarse como cobertura general RM todavia."
    )


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items() if key != "chart_data"}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple | set):
        return [_json_safe(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate AVM dataset coverage/diversity audit.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for audit outputs.")
    parser.add_argument("--stale-days", type=int, default=45, help="Age threshold for stale active listings.")
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    listings, price_history_counts = await _load_dataset()
    report = build_audit(listings, price_history_counts, stale_days=args.stale_days)
    artifacts = write_audit(report, output_dir=Path(args.output_dir))
    print_console_report(report, artifacts)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
