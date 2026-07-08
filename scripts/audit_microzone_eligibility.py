"""Read-only eligibility audit for shadow microzones."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.entities.listing import Listing  # noqa: E402
from core.normalization.geocode_precision import canonical_geocode_precision  # noqa: E402
from core.normalization.property_type import normalize_property_type as _property_type  # noqa: E402
from domain.geocoding.geo_signals import GeoSignalCandidate, recover_geo_signals  # noqa: E402
from domain.geocoding.geographic_microzones import (  # noqa: E402
    GeographicMicrozoneDecision,
    geographic_microzone_for,
)
from domain.geocoding.microzone_shadow import (  # noqa: E402
    ShadowMicrozoneAssignment,
    assign_shadow_microzone,
)
from domain.geocoding.microzones import MicrozoneSignals, extract_microzone_signals  # noqa: E402
from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.repositories.listing_repo import SqlAlchemyListingRepository  # noqa: E402

CRITICAL_APARTMENT_COMUNAS = (
    "las condes",
    "providencia",
    "nunoa",
    "santiago",
    "vitacura",
    "estacion central",
    "san miguel",
    "la florida",
    "macul",
    "independencia",
)
LOCATION_METADATA_KEYS = ("address", "address_label", "street_hint", "location_text", "location", "neighborhood")
STRONG_STREET_SOURCES = {"metadata_address", "metadata_street_hint", "detail_exact_address"}
STRONG_STREET_CONFIDENCES = {"high", "medium"}


@dataclass(frozen=True)
class ListingEligibility:
    listing_id: int | None
    title: str
    comuna: str
    property_type: str
    bucket: str
    bucket_reason: str
    lat: float | None
    lon: float | None
    has_lat_lon: bool
    geocode_precision: str
    geo_reason: str
    geo_query_source: str
    geo_query_confidence: str
    shadow_kind: str
    shadow_key: str | None
    shadow_confidence: str
    raw_metadata_keys: tuple[str, ...]
    address: str | None
    address_label: str | None
    street_hint: str | None
    location_text: str | None
    best_signal_type: str | None
    best_signal_source: str | None
    best_signal_confidence: str | None
    best_signal_value: str | None
    signal_types: tuple[str, ...]
    has_street_signal: bool
    has_corridor_signal: bool
    has_textual_microzone_signal: bool
    street_used_only_as_reference: bool
    street_microzone_candidate: bool
    current_street_blocker: str | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate read-only microzone eligibility audit.")
    parser.add_argument("--output-dir", default="reports/microzones")
    parser.add_argument("--examples-per-bucket", type=int, default=12)
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    start = perf_counter()
    async with get_session_factory()() as session:
        listings = list(await SqlAlchemyListingRepository(session).list_active())

    rows = [classify_listing(listing) for listing in listings if listing.is_active]
    report = build_report(
        rows=rows,
        examples_per_bucket=args.examples_per_bucket,
        runtime_ms=round((perf_counter() - start) * 1000, 2),
    )
    write_outputs(report, Path(args.output_dir))
    print(
        json.dumps(
            {
                "active_listings": report["summary"]["active_listings"],
                "geo_500m_success": report["buckets"]["geo_500m_success"]["count"],
                "has_lat_lon_but_not_geo_500m": report["buckets"]["has_lat_lon_but_not_geo_500m"]["count"],
                "has_street_signal_no_lat_lon": report["buckets"]["has_street_signal_no_lat_lon"]["count"],
                "street_used_only_as_reference": report["buckets"]["street_used_only_as_reference"]["count"],
                "street_microzone_candidates": report["summary"]["street_microzone_candidates"],
                "markdown": str(Path(args.output_dir) / "microzone_eligibility_audit_latest.md"),
                "json": str(Path(args.output_dir) / "microzone_eligibility_audit_latest.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def classify_listing(listing: Listing) -> ListingEligibility:
    raw_metadata = _raw_metadata(listing)
    street_hint = _metadata_str(raw_metadata, "street_hint")
    lat, lon = _lat_lon(listing)
    has_lat_lon = lat is not None and lon is not None
    precision = canonical_geocode_precision(listing.geocode_precision)
    geo_decision = geographic_microzone_for(_geo_value(listing, lat=lat, lon=lon))
    shadow = assign_shadow_microzone(listing)
    recovery = recover_geo_signals(title=listing.title, raw_metadata=raw_metadata, url=listing.url)
    candidates = list(recovery.candidates)
    signals = extract_microzone_signals(title=listing.title, raw_metadata=raw_metadata)
    best_signal = _best_signal(candidates)
    signal_types = tuple(sorted({candidate.signal_type for candidate in candidates}))
    has_street_signal = any(candidate.signal_type == "street" for candidate in candidates)
    has_corridor_signal = _has_corridor_signal(candidates, signals)
    has_textual_microzone_signal = _has_textual_microzone_signal(signals)
    street_candidate = _street_microzone_candidate(listing, candidates)
    has_street_reference = has_street_signal or street_hint is not None
    street_reference_only = has_street_reference and not shadow.is_real_microzone
    current_street_blocker = _street_blocker(
        shadow,
        has_street_reference=has_street_reference,
        has_street_signal=has_street_signal,
        street_candidate=street_candidate,
    )
    bucket, bucket_reason = bucket_for(
        listing=listing,
        shadow=shadow,
        geo_decision=geo_decision,
        has_lat_lon=has_lat_lon,
        has_street_signal=has_street_signal,
        has_corridor_signal=has_corridor_signal,
        has_textual_microzone_signal=has_textual_microzone_signal,
        street_reference_only=street_reference_only,
        candidates=candidates,
    )
    return ListingEligibility(
        listing_id=listing.id,
        title=listing.title,
        comuna=listing.comuna,
        property_type=_property_type(listing),
        bucket=bucket,
        bucket_reason=bucket_reason,
        lat=lat,
        lon=lon,
        has_lat_lon=has_lat_lon,
        geocode_precision=precision,
        geo_reason=geo_decision.reason,
        geo_query_source=geo_decision.query_source,
        geo_query_confidence=geo_decision.query_confidence,
        shadow_kind=shadow.microzone_kind,
        shadow_key=shadow.microzone_key,
        shadow_confidence=shadow.confidence,
        raw_metadata_keys=tuple(sorted(raw_metadata.keys())),
        address=_metadata_str(raw_metadata, "address"),
        address_label=_metadata_str(raw_metadata, "address_label"),
        street_hint=street_hint,
        location_text=_metadata_str(raw_metadata, "location_text"),
        best_signal_type=best_signal.signal_type if best_signal else None,
        best_signal_source=best_signal.source if best_signal else None,
        best_signal_confidence=best_signal.confidence if best_signal else None,
        best_signal_value=best_signal.value if best_signal else None,
        signal_types=signal_types,
        has_street_signal=has_street_signal,
        has_corridor_signal=has_corridor_signal,
        has_textual_microzone_signal=has_textual_microzone_signal,
        street_used_only_as_reference=street_reference_only,
        street_microzone_candidate=street_candidate,
        current_street_blocker=current_street_blocker,
    )


def bucket_for(
    *,
    listing: Listing,
    shadow: ShadowMicrozoneAssignment,
    geo_decision: GeographicMicrozoneDecision,
    has_lat_lon: bool,
    has_street_signal: bool,
    has_corridor_signal: bool,
    has_textual_microzone_signal: bool,
    street_reference_only: bool,
    candidates: Sequence[GeoSignalCandidate],
) -> tuple[str, str]:
    if shadow.microzone_kind == "geo_500m":
        return "geo_500m_success", _geo_success_reason(geo_decision)
    if has_lat_lon:
        return "has_lat_lon_but_not_geo_500m", _geo_failure_reason(geo_decision)
    if street_reference_only:
        return "street_used_only_as_reference", "street signal exists but no geo_500m or textual operational assignment was produced"
    if has_street_signal or has_corridor_signal or has_textual_microzone_signal:
        return "has_street_signal_no_lat_lon", _signal_reason(candidates, has_textual_microzone_signal)
    if _has_comuna(listing):
        return "comuna_fallback_only", "only comuna is usable for shadow assignment"
    return "no_location_signal", "no coordinates, comuna, or usable text location signal"


def build_report(
    *,
    rows: Sequence[ListingEligibility],
    examples_per_bucket: int,
    runtime_ms: float,
) -> dict[str, Any]:
    active_count = len(rows)
    buckets = bucket_summary(rows, examples_per_bucket=examples_per_bucket)
    geo_success = [row for row in rows if row.bucket == "geo_500m_success"]
    geo_failures = [row for row in rows if row.bucket == "has_lat_lon_but_not_geo_500m"]
    street_rows = [row for row in rows if _has_street_reference(row)]
    street_no_real = [row for row in street_rows if not _real_microzone(row)]
    street_candidates = [row for row in rows if row.street_microzone_candidate]
    apartments = [row for row in rows if row.property_type == "apartment"]
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "summary": {
            "active_listings": active_count,
            "by_property_type": counter_dict(Counter(row.property_type for row in rows)),
            "street_signal_usable_no_real_microzone": len(street_no_real),
            "street_microzone_candidates": len(street_candidates),
            "geo_500m_success_pct": pct(len(geo_success), active_count),
            "runtime_ms": runtime_ms,
            "read_only": True,
            "productive_code_modified": False,
        },
        "buckets": buckets,
        "global_metrics": global_metrics(rows),
        "apartment_metrics": scoped_metrics(apartments, label="apartments"),
        "critical_apartment_comunas": critical_apartment_metrics(apartments),
        "geo_500m_success_analysis": geo_success_analysis(geo_success, geo_failures),
        "street_analysis": street_analysis(rows, street_rows, street_no_real, street_candidates),
        "technical_proposal_not_implemented": technical_proposal(),
        "recommendation": recommendation(rows, geo_success, street_candidates),
        "do_not_do_yet": [
            "Do not persist microzone assignments.",
            "Do not wire street warnings into Radar.",
            "Do not hard-filter comparables by microzone.",
            "Do not run external geocoding or broad backfills.",
            "Do not create a large manual catalog before validating street/corridor buckets.",
        ],
        "sample_rows": {
            "geo_500m_success": [row_dict(row) for row in geo_success[:examples_per_bucket]],
            "has_lat_lon_but_not_geo_500m": [row_dict(row) for row in geo_failures[:examples_per_bucket]],
            "street_microzone_candidates": [row_dict(row) for row in street_candidates[:examples_per_bucket]],
            "street_used_only_as_reference": [
                row_dict(row) for row in rows if row.bucket == "street_used_only_as_reference"
            ][:examples_per_bucket],
        },
    }
    return report


def bucket_summary(rows: Sequence[ListingEligibility], *, examples_per_bucket: int) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for bucket in (
        "geo_500m_success",
        "has_lat_lon_but_not_geo_500m",
        "has_street_signal_no_lat_lon",
        "street_used_only_as_reference",
        "comuna_fallback_only",
        "no_location_signal",
    ):
        group = [row for row in rows if row.bucket == bucket]
        result[bucket] = {
            "count": len(group),
            "pct": pct(len(group), len(rows)),
            "by_comuna": counter_dict(Counter(row.comuna for row in group), limit=25),
            "by_property_type": counter_dict(Counter(row.property_type for row in group)),
            "by_geocode_precision": counter_dict(Counter(row.geocode_precision for row in group)),
            "examples": [row_dict(row) for row in group[:examples_per_bucket]],
        }
    return result


def global_metrics(rows: Sequence[ListingEligibility]) -> dict[str, Any]:
    metadata_presence = {
        key: sum(1 for row in rows if getattr(row, key if key != "address" else "address") is not None)
        for key in ("address", "address_label", "street_hint", "location_text")
    }
    return {
        "total_active": len(rows),
        "by_property_type": counter_dict(Counter(row.property_type for row in rows)),
        "by_bucket": counter_dict(Counter(row.bucket for row in rows)),
        "by_comuna": breakdown(rows, "comuna"),
        "by_geocode_precision": breakdown(rows, "geocode_precision"),
        "metadata_field_coverage": {
            key: {"count": value, "pct": pct(value, len(rows))}
            for key, value in metadata_presence.items()
        },
        "street_signal_usable_no_real_microzone": sum(_has_street_reference(row) and not _real_microzone(row) for row in rows),
        "street_microzone_candidates": sum(row.street_microzone_candidate for row in rows),
        "corridor_signal_rows": sum(row.has_corridor_signal for row in rows),
        "textual_microzone_signal_rows": sum(row.has_textual_microzone_signal for row in rows),
    }


def scoped_metrics(rows: Sequence[ListingEligibility], *, label: str) -> dict[str, Any]:
    return {
        "label": label,
        "total": len(rows),
        "by_bucket": counter_dict(Counter(row.bucket for row in rows)),
        "by_geocode_precision": counter_dict(Counter(row.geocode_precision for row in rows)),
        "street_microzone_candidates": sum(row.street_microzone_candidate for row in rows),
        "street_signal_usable_no_real_microzone": sum(_has_street_reference(row) and not _real_microzone(row) for row in rows),
        "by_comuna": breakdown(rows, "comuna"),
    }


def critical_apartment_metrics(rows: Sequence[ListingEligibility]) -> list[dict[str, Any]]:
    critical = {_normalize_comuna(value) for value in CRITICAL_APARTMENT_COMUNAS}
    grouped: dict[str, list[ListingEligibility]] = defaultdict(list)
    for row in rows:
        normalized = _normalize_comuna(row.comuna)
        if normalized in critical:
            grouped[normalized].append(row)
    result = []
    for comuna in sorted(critical):
        group = grouped.get(comuna, [])
        result.append(
            {
                "comuna": comuna,
                "active_apartments": len(group),
                "geo_500m_success": sum(row.bucket == "geo_500m_success" for row in group),
                "street_microzone_candidates": sum(row.street_microzone_candidate for row in group),
                "street_signal_no_real_microzone": sum(_has_street_reference(row) and not _real_microzone(row) for row in group),
                "comuna_fallback_only": sum(row.bucket == "comuna_fallback_only" for row in group),
                "geo_500m_success_pct": pct(sum(row.bucket == "geo_500m_success" for row in group), len(group)),
            }
        )
    return result


def geo_success_analysis(
    successes: Sequence[ListingEligibility],
    failures: Sequence[ListingEligibility],
) -> dict[str, Any]:
    return {
        "count": len(successes),
        "top_comunas": counter_dict(Counter(row.comuna for row in successes), limit=20),
        "by_geocode_precision": counter_dict(Counter(row.geocode_precision for row in successes)),
        "by_query_source": counter_dict(Counter(row.geo_query_source for row in successes)),
        "by_query_confidence": counter_dict(Counter(row.geo_query_confidence for row in successes)),
        "raw_metadata_key_counts": counter_dict(Counter(key for row in successes for key in row.raw_metadata_keys), limit=30),
        "success_reason_counts": counter_dict(Counter(row.bucket_reason for row in successes)),
        "failure_reason_counts": counter_dict(Counter(row.bucket_reason for row in failures), limit=30),
        "comparison": {
            "successes_with_address_label_pct": pct(sum(row.address_label is not None for row in successes), len(successes)),
            "failures_with_address_label_pct": pct(sum(row.address_label is not None for row in failures), len(failures)),
            "successes_with_street_hint_pct": pct(sum(row.street_hint is not None for row in successes), len(successes)),
            "failures_with_street_hint_pct": pct(sum(row.street_hint is not None for row in failures), len(failures)),
            "successes_missing_geo_query_confidence_pct": pct(
                sum(row.geo_query_confidence == "unknown" for row in successes),
                len(successes),
            ),
            "failures_missing_geo_query_confidence_pct": pct(
                sum(row.geo_query_confidence == "unknown" for row in failures),
                len(failures),
            ),
        },
    }


def street_analysis(
    rows: Sequence[ListingEligibility],
    street_rows: Sequence[ListingEligibility],
    street_no_real: Sequence[ListingEligibility],
    street_candidates: Sequence[ListingEligibility],
) -> dict[str, Any]:
    return {
        "street_hint_used_for_assignment_today": "no",
        "street_hint_current_consumers": [
            "domain.geocoding.geo_signals.recover_geo_signals reads metadata.street_hint into GeoSignalCandidate rows.",
            "domain.geocoding.microzones.extract_microzone_signals includes street_hint in text, but extracts only metro, known avenue, neighborhood, intersection, or known landmark.",
            "domain.geocoding.microzone_shadow.assign_shadow_microzone uses geographic_microzone_for first, then textual tokens from signals_from_value; it does not consume generic street candidates.",
            "scripts.geocode_listings can use street_hint as a geocoding query source, but that is a separate backfill/geocoding path and is not run by this audit.",
        ],
        "what_blocks_street_plus_comuna": [
            "Generic street candidates are not mapped into a microzone key.",
            "geo_500m requires lat/lon and eligible geocode_precision, so street text without coordinates cannot enter geo_500m.",
            "signals_from_value ignores raw_metadata.geo_signal_candidates and only uses geo_signals/flat microzone metadata or fresh extract_microzone_signals.",
            "extract_microzone_signals has no arbitrary street token output; it only keeps known avenues, metro, landmarks, sector and intersections.",
        ],
        "street_signal_rows": len(street_rows),
        "street_signal_no_real_microzone": len(street_no_real),
        "street_microzone_candidates": len(street_candidates),
        "street_candidates_by_source": counter_dict(Counter(row.best_signal_source or "unknown" for row in street_candidates)),
        "street_candidates_by_confidence": counter_dict(Counter(row.best_signal_confidence or "unknown" for row in street_candidates)),
        "street_no_real_by_blocker": counter_dict(Counter(row.current_street_blocker or "unknown" for row in street_no_real), limit=20),
        "safe_new_categories": {
            "street_microzone": "safe as a read-only textual-operational category when source is metadata_address/metadata_street_hint/detail_exact_address, confidence is medium/high, comuna exists, and the normalized street is non-generic.",
            "corridor_microzone": "safe for known avenue, metro, or intersection tokens; confidence should be medium by default and high only with repeated corroboration.",
            "confidence": {
                "street_microzone": "medium by default; high only for exact address/detail source or repeated same street+comuna evidence.",
                "corridor_microzone": "medium for avenue/metro/intersection; low for title-only sector.",
            },
        },
    }


def technical_proposal() -> dict[str, str]:
    return {
        "geo_500m": "lat/lon plus eligible address/street precision and acceptable query confidence.",
        "street_microzone": "street + comuna + strong textual source, no invented coordinates.",
        "corridor_microzone": "known avenue, metro, or intersection corridor, no invented coordinates.",
        "comuna_fallback": "explicit fallback only, not a real microzone.",
        "none": "no usable location signal.",
    }


def recommendation(
    rows: Sequence[ListingEligibility],
    geo_success: Sequence[ListingEligibility],
    street_candidates: Sequence[ListingEligibility],
) -> dict[str, Any]:
    geo_pct = pct(len(geo_success), len(rows))
    street_pct = pct(len(street_candidates), len(rows))
    if street_candidates:
        next_step = "B then A, with C targeted later"
        reason = (
            "Create a read-only street_microzone/corridor_microzone simulation first, because "
            f"street/corridor text can lift operational coverage beyond the current geo_500m {geo_pct}% without inventing coordinates."
        )
    else:
        next_step = "A then C"
        reason = "Improve street extraction first, then use targeted forward geocoding for listings still blocked by missing coordinates."
    return {
        "recommended_order": next_step,
        "why": reason,
        "observed_geo_500m_pct": geo_pct,
        "observed_street_microzone_candidate_pct": street_pct,
        "options": {
            "A_improve_street_extraction": "useful, but only after measuring candidate quality by source.",
            "B_create_street_or_corridor_microzone": "best next shadow-only step; do not wire to production yet.",
            "C_improve_forward_geocoding": "targeted later for high-value comunas and listings with strong street text.",
            "D_persist_assignments": "not yet.",
            "E_gradual_order": "B shadow simulation, A precision improvements, C targeted forward geocoding, D only after stability.",
        },
    }


def write_outputs(report: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "microzone_eligibility_audit_latest.json"
    md_path = output_dir / "microzone_eligibility_audit_latest.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(markdown_report(report), encoding="utf-8")


def markdown_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    geo = report["geo_500m_success_analysis"]
    street = report["street_analysis"]
    rec = report["recommendation"]
    lines = [
        "# Microzone Eligibility Audit",
        "",
        f"Generated at: `{report['generated_at']}`",
        "",
        "## Executive Summary",
        "",
        f"- Active listings: `{summary['active_listings']}`",
        f"- Geo 500m success: `{report['buckets']['geo_500m_success']['count']}` (`{report['buckets']['geo_500m_success']['pct']}%`)",
        f"- Has lat/lon but not geo 500m: `{report['buckets']['has_lat_lon_but_not_geo_500m']['count']}`",
        f"- Has street/corridor signal without lat/lon: `{report['buckets']['has_street_signal_no_lat_lon']['count']}`",
        f"- Street used only as reference: `{report['buckets']['street_used_only_as_reference']['count']}`",
        f"- Street microzone candidates: `{summary['street_microzone_candidates']}`",
        f"- Recommended order: `{rec['recommended_order']}`",
        "",
        "## Why Geo 500m Works",
        "",
        "Geo 500m works only when the listing has usable lat/lon and `geocode_precision` is not comuna, comuna_centroid, or unknown. The current geographic decision also checks query source/confidence before building the 500m grid id.",
        "",
        f"- Top comunas: `{geo['top_comunas']}`",
        f"- Geocode precision: `{geo['by_geocode_precision']}`",
        f"- Query source: `{geo['by_query_source']}`",
        f"- Query confidence: `{geo['by_query_confidence']}`",
        f"- Main failure reasons with lat/lon: `{geo['failure_reason_counts']}`",
        "",
        "## Buckets",
        "",
        "| Bucket | Count | % |",
        "| --- | ---: | ---: |",
    ]
    for bucket, data in report["buckets"].items():
        lines.append(f"| `{bucket}` | {data['count']} | {data['pct']} |")
    lines.extend(
        [
            "",
            "## Street Finding",
            "",
            f"- street_hint used for assignment today: `{street['street_hint_used_for_assignment_today']}`",
            f"- Street signal rows: `{street['street_signal_rows']}`",
            f"- Street signal without real microzone: `{street['street_signal_no_real_microzone']}`",
            f"- Street microzone candidates: `{street['street_microzone_candidates']}`",
            f"- Street blockers: `{street['street_no_real_by_blocker']}`",
            "",
            "Current consumers:",
        ]
    )
    for item in street["street_hint_current_consumers"]:
        lines.append(f"- {item}")
    lines.extend(["", "What blocks street + comuna:"])
    for item in street["what_blocks_street_plus_comuna"]:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## Apartment Metrics",
            "",
            f"- Active apartments: `{report['apartment_metrics']['total']}`",
            f"- Apartment buckets: `{report['apartment_metrics']['by_bucket']}`",
            f"- Apartment street microzone candidates: `{report['apartment_metrics']['street_microzone_candidates']}`",
            "",
            "## Critical Apartment Comunas",
            "",
            "| Comuna | Apartments | Geo 500m | Street Candidates | Street No Real | Comuna Fallback |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in report["critical_apartment_comunas"]:
        lines.append(
            f"| `{row['comuna']}` | {row['active_apartments']} | {row['geo_500m_success']} | "
            f"{row['street_microzone_candidates']} | {row['street_signal_no_real_microzone']} | "
            f"{row['comuna_fallback_only']} |"
        )
    lines.extend(
        [
            "",
            "## Proposal Not Implemented",
            "",
        ]
    )
    for key, value in report["technical_proposal_not_implemented"].items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            rec["why"],
            "",
            "## What Not To Do Yet",
            "",
        ]
    )
    for item in report["do_not_do_yet"]:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## Example Rows",
            "",
            "See JSON `sample_rows` for concrete examples by bucket.",
            "",
            "## Productive Safety",
            "",
            "This audit is read-only. It does not write DB rows, create migrations, touch Radar, touch AVM, touch frontend, run scrapers, or call external geocoding.",
            "",
        ]
    )
    return "\n".join(lines)


def _best_signal(candidates: Sequence[GeoSignalCandidate]) -> GeoSignalCandidate | None:
    if not candidates:
        return None
    score_by_confidence = {"high": 3, "medium": 2, "low": 1}
    score_by_type = {"street": 5, "intersection": 4, "metro": 3, "avenue": 3, "sector": 2, "barrio": 2}
    return max(
        candidates,
        key=lambda item: (
            score_by_confidence.get(item.confidence, 0),
            score_by_type.get(item.signal_type, 0),
            item.source,
        ),
    )


def _street_microzone_candidate(listing: Listing, candidates: Sequence[GeoSignalCandidate]) -> bool:
    if not _has_comuna(listing):
        return False
    return any(
        candidate.signal_type == "street"
        and candidate.source in STRONG_STREET_SOURCES
        and candidate.confidence in STRONG_STREET_CONFIDENCES
        for candidate in candidates
    )


def _street_blocker(
    shadow: ShadowMicrozoneAssignment,
    *,
    has_street_reference: bool,
    has_street_signal: bool,
    street_candidate: bool,
) -> str | None:
    if not has_street_reference:
        return None
    if shadow.microzone_kind == "geo_500m":
        return "street_present_but_geo_500m_takes_precedence"
    if shadow.microzone_kind == "textual":
        return "street_present_but_current_textual_assignment_uses_corridor_or_landmark"
    if not has_street_signal:
        return "street_hint_present_but_not_extracted_as_street"
    if street_candidate:
        return "generic_street_not_mapped_to_operational_microzone"
    return "street_signal_too_weak_or_from_low_confidence_source"


def _geo_success_reason(decision: GeographicMicrozoneDecision) -> str:
    return f"eligible_coordinates:{decision.precision}:{decision.query_source}:{decision.query_confidence}"


def _geo_failure_reason(decision: GeographicMicrozoneDecision) -> str:
    if decision.reason.startswith("excluded_precision:"):
        return decision.reason
    if decision.reason == "no_coordinates":
        return "lat_lon_invalid_or_partial"
    return decision.reason


def _signal_reason(candidates: Sequence[GeoSignalCandidate], has_textual_microzone_signal: bool) -> str:
    signal_types = sorted({candidate.signal_type for candidate in candidates})
    if signal_types:
        return f"text_signal:{','.join(signal_types)}"
    if has_textual_microzone_signal:
        return "textual_microzone_signal_from_microzones"
    return "text_signal:unknown"


def _has_corridor_signal(candidates: Sequence[GeoSignalCandidate], signals: MicrozoneSignals) -> bool:
    if any(candidate.signal_type in {"avenue", "metro", "intersection"} for candidate in candidates):
        return True
    return bool(signals.nearby_avenue or signals.nearby_metro or signals.intersection_hint)


def _has_textual_microzone_signal(signals: MicrozoneSignals) -> bool:
    return bool(
        signals.nearby_metro
        or signals.nearby_avenue
        or signals.intersection_hint
        or signals.landmark_tokens
        or (signals.neighborhood_hint and signals.confidence >= 0.55)
    )


def breakdown(rows: Sequence[ListingEligibility], field: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[ListingEligibility]] = defaultdict(list)
    for row in rows:
        grouped[str(getattr(row, field) or "unknown")].append(row)
    result = []
    for value, group in grouped.items():
        result.append(
            {
                "value": value,
                "active": len(group),
                "bucket_counts": counter_dict(Counter(item.bucket for item in group)),
                "street_microzone_candidates": sum(item.street_microzone_candidate for item in group),
                "geo_500m_success_pct": pct(sum(item.bucket == "geo_500m_success" for item in group), len(group)),
            }
        )
    return sorted(result, key=lambda row: (-row["active"], row["value"]))


def row_dict(row: ListingEligibility) -> dict[str, Any]:
    payload = asdict(row)
    payload["raw_metadata_keys"] = list(row.raw_metadata_keys)
    payload["signal_types"] = list(row.signal_types)
    return payload


def counter_dict(counter: Counter[str], *, limit: int | None = None) -> dict[str, int]:
    return dict(counter.most_common(limit))


def pct(numerator: int | float, denominator: int | float) -> float:
    return round(float(numerator) / float(denominator) * 100, 2) if denominator else 0.0


def _real_microzone(row: ListingEligibility) -> bool:
    return row.shadow_kind in {"geo_500m", "textual"}


def _has_street_reference(row: ListingEligibility) -> bool:
    return row.has_street_signal or row.street_hint is not None


def _geo_value(listing: Listing, *, lat: float | None, lon: float | None) -> dict[str, Any]:
    return {
        "lat": lat,
        "lon": lon,
        "comuna": listing.comuna,
        "geocode_precision": listing.geocode_precision,
        "raw_metadata": _raw_metadata(listing),
    }


def _lat_lon(listing: Listing) -> tuple[float | None, float | None]:
    if listing.coordinates is None:
        return None, None
    return listing.coordinates.lat, listing.coordinates.lon


def _raw_metadata(listing: Listing) -> dict[str, Any]:
    return listing.raw_metadata if isinstance(listing.raw_metadata, dict) else {}


def _metadata_str(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _has_comuna(listing: Listing) -> bool:
    return bool(str(listing.comuna or "").strip())


def _normalize_comuna(value: str | None) -> str:
    return str(value or "").replace("_", " ").strip().lower()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
