"""Read-only validation of Phase 5A enrichment candidates."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from core.entities.listing import Listing
from core.normalization.property_type import normalize_property_type
from domain.data_quality.enrichment_audit import (
    classify_canonical_price_opportunity,
    classify_land_area_opportunity,
    classify_microzone_opportunity,
    dataset_signature,
    detect_duplicate_candidates,
)
from domain.geocoding.microzones import MicrozoneSignals, extract_microzone_signals
from domain.ingestion.data_cleaning import extract_area_fields_with_provenance
from domain.valuation.product_classification import classify_product

LAND_ACCEPT = "accept_high_confidence"
LAND_REVIEW = "review_required"
MICROZONE_SOFT = "use_only_as_soft_signal"
_LAND_CANDIDATE_CATEGORIES = frozenset(
    {"metadata_structured_unmapped", "text_recoverable", "text_recoverable_thousands_normalized"}
)
_LAND_MENTION_CATEGORY = "land_mentioned_without_value"
_AREA_CONFLICT_CATEGORY = "inconsistent_area_fields"
_MICROZONE_CANDIDATE_PREFIX = "potential_"
_PRICE_REFRESH_CATEGORY = "legacy_unrecoverable_refresh_candidate"
_LAND_MIN_M2 = 20.0
_LAND_MAX_M2 = 20_000.0
_LAND_CONTEXT_RE = re.compile(
    r".{0,90}(?:terreno|sitio|lote|superficie\s+(?:de\s+)?terreno).{0,90}", re.I | re.S
)
_AREA_NUMBER_RE = re.compile(r"\b\d{1,5}(?:[.,]\d{1,3})?\s*(?:m2|m\s*2|m²|mts2|metros)?\b", re.I)
_NOT_LAND_RE = re.compile(
    r"(?:uf\s*/?\s*m2|precio\s+por\s+m2|gastos?\s+comunes?|contribuciones?|valor\s+m2)", re.I
)
_LAND_ATTRIBUTE_RE = re.compile(
    r"(?:amplio|gran|hermoso|propio|privado|total|superficie|fondo|frente|patio).{0,25}terreno|"
    r"terreno.{0,25}(?:amplio|grande|propio|privado|total|fondo|frente)",
    re.I,
)
_LAND_OPPORTUNITY_RE = re.compile(
    r"(?:oportunidad|sitio|lote|demoler|demolici[oó]n|solo terreno|vendo terreno|venta terreno)", re.I
)
_LAND_LOCATION_RE = re.compile(r"(?:calle|avenida|av\.?|sector|condominio).{0,30}terreno", re.I)
_EXPLICIT_LAND_PATTERNS = (
    re.compile(r"(?:terreno|sitio|lote|sup\.?\s*terreno|superficie\s+(?:de\s+)?terreno)\s*(?:de|total)?\s*[:\-]?\s*(\d{1,5}(?:[.,]\d{1,3})?)\s*(?:m2|m\s*2|m²|mts2|metros)?", re.I),
    re.compile(r"(\d{1,5}(?:[.,]\d{1,3})?)\s*(?:m2|m\s*2|m²|mts2|metros)\s*(?:de\s+)?(?:terreno|sitio|lote)", re.I),
)


def build_enrichment_validation(
    listings: Sequence[Listing],
    *,
    phase5a_report: dict[str, Any],
    uf_to_clp: Decimal,
    refresh_sample_size: int = 50,
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    """Recalculate and validate Phase 5A candidates without side effects."""
    ordered = sorted(listings, key=_listing_sort_key)
    active = [item for item in ordered if item.is_active]
    phase5a_signature = str(phase5a_report.get("dataset", {}).get("signature") or "")
    current_signature = dataset_signature(ordered)

    land_rows = []
    mention_rows = []
    inconsistency_rows = []
    microzone_rows = []
    for listing in active:
        if normalize_property_type(listing) == "house":
            land_opportunity = classify_land_area_opportunity(listing)
            if land_opportunity.category in _LAND_CANDIDATE_CATEGORIES:
                land_rows.append(validate_land_area_candidate(listing))
            elif land_opportunity.category == _LAND_MENTION_CATEGORY:
                mention_rows.append(classify_land_mention(listing))
            elif land_opportunity.category == _AREA_CONFLICT_CATEGORY:
                inconsistency_rows.append(validate_surface_inconsistency(listing))
        microzone_opportunity = classify_microzone_opportunity(listing)
        if microzone_opportunity.category.startswith(_MICROZONE_CANDIDATE_PREFIX):
            microzone_rows.append(validate_microzone_candidate(listing))

    duplicate_rows = validate_duplicate_groups(active)
    refresh_rows = select_department_refresh_sample(
        active,
        uf_to_clp=uf_to_clp,
        sample_size=refresh_sample_size,
    )
    report = {
        "dataset": {
            "signature": current_signature,
            "phase5a_signature": phase5a_signature,
            "matches_phase5a": current_signature == phase5a_signature,
            "total_listings": len(ordered),
            "active_listings": len(active),
            "uf_to_clp": float(uf_to_clp),
        },
        "land_area": _land_summary(active, land_rows),
        "land_mentions_without_value": _category_summary(mention_rows, "classification"),
        "surface_inconsistencies": _category_summary(inconsistency_rows, "recommendation"),
        "microzone": _microzone_summary(microzone_rows),
        "duplicates_and_leakage": _duplicate_summary(duplicate_rows),
        "department_price_refresh_sample": _refresh_summary(refresh_rows, refresh_sample_size),
        "phase5c_plan": _phase5c_plan(active, land_rows, microzone_rows, duplicate_rows, refresh_rows),
        "implementation_guardrails": {
            "read_only": True,
            "database_writes": 0,
            "external_requests": 0,
            "apply_mode": False,
            "microzones_persisted": 0,
            "land_area_updated": 0,
            "duplicates_deleted": 0,
            "uf_37000_operational": False,
            "benchmark_default_changed": False,
        },
    }
    manifests = {
        "land_area_backfill_candidates": land_rows,
        "microzone_candidates": microzone_rows,
        "duplicate_groups": duplicate_rows,
        "department_price_refresh_sample": refresh_rows,
    }
    return report, manifests


def validate_land_area_candidate(listing: Listing) -> dict[str, Any]:
    """Validate one locally recoverable land-area candidate."""
    opportunity = classify_land_area_opportunity(listing)
    metadata = _metadata(listing)
    parsed = extract_area_fields_with_provenance(_raw_listing_payload(listing), title=listing.title)
    value = _positive_float(opportunity.suggested_value)
    built = _positive_float(listing.built_area_m2 or listing.usable_area_m2 or listing.m2)
    text = _listing_text(listing)
    evidence = _evidence_snippet(text, value)
    source = parsed.sources.get("land_area_m2") or opportunity.evidence
    warnings = list(parsed.warnings)
    explicit_land_values = _explicit_land_values(text)
    ratio = round(value / built, 3) if value and built else None
    unit = "m2" if re.search(r"(?:m2|m\s*2|m²|mts2|metros)", evidence, re.I) else "implicit_m2"

    status = LAND_ACCEPT
    reason = "explicit_land_context_with_plausible_value"
    if normalize_property_type(listing) != "house":
        status, reason = "reject_not_land_area", "property_type_is_not_house"
    elif _positive_float(listing.land_area_m2) is not None:
        status, reason = "reject_conflict", "land_area_already_present"
    elif value is None or value <= 0:
        status, reason = "reject_implausible", "missing_or_non_positive_value"
    elif value < _LAND_MIN_M2 or value > _LAND_MAX_M2:
        status, reason = "reject_implausible", f"outside_plausible_range_{_LAND_MIN_M2:g}_{_LAND_MAX_M2:g}"
    elif _NOT_LAND_RE.search(evidence):
        status, reason = "reject_not_land_area", "price_or_expense_context"
    elif len(explicit_land_values) > 1:
        status, reason = "reject_conflict", "multiple_incompatible_land_values"
    elif source == "text.house_slash_area_pair":
        status, reason = LAND_REVIEW, "slash_pair_requires_human_confirmation"
    elif source == "text.land_area_without_unit":
        status, reason = LAND_REVIEW, "land_label_present_but_unit_is_implicit"
    elif any("land_area_m2" in warning for warning in warnings) and not explicit_land_values:
        status, reason = LAND_REVIEW, "parser_warning_without_single_explicit_land_value"
    elif built and math.isclose(value, built, rel_tol=0.0, abs_tol=0.01) and "land_area" not in source:
        status, reason = "reject_not_land_area", "same_as_built_area_without_explicit_land_rule"
    elif ratio is not None and (ratio < 0.25 or ratio > 30):
        status, reason = LAND_REVIEW, "extreme_land_to_built_ratio"

    return {
        "listing_id": listing.id,
        "source": listing.source,
        "url": listing.url,
        "comuna": listing.comuna,
        "property_type": normalize_property_type(listing),
        "title": listing.title,
        "description_or_metadata": _description_or_metadata(metadata),
        "origin_field": source,
        "detected_value": value,
        "unit": unit,
        "evidence_text": evidence,
        "parser_rule": source,
        "parser_confidence": opportunity.confidence,
        "built_area_m2_current": built,
        "land_area_m2_current": _positive_float(listing.land_area_m2),
        "land_area_m2_proposed": value,
        "land_to_built_ratio": ratio,
        "plausible_range_m2": f"{_LAND_MIN_M2:g}-{_LAND_MAX_M2:g}",
        "parser_warnings": warnings,
        "explicit_land_values": explicit_land_values,
        "status": status,
        "decision_reason": reason,
        "dry_run_only": True,
    }


def classify_land_mention(listing: Listing) -> dict[str, Any]:
    text = _listing_text(listing)
    evidence = _evidence_snippet(text, None)
    product = classify_product(listing)
    if product.is_strong_special:
        classification = "possible_special_product_classification"
        utility = "product_classification_and_canonical_filtering"
    elif _LAND_LOCATION_RE.search(evidence):
        classification = "location_or_name_context"
        utility = "manual_review_only"
    elif _LAND_OPPORTUNITY_RE.search(evidence):
        classification = "opportunity_or_site_without_surface"
        utility = "product_classification_and_refresh_prioritization"
    elif _LAND_ATTRIBUTE_RE.search(evidence):
        classification = "real_land_attribute_without_surface"
        utility = "refresh_prioritization"
    elif listing.url:
        classification = "requires_detail_refresh"
        utility = "refresh_prioritization"
    else:
        classification = "not_recoverable"
        utility = "none"
    return {
        "listing_id": listing.id,
        "source": listing.source,
        "url": listing.url,
        "comuna": listing.comuna,
        "title": listing.title,
        "evidence_text": evidence,
        "classification": classification,
        "utility": utility,
        "product_class": product.product_class,
        "product_strength": product.strength,
        "surface_invented": False,
    }


def validate_surface_inconsistency(listing: Listing) -> dict[str, Any]:
    metadata = _metadata(listing)
    parsed = extract_area_fields_with_provenance(_raw_listing_payload(listing), title=listing.title)
    warnings = sorted({*parsed.warnings, *_string_list(metadata.get("area_parse_warnings"))})
    if any("land_area_m2" in warning for warning in warnings):
        recommendation = "manual_review"
        probable_impact = "possible_land_area_conflict"
    elif warnings:
        recommendation = "future_parser_correction"
        probable_impact = "built_area_candidate_was_ignored"
    elif listing.url:
        recommendation = "refresh"
        probable_impact = "inconsistent_structured_area_fields"
    else:
        recommendation = "do_not_touch"
        probable_impact = "insufficient_evidence"
    return {
        "listing_id": listing.id,
        "source": listing.source,
        "url": listing.url,
        "comuna": listing.comuna,
        "built_area_m2_current": listing.built_area_m2,
        "usable_area_m2_current": listing.usable_area_m2,
        "land_area_m2_current": listing.land_area_m2,
        "m2_raw": listing.m2,
        "metadata_area_sources": _area_metadata(metadata),
        "evidence_text": _evidence_snippet(_listing_text(listing), None),
        "parser_warnings": warnings,
        "possible_parser_error": bool(warnings),
        "probable_impact": probable_impact,
        "recommendation": recommendation,
        "dry_run_only": True,
    }


def validate_microzone_candidate(listing: Listing) -> dict[str, Any]:
    opportunity = classify_microzone_opportunity(listing)
    signals, source_field, source_text = _candidate_microzone_signals(listing, opportunity.category)
    signal_type, normalized = _primary_microzone_signal(signals)
    false_positive_risk = "low"
    recommendation = MICROZONE_SOFT
    reason = "single_local_text_signal_should_remain_soft"
    if signals.reason.startswith("rejected:"):
        false_positive_risk = "high"
        recommendation = "reject_false_positive"
        reason = signals.reason
    elif not normalized or signals.confidence < 0.55:
        false_positive_risk = "high"
        recommendation = "reject_ambiguous"
        reason = "signal_not_usable"
    elif signal_type in {"metro", "intersection"} and signals.confidence >= 0.7:
        recommendation = "accept_high_confidence"
        reason = "specific_known_geographic_signal"
    elif signal_type in {"avenue", "landmark"}:
        false_positive_risk = "medium"
        recommendation = MICROZONE_SOFT
        reason = "valid_but_not_unique_within_comuna"
    else:
        false_positive_risk = "medium"
        recommendation = "review_required"
        reason = "generic_or_context_dependent_signal"
    return {
        "listing_id": listing.id,
        "source": listing.source,
        "comuna": listing.comuna,
        "property_type": normalize_property_type(listing),
        "title": listing.title,
        "description_or_metadata": source_text,
        "source_field": source_field,
        "signal_detected": normalized,
        "signal_type": signal_type,
        "evidence": signals.reason,
        "false_positive_risk": false_positive_risk,
        "normalized_microzone": normalized,
        "confidence": signals.confidence,
        "recommendation": recommendation,
        "decision_reason": reason,
        "persisted": False,
    }


def validate_duplicate_groups(listings: Sequence[Listing]) -> list[dict[str, Any]]:
    by_id = {item.id: item for item in listings if item.id is not None}
    rows = []
    for candidate in detect_duplicate_candidates(listings):
        members = [by_id[item_id] for item_id in candidate["listing_ids"] if item_id in by_id]
        pair_similarities = [
            _title_similarity(left.title, right.title)
            for idx, left in enumerate(members)
            for right in members[idx + 1 :]
        ]
        max_similarity = max(pair_similarities, default=0.0)
        same_price = len({str(item.price.clp) for item in members}) == 1
        same_area = len({_area(item) for item in members}) == 1
        if candidate["kind"].startswith("exact_"):
            classification = "exact_duplicate"
        elif max_similarity >= 0.85 and same_price and same_area:
            classification = "near_duplicate_high_confidence"
        elif max_similarity >= 0.65:
            classification = "possible_duplicate"
        elif max_similarity >= 0.45:
            classification = "weak_duplicate"
        else:
            classification = "not_duplicate"
        rows.append(
            {
                "group_id": candidate["group_key"],
                "listing_ids": candidate["listing_ids"],
                "sources": candidate["sources"],
                "comunas": candidate["comunas"],
                "property_types": sorted({normalize_property_type(item) for item in members}),
                "prices_clp": [str(item.price.clp) for item in members],
                "areas_m2": [_area(item) for item in members],
                "bedrooms": [item.bedrooms for item in members],
                "bathrooms": [item.bathrooms for item in members],
                "normalized_titles": [_normalize_text(item.title) for item in members],
                "max_title_similarity": round(max_similarity, 4),
                "group_size": len(members),
                "classification": classification,
                "grouping_reason": candidate["kind"],
                "leakage_risk": candidate["leakage_risk"],
            }
        )
    return sorted(rows, key=lambda row: (row["classification"], row["group_id"]))


def select_department_refresh_sample(
    listings: Sequence[Listing],
    *,
    uf_to_clp: Decimal,
    sample_size: int = 50,
) -> list[dict[str, Any]]:
    candidates = [
        item
        for item in listings
        if item.is_active
        and normalize_property_type(item) == "apartment"
        and classify_canonical_price_opportunity(item, uf_to_clp=uf_to_clp).category == _PRICE_REFRESH_CATEGORY
    ]
    ordered = sorted(candidates, key=_refresh_sort_key)
    if not ordered or sample_size <= 0:
        return []
    price_values = sorted(float(item.price.clp) for item in ordered)
    selected: list[Listing] = []
    selected_ids: set[int | None] = set()
    groups: dict[str, list[Listing]] = defaultdict(list)
    for item in ordered:
        groups[str(item.comuna or "unknown")].append(item)
    for comuna in sorted(groups, key=lambda key: (-len(groups[key]), key)):
        _append_unique(selected, selected_ids, groups[comuna][len(groups[comuna]) // 2], sample_size)
    dimensions = (
        lambda item: _price_band(float(item.price.clp), price_values),
        lambda item: _area_band(_area(item)),
        lambda item: _age_band(item.last_seen_at or item.scraped_at, ordered),
        lambda item: "metadata_uf_hint" if _has_uf_hint(item) else "no_metadata_uf_hint",
    )
    for dimension in dimensions:
        buckets: dict[str, list[Listing]] = defaultdict(list)
        for item in ordered:
            buckets[dimension(item)].append(item)
        for key in sorted(buckets):
            _append_unique(selected, selected_ids, buckets[key][len(buckets[key]) // 2], sample_size)
    group_names = sorted(groups, key=lambda key: (-len(groups[key]), key))
    max_group_size = max((len(group) for group in groups.values()), default=0)
    for position in range(max_group_size):
        for comuna in group_names:
            group = groups[comuna]
            if position < len(group):
                _append_unique(selected, selected_ids, group[position], sample_size)
    selected = selected[: min(sample_size, len(ordered))]
    return [
        {
            "listing_id": item.id,
            "url": item.url,
            "comuna": item.comuna,
            "title": item.title,
            "price_clp_current": str(item.price.clp),
            "currency_current": item.price_currency,
            "price_uf_source": item.price_uf_source,
            "price_uf_confidence": item.price_uf_confidence,
            "legacy_unrecoverable_reason": "legacy_uf_missing_price_uf",
            "last_seen_at": _iso(item.last_seen_at or item.scraped_at),
            "surface_m2": _area(item),
            "price_band": _price_band(float(item.price.clp), price_values),
            "surface_band": _area_band(_area(item)),
            "metadata_textual_uf_hint": _has_uf_hint(item),
            "metadata_uf_signal_kind": _uf_signal_kind(item),
            "refresh_priority": _refresh_priority(item),
            "priority_reason": _refresh_reason(item),
            "visit_performed": False,
        }
        for item in selected
    ]


def write_validation_outputs(
    output_dir: Path,
    report: dict[str, Any],
    manifests: dict[str, list[dict[str, Any]]],
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": output_dir / "data_enrichment_validation_latest.json",
        "markdown": output_dir / "data_enrichment_validation_latest.md",
    }
    paths["json"].write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    paths["markdown"].write_text(markdown_report(report), encoding="utf-8")
    for name, rows in manifests.items():
        json_path = output_dir / f"{name}.json"
        csv_path = output_dir / f"{name}.csv"
        json_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        _write_csv(csv_path, rows)
        paths[f"{name}_json"] = json_path
        paths[f"{name}_csv"] = csv_path
    return {key: str(path) for key, path in paths.items()}


def markdown_report(report: dict[str, Any]) -> str:
    dataset = report["dataset"]
    land = report["land_area"]
    mentions = report["land_mentions_without_value"]
    inconsistencies = report["surface_inconsistencies"]
    microzone = report["microzone"]
    duplicates = report["duplicates_and_leakage"]
    refresh = report["department_price_refresh_sample"]
    plan = report["phase5c_plan"]
    preflight = report.get("preflight", {})
    tests = report.get("tests", {})
    lines = [
        "# Phase 5B Data Enrichment Dry-run Validation",
        "",
        "## Preflight",
        "",
        f"- Branch: `{preflight.get('branch', 'pending')}`",
        f"- HEAD: `{preflight.get('head', 'pending')}`",
        f"- Git status before generation: `{preflight.get('git_status', 'pending') or 'clean'}`",
        f"- Phase 5A signature matches: `{dataset['matches_phase5a']}`",
        f"- Database mode: `{preflight.get('database_mode', 'select_only_session_with_explicit_rollback')}`",
        "- External requests: `0`",
        "",
        "## Land Area Validation",
        "",
        f"- Recalculated: `{land['candidates_recalculated']}`",
        f"- Accepted: `{land['accepted']}`",
        f"- Review: `{land['review']}`",
        f"- Rejected: `{land['rejected']}`",
        f"- Current coverage: `{land['current_coverage_pct']}%`",
        f"- Potential accepted coverage: `{land['potential_accepted_coverage_pct']}%`",
        f"- Potential coverage including review cases: `{land['potential_with_review_coverage_pct']}%`",
        "",
        "## Land Mentions Without Numeric Value",
        "",
        f"- Cases: `{mentions['total']}`",
        f"- Classifications: `{mentions['counts']}`",
        "- No surface was inferred from a non-numeric mention.",
        "",
        "## Surface Inconsistencies",
        "",
        f"- Cases: `{inconsistencies['total']}`",
        f"- Recommendations: `{inconsistencies['counts']}`",
        "",
        "## Microzone Validation",
        "",
        f"- Candidates: `{microzone['candidates']}`",
        f"- Accepted: `{microzone['accepted']}`",
        f"- Review: `{microzone['review']}`",
        f"- Soft signal only: `{microzone['soft_signal_only']}`",
        f"- Rejected: `{microzone['rejected']}`",
        f"- Persistence recommendation: `{microzone['persistence_recommendation']}`",
        "- No microzone was persisted.",
        "",
        "## Duplicates And Leakage",
        "",
        f"- Groups: `{duplicates['groups']}`",
        f"- Affected listings: `{duplicates['affected_listings']}`",
        f"- Validated duplicate groups: `{duplicates['validated_duplicate_groups']}`",
        f"- Validated affected listings: `{duplicates['validated_affected_listings']}`",
        f"- Classifications: `{duplicates['classification_counts']}`",
        f"- Proposal: `{duplicates['evaluator_proposal']}`",
        "",
        "## Department Canonical Price Refresh Sample",
        "",
        f"- Requested sample: `{refresh['requested']}`",
        f"- Selected: `{refresh['selected']}`",
        f"- Comunas represented: `{refresh['comunas_represented']}`",
        f"- Price bands: `{refresh['price_bands']}`",
        f"- Surface bands: `{refresh['surface_bands']}`",
        f"- UF metadata signals: `{refresh['metadata_uf_signal_kinds']}`",
        f"- Limitation: `{refresh['metadata_signal_limitation']}`",
        "- URLs were not visited.",
        "",
        "## Phase 5C Plan",
        "",
    ]
    for area, payload in plan.items():
        lines.extend((f"### {area}", "", f"- `{payload}`", ""))
    lines.extend(("## Tests", ""))
    for name, payload in tests.items():
        if isinstance(payload, dict):
            lines.append(f"- `{name}`: `{payload.get('result')}` - `{payload.get('command')}`")
    lines.extend(
        (
            "",
            "## Git",
            "",
            f"- Branch: `{preflight.get('branch', 'pending')}`",
            f"- HEAD at report generation: `{preflight.get('head', 'pending')}`",
            f"- Working tree before report generation: `{preflight.get('git_status', 'pending') or 'clean'}`",
            f"- Recent commits: `{preflight.get('recent_commits', [])}`",
            f"- Configured remotes: `{preflight.get('remote_count', 0)}`",
        )
    )
    lines.extend(("", "## Guardrails", ""))
    lines.extend(f"- `{key}`: `{value}`" for key, value in report["implementation_guardrails"].items())
    return "\n".join(lines) + "\n"


def _land_summary(active: Sequence[Listing], rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    houses = [item for item in active if normalize_property_type(item) == "house"]
    current = sum(_positive_float(item.land_area_m2) is not None for item in houses)
    accepted = sum(row["status"] == LAND_ACCEPT for row in rows)
    review = sum(row["status"] == LAND_REVIEW for row in rows)
    rejected = len(rows) - accepted - review
    return {
        "houses": len(houses),
        "current_land_area": current,
        "candidates_recalculated": len(rows),
        "status_counts": dict(sorted(Counter(row["status"] for row in rows).items())),
        "accepted": accepted,
        "review": review,
        "rejected": rejected,
        "current_coverage_pct": _pct(current, len(houses)),
        "potential_accepted_coverage_pct": _pct(current + accepted, len(houses)),
        "potential_with_review_coverage_pct": _pct(current + accepted + review, len(houses)),
        "examples": list(rows[:10]),
    }


def _microzone_summary(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(row["recommendation"] for row in rows)
    return {
        "candidates": len(rows),
        "recommendation_counts": dict(sorted(counts.items())),
        "accepted": counts["accept_high_confidence"],
        "review": counts["review_required"],
        "soft_signal_only": counts[MICROZONE_SOFT],
        "rejected": counts["reject_ambiguous"] + counts["reject_false_positive"],
        "persistence_recommendation": "persist_only_accepted_after_corpus_review; keep avenues and landmarks as soft signals",
        "examples": list(rows[:10]),
    }


def _duplicate_summary(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    affected = {item_id for row in rows for item_id in row["listing_ids"]}
    confirmed = [row for row in rows if row["classification"] != "not_duplicate"]
    confirmed_affected = {item_id for row in confirmed for item_id in row["listing_ids"]}
    return {
        "groups": len(rows),
        "affected_listings": len(affected),
        "validated_duplicate_groups": len(confirmed),
        "validated_affected_listings": len(confirmed_affected),
        "classification_counts": dict(sorted(Counter(row["classification"] for row in rows).items())),
        "leakage_risk": "medium" if rows else "low",
        "evaluator_proposal": {
            "default_behavior": "unchanged",
            "future_flag": "--dedupe-diagnostics",
            "target_rule": "report whether target belongs to a validated duplicate group",
            "candidate_rule": "diagnose and optionally exclude copies of target in experimental runs",
            "metrics": "report benchmark metrics with and without validated high-confidence groups",
        },
        "examples": list(rows[:10]),
    }


def _refresh_summary(rows: Sequence[dict[str, Any]], requested: int) -> dict[str, Any]:
    return {
        "requested": requested,
        "selected": len(rows),
        "comunas_represented": len({row["comuna"] for row in rows}),
        "price_bands": dict(sorted(Counter(row["price_band"] for row in rows).items())),
        "surface_bands": dict(sorted(Counter(row["surface_band"] for row in rows).items())),
        "metadata_textual_uf_hint": dict(sorted(Counter(str(row["metadata_textual_uf_hint"]) for row in rows).items())),
        "metadata_uf_signal_kinds": dict(sorted(Counter(row["metadata_uf_signal_kind"] for row in rows).items())),
        "metadata_signal_limitation": "all eligible legacy candidates retain structured UF currency, but none in the selected sample retains local textual UF evidence",
        "selection_method": "deterministic coverage-first sample by comuna, price, surface, age and metadata UF hint",
        "external_visits": 0,
        "examples": list(rows[:10]),
    }


def _phase5c_plan(active, land_rows, microzone_rows, duplicate_rows, refresh_rows) -> dict[str, Any]:
    accepted_land = sum(row["status"] == LAND_ACCEPT for row in land_rows)
    review_land = sum(row["status"] == LAND_REVIEW for row in land_rows)
    rejected_land = len(land_rows) - accepted_land - review_land
    houses = sum(normalize_property_type(item) == "house" for item in active)
    current_land = sum(
        normalize_property_type(item) == "house" and _positive_float(item.land_area_m2) is not None for item in active
    )
    accepted_micro = sum(row["recommendation"] == "accept_high_confidence" for row in microzone_rows)
    return {
        "land_area": {
            "apply_candidates": accepted_land,
            "review_candidates": review_land,
            "rejected_candidates": rejected_land,
            "expected_coverage_pct": _pct(current_land + accepted_land, houses),
            "minimum_tests": "candidate fixture corpus, parser provenance, idempotency, row-count and before/after snapshot",
            "rollback": "export listing_id and previous land_area_m2; one transaction; rollback on count/value mismatch",
            "future_command": "python scripts/backfill_house_area_corrections.py --manifest <approved.json> --limit <N> --dry-run",
            "safety_limits": "approved IDs only, one transaction, max rows equal manifest, no parser-wide apply",
        },
        "microzone": {
            "persist_candidates": accepted_micro,
            "soft_or_review_candidates": len(microzone_rows) - accepted_micro,
            "recommendation": "prefer soft signals until a comuna-aware false-positive corpus passes",
            "minimum_tests": "known metro/intersection positives and avenue/marketing false positives",
            "rollback": "snapshot raw_metadata keys and restore only touched IDs in one transaction",
        },
        "duplicates": {
            "diagnostic_groups": len(duplicate_rows),
            "recommendation": "add opt-in evaluator diagnostics before any exclusion behavior",
            "measurement": "same split and seed; compare metrics, coverage and extreme errors with/without high-confidence dedupe",
        },
        "department_price_refresh": {
            "pilot_recommended": bool(refresh_rows),
            "pilot_size": len(refresh_rows),
            "mode_order": "cache-only/no-external first, then separately approved limited network pilot",
            "stop_conditions": "captcha/block, >10% parse errors, unexpected currency, missing real UF, or DB delta outside approved IDs",
            "rollback": "snapshot canonical price/provenance fields and price history; transactional apply in a separate phase",
            "success_metric": "valid strong canonical UF recovery rate >=37.42% with zero fallback UF and audited provenance",
        },
    }


def _category_summary(rows: Sequence[dict[str, Any]], key: str) -> dict[str, Any]:
    return {"total": len(rows), "counts": dict(sorted(Counter(str(row[key]) for row in rows).items())), "examples": list(rows[:10])}


def _candidate_microzone_signals(listing: Listing, category: str) -> tuple[MicrozoneSignals, str, str]:
    metadata = _metadata(listing)
    if category == "potential_from_title":
        return extract_microzone_signals(title=listing.title, raw_metadata={}), "title", listing.title
    if category == "potential_from_description":
        value = str(metadata.get("description") or metadata.get("detail_text") or "")
        return extract_microzone_signals(raw_metadata={"description": value}), "description", value
    structured = {key: metadata.get(key) for key in ("address_label", "street_hint", "location_text", "location", "neighborhood")}
    value = " | ".join(f"{key}={raw}" for key, raw in structured.items() if raw)
    return extract_microzone_signals(raw_metadata=structured), "metadata", value


def _primary_microzone_signal(signals: MicrozoneSignals) -> tuple[str, str | None]:
    if signals.nearby_metro:
        return "metro", f"metro:{signals.nearby_metro}"
    if signals.intersection_hint:
        return "intersection", f"intersection:{signals.intersection_hint}"
    if signals.nearby_avenue:
        return "avenue", f"avenue:{signals.nearby_avenue}"
    if signals.neighborhood_hint:
        return "sector", f"sector:{signals.neighborhood_hint}"
    if signals.landmark_tokens:
        token = signals.landmark_tokens[0]
        prefix = token.split(":", 1)[0]
        signal_type = "park" if "parque" in token else "plaza" if "plaza" in token else "landmark"
        return signal_type if prefix == "landmark" else prefix, token
    return "unknown", None


def _raw_listing_payload(listing: Listing) -> dict[str, Any]:
    return {
        "property_type": listing.property_type,
        "description": _metadata(listing).get("description") or _metadata(listing).get("detail_text"),
        "m2": listing.m2,
        "built_area_m2": listing.built_area_m2,
        "land_area_m2": listing.land_area_m2,
        "usable_area_m2": listing.usable_area_m2,
        "raw_metadata": _metadata(listing),
    }


def _listing_text(listing: Listing) -> str:
    metadata = _metadata(listing)
    return " ".join(
        str(value)
        for value in (listing.title, metadata.get("description"), metadata.get("detail_text"), metadata.get("card_text"))
        if isinstance(value, str) and value.strip()
    )


def _evidence_snippet(text: str, value: float | None) -> str:
    match = _LAND_CONTEXT_RE.search(text)
    if not match and value is not None:
        value_pattern = re.compile(rf".{{0,90}}{re.escape(format(value, 'g'))}.{{0,90}}", re.I | re.S)
        match = value_pattern.search(text)
    snippet = match.group(0) if match else text[:240]
    return re.sub(r"\s+", " ", snippet).strip()[:280]


def _description_or_metadata(metadata: dict[str, Any]) -> str:
    for key in ("description", "detail_text", "card_text"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return re.sub(r"\s+", " ", value).strip()[:500]
    payload = {key: metadata.get(key) for key in sorted(metadata) if any(token in key.lower() for token in ("area", "terreno", "surface", "m2"))}
    return json.dumps(payload, ensure_ascii=False, default=str)[:500]


def _area_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        key: metadata.get(key)
        for key in sorted(metadata)
        if any(token in key.lower() for token in ("area", "terreno", "surface", "m2"))
    }


def _metadata(listing: Listing) -> dict[str, Any]:
    return listing.raw_metadata if isinstance(listing.raw_metadata, dict) else {}


def _positive_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _area(listing: Listing) -> float | None:
    return _positive_float(listing.built_area_m2 or listing.usable_area_m2 or listing.m2)


def _normalize_text(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "").lower())
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return " ".join(re.sub(r"[^a-z0-9\s]", " ", ascii_text).split())


def _title_similarity(left: str, right: str) -> float:
    left_tokens = set(_normalize_text(left).split())
    right_tokens = set(_normalize_text(right).split())
    union = left_tokens | right_tokens
    return len(left_tokens & right_tokens) / len(union) if union else 0.0


def _refresh_sort_key(listing: Listing) -> tuple[str, float, float, str]:
    return (str(listing.comuna or ""), float(listing.price.clp), _area(listing) or 0.0, str(listing.id or ""))


def _append_unique(selected: list[Listing], selected_ids: set[int | None], item: Listing, limit: int) -> None:
    if len(selected) >= limit or item.id in selected_ids:
        return
    selected.append(item)
    selected_ids.add(item.id)


def _price_band(value: float, sorted_values: Sequence[float]) -> str:
    if not sorted_values:
        return "unknown"
    q1 = sorted_values[len(sorted_values) // 4]
    q3 = sorted_values[(len(sorted_values) * 3) // 4]
    return "low" if value <= q1 else "high" if value >= q3 else "mid"


def _area_band(value: float | None) -> str:
    if value is None:
        return "missing"
    if value < 50:
        return "small_lt_50"
    if value <= 90:
        return "medium_50_90"
    return "large_gt_90"


def _age_band(value: datetime | None, candidates: Sequence[Listing]) -> str:
    dates = sorted(item.last_seen_at or item.scraped_at for item in candidates if item.last_seen_at or item.scraped_at)
    if value is None or not dates:
        return "unknown"
    median = dates[len(dates) // 2]
    return "older" if value <= median else "recent"


def _has_uf_hint(listing: Listing) -> bool:
    metadata = _metadata(listing)
    values = [
        metadata.get(key)
        for key in ("price_text", "price_raw", "card_text", "description", "detail_text")
    ]
    return any("uf" in str(value or "").lower() for value in values)


def _refresh_priority(listing: Listing) -> str:
    if listing.url and _has_uf_hint(listing):
        return "high"
    if listing.url:
        return "medium"
    return "low"


def _uf_signal_kind(listing: Listing) -> str:
    if _has_uf_hint(listing):
        return "textual_uf_evidence"
    metadata = _metadata(listing)
    structured = listing.price_currency or metadata.get("currency_original") or metadata.get("price_currency")
    if str(structured or "").strip().upper() in {"UF", "CLF"}:
        return "structured_currency_only"
    return "no_local_uf_signal"


def _refresh_reason(listing: Listing) -> str:
    if listing.url and _has_uf_hint(listing):
        return "url_available_and_local_uf_hint"
    if listing.url:
        return "url_available_for_future_controlled_refresh"
    return "missing_url"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list | tuple):
        return [str(item) for item in value]
    return [str(value)] if value else []


def _explicit_land_values(text: str) -> list[float]:
    values: list[float] = []
    for pattern in _EXPLICIT_LAND_PATTERNS:
        for match in pattern.finditer(text):
            value = _parse_localized_number(match.group(1))
            if value is not None and not any(math.isclose(value, current, abs_tol=0.01) for current in values):
                values.append(value)
    return sorted(values)


def _parse_localized_number(value: str) -> float | None:
    cleaned = str(value).strip()
    if "." in cleaned and "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".") if cleaned.rfind(",") > cleaned.rfind(".") else cleaned.replace(",", "")
    elif "." in cleaned:
        parts = cleaned.split(".")
        if len(parts) > 1 and all(len(part) == 3 for part in parts[1:]):
            cleaned = "".join(parts)
    elif "," in cleaned:
        parts = cleaned.split(",")
        cleaned = "".join(parts) if len(parts) > 1 and all(len(part) == 3 for part in parts[1:]) else cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _listing_sort_key(listing: Listing) -> tuple[int, str, str]:
    return (listing.id if listing.id is not None else -1, str(listing.source or ""), str(listing.external_id or ""))


def _pct(value: int, total: int) -> float:
    return round(value * 100 / total, 2) if total else 0.0


def _write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row}) if rows else ["status"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return value


def validation_signature(report: dict[str, Any], manifests: dict[str, list[dict[str, Any]]]) -> str:
    payload = {"report": report, "manifests": manifests}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()
