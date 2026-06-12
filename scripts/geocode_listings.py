"""Conservative geocoding dry-run/apply script for AVM listings.

Dry-run is the default. It may call Nominatim with cache and rate limiting so
we can estimate match quality, but it never writes to the database.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote, urlparse

import httpx
from redis.asyncio import Redis
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import get_settings  # noqa: E402
from config.comunas import get_coordinates, normalize_comuna  # noqa: E402
from core.normalization.geocode_precision import (  # noqa: E402
    canonical_geocode_precision,
    geocode_precision_rank,
)
from core.value_objects.location import Coordinates  # noqa: E402
from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.models import ListingORM  # noqa: E402
from infrastructure.external.nominatim_client import (  # noqa: E402
    GeocodingResult,
    NominatimClient,
    build_nominatim_query,
)

_log = logging.getLogger(__name__)
DEFAULT_REPORT_DIR = Path("reports/geocoding")
GEOCODE_BACKFILL_VERSION = "geocode_backfill_v1"
REPEATED_COORDINATE_BLOCK_THRESHOLD = 5

GeocodePrecision = Literal["address", "street", "street_address", "street_name", "landmark_or_sector", "comuna_centroid", "unknown"]
GeocodeQuerySource = Literal[
    "metadata_address",
    "metadata_street_hint",
    "metadata_location_text",
    "geo_signal_candidate",
    "title_inferred_street",
    "url_inferred",
    "comuna_fallback",
]
GeocodeQueryConfidence = Literal["high", "medium", "low"]

_UNKNOWN_COMUNAS = {"", "unknown", "desconocida", "sin comuna", "marte", "region metropolitana"}
_METADATA_LOCATION_KEYS = ("address", "address_label", "street_hint", "location_text", "location")
_DESCRIPTION_KEYS = ("description", "descripcion", "details", "body", "summary")
_URL_STOP_WORDS = {
    "departamento",
    "venta",
    "propiedades",
    "apartamentos",
    "bienes",
    "raices",
    "de",
    "en",
}
_STREET_MARKERS = r"calle|av\.?|avenida|pasaje|camino|diagonal"
_WORD_CHARS = r"A-Za-zÁÉÍÓÚÑáéíóúñ"
_TITLE_STOP_WORDS = {
    "en",
    "venta",
    "vende",
    "departamento",
    "depto",
    "dpto",
    "oportunidad",
    "comuna",
    "dormitorio",
    "dorm",
    "bano",
    "banio",
    "estacionamiento",
    "bodega",
    "uf",
    "hogar",
    "subsidio",
    "propio",
    "para",
    "vivir",
    "invertir",
    "presidente",
    "casa",
    "casas",
    "piscina",
    "jardin",
    "jardín",
    "gran",
    "excelente",
    "ubicacion",
    "ubicación",
    "oferta",
    "especial",
    "propiedad",
    "acceso",
    "independiente",
    "estado",
    "conservacion",
    "conservación",
    "conser",
    "amplia",
    "amplio",
    "tranquilo",
    "tranquila",
    "sector",
}
_MARKETING_HINT_PATTERNS = (
    re.compile(r"\b(casa|casas)\s+y\s+(piscina|jardin|jardín)\b", re.IGNORECASE),
    re.compile(r"\b(dos|2)\s+casas\b", re.IGNORECASE),
    re.compile(r"\b(gran\s+)?oportunidad\b", re.IGNORECASE),
    re.compile(r"\bsector\s+(tranquilo|tranquila|residencial|consolidado)\b", re.IGNORECASE),
)
_GENERIC_NOMINATIM_TYPES = {
    "administrative",
    "borough",
    "city",
    "city_district",
    "county",
    "municipality",
    "neighbourhood",
    "postcode",
    "region",
    "state",
    "suburb",
    "town",
    "village",
}
_ADDRESS_RESULT_TYPES = {"house", "building", "apartments", "residential"}
_STREET_RESULT_TYPES = {"road", "residential", "tertiary", "secondary", "primary", "unclassified", "service"}
_AUTO_APPLY_STREET_RESULT_TYPES = _STREET_RESULT_TYPES | {"pedestrian", "living_street", "trunk", "motorway"}
_MAX_COMUNA_DISTANCE_KM = 15.0
_AMBIGUOUS_REJECTION_REASONS = {
    "weak_requested_precision",
    "generic_nominatim_result",
    "centroid_like_result",
}
_ADDRESS_NUMBER_PATTERNS = (
    re.compile(rf"\b({_STREET_MARKERS})\s+([^,;|/\\]{{2,60}}?)\s+(\d{{1,5}})\b", re.IGNORECASE),
    re.compile(rf"\b([{_WORD_CHARS}]+(?:\s+[{_WORD_CHARS}]+){{0,4}})\s+(\d{{2,5}})\b", re.IGNORECASE),
)
_EXPLICIT_STREET_PATTERN = re.compile(rf"\b({_STREET_MARKERS})\s+([^,;|/\\-]{{2,60}})", re.IGNORECASE)
_METRO_PATTERN = re.compile(
    rf"\b(?:a\s+pasos\s+de\s+|cerca\s+de\s+|sector\s+)?metro\s+([{_WORD_CHARS} ]{{2,45}})",
    re.IGNORECASE,
)
_INTERSECTION_PATTERNS = (
    re.compile(rf"\b([{_WORD_CHARS}. ]{{3,45}})\s*/\s*([{_WORD_CHARS}. ]{{3,45}})\b", re.IGNORECASE),
    re.compile(rf"\b([{_WORD_CHARS}. ]{{3,45}})\s+(?:con|esquina)\s+([{_WORD_CHARS}. ]{{3,45}})\b", re.IGNORECASE),
)
_DEPARTMENT_IN_STREET_PATTERN = re.compile(
    rf"\bdepartamento\s+en\s+(?!venta\b)([{_WORD_CHARS}' ]{{3,45}})",
    re.IGNORECASE,
)
_KNOWN_STREET_SNIPPETS = (
    "Antonio Varas",
    "Fray Camilo Henriquez",
    "Blest Gana",
    "Lord Cochrane",
    "Portugal",
    "Santa Isabel",
    "Vicuna Mackenna",
    "Pedro de Valdivia",
    "Irarrazaval",
    "Berlin",
)


@dataclass
class GeocodingAttempt:
    listing_id: int
    title: str
    comuna: str
    query: str | None
    proposed_precision: GeocodePrecision
    action: str
    reason: str
    lat: float | None = None
    lon: float | None = None
    current_lat: float | None = None
    current_lon: float | None = None
    current_precision: str | None = None
    query_source: GeocodeQuerySource | None = None
    query_confidence: GeocodeQueryConfidence | None = None
    query_rule: str | None = None
    geocode_signal_type: str | None = None
    geocode_signal_source: str | None = None


@dataclass(frozen=True)
class AddressCandidate:
    text: str | None
    precision: GeocodePrecision
    source: str
    reason: str
    query_source: GeocodeQuerySource
    query_confidence: GeocodeQueryConfidence
    query_rule: str
    geocode_signal_type: str | None = None
    geocode_signal_source: str | None = None


@dataclass(frozen=True)
class CleanedGeoHint:
    cleaned_value: str | None
    is_usable: bool
    confidence: GeocodeQueryConfidence
    reason: str
    detected_signal_type: str | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class TextGeocodingHint:
    text: str | None
    precision: GeocodePrecision
    rule: str


@dataclass(frozen=True)
class GeocodingQueryPlan:
    query: str | None
    precision: GeocodePrecision
    query_source: GeocodeQuerySource
    query_confidence: GeocodeQueryConfidence
    query_rule: str
    geocode_signal_type: str | None = None
    geocode_signal_source: str | None = None

    def with_precision(self, precision: GeocodePrecision) -> GeocodingQueryPlan:
        return GeocodingQueryPlan(
            query=self.query,
            precision=precision,
            query_source=self.query_source,
            query_confidence=self.query_confidence,
            query_rule=self.query_rule,
            geocode_signal_type=self.geocode_signal_type,
            geocode_signal_source=self.geocode_signal_source,
        )


@dataclass(frozen=True)
class ValidatedGeocode:
    coordinates: Coordinates
    precision: Literal["address", "street"]
    confidence: float
    reason: str
    raw_type: str | None
    raw_class: str | None
    display_name: str | None


@dataclass
class BackfillStats:
    total_candidates: int = 0
    geocoded: int = 0
    would_geocode: int = 0
    skipped: int = 0
    skipped_existing_coordinates: int = 0
    skipped_weak_query: int = 0
    rejected_by_guardrails: int = 0
    ambiguous: int = 0
    no_sufficient_query: int = 0
    not_found: int = 0
    repeated_coordinates: int = 0
    failed: int = 0
    cache_hits: int = 0
    external_requests: int = 0
    dry_run: bool = True
    precision_counts: Counter[str] = field(default_factory=Counter)
    assigned_precision_counts: Counter[str] = field(default_factory=Counter)
    rejection_reasons: Counter[str] = field(default_factory=Counter)
    query_source_counts: Counter[str] = field(default_factory=Counter)
    query_confidence_counts: Counter[str] = field(default_factory=Counter)
    geocode_signal_type_counts: Counter[str] = field(default_factory=Counter)
    geocode_signal_source_counts: Counter[str] = field(default_factory=Counter)
    legacy_hint_accepted: int = 0
    legacy_hint_rejected: int = 0
    legacy_hint_rejection_reasons: Counter[str] = field(default_factory=Counter)
    legacy_hint_signal_type_counts: Counter[str] = field(default_factory=Counter)
    legacy_hint_cleaned_examples: list[dict[str, str]] = field(default_factory=list)
    title_inferred_blocked: int = 0
    by_comuna: Counter[str] = field(default_factory=Counter)
    examples: list[GeocodingAttempt] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.failed > 0 and self.geocoded == 0 and self.would_geocode == 0:
            return "warning"
        return "ok"


async def run_backfill(
    *,
    dry_run: bool = True,
    apply: bool = False,
    limit: int | None = None,
    sleep_seconds: float = 1.0,
    only_active: bool = False,
    only_missing_coordinates: bool = False,
    comuna: str | None = None,
    property_type: str | None = None,
    no_external: bool = False,
    overwrite: bool = False,
    allow_title_inferred: bool = False,
    examples_limit: int = 12,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> BackfillStats:
    settings = get_settings()
    stats = BackfillStats(dry_run=dry_run)
    factory = session_factory or get_session_factory()
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    async with httpx.AsyncClient() as http_client:
        geocoder = NominatimClient(
            api_url=settings.nominatim_url,
            http_client=http_client,
            redis=redis,
            user_agent=settings.nominatim_user_agent,
        )
        try:
            async with factory() as session:
                candidates = await load_candidates(
                    session,
                    limit=limit,
                    only_active=only_active,
                    only_missing_coordinates=only_missing_coordinates,
                    comuna=comuna,
                    property_type=property_type,
                )
                stats.total_candidates = len(candidates)
                for listing in candidates:
                    await _process_listing(
                        session,
                        geocoder,
                        listing,
                        stats,
                        dry_run=dry_run,
                        apply=apply,
                        sleep_seconds=sleep_seconds,
                        no_external=no_external,
                        overwrite=overwrite,
                        allow_title_inferred=allow_title_inferred,
                        examples_limit=examples_limit,
                    )
                if apply:
                    await session.commit()
                else:
                    await session.rollback()
        except SQLAlchemyError:
            _log.exception("Could not complete geocoding backfill.")
            raise
        finally:
            await redis.aclose()
    stats.cache_hits = geocoder.cache_hits
    stats.external_requests = geocoder.external_requests
    return stats


async def load_candidates(
    session: AsyncSession,
    *,
    limit: int | None,
    only_active: bool = False,
    only_missing_coordinates: bool = False,
    comuna: str | None = None,
    property_type: str | None = None,
) -> list[ListingORM]:
    conditions = []
    if property_type:
        conditions.append(ListingORM.property_type == property_type)
    if only_active:
        conditions.append(ListingORM.status == "active")
    if only_missing_coordinates:
        conditions.append(or_(ListingORM.lat.is_(None), ListingORM.lon.is_(None)))
    else:
        conditions.append(
            or_(
                and_(ListingORM.lat.is_(None), ListingORM.lon.is_(None)),
                and_(
                    ListingORM.lat.is_not(None),
                    ListingORM.lon.is_not(None),
                    ListingORM.geocode_precision.is_(None),
                ),
            )
        )
    if comuna:
        conditions.append(ListingORM.comuna == comuna)

    stmt = select(ListingORM).where(*conditions).order_by(
        case((ListingORM.status == "active", 0), else_=1),
        ListingORM.id,
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _process_listing(
    session: AsyncSession,
    geocoder: NominatimClient,
    listing: ListingORM,
    stats: BackfillStats,
    *,
    dry_run: bool,
    apply: bool,
    sleep_seconds: float,
    no_external: bool,
    overwrite: bool = False,
    allow_title_inferred: bool = False,
    examples_limit: int = 12,
) -> None:
    stats.by_comuna[listing.comuna or "unknown"] += 1
    before_lat = getattr(listing, "lat", None)
    before_lon = getattr(listing, "lon", None)
    before_precision = canonical_geocode_precision(getattr(listing, "geocode_precision", None))
    if should_skip_comuna(listing.comuna):
        stats.skipped += 1
        stats.no_sufficient_query += 1
        stats.rejection_reasons["unknown_comuna"] += 1
        _record_example(
            stats,
            listing,
            GeocodingQueryPlan(None, "unknown", "comuna_fallback", "low", "unknown_comuna"),
            "skipped",
            "unknown_comuna",
            examples_limit,
        )
        return

    _record_legacy_hint_cleaning_stats(stats, listing)
    plan = build_geocoding_query_plan(listing)
    query = plan.query
    precision = plan.precision
    stats.precision_counts[precision] += 1
    stats.query_source_counts[plan.query_source] += 1
    stats.query_confidence_counts[plan.query_confidence] += 1
    if plan.geocode_signal_type:
        stats.geocode_signal_type_counts[plan.geocode_signal_type] += 1
    if plan.geocode_signal_source:
        stats.geocode_signal_source_counts[plan.geocode_signal_source] += 1
    if not query:
        stats.skipped += 1
        stats.no_sufficient_query += 1
        stats.rejection_reasons["no_usable_location_signal"] += 1
        _record_example(stats, listing, plan, "skipped", "no_usable_location_signal", examples_limit)
        return

    has_existing_coordinates = listing.lat is not None or listing.lon is not None
    if has_existing_coordinates and not overwrite:
        stats.skipped += 1
        stats.skipped_existing_coordinates += 1
        stats.rejection_reasons["existing_coordinates_not_overwritten"] += 1
        _record_example(stats, listing, plan, "skipped", "existing_coordinates_not_overwritten", examples_limit)
        return

    if is_weak_geocoding_query(query=query, precision=precision, comuna=listing.comuna):
        stats.skipped += 1
        stats.skipped_weak_query += 1
        stats.no_sufficient_query += 1
        stats.rejection_reasons["skipped_weak_query"] += 1
        _record_example(stats, listing, plan, "skipped", "skipped_weak_query", examples_limit)
        return

    if apply and plan.query_source == "title_inferred_street" and not allow_title_inferred:
        stats.skipped += 1
        stats.title_inferred_blocked += 1
        stats.rejection_reasons["title_inferred_requires_explicit_flag"] += 1
        _record_example(stats, listing, plan, "blocked", "title_inferred_requires_explicit_flag", examples_limit)
        return

    _log.info("geocode listing_id=%s query=%r precision=%s dry_run=%s", listing.id, query, precision, dry_run)
    if no_external:
        stats.would_geocode += 1
        _record_example(stats, listing, plan, "would_geocode", "no_external_preview", examples_limit)
        return

    geocode_result = await _geocode_with_metadata(geocoder, query, _format_comuna_for_query(listing.comuna))
    if geocoder.last_cache_hit:
        stats.cache_hits += 1
    validated = validate_geocoding_result(
        geocode_result,
        requested_precision=precision,
        expected_comuna=listing.comuna,
    )
    if geocode_result is None:
        stats.failed += 1
        stats.not_found += 1
        stats.rejection_reasons["geocoder_returned_no_coordinates"] += 1
        _record_example(stats, listing, plan, "not_found", "geocoder_returned_no_coordinates", examples_limit)
    elif validated is None:
        reason = geocoding_rejection_reason(
            geocode_result,
            requested_precision=precision,
            expected_comuna=listing.comuna,
        ) or "geocoder_result_failed_validation"
        _record_guardrail_rejection(stats, reason)
        _record_example(stats, listing, plan, "rejected", reason, examples_limit, lat=geocode_result.coordinates.lat, lon=geocode_result.coordinates.lon)
    elif has_existing_coordinates and not _can_overwrite_existing_geocode(listing, validated):
        stats.skipped += 1
        stats.skipped_existing_coordinates += 1
        stats.rejection_reasons["existing_precision_better"] += 1
        _record_example(
            stats,
            listing,
            plan.with_precision(validated.precision),
            "skipped",
            "existing_precision_better",
            examples_limit,
            lat=validated.coordinates.lat,
            lon=validated.coordinates.lon,
            current_lat=before_lat,
            current_lon=before_lon,
            current_precision=before_precision,
        )
    elif await _has_suspicious_repeated_coordinates(session, listing, validated.coordinates):
        _record_guardrail_rejection(stats, "repeated_coordinates")
        stats.repeated_coordinates += 1
        _record_example(
            stats,
            listing,
            plan.with_precision(validated.precision),
            "rejected",
            "repeated_coordinates",
            examples_limit,
            lat=validated.coordinates.lat,
            lon=validated.coordinates.lon,
            current_lat=before_lat,
            current_lon=before_lon,
            current_precision=before_precision,
        )
    elif dry_run:
        stats.would_geocode += 1
        stats.assigned_precision_counts[validated.precision] += 1
        _record_example(
            stats,
            listing,
            plan.with_precision(validated.precision),
            "would_apply",
            validated.reason,
            examples_limit,
            lat=validated.coordinates.lat,
            lon=validated.coordinates.lon,
        )
    elif apply:
        listing.lat = validated.coordinates.lat
        listing.lon = validated.coordinates.lon
        listing.geocode_precision = validated.precision
        listing.raw_metadata = _metadata_with_geocode_provenance(
            listing.raw_metadata,
            plan=plan,
            validated=validated,
        )
        session.add(listing)
        stats.geocoded += 1
        stats.assigned_precision_counts[validated.precision] += 1
        _record_example(
            stats,
            listing,
            plan.with_precision(validated.precision),
            "applied",
            validated.reason,
            examples_limit,
            lat=validated.coordinates.lat,
            lon=validated.coordinates.lon,
        )

    if not geocoder.last_cache_hit and sleep_seconds > 0:
        await asyncio.sleep(sleep_seconds)


def build_geocoding_query(listing: ListingORM) -> tuple[str | None, GeocodePrecision]:
    plan = build_geocoding_query_plan(listing)
    return plan.query, plan.precision


def build_geocoding_query_plan(listing: ListingORM) -> GeocodingQueryPlan:
    comuna = getattr(listing, "comuna", None)
    if should_skip_comuna(comuna):
        return GeocodingQueryPlan(
            query=None,
            precision="unknown",
            query_source="comuna_fallback",
            query_confidence="low",
            query_rule="unknown_comuna",
        )

    comuna_query = _format_comuna_for_query(comuna)
    title = getattr(listing, "title", "") or ""
    url = getattr(listing, "url", "") or ""
    raw_metadata = getattr(listing, "raw_metadata", None)
    description = _description_from_metadata(raw_metadata)
    candidate = extract_address_candidate(
        title=title,
        description=description,
        url=url,
        comuna=comuna,
        raw_metadata=raw_metadata,
    )
    if candidate.text:
        return GeocodingQueryPlan(
            query=build_nominatim_query(candidate.text, comuna_query),
            precision=candidate.precision,
            query_source=candidate.query_source,
            query_confidence=candidate.query_confidence,
            query_rule=candidate.query_rule,
            geocode_signal_type=candidate.geocode_signal_type,
            geocode_signal_source=candidate.geocode_signal_source,
        )
    return GeocodingQueryPlan(
        query=f"{comuna_query}, Santiago, Chile",
        precision="comuna_centroid",
        query_source="comuna_fallback",
        query_confidence="low",
        query_rule="comuna_fallback",
    )


async def _geocode_with_metadata(
    geocoder: Any,
    query: str,
    comuna: str,
) -> GeocodingResult | None:
    if hasattr(geocoder, "geocode_with_metadata"):
        return await geocoder.geocode_with_metadata(query, comuna)
    coords = await geocoder.geocode(query, comuna)
    if coords is None:
        return None
    return GeocodingResult(coordinates=coords, query=query, provider="test")


def validate_geocoding_result(
    result: GeocodingResult | None,
    *,
    requested_precision: GeocodePrecision,
    expected_comuna: str | None,
) -> ValidatedGeocode | None:
    if geocoding_rejection_reason(
        result,
        requested_precision=requested_precision,
        expected_comuna=expected_comuna,
    ):
        return None

    expected_centroid = get_coordinates(expected_comuna or "")
    distance_to_expected = None
    if expected_centroid is not None:
        distance_to_expected = result.coordinates.distance_km(Coordinates(*expected_centroid))
        if distance_to_expected > _MAX_COMUNA_DISTANCE_KM:
            return None
        if distance_to_expected < 0.25 and _looks_like_centroid_result(result):
            return None

    if _has_conflicting_comuna(result, expected_comuna):
        return None

    raw_type = _normalized_raw_type(result)
    has_house_number = bool((result.address or {}).get("house_number"))
    is_address = (
        requested_precision == "street_address"
        and (has_house_number or raw_type in _ADDRESS_RESULT_TYPES)
        and (not result.from_cache or result.raw_type is not None or bool(result.address))
    )
    precision: Literal["address", "street"] = "address" if is_address else "street"

    confidence = 0.65 if precision == "street" else 0.85
    reasons = [precision]
    if result.from_cache:
        confidence -= 0.08
        reasons.append("cached_without_full_validation" if result.raw_type is None else "cached")
    if distance_to_expected is not None:
        confidence += 0.08
        reasons.append("near_expected_comuna")
    if raw_type:
        reasons.append(f"raw_type:{raw_type}")
    return ValidatedGeocode(
        coordinates=result.coordinates,
        precision=precision,
        confidence=round(max(0.0, min(1.0, confidence)), 3),
        reason=";".join(reasons),
        raw_type=result.raw_type or result.raw_addresstype,
        raw_class=result.raw_class,
        display_name=result.display_name,
    )


def geocoding_rejection_reason(
    result: GeocodingResult | None,
    *,
    requested_precision: GeocodePrecision,
    expected_comuna: str | None,
) -> str | None:
    if result is None:
        return "geocoder_returned_no_coordinates"
    if requested_precision in {"unknown", "comuna_centroid", "landmark_or_sector"}:
        return "weak_requested_precision"
    if _is_result_outside_chile(result):
        return "outside_chile"
    if _is_generic_nominatim_result(result):
        return "generic_nominatim_result"
    if requested_precision == "street_name" and _has_unsupported_street_raw_type(result):
        return "unsupported_street_raw_type"

    expected_centroid = get_coordinates(expected_comuna or "")
    if expected_centroid is not None:
        distance_to_expected = result.coordinates.distance_km(Coordinates(*expected_centroid))
        if distance_to_expected > _MAX_COMUNA_DISTANCE_KM:
            return "too_far_from_expected_comuna"
        if distance_to_expected < 0.25 and _looks_like_centroid_result(result):
            return "centroid_like_result"

    if _has_conflicting_comuna(result, expected_comuna):
        return "conflicting_comuna"
    return None


def select_location_text(
    *,
    title: str,
    description: str = "",
    comuna: str,
    raw_metadata: dict[str, Any] | None,
) -> tuple[str | None, GeocodePrecision]:
    candidate = extract_address_candidate(title=title, description=description, url="", comuna=comuna, raw_metadata=raw_metadata)
    return candidate.text, candidate.precision


def extract_address_candidate(
    *,
    title: str,
    description: str = "",
    url: str = "",
    comuna: str,
    raw_metadata: dict[str, Any] | None,
) -> AddressCandidate:
    metadata = raw_metadata or {}
    for key in _METADATA_LOCATION_KEYS:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            cleaned = clean_legacy_geo_hint(value, key=key, comuna=comuna)
            if not cleaned.is_usable or not cleaned.cleaned_value:
                continue
            return AddressCandidate(
                text=cleaned.cleaned_value,
                precision=_legacy_signal_precision(cleaned),
                source=f"raw_metadata.{key}",
                reason="metadata_location_hint",
                query_source=_metadata_query_source(key),
                query_confidence=cleaned.confidence,
                query_rule=f"raw_metadata.{key}",
                geocode_signal_type=cleaned.detected_signal_type,
                geocode_signal_source=f"raw_metadata.{key}",
            )

    candidate = _candidate_from_geo_signal_candidates(metadata, comuna=comuna)
    if candidate is not None:
        return candidate

    hint = extract_geocoding_hint_details(title, description, comuna)
    if hint.text:
        return AddressCandidate(
            text=normalize_street_name(hint.text),
            precision=hint.precision,
            source="title_description",
            reason="text_location_hint",
            query_source="title_inferred_street",
            query_confidence="low",
            query_rule=hint.rule,
        )

    url_hint, url_precision = extract_url_address_hint(url, comuna)
    if url_hint:
        return AddressCandidate(
            text=normalize_street_name(url_hint),
            precision=url_precision,
            source="url",
            reason="url_slug_location_hint",
            query_source="url_inferred",
            query_confidence="low",
            query_rule="url.slug_location_hint",
        )

    return AddressCandidate(
        text=None,
        precision="unknown",
        source="none",
        reason="no_usable_location_signal",
        query_source="comuna_fallback",
        query_confidence="low",
        query_rule="no_usable_location_signal",
    )


def _candidate_from_geo_signal_candidates(metadata: dict[str, Any], *, comuna: str) -> AddressCandidate | None:
    candidates = metadata.get("geo_signal_candidates")
    if not isinstance(candidates, list):
        return None
    for item in sorted(
        (item for item in candidates if isinstance(item, dict)),
        key=_geo_signal_candidate_priority,
    ):
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "")
        confidence = str(item.get("confidence") or "")
        signal_type = str(item.get("signal_type") or "")
        if source in {"title", "url_slug"} or confidence == "low":
            continue
        if signal_type not in {
            "address",
            "street",
            "avenue",
            "intersection",
            "metro",
            "plaza",
            "parque",
            "mall",
            "barrio",
            "sector",
        }:
            continue
        value = item.get("value")
        if not isinstance(value, str) or not value.strip():
            continue
        location_text = normalize_street_name(value)
        if source in {"metadata_address", "metadata_street_hint"}:
            cleaned = clean_legacy_geo_hint(location_text, key=source, comuna=comuna)
            if not cleaned.is_usable or not cleaned.cleaned_value:
                continue
            location_text = cleaned.cleaned_value
            signal_type = cleaned.detected_signal_type or signal_type
            confidence = cleaned.confidence
        if not _is_usable_geo_signal_candidate(location_text, signal_type=signal_type, comuna=comuna):
            continue
        return AddressCandidate(
            text=location_text,
            precision=_geo_signal_precision(location_text, signal_type=signal_type),
            source=f"geo_signal_candidates.{source}",
            reason="geo_signal_candidate",
            query_source="geo_signal_candidate",
            query_confidence="high" if confidence == "high" else "medium",
            query_rule=f"geo_signal_candidates.{item.get('rule') or signal_type}",
            geocode_signal_type=signal_type,
            geocode_signal_source=source,
        )
    return None


def _geo_signal_candidate_priority(item: dict[str, Any]) -> tuple[int, int]:
    confidence_rank = {"high": 0, "medium": 1}.get(str(item.get("confidence") or ""), 9)
    signal_rank = {
        "address": 0,
        "street": 1,
        "avenue": 2,
        "intersection": 3,
        "metro": 4,
        "plaza": 5,
        "parque": 6,
        "mall": 7,
        "barrio": 8,
        "sector": 9,
    }.get(str(item.get("signal_type") or ""), 99)
    return confidence_rank, signal_rank


def _is_usable_geo_signal_candidate(value: str, *, signal_type: str, comuna: str | None) -> bool:
    if signal_type in {"metro", "plaza", "parque", "mall", "barrio", "sector"}:
        normalized = _normalize_text(value)
        if not normalized or normalized in {"metro", "plaza", "parque", "mall", "barrio", "sector"}:
            return False
        if comuna and normalized == _normalize_text(_format_comuna_for_query(comuna)):
            return False
        if any(pattern.search(value) for pattern in _MARKETING_HINT_PATTERNS):
            return False
        return True
    return _is_usable_location_candidate(value, comuna=comuna)


def _geo_signal_precision(value: str, *, signal_type: str) -> GeocodePrecision:
    if signal_type == "address":
        return classify_location_text(value)
    if signal_type in {"street", "avenue", "intersection"}:
        return "street_address" if _contains_street_number(value) else "street_name"
    return "landmark_or_sector"


_LEGACY_SUFFIX_PATTERN = re.compile(
    r"\b(?:caracteristicas|característica|características|detalles?|descripci[oó]n|descripcion|"
    r"ver\s+m[aá]s|publicado|precio|superficie|dormitorios?|baños?|banos?|estacionamientos?|"
    r"bodega|gastos\s+comunes)\b",
    re.IGNORECASE,
)
_LEGACY_MARKETING_PATTERN = re.compile(
    r"\b(?:lindo|linda|amplio|amplia|oportunidad|exclusivo|exclusiva|gran\s+espacio|"
    r"vista|vistas|remodelado|remodelada|moderno|moderna|excelente|penthouse|"
    r"luminoso|luminosa|maravilloso|maravillosa|seguro|segura|equipado|equipada)\b",
    re.IGNORECASE,
)
_LEGACY_WEAK_STREET_PATTERNS = (
    re.compile(r"\bcalle\s+interior\s+de\s+barrio\b", re.IGNORECASE),
    re.compile(r"\bcalle\s+residencial\b", re.IGNORECASE),
)
_LEGACY_METRO_PATTERN = re.compile(r"\b(?:metro|estaci[oó]n)\s+([A-Za-zÁÉÍÓÚÑáéíóúñ0-9 .'-]{2,50})", re.IGNORECASE)
_LEGACY_INTERSECTION_PATTERNS = (
    re.compile(r"\b([A-Za-zÁÉÍÓÚÑáéíóúñ0-9 .'-]{3,50})\s*/\s*([A-Za-zÁÉÍÓÚÑáéíóúñ0-9 .'-]{3,50})\b", re.IGNORECASE),
    re.compile(r"\b([A-Za-zÁÉÍÓÚÑáéíóúñ0-9 .'-]{3,50})\s+(?:con|esquina)\s+([A-Za-zÁÉÍÓÚÑáéíóúñ0-9 .'-]{3,50})\b", re.IGNORECASE),
)
_LEGACY_STREET_PATTERN = re.compile(
    r"\b(calle|pasaje|camino|diagonal)\s+([A-Za-zÁÉÍÓÚÑáéíóúñ0-9 .'-]{3,64})",
    re.IGNORECASE,
)
_LEGACY_AVENUE_PATTERN = re.compile(
    r"\b(av\.?|avenida|avda\.?)\s+([A-Za-zÁÉÍÓÚÑáéíóúñ0-9 .'-]{3,64})",
    re.IGNORECASE,
)
_LEGACY_SECTOR_PATTERN = re.compile(
    r"\b(barrio|sector|plaza|parque|mall)\s+([A-Za-zÁÉÍÓÚÑáéíóúñ0-9 .'-]{3,50})",
    re.IGNORECASE,
)


def clean_legacy_geo_hint(raw: str, *, key: str = "address_label", comuna: str | None = None) -> CleanedGeoHint:
    """Clean legacy address_label/street_hint before turning it into a query."""
    original = str(raw or "").strip()
    if not original:
        return CleanedGeoHint(None, False, "low", "empty")
    value = _normalize_legacy_hint_spacing(original)
    warnings: list[str] = []
    trimmed = _LEGACY_SUFFIX_PATTERN.split(value, maxsplit=1)[0].strip(" ,.-/|")
    if trimmed != value:
        warnings.append("suffix_removed")
        value = trimmed
    if not value:
        return CleanedGeoHint(None, False, "low", "empty_after_suffix")
    if any(pattern.search(value) for pattern in _LEGACY_WEAK_STREET_PATTERNS):
        return CleanedGeoHint(None, False, "low", "weak_street_context", "sector", tuple(warnings))

    metro = _clean_legacy_metro(value, warnings=warnings)
    if metro:
        return CleanedGeoHint(metro, True, "medium", "accepted_metro_landmark", "metro", tuple(warnings))

    intersection = _clean_legacy_intersection(value, warnings=warnings)
    if intersection:
        return CleanedGeoHint(intersection, True, "medium", "accepted_intersection", "intersection", tuple(warnings))

    street = _clean_legacy_street(value, warnings=warnings, comuna=comuna)
    if street:
        signal_type = "avenue" if _normalize_text(street).startswith("avenida ") else "street"
        reason = "accepted_avenue" if signal_type == "avenue" else "accepted_street"
        return CleanedGeoHint(street, True, "medium", reason, signal_type, tuple(warnings))

    sector = _clean_legacy_sector(value, warnings=warnings)
    if sector:
        return CleanedGeoHint(sector, True, "medium", "accepted_sector_landmark", "sector", tuple(warnings))

    known_street = _extract_known_street(value)
    if known_street is not None:
        if _looks_commercial_legacy_text(value):
            return CleanedGeoHint(None, False, "low", "marketing_text", warnings=tuple(warnings))
        if _normalize_text(known_street) == "las condes":
            warnings.append("ambiguous_comuna_named_avenue")
            if comuna:
                known_street = f"{known_street}, {_format_comuna_for_query(comuna)}"
        return CleanedGeoHint(known_street, True, "medium", "accepted_known_street", "street", tuple(warnings))

    if _looks_commercial_legacy_text(value):
        return CleanedGeoHint(None, False, "low", "marketing_text", warnings=tuple(warnings))
    if len(_normalize_text(value).split()) > 8:
        return CleanedGeoHint(None, False, "low", "too_many_tokens", warnings=tuple(warnings))
    return CleanedGeoHint(None, False, "low", "no_place_like_signal", warnings=tuple(warnings))


def _legacy_signal_precision(cleaned: CleanedGeoHint) -> GeocodePrecision:
    if cleaned.detected_signal_type in {"metro", "plaza", "parque", "mall", "barrio", "sector"}:
        return "landmark_or_sector"
    if cleaned.detected_signal_type in {"street", "avenue", "intersection"}:
        return "street_address" if cleaned.cleaned_value and _contains_street_number(cleaned.cleaned_value) else "street_name"
    return classify_location_text(cleaned.cleaned_value or "")


def _normalize_legacy_hint_spacing(value: str) -> str:
    value = re.sub(r"([a-záéíóúñ])([A-ZÁÉÍÓÚÑ])", r"\1 \2", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip(" ,.-/|")


def _clean_legacy_metro(value: str, *, warnings: list[str]) -> str | None:
    match = _LEGACY_METRO_PATTERN.search(value)
    if not match:
        return None
    station = _clean_legacy_fragment(match.group(1))
    if not station:
        return None
    return f"Metro {station}"


def _clean_legacy_intersection(value: str, *, warnings: list[str]) -> str | None:
    for pattern in _LEGACY_INTERSECTION_PATTERNS:
        match = pattern.search(value)
        if not match:
            continue
        left = _clean_legacy_intersection_side(match.group(1))
        right = _clean_legacy_intersection_side(match.group(2))
        if left and right:
            return f"{left} y {right}"
    return None


def _clean_legacy_street(value: str, *, warnings: list[str], comuna: str | None) -> str | None:
    for pattern, canonical in ((_LEGACY_AVENUE_PATTERN, "Avenida"), (_LEGACY_STREET_PATTERN, None)):
        match = pattern.search(value)
        if not match:
            continue
        marker = canonical or _canonical_street_marker(match.group(1))
        name = _clean_legacy_fragment(match.group(2))
        if not name:
            return None
        if _has_weak_trailing_article(name):
            return None
        if _looks_commercial_legacy_text(name):
            return None
        if _normalize_text(name).startswith("las condes"):
            warnings.append("ambiguous_comuna_named_avenue")
            if comuna:
                return f"{marker} {name}, {_format_comuna_for_query(comuna)}"
        return f"{marker} {name}"
    return None


def _clean_legacy_sector(value: str, *, warnings: list[str]) -> str | None:
    match = _LEGACY_SECTOR_PATTERN.search(value)
    if not match:
        return None
    marker = match.group(1).title()
    name = _clean_legacy_fragment(match.group(2))
    if not name or _looks_commercial_legacy_text(name):
        return None
    return f"{marker} {name}"


def _clean_legacy_intersection_side(value: str) -> str:
    value = _LEGACY_SUFFIX_PATTERN.split(value, maxsplit=1)[0]
    words = [
        word
        for word in re.split(r"\s+", value.strip(" ,.-/|"))
        if _normalize_text(word) not in {"departamento", "depto", "dpto", "casa", "calle", "av", "avenida"}
    ]
    return _clean_legacy_fragment(" ".join(words[-4:]))


def _clean_legacy_fragment(value: str) -> str:
    value = _LEGACY_SUFFIX_PATTERN.split(value, maxsplit=1)[0]
    value = re.split(
        r"\b(?:en venta|venta|vende|departamento|depto|dpto|casa|dormitorios?|dorm|baños?|banos?|"
        r"estacionamientos?|estac|bodega|uf|m2|comuna|con una superficie|muy cerca de)\b",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    value = re.split(
        r"\b(?:te\s+ofrece|ofrece|experiencia|una\s+experiencia)\b",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return re.sub(r"\s+", " ", value).strip(" ,.-/|")


def _canonical_street_marker(value: str) -> str:
    normalized = _normalize_text(value)
    if normalized.startswith("pasaje"):
        return "Pasaje"
    if normalized.startswith("camino"):
        return "Camino"
    if normalized.startswith("diagonal"):
        return "Diagonal"
    return "Calle"


def _looks_commercial_legacy_text(value: str) -> bool:
    normalized = _normalize_text(value)
    if not normalized:
        return True
    return bool(_LEGACY_MARKETING_PATTERN.search(value))


def _has_weak_trailing_article(value: str) -> bool:
    normalized = _normalize_text(value)
    return normalized.endswith((" la", " el", " los", " las")) or bool(re.search(r"\.\s*(la|el|los|las)$", value, re.IGNORECASE))


def _metadata_query_source(key: str) -> GeocodeQuerySource:
    if key in {"address", "address_label"}:
        return "metadata_address"
    if key == "street_hint":
        return "metadata_street_hint"
    return "metadata_location_text"


def _metadata_query_confidence(*, key: str, location_text: str) -> GeocodeQueryConfidence:
    if key == "address":
        return "high" if _contains_street_number(location_text) else "medium"
    if key in {"address_label", "street_hint"}:
        return "medium"
    return "low"


def _is_usable_location_candidate(value: str, *, comuna: str | None) -> bool:
    normalized = _normalize_text(value)
    if not normalized:
        return False
    if normalized.startswith("casa "):
        return False
    if normalized in {"region metropolitana", "region metropolitana santiago", "santiago", "santiago chile"}:
        return False
    if normalized in {"camino", "camino a", "avenida", "av", "calle", "pasaje", "diagonal"}:
        return False
    if comuna and normalized == _normalize_text(_format_comuna_for_query(comuna)):
        return False
    if any(pattern.search(value) for pattern in _MARKETING_HINT_PATTERNS):
        return False
    if "camino a casa" in normalized:
        return False
    meaningful = [
        word
        for word in normalized.split()
        if word not in _TITLE_STOP_WORDS and not word.isdigit()
    ]
    if _contains_street_marker(value) or _contains_street_number(value):
        return bool(meaningful)
    if normalized.startswith("metro "):
        return True
    if _extract_known_street(value) is not None:
        return True
    if " y " in normalized:
        left, _, right = normalized.partition(" y ")
        return _is_usable_intersection_side(left) and _is_usable_intersection_side(right)
    return False


def extract_geocoding_hint(title: str, description: str, comuna: str) -> tuple[str | None, GeocodePrecision]:
    hint = extract_geocoding_hint_details(title, description, comuna)
    return hint.text, hint.precision


def extract_geocoding_hint_details(title: str, description: str, comuna: str) -> TextGeocodingHint:
    if should_skip_comuna(comuna):
        return TextGeocodingHint(None, "unknown", "unknown_comuna")

    text = _clean_search_text(f"{title} {description}")
    if not text:
        return TextGeocodingHint(None, "unknown", "empty_title_description")

    for pattern in _ADDRESS_NUMBER_PATTERNS:
        match = pattern.search(_ascii_text(text))
        if match is None:
            continue
        hint = _clean_hint(match.group(0))
        if _is_likely_address_number(hint):
            return TextGeocodingHint(hint, "street_address", "title_description.address_number")

    intersection = _extract_intersection(text)
    if intersection is not None:
        return TextGeocodingHint(intersection, "street_name", "title_description.intersection")

    explicit_street = _extract_explicit_street(text)
    if explicit_street is not None:
        return TextGeocodingHint(
            explicit_street,
            classify_location_text(explicit_street),
            "title_description.explicit_street",
        )

    metro = _extract_metro_hint(text)
    if metro is not None:
        return TextGeocodingHint(metro, "landmark_or_sector", "title_description.metro_landmark")

    known_street = _extract_known_street(text)
    if known_street is not None:
        return TextGeocodingHint(known_street, "street_name", "title_description.known_street")

    street_without_prefix = _extract_department_in_street(text, comuna)
    if street_without_prefix is not None:
        return TextGeocodingHint(street_without_prefix, "street_name", "title_description.department_in_street")

    return TextGeocodingHint(None, "unknown", "no_title_description_location_hint")


def extract_url_address_hint(url: str, comuna: str) -> tuple[str | None, GeocodePrecision]:
    if not url or should_skip_comuna(comuna):
        return None, "unknown"
    path = unquote(urlparse(url).path)
    slug = path.rsplit("/", maxsplit=1)[-1].replace("-", " ")
    slug = re.sub(r"\b\d{5,}\b", " ", slug)
    words = [
        word
        for word in _normalize_text(slug).split()
        if word and word not in _URL_STOP_WORDS and word not in _TITLE_STOP_WORDS
    ]
    if not words:
        return None, "unknown"
    text = " ".join(words[:5])
    if _normalize_text(text) == _normalize_text(comuna):
        return None, "unknown"
    if _contains_street_marker(text):
        return text, classify_location_text(text)
    if len(words) <= 4:
        return text, "street_name"
    return None, "unknown"


def normalize_street_name(value: str) -> str:
    clean = _clean_search_text(value)
    return re.sub(r"\s+", " ", clean).strip(" ,.-/")


def classify_query_strength(
    *,
    query: str | None,
    precision: GeocodePrecision,
    comuna: str | None = None,
) -> GeocodePrecision:
    if is_weak_geocoding_query(query=query, precision=precision, comuna=comuna):
        return "unknown"
    return precision


def _is_result_outside_chile(result: GeocodingResult) -> bool:
    address = result.address or {}
    country_code = str(address.get("country_code") or "").strip().lower()
    if country_code and country_code != "cl":
        return True
    lat = result.coordinates.lat
    lon = result.coordinates.lon
    return not (-56.0 <= lat <= -17.0 and -76.0 <= lon <= -66.0)


def _is_generic_nominatim_result(result: GeocodingResult) -> bool:
    raw_type = _normalized_raw_type(result)
    raw_class = (result.raw_class or "").strip().lower()
    if raw_type in _GENERIC_NOMINATIM_TYPES:
        return True
    return raw_class in {"boundary", "place"} and raw_type not in _STREET_RESULT_TYPES | _ADDRESS_RESULT_TYPES


def _has_unsupported_street_raw_type(result: GeocodingResult) -> bool:
    raw_type = _normalized_raw_type(result)
    if not raw_type:
        return False
    return raw_type not in _AUTO_APPLY_STREET_RESULT_TYPES


def _looks_like_centroid_result(result: GeocodingResult) -> bool:
    raw_type = _normalized_raw_type(result)
    raw_class = (result.raw_class or "").strip().lower()
    if raw_type in _GENERIC_NOMINATIM_TYPES:
        return True
    return raw_class in {"boundary", "place"}


def _has_conflicting_comuna(result: GeocodingResult, expected_comuna: str | None) -> bool:
    if not expected_comuna:
        return False
    expected = normalize_comuna(expected_comuna)
    address = result.address or {}
    for key in ("suburb", "city_district", "municipality", "town"):
        value = str(address.get(key) or "").strip()
        if not value:
            continue
        normalized = normalize_comuna(value)
        if normalized and normalized != expected and normalized not in {"santiago", "region_metropolitana"}:
            return True
    return False


def _normalized_raw_type(result: GeocodingResult) -> str:
    return str(result.raw_addresstype or result.raw_type or "").strip().lower()


def is_weak_geocoding_query(
    *,
    query: str | None,
    precision: GeocodePrecision,
    comuna: str | None = None,
) -> bool:
    if not query:
        return True
    if comuna:
        normalized_comuna = _normalize_text(_format_comuna_for_query(comuna))
        weak_parts = {normalized_comuna, "santiago", "chile"}
        query_parts = {_normalize_text(part) for part in query.split(",") if _normalize_text(part)}
        if query_parts and query_parts.issubset(weak_parts):
            return True
    return precision in {"unknown", "comuna_centroid", "landmark_or_sector"}


def _record_guardrail_rejection(stats: BackfillStats, reason: str) -> None:
    stats.failed += 1
    stats.rejected_by_guardrails += 1
    stats.rejection_reasons[reason] += 1
    if reason in _AMBIGUOUS_REJECTION_REASONS:
        stats.ambiguous += 1


def _can_overwrite_existing_geocode(listing: ListingORM, validated: ValidatedGeocode) -> bool:
    existing_precision = canonical_geocode_precision(getattr(listing, "geocode_precision", None))
    return geocode_precision_rank(validated.precision) >= geocode_precision_rank(existing_precision)


async def _has_suspicious_repeated_coordinates(
    session: AsyncSession,
    listing: ListingORM,
    coordinates: Coordinates,
) -> bool:
    execute = getattr(session, "execute", None)
    if execute is None:
        return False

    stmt = select(func.count(ListingORM.id)).where(
        ListingORM.id != listing.id,
        ListingORM.comuna == listing.comuna,
        ListingORM.lat == coordinates.lat,
        ListingORM.lon == coordinates.lon,
    )
    try:
        result = await execute(stmt)
    except Exception:  # pragma: no cover - defensive for dry-run adapters/tests
        _log.debug("Could not evaluate repeated geocode coordinates.", exc_info=True)
        return False

    count = result.scalar_one() if hasattr(result, "scalar_one") else result.scalar()
    return int(count or 0) >= REPEATED_COORDINATE_BLOCK_THRESHOLD


def _metadata_with_geocode_provenance(
    raw_metadata: dict[str, Any] | None,
    *,
    plan: GeocodingQueryPlan,
    validated: ValidatedGeocode,
) -> dict[str, Any]:
    metadata = dict(raw_metadata or {})
    metadata.update(
        {
            "geocode_provider": "nominatim",
            "geocode_query": plan.query,
            "geocode_query_source": plan.query_source,
            "geocode_query_confidence": plan.query_confidence,
            "geocode_query_rule": plan.query_rule,
            "geocode_signal_type": plan.geocode_signal_type,
            "geocode_signal_source": plan.geocode_signal_source,
            "geocode_precision": validated.precision,
            "geocode_confidence": validated.confidence,
            "geocode_reason": validated.reason,
            "geocode_applied_at": datetime.now(UTC).isoformat(),
            "geocode_version": GEOCODE_BACKFILL_VERSION,
            "geocode_source": "nominatim",
            "geocode_score": validated.confidence,
            "geocode_raw_type": validated.raw_type,
            "geocode_raw_class": validated.raw_class,
            "geocode_display_name": validated.display_name,
        }
    )
    if plan.query_source in {"metadata_address", "metadata_street_hint", "metadata_location_text"}:
        metadata["legacy_hint_cleaned"] = (plan.query or "").split(",", 1)[0]
        metadata["legacy_hint_signal_type"] = plan.geocode_signal_type
    return metadata


def _record_legacy_hint_cleaning_stats(stats: BackfillStats, listing: ListingORM) -> None:
    metadata = getattr(listing, "raw_metadata", None)
    if not isinstance(metadata, dict):
        return
    for key in _METADATA_LOCATION_KEYS:
        value = metadata.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        cleaned = clean_legacy_geo_hint(value, key=key, comuna=getattr(listing, "comuna", None))
        if cleaned.is_usable:
            stats.legacy_hint_accepted += 1
            stats.legacy_hint_signal_type_counts[cleaned.detected_signal_type or "unknown"] += 1
            if cleaned.cleaned_value and cleaned.cleaned_value != normalize_street_name(value) and len(stats.legacy_hint_cleaned_examples) < 20:
                stats.legacy_hint_cleaned_examples.append(
                    {
                        "listing_id": str(getattr(listing, "id", "")),
                        "key": key,
                        "before": normalize_street_name(value),
                        "after": cleaned.cleaned_value,
                        "reason": cleaned.reason,
                        "signal_type": cleaned.detected_signal_type or "",
                    }
                )
        else:
            stats.legacy_hint_rejected += 1
            stats.legacy_hint_rejection_reasons[cleaned.reason] += 1
            if len(stats.legacy_hint_cleaned_examples) < 20:
                stats.legacy_hint_cleaned_examples.append(
                    {
                        "listing_id": str(getattr(listing, "id", "")),
                        "key": key,
                        "before": normalize_street_name(value),
                        "after": "",
                        "reason": cleaned.reason,
                        "signal_type": cleaned.detected_signal_type or "",
                    }
                )


def _record_example(
    stats: BackfillStats,
    listing: ListingORM,
    plan: GeocodingQueryPlan,
    action: str,
    reason: str,
    examples_limit: int,
    *,
    lat: float | None = None,
    lon: float | None = None,
    current_lat: float | None = None,
    current_lon: float | None = None,
    current_precision: str | None = None,
) -> None:
    if len(stats.examples) >= examples_limit:
        return
    stats.examples.append(
        GeocodingAttempt(
            listing_id=listing.id,
            title=_trim_log_text(getattr(listing, "title", "") or "", max_len=72),
            comuna=getattr(listing, "comuna", "") or "",
            query=plan.query,
            proposed_precision=plan.precision,
            action=action,
            reason=reason,
            lat=lat,
            lon=lon,
            current_lat=getattr(listing, "lat", None) if current_lat is None else current_lat,
            current_lon=getattr(listing, "lon", None) if current_lon is None else current_lon,
            current_precision=(
                canonical_geocode_precision(getattr(listing, "geocode_precision", None))
                if current_precision is None
                else current_precision
            ),
            query_source=plan.query_source,
            query_confidence=plan.query_confidence,
            query_rule=plan.query_rule,
            geocode_signal_type=plan.geocode_signal_type,
            geocode_signal_source=plan.geocode_signal_source,
        )
    )


def _description_from_metadata(raw_metadata: dict[str, Any] | None) -> str:
    metadata = raw_metadata or {}
    for key in _DESCRIPTION_KEYS:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _clean_search_text(value: str) -> str:
    value = value.replace("+", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip(" ,.-")


def _clean_hint(value: str) -> str:
    value = re.sub(r"([a-záéíóúñ])([A-ZÁÉÍÓÚÑ])", r"\1 \2", value)
    value = re.split(
        r"\b(comuna|sector|metro|en venta|venta|vende|depto|dpto|departamento|casa|esta\s+propiedad|propiedad|excelente|estado|conservacion|conservación|dormitorio|dorm|bano|banio|estac)\b",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    value = re.split(
        r"\b(te\s+ofrece|ofrece|experiencia|uf)\b",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return re.sub(r"\s+", " ", value).strip(" ,.-/")


def _extract_intersection(text: str) -> str | None:
    ascii_text = _ascii_text(text)
    if "/" in ascii_text:
        parts = ascii_text.split("/")
        for index in range(len(parts) - 1):
            left = _clean_intersection_side(parts[index])
            right = _clean_intersection_side(parts[index + 1])
            if _is_usable_intersection_side(left) and _is_usable_intersection_side(right):
                return f"{left} y {right}"

    for pattern in _INTERSECTION_PATTERNS:
        for match in pattern.finditer(ascii_text):
            left = _clean_intersection_side(match.group(1))
            right = _clean_intersection_side(match.group(2))
            if _is_usable_intersection_side(left) and _is_usable_intersection_side(right):
                return f"{left} y {right}"
    return None


def _clean_intersection_side(value: str) -> str:
    marker_match = _EXPLICIT_STREET_PATTERN.search(_ascii_text(value))
    if marker_match is not None:
        return _clean_hint(marker_match.group(0))
    value = _clean_hint(value)
    known = _extract_known_street(value)
    if known is not None:
        return known
    value = re.sub(
        r"\b(en|venta|vende|amplio|dpto|depto|departamento|casa|ubicado|sector|metro)\b",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    words = [word for word in re.split(r"\s+", value.strip(" ,.-/")) if word]
    if len(words) > 4:
        words = words[-4:]
    if words and _normalize_text(words[0]) in {"av", "av.", "avenida", "calle", "pasaje", "camino", "diagonal"}:
        return " ".join(words[:4]).strip(" ,.-/")
    return " ".join(words[:3]).strip(" ,.-/")


def _is_usable_intersection_side(value: str) -> bool:
    normalized = _normalize_text(value)
    words = [word for word in normalized.split() if word and word not in _TITLE_STOP_WORDS]
    return bool(words) and len(normalized) >= 3 and not normalized.isdigit()


def _extract_explicit_street(text: str) -> str | None:
    match = _EXPLICIT_STREET_PATTERN.search(_ascii_text(text))
    if match is None:
        return None
    hint = _clean_hint(match.group(0))
    if not _is_usable_title_fragment(hint):
        return None
    return hint


def _extract_metro_hint(text: str) -> str | None:
    match = _METRO_PATTERN.search(_ascii_text(text))
    if match is None:
        return None
    station = _clean_landmark(match.group(1))
    if not station:
        return None
    return f"Metro {station}"


def _clean_landmark(value: str) -> str:
    value = re.split(
        r"\b(en|venta|vende|depto|dpto|departamento|con|cercano|a pasos|excelente|oportunidad)\b",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    words = [word for word in re.split(r"\s+", value.strip(" ,.-/")) if word]
    return " ".join(words[:4]).strip(" ,.-/")


def _extract_known_street(text: str) -> str | None:
    normalized_text = _normalize_text(text)
    for snippet in _KNOWN_STREET_SNIPPETS:
        if _normalize_text(snippet) in normalized_text:
            return snippet
    return None


def _extract_department_in_street(text: str, comuna: str) -> str | None:
    match = _DEPARTMENT_IN_STREET_PATTERN.search(_ascii_text(text))
    if match is None:
        return None
    hint = _clean_landmark(match.group(1))
    if not hint or _normalize_text(hint) == _normalize_text(comuna):
        return None
    if any(word in _TITLE_STOP_WORDS for word in _normalize_text(hint).split()):
        return None
    return hint


def _is_likely_address_number(hint: str) -> bool:
    normalized = _normalize_text(hint)
    if not re.search(r"\d{1,5}\b", normalized):
        return False
    if _contains_street_marker(hint):
        return True
    if _extract_known_street(hint) is not None:
        return True
    words = [word for word in normalized.split() if word and not word.isdigit()]
    noisy = {"townhouse", "estacionamiento", "bodega", "uf", "dorm", "bano", "banio", "terraza", "mas", "m2", "mt2"}
    return bool(words) and not any(word in noisy for word in words)


def extract_title_address_fragment(title: str) -> tuple[str | None, GeocodePrecision]:
    clean_title = re.sub(r"\s+", " ", title).strip(" ,")
    if not clean_title:
        return None, "unknown"
    for pattern in (
        re.compile(r"\b(calle)\s+([^,;|/\\-]+(?:\s+\d{1,5})?)", re.IGNORECASE),
        re.compile(r"\b(av\.?|avenida)\s+([^,;|/\\-]+(?:\s+\d{1,5})?)", re.IGNORECASE),
        re.compile(r"\b(pasaje|camino|diagonal)\s+([^,;|/\\-]+(?:\s+\d{1,5})?)", re.IGNORECASE),
        re.compile(r"\b([a-z]+(?:\s+[a-z]+){0,3})\s+(\d{2,5})\b", re.IGNORECASE),
    ):
        match = pattern.search(_ascii_text(clean_title))
        if match is None:
            continue
        fragment = f"{match.group(1)} {match.group(2)}"
        fragment = _clean_title_fragment(fragment)
        if _is_usable_title_fragment(fragment):
            return fragment, classify_location_text(fragment)
    return None, "unknown"


def classify_location_text(location_text: str) -> GeocodePrecision:
    if _contains_street_number(location_text):
        return "street_address"
    if _contains_street_marker(location_text):
        return "street_name"
    if _normalize_text(location_text).startswith("metro "):
        return "landmark_or_sector"
    return "street_name"


def _clean_title_fragment(fragment: str) -> str:
    fragment = re.split(
        r"\b(en venta|venta|vende|depto|dpto|departamento)\b",
        fragment,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return re.sub(r"\s+", " ", fragment).strip(" ,.-")


def _is_usable_title_fragment(fragment: str) -> bool:
    normalized = re.sub(r"[^a-z0-9 ]+", " ", _normalize_text(fragment))
    words = [word for word in normalized.split() if word]
    meaningful_words = [word for word in words if word not in _TITLE_STOP_WORDS and not word.isdigit()]
    has_number = any(word.isdigit() for word in words)
    return bool(meaningful_words) and (_contains_street_marker(fragment) or has_number)


def _contains_street_marker(value: str) -> bool:
    return bool(re.search(r"\b(calle|av\.?|avenida|pasaje|camino|diagonal)\b", _normalize_text(value), re.IGNORECASE))


def _contains_street_number(value: str) -> bool:
    return bool(re.search(r"\b[a-zA-Z][\w. ]+\s+\d{1,5}\b", _ascii_text(value)))


def _ascii_text(value: str) -> str:
    return unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")


def _normalize_text(value: str) -> str:
    ascii_text = _ascii_text(value)
    ascii_text = re.sub(r"[^a-zA-Z0-9. ]+", " ", ascii_text)
    return re.sub(r"\s+", " ", ascii_text).strip().lower()


def _trim_log_text(value: str, *, max_len: int = 90) -> str:
    clean = re.sub(r"\s+", " ", value).strip()
    if len(clean) <= max_len:
        return clean
    return f"{clean[: max_len - 3]}..."


def should_skip_comuna(comuna: str | None) -> bool:
    if comuna is None:
        return True
    normalized = comuna.strip().lower()
    return normalized in _UNKNOWN_COMUNAS


def _format_comuna_for_query(comuna: str) -> str:
    return re.sub(r"\s+", " ", comuna.replace("_", " ")).strip().title()


def print_stats(stats: BackfillStats) -> None:
    canonical_counts = _canonical_precision_counts(stats.precision_counts)
    assigned_counts = _canonical_precision_counts(stats.assigned_precision_counts)
    print("== AVM geocoding dry-run/backfill ==")
    print(f"dry_run\t{stats.dry_run}")
    print(f"total_candidates\t{stats.total_candidates}")
    print(f"would_geocode\t{stats.would_geocode}")
    print(f"geocoded\t{stats.geocoded}")
    print(f"skipped\t{stats.skipped}")
    print(f"skipped_existing_coordinates\t{stats.skipped_existing_coordinates}")
    print(f"skipped_weak_query\t{stats.skipped_weak_query}")
    print(f"rejected_by_guardrails\t{stats.rejected_by_guardrails}")
    print(f"ambiguous\t{stats.ambiguous}")
    print(f"no_sufficient_query\t{stats.no_sufficient_query}")
    print(f"not_found\t{stats.not_found}")
    print(f"repeated_coordinates\t{stats.repeated_coordinates}")
    print(f"title_inferred_blocked\t{stats.title_inferred_blocked}")
    print(f"failed\t{stats.failed}")
    print(f"cache_hits\t{stats.cache_hits}")
    print(f"external_requests\t{stats.external_requests}")
    print("\n== Canonical precision counts ==")
    for precision in ("address", "street", "comuna", "comuna_centroid", "unknown"):
        print(f"{precision}\t{canonical_counts[precision]}")
    print("\n== Assigned precision counts ==")
    for precision in ("address", "street", "comuna", "comuna_centroid", "unknown"):
        print(f"{precision}\t{assigned_counts[precision]}")
    print("\n== Query source counts ==")
    for source, count in stats.query_source_counts.most_common():
        print(f"{source}\t{count}")
    print("\n== Query confidence counts ==")
    for confidence, count in stats.query_confidence_counts.most_common():
        print(f"{confidence}\t{count}")

    print("\n== Geo signal type counts ==")
    for signal_type, count in stats.geocode_signal_type_counts.most_common():
        print(f"{signal_type}\t{count}")

    print("\n== Geo signal source counts ==")
    for signal_source, count in stats.geocode_signal_source_counts.most_common():
        print(f"{signal_source}\t{count}")
    print("\n== Legacy hint cleaning ==")
    print(f"accepted\t{stats.legacy_hint_accepted}")
    print(f"rejected\t{stats.legacy_hint_rejected}")
    print("\n== Legacy hint signal types ==")
    for signal_type, count in stats.legacy_hint_signal_type_counts.most_common():
        print(f"{signal_type}\t{count}")
    print("\n== Legacy hint rejection reasons ==")
    for reason, count in stats.legacy_hint_rejection_reasons.most_common(20):
        print(f"{reason}\t{count}")
    print("\n== Candidate comunas ==")
    for comuna, count in stats.by_comuna.most_common(20):
        print(f"{comuna}\t{count}")
    print("\n== Rejection reasons ==")
    for reason, count in stats.rejection_reasons.most_common(20):
        print(f"{reason}\t{count}")
    print("\n== Examples ==")
    print(
        "id\taction\treason\tprecision\tquery_source\tquery_confidence\tquery_rule\t"
        "geocode_signal_type\tgeocode_signal_source\t"
        "before_lat\tbefore_lon\tbefore_precision\tlat\tlon\tcomuna\tquery\ttitle"
    )
    for example in stats.examples:
        print(
            f"{example.listing_id}\t{example.action}\t{example.reason}\t"
            f"{canonical_geocode_precision(example.proposed_precision)}\t"
            f"{example.query_source}\t{example.query_confidence}\t{example.query_rule}\t"
            f"{example.geocode_signal_type or ''}\t{example.geocode_signal_source or ''}\t"
            f"{example.current_lat}\t{example.current_lon}\t{example.current_precision}\t"
            f"{example.lat}\t{example.lon}\t"
            f"{example.comuna}\t{example.query}\t{example.title}"
        )


def write_post_run_report(stats: BackfillStats, *, output_dir: Path = DEFAULT_REPORT_DIR) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = _stats_payload(stats)
    json_path = output_dir / "geocode_backfill_latest.json"
    md_path = output_dir / "geocode_backfill_latest.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_markdown_report(payload), encoding="utf-8")
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    (output_dir / f"geocode_backfill_{stamp}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return md_path, json_path


def _stats_payload(stats: BackfillStats) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "status": stats.status,
        "dry_run": stats.dry_run,
        "total_candidates": stats.total_candidates,
        "geocoded": stats.geocoded,
        "would_geocode": stats.would_geocode,
        "skipped": stats.skipped,
        "skipped_existing_coordinates": stats.skipped_existing_coordinates,
        "skipped_weak_query": stats.skipped_weak_query,
        "rejected_by_guardrails": stats.rejected_by_guardrails,
        "ambiguous": stats.ambiguous,
        "no_sufficient_query": stats.no_sufficient_query,
        "not_found": stats.not_found,
        "repeated_coordinates": stats.repeated_coordinates,
        "title_inferred_blocked": stats.title_inferred_blocked,
        "failed": stats.failed,
        "cache_hits": stats.cache_hits,
        "external_requests": stats.external_requests,
        "precision_counts": dict(_canonical_precision_counts(stats.precision_counts)),
        "assigned_precision_counts": dict(_canonical_precision_counts(stats.assigned_precision_counts)),
        "rejection_reasons": dict(stats.rejection_reasons),
        "query_source_counts": dict(stats.query_source_counts),
        "query_confidence_counts": dict(stats.query_confidence_counts),
        "geocode_signal_type_counts": dict(stats.geocode_signal_type_counts),
        "geocode_signal_source_counts": dict(stats.geocode_signal_source_counts),
        "legacy_hint_accepted": stats.legacy_hint_accepted,
        "legacy_hint_rejected": stats.legacy_hint_rejected,
        "legacy_hint_rejection_reasons": dict(stats.legacy_hint_rejection_reasons),
        "legacy_hint_signal_type_counts": dict(stats.legacy_hint_signal_type_counts),
        "legacy_hint_cleaned_examples": stats.legacy_hint_cleaned_examples,
        "by_comuna": dict(stats.by_comuna),
        "examples": [
            {
                "listing_id": item.listing_id,
                "title": item.title,
                "comuna": item.comuna,
                "query": item.query,
                "proposed_precision": canonical_geocode_precision(item.proposed_precision),
                "action": item.action,
                "reason": item.reason,
                "lat": item.lat,
                "lon": item.lon,
                "current_lat": item.current_lat,
                "current_lon": item.current_lon,
                "current_precision": item.current_precision,
                "query_source": item.query_source,
                "query_confidence": item.query_confidence,
                "query_rule": item.query_rule,
                "geocode_signal_type": item.geocode_signal_type,
                "geocode_signal_source": item.geocode_signal_source,
            }
            for item in stats.examples
        ],
    }


def _markdown_report(payload: dict[str, Any]) -> str:
    lines = [
        "# AVM Geocode Backfill Report",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Status: `{payload['status']}`",
        f"- Dry run: {payload['dry_run']}",
        f"- Total candidates: {payload['total_candidates']}",
        f"- Applied geocodes: {payload['geocoded']}",
        f"- Would geocode: {payload['would_geocode']}",
        f"- Skipped: {payload['skipped']}",
        f"- Skipped existing coordinates: {payload['skipped_existing_coordinates']}",
        f"- Skipped weak query: {payload['skipped_weak_query']}",
        f"- Rejected by guardrails: {payload['rejected_by_guardrails']}",
        f"- Ambiguous: {payload['ambiguous']}",
        f"- No sufficient query: {payload['no_sufficient_query']}",
        f"- Not found: {payload['not_found']}",
        f"- Repeated coordinates: {payload['repeated_coordinates']}",
        f"- Title inferred blocked: {payload['title_inferred_blocked']}",
        f"- Failed/rejected: {payload['failed']}",
        f"- Cache hits: {payload['cache_hits']}",
        f"- External requests: {payload['external_requests']}",
        "",
        "## Precision Counts",
        "",
        _simple_table("precision", payload["precision_counts"]),
        "",
        "## Assigned Precision Counts",
        "",
        _simple_table("precision", payload["assigned_precision_counts"]),
        "",
        "## Query Source Counts",
        "",
        _simple_table("source", payload["query_source_counts"]),
        "",
        "## Query Confidence Counts",
        "",
        _simple_table("confidence", payload["query_confidence_counts"]),
        "",
        "## Geo Signal Type Counts",
        "",
        _simple_table("signal_type", payload["geocode_signal_type_counts"]),
        "",
        "## Geo Signal Source Counts",
        "",
        _simple_table("signal_source", payload["geocode_signal_source_counts"]),
        "",
        "## Legacy Hint Cleaning",
        "",
        f"- Accepted: {payload['legacy_hint_accepted']}",
        f"- Rejected: {payload['legacy_hint_rejected']}",
        "",
        "### Legacy Hint Signal Types",
        "",
        _simple_table("signal_type", payload["legacy_hint_signal_type_counts"]),
        "",
        "### Legacy Hint Rejection Reasons",
        "",
        _simple_table("reason", payload["legacy_hint_rejection_reasons"]),
        "",
        "### Legacy Hint Examples",
        "",
        _legacy_examples_table(payload["legacy_hint_cleaned_examples"]),
        "",
        "## By Comuna",
        "",
        _simple_table("comuna", payload["by_comuna"]),
        "",
        "## Rejection Reasons",
        "",
        _simple_table("reason", payload["rejection_reasons"]),
        "",
        "## Examples",
        "",
        _examples_table(payload["examples"]),
        "",
        "## Blocked Examples",
        "",
        _examples_table([row for row in payload["examples"] if row.get("action") == "blocked"]),
    ]
    return "\n".join(lines) + "\n"


def _simple_table(label: str, values: dict[str, int]) -> str:
    if not values:
        return "_No data._"
    lines = [f"| {label} | count |", "|---|---:|"]
    for key, value in sorted(values.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| {key} | {value} |")
    return "\n".join(lines)


def _canonical_precision_counts(values: Counter[str]) -> Counter[str]:
    counts: Counter[str] = Counter(dict.fromkeys(("address", "street", "comuna", "comuna_centroid", "unknown"), 0))
    for precision, count in values.items():
        counts[canonical_geocode_precision(precision)] += count
    return Counter({key: value for key, value in counts.items() if value > 0})


def _examples_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "_No examples._"
    columns = [
        "listing_id",
        "action",
        "reason",
        "proposed_precision",
        "query_source",
        "query_confidence",
        "query_rule",
        "geocode_signal_type",
        "geocode_signal_source",
        "current_lat",
        "current_lon",
        "current_precision",
        "lat",
        "lon",
        "comuna",
        "query",
        "title",
    ]
    lines = ["| " + " | ".join(columns) + " |", "|" + "|".join("---" for _ in columns) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(column)) for column in columns) + " |")
    return "\n".join(lines)


def _legacy_examples_table(rows: list[dict[str, str]]) -> str:
    if not rows:
        return "_No examples._"
    columns = ["listing_id", "key", "reason", "signal_type", "before", "after"]
    lines = ["| " + " | ".join(columns) + " |", "|" + "|".join("---" for _ in columns) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(column, "")) for column in columns) + " |")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Conservative geocoding dry-run/backfill using Nominatim.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Inspect and geocode with no DB writes. Default.")
    mode.add_argument("--apply", action="store_true", help="Write coordinates for accepted geocoder matches.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of listings to inspect.")
    parser.add_argument("--only-active", action="store_true", help="Only inspect active listings.")
    parser.add_argument(
        "--only-missing-coordinates",
        action="store_true",
        help="Only inspect listings with missing lat or lon.",
    )
    parser.add_argument("--comuna", "--commune", dest="comuna", type=str, default=None, help="Restrict to one normalized comuna value.")
    parser.add_argument(
        "--property-type",
        choices=("apartment", "house"),
        default=None,
        help="Restrict to one property type. Omit to process apartments and houses.",
    )
    parser.add_argument("--no-external", action="store_true", help="Preview queries without calling Nominatim.")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow replacing existing coordinates when the accepted precision is not worse.",
    )
    parser.add_argument(
        "--allow-title-inferred",
        action="store_true",
        help="Allow --apply to write geocodes whose query was inferred from listing title text.",
    )
    parser.add_argument("--examples", type=int, default=12, help="Maximum examples to print.")
    parser.add_argument("--output-dir", default=str(DEFAULT_REPORT_DIR), help="Directory for post-run reports.")
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=1.0,
        help="Delay after uncached external Nominatim requests.",
    )
    return parser.parse_args()


async def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = parse_args()
    if args.limit is not None and args.limit < 1:
        print("ERROR: --limit must be greater than 0.", file=sys.stderr)
        return 2
    if args.examples < 0:
        print("ERROR: --examples must be >= 0.", file=sys.stderr)
        return 2
    if args.sleep_seconds < 1.0:
        print("ERROR: --sleep-seconds must be at least 1.0 for Nominatim policy.", file=sys.stderr)
        return 2

    dry_run = not args.apply
    stats = await run_backfill(
        dry_run=dry_run,
        apply=bool(args.apply),
        limit=args.limit,
        sleep_seconds=float(args.sleep_seconds),
        only_active=bool(args.only_active),
        only_missing_coordinates=bool(args.only_missing_coordinates),
        comuna=args.comuna,
        property_type=args.property_type,
        no_external=bool(args.no_external),
        overwrite=bool(args.overwrite),
        allow_title_inferred=bool(args.allow_title_inferred),
        examples_limit=int(args.examples),
    )
    print_stats(stats)
    md_path, json_path = write_post_run_report(stats, output_dir=Path(args.output_dir))
    print("\n== Report files ==")
    print(f"markdown\t{md_path}")
    print(f"json\t{json_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(asyncio.run(main()))
