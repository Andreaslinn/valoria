"""Read-only enrichment opportunity audit for Valoria listing data."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from core.entities.listing import Listing
from core.normalization.property_type import normalize_property_type
from domain.geocoding.microzones import extract_microzone_signals, signals_from_value
from domain.geocoding.quality import has_valid_coordinates, normalized_precision_for
from domain.ingestion.data_cleaning import extract_area_fields_with_provenance
from domain.valuation.canonical_price import valuation_price_basis
from domain.valuation.price_surface import microzone_tokens_for
from domain.valuation.product_classification import classify_product

USEFUL_GEOCODE_PRECISIONS = frozenset({"address", "street"})
LAND_METADATA_KEYS = (
    "land_area_m2",
    "terrain_m2",
    "terreno_m2",
    "surface_land",
    "superficie_terreno",
    "sup_terreno",
)
ADDRESS_METADATA_KEYS = ("address_label", "street_hint", "address", "direccion", "location_address")
PUBLICATION_DATE_KEYS = ("published_at", "publication_date", "fecha_publicacion", "created_at_source")
LAND_TERMS_RE = re.compile(r"\b(terreno|superficie\s+(?:de\s+)?terreno|sup\.?\s*terreno|sitio|lote)\b", re.I)
THOUSANDS_AREA_RE = re.compile(r"\b\d{1,3}(?:[.,]\d{3})+\s*(?:m2|m\s*2|mts2|metros)?\b", re.I)
TITLE_ADDRESS_RE = re.compile(
    r"\b(?:calle|avenida|av\.?|pasaje|camino)\s+[a-z0-9áéíóúñ.\- ]{3,45}(?:\s+\d{2,6})?\b",
    re.I,
)


@dataclass(frozen=True)
class Opportunity:
    listing_id: int | None
    source: str
    comuna: str
    property_type: str
    category: str
    confidence: str
    evidence: str
    suggested_value: str | float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_enrichment_audit(
    listings: Sequence[Listing],
    *,
    uf_to_clp: Decimal,
    benchmark_cases: int,
    examples: int = 50,
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    ordered = sorted(listings, key=_listing_sort_key)
    active = [listing for listing in ordered if listing.is_active]
    houses = [listing for listing in active if normalize_property_type(listing) == "house"]
    apartments = [listing for listing in active if normalize_property_type(listing) == "apartment"]

    land_rows = [classify_land_area_opportunity(item).to_dict() for item in houses]
    geocode_rows = [classify_geocode_opportunity(item).to_dict() for item in active]
    microzone_rows = [classify_microzone_opportunity(item).to_dict() for item in active]
    canonical_rows = [classify_canonical_price_opportunity(item, uf_to_clp=uf_to_clp).to_dict() for item in apartments]
    duplicate_rows = detect_duplicate_candidates(active)

    product_rows = [_product_row(item) for item in active]
    report = {
        "dataset": {
            "signature": dataset_signature(ordered),
            "total_listings": len(ordered),
            "active_listings": len(active),
            "benchmark_cases": benchmark_cases,
            "uf_to_clp": float(uf_to_clp),
        },
        "coverage": coverage_report(ordered, active, uf_to_clp=uf_to_clp),
        "land_area": {
            **opportunity_summary(land_rows, total=len(houses), examples=examples),
            "recovery_tiers": _land_recovery_tiers(land_rows, total=len(houses)),
        },
        "geocoding": {
            **opportunity_summary(geocode_rows, total=len(active), examples=examples),
            "precision_counts": dict(sorted(Counter(normalized_precision_for(item) for item in active).items())),
            "coordinates_valid": _count(active, has_valid_coordinates),
        },
        "microzone": {
            **opportunity_summary(microzone_rows, total=len(active), examples=examples),
            "signals": microzone_signal_summary(active),
            "persisted_current": _coverage(active, lambda item: bool(_persisted_microzone_tokens(item.raw_metadata or {}))),
            "operational_or_derived": _coverage(active, lambda item: bool(microzone_tokens_for(item))),
        },
        "canonical_price_apartments": {
            **opportunity_summary(canonical_rows, total=len(apartments), examples=examples),
            "currency_counts": dict(sorted(Counter(_currency(item) for item in apartments).items())),
            "price_uf_source_counts": dict(sorted(Counter(str(item.price_uf_source or "missing") for item in apartments).items())),
            "recovery_tiers": _canonical_recovery_tiers(canonical_rows, total=len(apartments)),
        },
        "product_classification": product_classification_summary(product_rows, examples=examples),
        "duplicates_and_leakage": duplicate_summary(duplicate_rows, active_count=len(active), examples=examples),
        "dates": date_coverage(active),
        "source_audit": source_audit_findings(),
        "enrichment_plan": enrichment_plan(
            houses=houses,
            apartments=apartments,
            land_rows=land_rows,
            geocode_rows=geocode_rows,
            microzone_rows=microzone_rows,
            canonical_rows=canonical_rows,
        ),
        "implementation_guardrails": {
            "read_only": True,
            "database_writes": 0,
            "external_requests": 0,
            "apply_mode": False,
            "uf_37000_operational": False,
        },
    }
    csv_rows = {
        "field_coverage": coverage_csv_rows(report["coverage"]),
        "land_area_opportunities": land_rows,
        "geocoding_opportunities": geocode_rows,
        "microzone_opportunities": microzone_rows,
        "canonical_price_opportunities": canonical_rows,
        "duplicate_candidates": duplicate_rows,
    }
    return report, csv_rows


def coverage_report(all_listings: Sequence[Listing], active: Sequence[Listing], *, uf_to_clp: Decimal) -> dict[str, Any]:
    by_type = {
        "house": [item for item in active if normalize_property_type(item) == "house"],
        "apartment": [item for item in active if normalize_property_type(item) == "apartment"],
        "unknown": [item for item in active if normalize_property_type(item) not in {"house", "apartment"}],
    }
    return {
        "global": {
            "total": len(all_listings),
            "active": len(active),
            "property_type": dict(sorted(Counter(normalize_property_type(item) for item in active).items())),
            "source": dict(sorted(Counter(str(item.source or "unknown") for item in active).items())),
            "comuna": dict(sorted(Counter(str(item.comuna or "unknown") for item in active).items())),
            "currency": dict(sorted(Counter(_currency(item) for item in active).items())),
            "geocode_precision": dict(sorted(Counter(normalized_precision_for(item) for item in active).items())),
            "canonical_price": _coverage(active, lambda item: _canonical_usable(item, uf_to_clp)),
            "microzone": _coverage(active, lambda item: bool(microzone_tokens_for(item))),
            "land_area": _coverage(active, _has_land),
        },
        "house": _segment_coverage(by_type["house"], uf_to_clp=uf_to_clp, house=True),
        "apartment": _segment_coverage(by_type["apartment"], uf_to_clp=uf_to_clp, house=False),
        "by_comuna": {
            comuna: {
                "active": len(rows),
                "houses": sum(normalize_property_type(item) == "house" for item in rows),
                "apartments": sum(normalize_property_type(item) == "apartment" for item in rows),
                "useful_geocode_pct": _pct(_count(rows, _useful_geocode), len(rows)),
                "microzone_pct": _pct(_count(rows, lambda item: bool(microzone_tokens_for(item))), len(rows)),
                "canonical_price_pct": _pct(_count(rows, lambda item: _canonical_usable(item, uf_to_clp)), len(rows)),
            }
            for comuna, rows in _group_by(active, lambda item: str(item.comuna or "unknown")).items()
        },
    }


def classify_land_area_opportunity(listing: Listing) -> Opportunity:
    base = _opportunity_base(listing)
    if _has_land(listing):
        return Opportunity(**base, category="present", confidence="observed", evidence="listing.land_area_m2", suggested_value=listing.land_area_m2)
    metadata = listing.raw_metadata if isinstance(listing.raw_metadata, dict) else {}
    for key in LAND_METADATA_KEYS:
        value = _positive_number(metadata.get(key))
        if value is not None:
            return Opportunity(**base, category="metadata_structured_unmapped", confidence="high", evidence=key, suggested_value=value)

    raw = _raw_listing_payload(listing)
    parsed = extract_area_fields_with_provenance(raw, title=listing.title)
    suggested = parsed.areas.get("land_area_m2")
    text = _listing_text(listing)
    if suggested is not None:
        category = "text_recoverable_thousands_normalized" if THOUSANDS_AREA_RE.search(text) else "text_recoverable"
        return Opportunity(
            **base,
            category=category,
            confidence="high" if parsed.sources.get("land_area_m2", "").startswith("text.land_area") else "medium",
            evidence=parsed.sources.get("land_area_m2", "area_parser"),
            suggested_value=suggested,
        )
    warnings = metadata.get("area_parse_warnings")
    if warnings or _inconsistent_areas(listing):
        return Opportunity(**base, category="inconsistent_area_fields", confidence="review", evidence=str(warnings or "area_ratio"))
    if LAND_TERMS_RE.search(text):
        return Opportunity(**base, category="land_mentioned_without_value", confidence="low", evidence="text_land_term")
    if listing.source == "yapo" and listing.url and not _detail_text_available(metadata):
        return Opportunity(**base, category="refresh_candidate", confidence="medium", evidence="yapo_url_without_detail_text")
    if _detail_text_available(metadata):
        return Opportunity(**base, category="not_in_available_publication_text", confidence="low", evidence="detail_text_without_land_signal")
    return Opportunity(**base, category="not_recoverable_current_data", confidence="none", evidence="no_land_signal")


def classify_geocode_opportunity(listing: Listing) -> Opportunity:
    base = _opportunity_base(listing)
    precision = normalized_precision_for(listing)
    metadata = listing.raw_metadata if isinstance(listing.raw_metadata, dict) else {}
    if precision in USEFUL_GEOCODE_PRECISIONS:
        return Opportunity(**base, category="already_reliable", confidence="observed", evidence=precision)
    for key in ADDRESS_METADATA_KEYS:
        if _meaningful_text(metadata.get(key)):
            return Opportunity(**base, category="recoverable_metadata_address", confidence="high", evidence=key)
    if TITLE_ADDRESS_RE.search(_normalize_text(listing.title)):
        confidence = "high" if re.search(r"\b\d{2,6}\b", listing.title or "") else "medium"
        return Opportunity(**base, category="recoverable_title_street", confidence=confidence, evidence="title")
    signals = signals_from_value(listing)
    if signals.confidence >= 0.55:
        return Opportunity(**base, category="recoverable_geo_signal", confidence="medium", evidence=signals.reason)
    if has_valid_coordinates(listing):
        return Opportunity(**base, category="coordinates_low_precision", confidence="review", evidence=precision)
    if listing.comuna:
        return Opportunity(**base, category="commune_only", confidence="low", evidence="comuna")
    return Opportunity(**base, category="not_recoverable", confidence="none", evidence="no_location_signal")


def classify_microzone_opportunity(listing: Listing) -> Opportunity:
    base = _opportunity_base(listing)
    metadata = listing.raw_metadata if isinstance(listing.raw_metadata, dict) else {}
    current = _persisted_microzone_tokens(metadata)
    if current:
        return Opportunity(**base, category="current", confidence="high", evidence=",".join(current[:4]))
    title_signal = extract_microzone_signals(title=listing.title, raw_metadata={})
    if title_signal.confidence >= 0.55:
        return Opportunity(**base, category="potential_from_title", confidence="medium", evidence=title_signal.reason)
    description = metadata.get("description") or metadata.get("detail_text")
    description_signal = extract_microzone_signals(title=None, raw_metadata={"description": description})
    if description_signal.confidence >= 0.55:
        return Opportunity(**base, category="potential_from_description", confidence="medium", evidence=description_signal.reason)
    structured = {key: metadata.get(key) for key in ("address_label", "street_hint", "location_text", "location", "neighborhood")}
    metadata_signal = extract_microzone_signals(title=None, raw_metadata=structured)
    if metadata_signal.confidence >= 0.55:
        return Opportunity(**base, category="potential_from_metadata", confidence="high", evidence=metadata_signal.reason)
    return Opportunity(**base, category="no_current_signal", confidence="none", evidence="no_microzone_signal")


def classify_canonical_price_opportunity(listing: Listing, *, uf_to_clp: Decimal) -> Opportunity:
    base = _opportunity_base(listing)
    basis = valuation_price_basis(listing, uf_to_clp)
    if basis.is_usable_for_valuation:
        category = "usable_native_uf" if basis.basis_used == "canonical_uf" else "usable_clp_converted"
        return Opportunity(**base, category=category, confidence="high", evidence=basis.quality, suggested_value=float(basis.amount_uf or 0))
    reason = str(basis.exclusion_reason or basis.quality or "unknown")
    category = {
        "legacy_uf_missing_price_uf": "legacy_unrecoverable",
        "estimated_uf_not_strong": "estimated_low_confidence",
        "low_confidence_uf_not_strong": "estimated_low_confidence",
        "uf_fallback_not_canonical": "artifact_or_fallback",
        "unknown_currency": "missing_or_unknown_currency",
        "missing_clp_price": "price_missing",
    }.get(reason, reason)
    if category == "legacy_unrecoverable" and listing.source == "yapo" and listing.url:
        category = "legacy_unrecoverable_refresh_candidate"
    return Opportunity(**base, category=category, confidence="none", evidence=reason)


def detect_duplicate_candidates(listings: Sequence[Listing]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for kind, key_fn in (
        ("exact_url", lambda item: _normalized_url(item.url)),
        ("exact_source_external_id", lambda item: f"{item.source}|{item.external_id}" if item.external_id else None),
        ("exact_fingerprint", lambda item: item.fingerprint or None),
    ):
        for key, group in _group_by_nonempty(listings, key_fn).items():
            if len(group) > 1:
                rows.append(_duplicate_row(kind, key, group, leakage_risk="high"))

    buckets = _group_by_nonempty(listings, _near_duplicate_bucket)
    seen_pairs: set[tuple[int | None, int | None]] = set()
    for key, group in buckets.items():
        if len(group) < 2:
            continue
        matches: list[Listing] = []
        for idx, left in enumerate(group):
            for right in group[idx + 1 :]:
                pair = tuple(sorted((left.id, right.id), key=lambda value: -1 if value is None else value))
                if pair in seen_pairs or not _near_duplicate_match(left, right):
                    continue
                seen_pairs.add(pair)
                matches.extend((left, right))
        unique = {item.id if item.id is not None else id(item): item for item in matches}
        if len(unique) > 1:
            rows.append(_duplicate_row("near_duplicate", key, list(unique.values()), leakage_risk="medium_high"))
    return sorted(rows, key=lambda row: (row["kind"], row["group_key"]))


def opportunity_summary(rows: Sequence[dict[str, Any]], *, total: int, examples: int) -> dict[str, Any]:
    counts = Counter(str(row["category"]) for row in rows)
    recoverable = sum(
        count
        for category, count in counts.items()
        if category.startswith(("metadata_", "text_recoverable", "refresh_candidate", "recoverable_", "potential_", "legacy_unrecoverable_refresh_candidate"))
    )
    return {
        "total": total,
        "category_counts": dict(sorted(counts.items())),
        "recoverable_or_candidate_count": recoverable,
        "recoverable_or_candidate_pct": _pct(recoverable, total),
        "examples": list(rows[: max(0, examples)]),
    }


def microzone_signal_summary(listings: Sequence[Listing]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    for listing in listings:
        signals = signals_from_value(listing)
        if signals.nearby_metro:
            counts["metro"] += 1
        if signals.nearby_avenue:
            counts["avenue"] += 1
        if signals.neighborhood_hint:
            counts["neighborhood"] += 1
        if signals.intersection_hint:
            counts["intersection"] += 1
        if signals.landmark_tokens:
            counts["landmark"] += 1
    return dict(sorted(counts.items()))


def product_classification_summary(rows: Sequence[dict[str, Any]], *, examples: int) -> dict[str, Any]:
    false_positive_risks: Counter[str] = Counter()
    for row in rows:
        terms = set(row.get("terms") or [])
        if row["property_type"] == "apartment" and row["product_class"] == "commercial_use" and "bodega" in terms:
            false_positive_risks["apartment_bodega_storage_ambiguity"] += 1
        if row["product_class"] == "land_or_site" and row["strength"] == "weak":
            false_positive_risks["weak_land_context"] += 1
        if row["product_class"] == "investment_or_income" and row["strength"] == "weak":
            false_positive_risks["weak_investment_language"] += 1
    return {
        "class_counts": dict(sorted(Counter(str(row["product_class"]) for row in rows).items())),
        "strength_counts": dict(sorted(Counter(str(row["strength"]) for row in rows).items())),
        "unknown_count": sum(row["product_class"] == "unknown" for row in rows),
        "strong_special_count": sum(row["strength"] == "strong" and row["product_class"] != "standard_residential" for row in rows),
        "potential_false_positive_counts": dict(sorted(false_positive_risks.items())),
        "examples": list(rows[: max(0, examples)]),
    }


def duplicate_summary(rows: Sequence[dict[str, Any]], *, active_count: int, examples: int) -> dict[str, Any]:
    affected_ids = {listing_id for row in rows for listing_id in row["listing_ids"]}
    near = [row for row in rows if row["kind"] == "near_duplicate"]
    return {
        "active_listings": active_count,
        "group_counts": dict(sorted(Counter(row["kind"] for row in rows).items())),
        "affected_listings": len(affected_ids),
        "affected_pct": _pct(len(affected_ids), active_count),
        "near_duplicate_groups": len(near),
        "benchmark_leakage_risk": "medium" if near else "low",
        "examples": list(rows[: max(0, examples)]),
    }


def date_coverage(listings: Sequence[Listing]) -> dict[str, Any]:
    return {
        "scraped_at": _coverage(listings, lambda item: isinstance(item.scraped_at, datetime)),
        "last_seen_at": _coverage(listings, lambda item: isinstance(item.last_seen_at, datetime)),
        "publication_date_metadata": _coverage(
            listings,
            lambda item: any(_meaningful_text((item.raw_metadata or {}).get(key)) for key in PUBLICATION_DATE_KEYS),
        ),
        "temporal_evaluation_note": "scraped_at is an observation timestamp, not necessarily the original publication date",
    }


def enrichment_plan(
    *,
    houses: Sequence[Listing],
    apartments: Sequence[Listing],
    land_rows: Sequence[dict[str, Any]],
    geocode_rows: Sequence[dict[str, Any]],
    microzone_rows: Sequence[dict[str, Any]],
    canonical_rows: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    def count(rows: Sequence[dict[str, Any]], prefixes: tuple[str, ...]) -> int:
        return sum(str(row["category"]).startswith(prefixes) for row in rows)

    current_land = sum(_has_land(item) for item in houses)
    land_high = count(land_rows, ("metadata_structured", "text_recoverable"))
    current_geo = sum(_useful_geocode(item) for item in [*houses, *apartments])
    geo_recoverable = count(geocode_rows, ("recoverable_metadata", "recoverable_title", "recoverable_geo"))
    current_micro = sum(bool(microzone_tokens_for(item)) for item in [*houses, *apartments])
    micro_recoverable = count(microzone_rows, ("potential_",))
    current_canonical = sum(row["category"].startswith("usable_") for row in canonical_rows)
    canonical_refresh = count(canonical_rows, ("legacy_unrecoverable_refresh_candidate",))
    canonical_needed_for_60 = min(canonical_refresh, max(0, math.ceil(len(apartments) * 0.60) - current_canonical))
    quick_wins = [
        _quick_win("land_area_m2", current_land, len(houses), land_high, "low", "medium", False, True, "parser/backfill dry-run tests and area conflict tests"),
        _quick_win("geocode_precision", current_geo, len(houses) + len(apartments), geo_recoverable, "medium", "medium", False, True, "cache-only/no-external classification and comuna guardrails"),
        _quick_win("microzone", current_micro, len(houses) + len(apartments), micro_recoverable, "medium", "low", False, True, "false-positive corpus for title/description/metadata"),
        _quick_win("canonical_price_apartment", current_canonical, len(apartments), canonical_needed_for_60, "high", "medium", False, True, "price provenance, refresh sampling and artifact fixtures"),
        _quick_win("duplicate_diagnostics", 0, len(houses) + len(apartments), 0, "low", "low", False, False, "deterministic exact/near duplicate tests"),
    ]
    return {
        "quick_wins": quick_wins,
        "phases": [
            {"phase": "D1_report_only", "actions": ["land parser opportunity report", "canonical price provenance report", "duplicate candidate report"], "apply": False},
            {"phase": "D2_cache_only", "actions": ["geocoding cache-only validation", "microzone extraction corpus validation", "refresh candidate sampling"], "apply": False},
            {"phase": "D3_limited_backfill_candidate", "actions": ["review high-confidence land and canonical price candidates", "define rollback and acceptance thresholds"], "apply": False},
            {"phase": "D4_future_controlled_apply", "actions": ["separate approved implementation after benchmark gate"], "apply": "not_in_phase5a"},
        ],
        "future_commands": [
            "python scripts/audit_data_enrichment_opportunities.py --output-dir reports/data_quality/phase5a --no-external-requests --examples 50",
            "python scripts/geocode_listings.py --dry-run --no-external --limit 100 --examples 25",
            "python scripts/refresh_scraper.py --dry-run --limit 100",
            "python scripts/preview_property_type_backfill.py --changed-only --summary-only",
        ],
        "coverage_targets": {
            "houses_land_area_m2": [25, 40, 70],
            "houses_microzone": [35, 50],
            "houses_useful_geocode": [60, 70],
            "apartments_canonical_price": [60],
            "apartments_microzone": [35, 50],
            "apartments_useful_geocode": [60, 70],
        },
        "expected_engine_impact": {
            "comparables_legacy": "better candidate geography and house land completeness; no guaranteed MAPE change",
            "comparables_canonical": "higher canonical/product/geographic coverage and fewer insufficient-data outcomes",
            "comparables_canonical_outliers": "same robust logic with denser, cleaner candidate pools",
            "hedonic_house_minimal": "larger usable sample and missingness reduction",
            "ml_lab": "better feature coverage and lower duplicate leakage risk",
            "house_land_building_future": "land_area and local geography are hard prerequisites",
            "consensus_future": "more comparable coverage and better segment calibration inputs",
        },
    }


def source_audit_findings() -> dict[str, Any]:
    return {
        "yapo_card_parser": "card data is structurally sparse; detail parser is the main source for land area, description and native UF",
        "yapo_detail_parser": "supports structured built/usable/total area labels, land text patterns and thousands separators",
        "portal_parser": "card parser exposes basic attributes but no equivalent detail enrichment path in the audited module",
        "refresh_scraper": "--dry-run selects and reports candidates without fetching URLs; non-dry-run performs external requests and writes, so it was not executed",
        "geocoding": "existing CLI supports --dry-run --no-external; title-inferred apply requires an explicit opt-in",
        "microzones": "mappers enrich microzone signals in memory on read; persisted metadata and operational derived coverage must be distinguished",
        "canonical_price": "native strong UF and CLP converted with a real inferred UF are usable; weak, fallback and legacy-unrecoverable UF are excluded",
        "deduplication": "fingerprint is source-agnostic for complete listings and excludes price; ORM also enforces unique fingerprint and source/external_id",
        "dates": "scraped_at and last_seen_at exist, but original publication date is absent in current metadata",
    }


def _land_recovery_tiers(rows: Sequence[dict[str, Any]], *, total: int) -> dict[str, Any]:
    counts = Counter(str(row["category"]) for row in rows)
    current = counts["present"]
    direct = counts["metadata_structured_unmapped"] + counts["text_recoverable"] + counts["text_recoverable_thousands_normalized"]
    refresh = counts["refresh_candidate"]
    return {
        "current_count": current,
        "current_pct": _pct(current, total),
        "direct_high_confidence_count": direct,
        "direct_high_confidence_potential_pct": _pct(current + direct, total),
        "refresh_candidate_count": refresh,
        "refresh_theoretical_ceiling_pct": _pct(current + direct + refresh, total),
        "warning": "refresh candidates are not guaranteed recoveries; sample yield must be measured before any apply",
    }


def _canonical_recovery_tiers(rows: Sequence[dict[str, Any]], *, total: int) -> dict[str, Any]:
    counts = Counter(str(row["category"]) for row in rows)
    current = counts["usable_native_uf"] + counts["usable_clp_converted"]
    refresh = counts["legacy_unrecoverable_refresh_candidate"]
    needed_for_60 = max(0, math.ceil(total * 0.60) - current)
    return {
        "current_count": current,
        "current_pct": _pct(current, total),
        "refresh_candidate_count": refresh,
        "refresh_theoretical_ceiling_pct": _pct(current + refresh, total),
        "recoveries_needed_for_60_pct": needed_for_60,
        "required_refresh_yield_pct": round(100 * needed_for_60 / refresh, 2) if refresh else None,
        "warning": "legacy UF recovery requires fresh source evidence; old CLP snapshots must not be reverse-engineered with UF 37000",
    }


def write_audit_outputs(output_dir: Path, report: dict[str, Any], csv_rows: dict[str, list[dict[str, Any]]]) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "data_enrichment_audit_latest.json"
    md_path = output_dir / "data_enrichment_audit_latest.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(markdown_report(report), encoding="utf-8")
    paths = {"json": str(json_path), "markdown": str(md_path)}
    for name, rows in csv_rows.items():
        path = output_dir / f"{name}.csv"
        _write_csv(path, rows)
        paths[name] = str(path)
    return paths


def markdown_report(report: dict[str, Any]) -> str:
    dataset = report["dataset"]
    coverage = report["coverage"]
    phase4a = report.get("phase4a_closure", {})
    preflight = report.get("preflight", {})
    lines = [
        "# Phase 5A Data Enrichment Audit",
        "",
        "## Phase 4A Closure",
        "",
        f"Commits: `{', '.join(phase4a.get('commits', []))}`",
        f"Tests: `{', '.join(phase4a.get('tests', []))}`",
        f"Clean before Phase 5A: `{phase4a.get('working_tree_clean_before_phase5a')}`",
        "",
        "## Phase 5A Preflight",
        "",
        f"Branch: `{preflight.get('branch')}`",
        f"HEAD: `{preflight.get('head')}`",
        f"Database mode: `{preflight.get('database_mode')}`",
        f"External requests: `{preflight.get('external_requests')}`",
        "",
        f"Dataset signature: `{dataset['signature']}`",
        f"Total listings: `{dataset['total_listings']}`",
        f"Active listings: `{dataset['active_listings']}`",
        f"Benchmark cases: `{dataset['benchmark_cases']}`",
        "",
        "## Coverage",
        "",
        "| Segment | Total | Built | Land | Canonical price | Useful geocode | Microzone |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for segment in ("house", "apartment"):
        row = coverage[segment]
        lines.append(
            f"| `{segment}` | {row['total']} | {row['built_area_m2']['valid_pct']} | "
            f"{row['land_area_m2']['valid_pct']} | {row['canonical_price']['valid_pct']} | "
            f"{row['useful_geocode']['valid_pct']} | {row['microzone']['valid_pct']} |"
        )
    for section, title in (
        ("land_area", "Land Area"),
        ("geocoding", "Geocoding"),
        ("microzone", "Microzone"),
        ("canonical_price_apartments", "Canonical Price Apartments"),
    ):
        payload = report[section]
        lines.extend(["", f"## {title}", "", "| Category | Count |", "| --- | ---: |"])
        for category, count in payload["category_counts"].items():
            lines.append(f"| `{category}` | {count} |")
        lines.append(f"\nRecoverable or candidate: `{payload['recoverable_or_candidate_count']}` ({payload['recoverable_or_candidate_pct']}%).")
        if "recovery_tiers" in payload:
            lines.extend(["", "Recovery tiers:", ""])
            for key, value in payload["recovery_tiers"].items():
                lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Source Audit", ""])
    for key, value in report["source_audit"].items():
        lines.append(f"- `{key}`: {value}")
    product = report["product_classification"]
    lines.extend(["", "## Product Classification", "", "| Class | Count |", "| --- | ---: |"])
    for category, count in product["class_counts"].items():
        lines.append(f"| `{category}` | {count} |")
    lines.append(f"\nUnknown: `{product['unknown_count']}`. Strong special: `{product['strong_special_count']}`.")
    if product["potential_false_positive_counts"]:
        lines.append(f"Potential false-positive risks: `{product['potential_false_positive_counts']}`.")
    duplicates = report["duplicates_and_leakage"]
    lines.extend([
        "",
        "## Duplicates And Leakage",
        "",
        f"Affected listings: `{duplicates['affected_listings']}` ({duplicates['affected_pct']}%).",
        f"Near duplicate groups: `{duplicates['near_duplicate_groups']}`.",
        f"Benchmark leakage risk: `{duplicates['benchmark_leakage_risk']}`.",
        "",
        "## Quick Wins",
        "",
        "| Field | Current % | Potential % | Risk | Difficulty |",
        "| --- | ---: | ---: | --- | --- |",
    ])
    for item in report["enrichment_plan"]["quick_wins"]:
        lines.append(f"| `{item['field']}` | {item['current_pct']} | {item['potential_pct']} | {item['risk']} | {item['difficulty']} |")
    lines.extend(["", "## Enrichment Phases", ""])
    for phase in report["enrichment_plan"]["phases"]:
        lines.append(f"- `{phase['phase']}`: {', '.join(phase['actions'])}; apply=`{phase['apply']}`")
    lines.extend(["", "## Future Dry-run Commands", ""])
    for command in report["enrichment_plan"]["future_commands"]:
        lines.append(f"- `{command}`")
    lines.extend(["", "## Expected Engine Impact", ""])
    for engine, impact in report["enrichment_plan"]["expected_engine_impact"].items():
        lines.append(f"- `{engine}`: {impact}")
    lines.extend(["", "## Date Coverage", ""])
    for key, value in report["dates"].items():
        lines.append(f"- `{key}`: `{value}`")
    if report.get("tests"):
        lines.extend(["", "## Tests", "", "| Scope | Result | Command |", "| --- | --- | --- |"])
        for key, value in report["tests"].items():
            if isinstance(value, dict) and "command" in value:
                lines.append(f"| `{key}` | `{value['result']}` | `{value['command']}` |")
        lines.append(f"\nFailed: `{report['tests'].get('failed', 0)}`. Skipped: `{report['tests'].get('skipped', 0)}`.")
    lines.extend(["", "## Guardrails", ""])
    for key, value in report["implementation_guardrails"].items():
        lines.append(f"- `{key}`: `{value}`")
    return "\n".join(lines) + "\n"


def coverage_csv_rows(coverage: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for segment in ("house", "apartment"):
        for field, payload in coverage[segment].items():
            if isinstance(payload, dict) and "valid_count" in payload:
                rows.append({"segment": segment, "field": field, **payload})
    return rows


def dataset_signature(listings: Sequence[Listing]) -> str:
    payload = [
        {
            "id": item.id,
            "fingerprint": item.fingerprint,
            "status": item.status,
            "price_clp": str(item.price.clp),
            "property_type": normalize_property_type(item),
            "comuna": item.comuna,
        }
        for item in sorted(listings, key=_listing_sort_key)
    ]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _segment_coverage(listings: Sequence[Listing], *, uf_to_clp: Decimal, house: bool) -> dict[str, Any]:
    payload = {
        "total": len(listings),
        "built_area_m2": _coverage(listings, lambda item: _positive_number(item.built_area_m2) is not None),
        "usable_area_m2": _coverage(listings, lambda item: _positive_number(item.usable_area_m2) is not None),
        "land_area_m2": _coverage(listings, _has_land),
        "bedrooms": _coverage(listings, lambda item: item.bedrooms is not None and int(item.bedrooms) >= 0),
        "bathrooms": _coverage(listings, lambda item: item.bathrooms is not None and int(item.bathrooms) >= 0),
        "parking": _coverage(listings, lambda item: item.parking is not None and int(item.parking) >= 0),
        "canonical_price": _coverage(listings, lambda item: _canonical_usable(item, uf_to_clp)),
        "useful_geocode": _coverage(listings, _useful_geocode),
        "coordinates": _coverage(listings, has_valid_coordinates),
        "microzone": _coverage(listings, lambda item: bool(microzone_tokens_for(item))),
        "title": _coverage(listings, lambda item: _meaningful_text(item.title)),
        "description": _coverage(listings, lambda item: _detail_text_available(item.raw_metadata or {})),
        "product_classification": _coverage(listings, lambda item: classify_product(item).product_class != "unknown"),
    }
    if house:
        payload["built_and_land"] = _coverage(listings, lambda item: _positive_number(item.built_area_m2) is not None and _has_land(item))
    return payload


def _product_row(listing: Listing) -> dict[str, Any]:
    evidence = classify_product(listing)
    return {
        "listing_id": listing.id,
        "source": listing.source,
        "comuna": listing.comuna,
        "property_type": normalize_property_type(listing),
        **evidence.to_dict(),
    }


def _quick_win(field: str, current: int, total: int, recoverable: int, risk: str, difficulty: str, migration: bool, db_apply: bool, tests: str) -> dict[str, Any]:
    potential = min(total, current + recoverable)
    return {
        "field": field,
        "current_count": current,
        "current_pct": _pct(current, total),
        "potential_count": potential,
        "potential_pct": _pct(potential, total),
        "recoverable_count": recoverable,
        "risk": risk,
        "difficulty": difficulty,
        "migration_needed": migration,
        "future_db_apply_needed": db_apply,
        "tests_required": tests,
    }


def _duplicate_row(kind: str, key: str, group: Sequence[Listing], *, leakage_risk: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "group_key": hashlib.sha1(key.encode("utf-8")).hexdigest()[:16],
        "listing_ids": sorted(item.id for item in group if item.id is not None),
        "sources": sorted({str(item.source or "unknown") for item in group}),
        "comunas": sorted({str(item.comuna or "unknown") for item in group}),
        "group_size": len(group),
        "leakage_risk": leakage_risk,
    }


def _near_duplicate_bucket(listing: Listing) -> str | None:
    area = listing.built_area_m2 or listing.usable_area_m2 or listing.m2
    if not area or area <= 0 or listing.price.clp <= 0:
        return None
    return "|".join(
        (
            str(listing.comuna or "unknown"),
            normalize_property_type(listing),
            str(round(float(area) / 5) * 5),
            str(int(listing.bedrooms or 0)),
            str(int(listing.bathrooms or 0)),
            str(round(float(listing.price.clp) / 5_000_000) * 5_000_000),
        )
    )


def _near_duplicate_match(left: Listing, right: Listing) -> bool:
    if left.id == right.id:
        return False
    left_tokens = set(_normalize_text(left.title).split())
    right_tokens = set(_normalize_text(right.title).split())
    union = left_tokens | right_tokens
    title_similarity = len(left_tokens & right_tokens) / len(union) if union else 0.0
    close_coords = False
    if has_valid_coordinates(left) and has_valid_coordinates(right):
        assert left.coordinates is not None and right.coordinates is not None
        close_coords = math.hypot(left.coordinates.lat - right.coordinates.lat, left.coordinates.lon - right.coordinates.lon) <= 0.002
    return title_similarity >= 0.65 or close_coords


def _opportunity_base(listing: Listing) -> dict[str, Any]:
    return {
        "listing_id": listing.id,
        "source": str(listing.source or "unknown"),
        "comuna": str(listing.comuna or "unknown"),
        "property_type": normalize_property_type(listing),
    }


def _raw_listing_payload(listing: Listing) -> dict[str, Any]:
    metadata = listing.raw_metadata if isinstance(listing.raw_metadata, dict) else {}
    return {
        "property_type": listing.property_type,
        "description": metadata.get("description") or metadata.get("detail_text"),
        "m2": listing.m2,
        "built_area_m2": listing.built_area_m2,
        "land_area_m2": listing.land_area_m2,
        "usable_area_m2": listing.usable_area_m2,
        "raw_metadata": metadata,
    }


def _listing_text(listing: Listing) -> str:
    metadata = listing.raw_metadata if isinstance(listing.raw_metadata, dict) else {}
    return " ".join(
        str(value)
        for value in (listing.title, metadata.get("description"), metadata.get("detail_text"), metadata.get("card_text"))
        if _meaningful_text(value)
    )


def _inconsistent_areas(listing: Listing) -> bool:
    built = _positive_number(listing.built_area_m2 or listing.usable_area_m2 or listing.m2)
    land = _positive_number(listing.land_area_m2)
    return bool(built and land and (land / built < 0.25 or land / built > 25))


def _detail_text_available(metadata: dict[str, Any]) -> bool:
    return any(_meaningful_text(metadata.get(key)) for key in ("description", "detail_text", "card_text"))


def _persisted_microzone_tokens(metadata: dict[str, Any]) -> tuple[str, ...]:
    tokens = metadata.get("geo_microzone_tokens")
    confidence = _positive_number(metadata.get("microzone_confidence")) or 0.0
    if isinstance(tokens, (list, tuple)) and confidence >= 0.55:
        return tuple(str(token) for token in tokens if str(token).strip())
    signals = metadata.get("geo_signals")
    if isinstance(signals, dict) and float(signals.get("confidence") or 0.0) >= 0.55:
        signal_tokens = signals.get("landmark_tokens")
        if isinstance(signal_tokens, (list, tuple)):
            return tuple(str(token) for token in signal_tokens if str(token).strip())
    return ()


def _canonical_usable(listing: Listing, uf_to_clp: Decimal) -> bool:
    basis = valuation_price_basis(listing, uf_to_clp)
    return bool(basis.is_usable_for_valuation and basis.amount_uf is not None)


def _useful_geocode(listing: Listing) -> bool:
    return normalized_precision_for(listing) in USEFUL_GEOCODE_PRECISIONS


def _has_land(listing: Listing) -> bool:
    return _positive_number(listing.land_area_m2) is not None


def _currency(listing: Listing) -> str:
    metadata = listing.raw_metadata if isinstance(listing.raw_metadata, dict) else {}
    raw = listing.price_currency or metadata.get("currency_original") or metadata.get("currency")
    return str(raw or "missing").strip().upper()


def _positive_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _coverage(items: Sequence[Any], predicate: Callable[[Any], bool]) -> dict[str, Any]:
    valid = _count(items, predicate)
    return {"valid_count": valid, "total": len(items), "valid_pct": _pct(valid, len(items))}


def _count(items: Sequence[Any], predicate: Callable[[Any], bool]) -> int:
    return sum(bool(predicate(item)) for item in items)


def _pct(value: int, total: int) -> float:
    return round(100 * value / total, 2) if total else 0.0


def _group_by(items: Sequence[Any], key_fn: Callable[[Any], str]) -> dict[str, list[Any]]:
    groups: dict[str, list[Any]] = defaultdict(list)
    for item in items:
        groups[key_fn(item)].append(item)
    return dict(sorted(groups.items()))


def _group_by_nonempty(items: Sequence[Any], key_fn: Callable[[Any], str | None]) -> dict[str, list[Any]]:
    groups: dict[str, list[Any]] = defaultdict(list)
    for item in items:
        key = key_fn(item)
        if key:
            groups[key].append(item)
    return dict(sorted(groups.items()))


def _normalized_url(value: str | None) -> str | None:
    if not value:
        return None
    return value.strip().lower().split("?", 1)[0].rstrip("/") or None


def _meaningful_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _normalize_text(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "").lower())
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return " ".join(re.findall(r"[a-z0-9]+", ascii_text))


def _listing_sort_key(listing: Listing) -> tuple[int, str, str]:
    return (listing.id if listing.id is not None else -1, str(listing.source or ""), str(listing.fingerprint or ""))


def _write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row}) or ["empty"]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value
