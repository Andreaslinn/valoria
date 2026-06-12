"""Limpieza y validacion de datos crudos de scrapers o la UI."""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from config.comunas import is_known_comuna, normalize_comuna
from config.constants import (
    LISTING_SOURCES,
    MAX_BATHROOMS,
    MAX_BEDROOMS,
    MAX_M2,
    MIN_M2,
    MIN_SALE_PRICE_CLP,
    PROPERTY_TYPES,
    RM_COMUNA_ALIASES,
)
from core.exceptions import UnknownComunaError, ValidationError
from core.normalization.geocode_precision import normalize_geocode_precision
from core.value_objects.location import Coordinates
from core.value_objects.price import Price
from domain.geocoding.microzones import enrich_raw_metadata_with_microzones

_TITLE_MAX_LEN = 512
_M2_RE = re.compile(r"(?P<num>\d+(?:[.,]\d+)?)\s*(?:m2|m²|mts2|metros)", re.IGNORECASE)
_AREA_RE = re.compile(r"(?P<num>\d+(?:[.,]\d+)?)\s*(?:m2|m²|mts2|metros)", re.IGNORECASE)
_AREA_PAIR_RE = re.compile(
    r"(?<!\d)(?P<first>\d{2,4}(?:[.,]\d+)?)\s*/\s*(?P<second>\d{2,4}(?:[.,]\d+)?)(?!\d)"
)
_AREA_PARSE_VERSION = "area_parser_v2"
_AREA_FIELDS = ("built_area_m2", "land_area_m2", "usable_area_m2")
_LAND_AREA_WITHOUT_UNIT_RE = re.compile(
    r"\b(?:sup(?:erficie)?\s*(?:de\s*)?(?:total\s*)?(?:terreno|sitio|lote)|"
    r"terreno|sitio|lote)(?P<gap>\D{0,18})(?P<num>\d{2,5}(?:[.,]\d+)?)\b"
)
_LAND_AREA_REVERSE_WITHOUT_UNIT_RE = re.compile(
    r"\b(?P<num>\d{2,5}(?:[.,]\d+)?)\s*(?:terreno|sitio|lote)\b"
)
_BUILT_AREA_WITHOUT_UNIT_RE = re.compile(
    r"\b(?:construidos?|construidas?|construccion|edificados?|edificadas?)"
    r"(?P<gap>[^\d/]{0,18})(?P<num>\d{2,5}(?:[.,]\d+)?)\b"
)
_AREA_NUMBER_PATTERN = r"(?:\d{1,3}(?:[.,]\d{3})+(?:,\d+)?|\d{2,5}(?:[.,]\d+)?)"
_M2_RE = re.compile(rf"(?P<num>{_AREA_NUMBER_PATTERN})\s*(?:m2|mÂ²|m²|mts2|metros)", re.IGNORECASE)
_AREA_RE = re.compile(rf"(?P<num>{_AREA_NUMBER_PATTERN})\s*(?:m2|mÂ²|m²|mts2|metros)", re.IGNORECASE)
_AREA_PAIR_RE = re.compile(
    rf"(?<!\d)(?P<first>{_AREA_NUMBER_PATTERN})\s*/\s*(?P<second>{_AREA_NUMBER_PATTERN})(?!\d)"
)
_LAND_AREA_WITHOUT_UNIT_RE = re.compile(
    rf"\b(?:sup(?:erficie)?\s*(?:de\s*)?(?:total\s*)?(?:terreno|sitio|lote)|"
    rf"terreno|sitio|lote)(?P<gap>\D{{0,18}})(?P<num>{_AREA_NUMBER_PATTERN})\b"
)
_LAND_AREA_REVERSE_WITHOUT_UNIT_RE = re.compile(
    rf"\b(?P<num>{_AREA_NUMBER_PATTERN})\s*(?:terreno|sitio|lote)\b"
)
_BUILT_AREA_WITHOUT_UNIT_RE = re.compile(
    r"\b(?:construidos?|construidas?|construccion|edificados?|edificadas?)"
    rf"(?P<gap>[^\d/]{{0,18}})(?P<num>{_AREA_NUMBER_PATTERN})\b"
)
_PUNCT_RE = re.compile(r"[^a-z0-9\s]")
_SPACE_RE = re.compile(r"\s+")
_LOCATION_NOISE_PHRASES = (
    "region metropolitana de santiago",
    "region metropolitana",
    "metropolitana de santiago",
    "santiago chile",
    "chile",
)
_LOCATION_NOISE_TOKENS = frozenset({"rm"})
_OUTSIDE_RM_MARKERS = (
    "valparaiso",
    "vina del mar",
    "vina",
    "rancagua",
    "concepcion",
    "temuco",
    "arica",
    "iquique",
    "antofagasta",
    "la serena",
    "coquimbo",
    "talca",
    "chillan",
    "los angeles",
    "valdivia",
    "osorno",
    "puerto montt",
)

_log = logging.getLogger(__name__)
_ALIAS_TO_SLUG = {key: normalize_comuna(value) for key, value in RM_COMUNA_ALIASES.items()}
_SLUG_TO_ALIAS_KEY = {normalize_comuna(value).replace("_", " "): value for value in RM_COMUNA_ALIASES.values()}


@dataclass
class CleanedListing:
    """Datos normalizados y validados, listos para deduplicar y persistir."""

    source: str
    external_id: str | None
    title: str
    comuna: str
    m2: float | None
    bedrooms: int
    bathrooms: int
    parking: int
    price: Price
    scraped_at: datetime
    property_type: str = "unknown"
    built_area_m2: float | None = None
    land_area_m2: float | None = None
    usable_area_m2: float | None = None
    url: str | None = None
    coordinates: Coordinates | None = None
    geocode_precision: str | None = None
    price_uf: Decimal | None = None
    price_currency: str | None = None
    price_uf_confidence: str | None = None
    price_uf_source: str | None = None
    price_recovery_method: str | None = None
    raw_metadata: dict = field(default_factory=dict)

    @property
    def quality_warnings(self) -> list[str]:
        raw = self.raw_metadata.get("data_quality_warnings", [])
        return list(raw) if isinstance(raw, list) else []

    @property
    def is_complete_for_comparables(self) -> bool:
        return self.m2 is not None and "unknown_comuna" not in self.quality_warnings


@dataclass(frozen=True)
class PropertyTypeGuess:
    value: str
    reason: str
    confidence: float
    source_fields: tuple[str, ...]


@dataclass(frozen=True)
class AreaParseResult:
    areas: dict[str, float]
    sources: dict[str, str]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class PriceProvenance:
    price_uf: Decimal | None
    price_currency: str | None
    price_uf_confidence: str | None
    price_uf_source: str | None
    price_recovery_method: str | None
    raw_metadata: dict[str, Any]


def clean_listing(raw: dict[str, Any], *, allow_incomplete: bool = False) -> CleanedListing:
    """Normaliza y valida un listing crudo.

    En modo estricto mantiene las validaciones historicas. En modo tolerante
    solo guarda incompletos cuando existen los minimos auditables: source,
    title, URL y precio valido.
    """
    source = _required_str(raw, "source")
    if source not in LISTING_SOURCES:
        raise ValidationError(f"source invalido: {source!r}. Validos: {sorted(LISTING_SOURCES)}")

    title = _required_str(raw, "title")[:_TITLE_MAX_LEN]
    url = _optional_str(raw.get("url"))
    if not _valid_url(url):
        raise ValidationError(f"invalid_url: {url!r}")

    warnings: list[str] = []
    raw_metadata = dict(raw.get("raw_metadata", {}))
    raw_metadata = enrich_raw_metadata_with_microzones(raw_metadata, title=title)

    detection = detect_comuna(raw, title=title)
    comuna_raw = detection.raw
    if detection.normalized is None:
        if not allow_incomplete:
            if comuna_raw:
                raise UnknownComunaError(f"Comuna desconocida: {comuna_raw!r}")
            raise ValidationError("Campo requerido ausente o vacio: 'comuna'")
        comuna = normalize_comuna(comuna_raw) if comuna_raw else "unknown"
        warnings.append("unknown_comuna")
    else:
        comuna = detection.normalized
    raw_metadata["comuna_raw"] = comuna_raw
    raw_metadata["comuna_normalized"] = comuna
    raw_metadata["comuna_extraction_source"] = detection.source
    raw_metadata["comuna_match_strategy"] = detection.match_strategy
    raw_metadata["comuna_match_value"] = detection.match_value
    raw_metadata["comuna_extraction_attempts"] = detection.attempts
    if detection.outside_rm_candidate:
        raw_metadata["outside_rm_candidate"] = True
    _log.debug(
        "Comuna detection comuna_raw=%r comuna_normalized=%r extraction_source=%s "
        "match_strategy=%s match_value=%r",
        comuna_raw,
        comuna,
        detection.source,
        detection.match_strategy,
        detection.match_value,
    )

    property_type_guess = infer_property_type(raw, title=title)
    property_type = property_type_guess.value
    raw_metadata["property_type_source_fields"] = list(property_type_guess.source_fields)
    raw_metadata["property_type_reason"] = property_type_guess.reason
    raw_metadata["property_type_confidence"] = property_type_guess.confidence
    built_area_m2, built_area_source = _first_explicit_area(raw, ("built_area_m2", "built_m2"))
    land_area_m2, land_area_source = _first_explicit_area(raw, ("land_area_m2", "terrain_m2", "terreno_m2"))
    usable_area_m2, usable_area_source = _first_explicit_area(raw, ("usable_area_m2", "useful_m2"))
    area_sources = {
        key: source
        for key, source in (
            ("built_area_m2", built_area_source),
            ("land_area_m2", land_area_source),
            ("usable_area_m2", usable_area_source),
        )
        if source is not None
    }
    parsed_areas = extract_area_fields_with_provenance(raw, title=title)
    built_area_m2 = _prefer_existing_area(
        built_area_m2,
        parsed_areas.areas.get("built_area_m2"),
        area_sources,
        "built_area_m2",
        parsed_areas.sources.get("built_area_m2"),
    )
    land_area_m2 = _prefer_existing_area(
        land_area_m2,
        parsed_areas.areas.get("land_area_m2"),
        area_sources,
        "land_area_m2",
        parsed_areas.sources.get("land_area_m2"),
    )
    usable_area_m2 = _prefer_existing_area(
        usable_area_m2,
        parsed_areas.areas.get("usable_area_m2"),
        area_sources,
        "usable_area_m2",
        parsed_areas.sources.get("usable_area_m2"),
    )

    m2 = _parse_optional_m2(raw.get("m2"), title=title, raw=raw)
    m2_is_known_land_area = (
        property_type == "house"
        and m2 is not None
        and land_area_m2 is not None
        and built_area_m2 is None
        and _same_area_value(m2, land_area_m2)
    )
    if property_type == "apartment":
        built_area_m2 = built_area_m2 or usable_area_m2 or m2
        usable_area_m2 = usable_area_m2 or built_area_m2
        if "built_area_m2" not in area_sources and built_area_m2 is not None:
            area_sources["built_area_m2"] = (
                area_sources.get("usable_area_m2") or "raw.m2.fallback"
            )
        if "usable_area_m2" not in area_sources and usable_area_m2 is not None:
            area_sources["usable_area_m2"] = area_sources.get("built_area_m2") or "raw.m2.fallback"
    else:
        if m2_is_known_land_area:
            m2 = None
            warnings.append("m2_identified_as_land_area")
        built_area_m2 = built_area_m2 or m2
        if "built_area_m2" not in area_sources and built_area_m2 is not None:
            area_sources["built_area_m2"] = "raw.m2.fallback"
    if m2 is None and built_area_m2 is not None:
        m2 = built_area_m2
    if m2 is None:
        if not allow_incomplete:
            raise ValidationError("Campo requerido ausente: 'm2'")
        warnings.append("missing_m2")
    elif not MIN_M2 <= m2 <= MAX_M2:
        if not allow_incomplete:
            raise ValidationError(f"m2 fuera de rango [{MIN_M2}, {MAX_M2}]: {m2}")
        m2 = None
        warnings.append("missing_m2")

    bedrooms = _parse_int(
        raw.get("bedrooms", 0 if allow_incomplete else None),
        field_name="bedrooms",
    )
    if not 0 <= bedrooms <= MAX_BEDROOMS:
        raise ValidationError(f"bedrooms fuera de rango [0, {MAX_BEDROOMS}]: {bedrooms}")

    bathrooms = _parse_int(
        raw.get("bathrooms", 0 if allow_incomplete else None),
        field_name="bathrooms",
    )
    if not 0 <= bathrooms <= MAX_BATHROOMS:
        raise ValidationError(f"bathrooms fuera de rango [0, {MAX_BATHROOMS}]: {bathrooms}")

    parking = _parse_int(raw.get("parking", 0), field_name="parking")
    if parking < 0:
        raise ValidationError(f"parking no puede ser negativo: {parking}")

    price_int = _parse_price(raw.get("price_clp"), field_name="price_clp")
    if price_int < MIN_SALE_PRICE_CLP:
        raise ValidationError(f"price_clp {price_int} bajo el minimo ({MIN_SALE_PRICE_CLP})")
    price_provenance = _extract_price_provenance(raw, raw_metadata)
    raw_metadata.update(price_provenance.raw_metadata)

    coords = _parse_coords(raw.get("lat"), raw.get("lon"))
    geocode_precision = _infer_geocode_precision(raw, raw_metadata=raw_metadata, coordinates=coords, comuna=comuna)

    scraped_at = raw.get("scraped_at") or datetime.now(UTC)
    if not isinstance(scraped_at, datetime):
        raise ValidationError(f"scraped_at debe ser datetime, recibido: {type(scraped_at).__name__}")

    if warnings:
        raw_metadata["data_quality"] = "incomplete"
        raw_metadata["data_quality_warnings"] = sorted(set(warnings))
    _store_area_parse_metadata(
        raw_metadata,
        sources=area_sources,
        warnings=parsed_areas.warnings,
    )

    return CleanedListing(
        source=source,
        external_id=_optional_str(raw.get("external_id")),
        title=title,
        comuna=comuna,
        property_type=property_type,
        m2=m2,
        built_area_m2=built_area_m2,
        land_area_m2=land_area_m2,
        usable_area_m2=usable_area_m2,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        parking=parking,
        price=Price(clp=Decimal(price_int)),
        scraped_at=scraped_at,
        url=url,
        coordinates=coords,
        geocode_precision=geocode_precision,
        price_uf=price_provenance.price_uf,
        price_currency=price_provenance.price_currency,
        price_uf_confidence=price_provenance.price_uf_confidence,
        price_uf_source=price_provenance.price_uf_source,
        price_recovery_method=price_provenance.price_recovery_method,
        raw_metadata=raw_metadata,
    )


@dataclass(frozen=True)
class ComunaDetection:
    raw: str | None
    normalized: str | None
    source: str
    match_strategy: str | None = None
    match_value: str | None = None
    attempts: list[dict[str, str | None]] = field(default_factory=list)
    outside_rm_candidate: bool = False


@dataclass(frozen=True)
class ComunaMatch:
    normalized: str
    strategy: str
    value: str


def detect_comuna(raw: dict[str, Any], *, title: str | None = None) -> ComunaDetection:
    """Detecta comuna RM antes de validar: title, location text, description."""
    title_text = title or _optional_str(raw.get("title"))
    raw_metadata = raw.get("raw_metadata", {})
    metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
    candidates = [
        ("title", title_text),
        ("location", raw.get("location")),
        ("location", raw.get("location_text")),
        ("location", raw.get("address")),
        ("location", raw.get("address_label")),
        ("location", raw.get("comuna")),
        ("location", metadata.get("location")),
        ("location", metadata.get("address")),
        ("location", metadata.get("address_label")),
        ("description", raw.get("description")),
        ("description", raw.get("descripcion")),
        ("description", metadata.get("description")),
    ]
    fallback_raw: str | None = None
    fallback_source = "missing"
    attempts: list[dict[str, str | None]] = []
    outside_rm_candidate = False
    for source, value in candidates:
        text = _optional_str(value)
        if not text:
            continue
        normalized_text = normalize_location_text(text)
        outside_rm_candidate = outside_rm_candidate or _looks_outside_rm(normalized_text)
        if fallback_raw is None:
            fallback_raw = text
            fallback_source = source
        match = match_comuna_candidate(text)
        attempts.append({
            "source": source,
            "text": _snippet(text, max_chars=160),
            "normalized_text": normalized_text,
            "match_strategy": match.strategy if match else None,
            "match_value": match.value if match else None,
            "normalized_result": match.normalized if match else None,
        })
        if match is not None:
            return ComunaDetection(
                raw=text,
                normalized=match.normalized,
                source=source,
                match_strategy=match.strategy,
                match_value=match.value,
                attempts=attempts,
                outside_rm_candidate=outside_rm_candidate,
            )
    explicit_comuna = _optional_str(raw.get("comuna"))
    if explicit_comuna is not None:
        return ComunaDetection(
            raw=explicit_comuna,
            normalized=None,
            source="location",
            attempts=attempts,
            outside_rm_candidate=outside_rm_candidate,
        )
    if fallback_raw is None:
        return ComunaDetection(
            raw=None,
            normalized=None,
            source="missing",
            attempts=attempts,
            outside_rm_candidate=outside_rm_candidate,
        )
    return ComunaDetection(
        raw=fallback_raw,
        normalized=None,
        source=fallback_source,
        attempts=attempts,
        outside_rm_candidate=outside_rm_candidate,
    )


def normalize_comuna_candidate(value: str) -> str | None:
    """Normaliza aliases RM y coincidencias parciales a slug canonico."""
    match = match_comuna_candidate(value)
    return match.normalized if match else None


def match_comuna_candidate(value: str) -> ComunaMatch | None:
    """Normaliza aliases RM y retorna estrategia diagnostica del match."""
    text = normalize_location_text(value)
    if not text:
        return None
    slug = normalize_comuna(text)
    if is_known_comuna(text):
        return ComunaMatch(normalized=normalize_comuna(text), strategy="exact", value=text)
    if slug in _SLUG_TO_ALIAS_KEY:
        canonical = _SLUG_TO_ALIAS_KEY[slug]
        return ComunaMatch(
            normalized=normalize_comuna(canonical),
            strategy="exact",
            value=text,
        )
    if text in _ALIAS_TO_SLUG:
        return ComunaMatch(normalized=_ALIAS_TO_SLUG[text], strategy="alias", value=text)
    padded = f" {text} "
    matches: list[tuple[int, str]] = []
    for alias, alias_slug in _ALIAS_TO_SLUG.items():
        if f" {alias} " in padded:
            matches.append((len(alias), alias_slug))
    if not matches:
        return None
    matches.sort(reverse=True)
    matched_len, matched_slug = matches[0]
    matched_alias = next(
        alias
        for alias, alias_slug in _ALIAS_TO_SLUG.items()
        if alias_slug == matched_slug and len(alias) == matched_len and f" {alias} " in padded
    )
    return ComunaMatch(
        normalized=matched_slug,
        strategy="partial_match",
        value=matched_alias,
    )


def normalize_location_text(value: str) -> str:
    """Normaliza texto de ubicacion para diagnostico y matching."""
    text = _normalize_search_text(value)
    padded = f" {text} "
    for phrase in _LOCATION_NOISE_PHRASES:
        padded = padded.replace(f" {phrase} ", " ")
    tokens = [
        token
        for token in _SPACE_RE.sub(" ", padded).strip().split()
        if token not in _LOCATION_NOISE_TOKENS
    ]
    return " ".join(tokens)


def _normalize_search_text(value: str) -> str:
    no_accents = "".join(
        ch
        for ch in unicodedata.normalize("NFD", value.lower())
        if unicodedata.category(ch) != "Mn"
    )
    no_punct = _PUNCT_RE.sub(" ", no_accents)
    return _SPACE_RE.sub(" ", no_punct).strip()


def _looks_outside_rm(normalized_text: str) -> bool:
    padded = f" {normalized_text} "
    return any(f" {marker} " in padded for marker in _OUTSIDE_RM_MARKERS)


def _snippet(value: str, *, max_chars: int) -> str:
    text = _SPACE_RE.sub(" ", value).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _required_str(raw: dict, key: str) -> str:
    val = raw.get(key)
    if val is None or not str(val).strip():
        raise ValidationError(f"Campo requerido ausente o vacio: {key!r}")
    return str(val).strip()


def _optional_str(val: Any) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    return s or None


def _valid_url(url: str | None) -> bool:
    return bool(url and (url.startswith("http://") or url.startswith("https://")))


def normalize_property_type(value: Any, *, title: str = "", raw: dict[str, Any] | None = None) -> str:
    payload = dict(raw or {})
    if value is not None:
        payload["property_type"] = value
    if title:
        payload["title"] = title
    return infer_property_type(payload, title=title).value


def infer_property_type(raw: dict[str, Any], *, title: str = "") -> PropertyTypeGuess:
    """Clasifica tipo de propiedad desde señales del anuncio, no del target."""
    for source, value in _property_type_candidates(raw, title=title):
        text = _normalize_search_text(value)
        if not text:
            continue
        matched = _match_property_type(text)
        if matched is None:
            continue
        property_type, token = matched
        confidence = 0.98 if source == "property_type" else 0.88
        return PropertyTypeGuess(
            value=property_type,
            reason=f"{source}:{token}",
            confidence=confidence,
            source_fields=(source,),
        )
    return PropertyTypeGuess(
        value="unknown",
        reason="fallback:unknown",
        confidence=0.35,
        source_fields=(),
    )


def _property_type_candidates(raw: dict[str, Any], *, title: str) -> list[tuple[str, str]]:
    raw_metadata = raw.get("raw_metadata", {})
    metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
    candidates: list[tuple[str, Any]] = [
        ("property_type", raw.get("property_type")),
        ("category", raw.get("category")),
        ("category", raw.get("categoria")),
        ("category", metadata.get("category")),
        ("category", metadata.get("categoria")),
        ("breadcrumbs", metadata.get("breadcrumbs")),
        ("url", raw.get("url")),
        ("url", metadata.get("url")),
        ("title", title or raw.get("title")),
        ("description", raw.get("description")),
        ("description", raw.get("descripcion")),
        ("description", metadata.get("description")),
        ("description", metadata.get("descripcion")),
    ]
    out: list[tuple[str, str]] = []
    for source, value in candidates:
        text = _metadata_text(value)
        if text:
            out.append((source, text))
    return out


def _metadata_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        parts = [
            _metadata_text(item)
            for key, item in value.items()
            if key not in {"target_label", "target_scope", "target_query"}
        ]
        return " ".join(part for part in parts if part)
    if isinstance(value, list | tuple | set):
        parts = [_metadata_text(item) for item in value]
        return " ".join(part for part in parts if part)
    text = str(value).strip()
    return text or None


def _match_property_type(text: str) -> tuple[str, str] | None:
    padded = f" {text} "
    if text in PROPERTY_TYPES:
        return (text, text)
    for token in ("oficina", "oficinas", "office"):
        if f" {token} " in padded:
            return ("office", token)
    for token in ("casa", "casas", "house", "houses"):
        if f" {token} " in padded and not _house_false_positive(padded):
            return ("house", token)
    for token in ("terreno", "terrenos", "sitio", "sitios", "lote", "lotes", "land"):
        if f" {token} " in padded:
            return ("land", token)
    for token in ("departamento", "departamentos", "depto", "dpto", "apartment", "apartamento", "apartamentos"):
        if f" {token} " in padded:
            return ("apartment", token)
    return None


def _house_false_positive(padded_text: str) -> bool:
    false_phrases = (" casa matriz ", " casa central ", " casa comercial ")
    return any(phrase in padded_text for phrase in false_phrases)


def extract_area_fields(raw: dict[str, Any], *, title: str) -> dict[str, float]:
    return extract_area_fields_with_provenance(raw, title=title).areas


def extract_area_fields_with_provenance(raw: dict[str, Any], *, title: str) -> AreaParseResult:
    raw_metadata = raw.get("raw_metadata", {})
    metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
    property_type = infer_property_type(raw, title=title).value
    haystack = " ".join(
        str(part)
        for part in (
            title,
            raw.get("description"),
            raw.get("descripcion"),
            metadata.get("description"),
            metadata.get("descripcion"),
        )
        if part
    )
    normalized = _normalize_area_text(haystack)
    areas: dict[str, float] = {}
    sources: dict[str, str] = {}
    warnings: list[str] = []
    _extract_slash_area_pair(
        _normalize_area_pair_text(haystack),
        property_type=property_type,
        areas=areas,
        sources=sources,
        warnings=warnings,
    )
    for match in _AREA_RE.finditer(haystack):
        value = _parse_area_number(match.group("num"))
        if value is None:
            continue
        before = _normalize_area_text(haystack[max(0, match.start() - 48):match.start()])
        after = _normalize_area_text(haystack[match.end():min(len(haystack), match.end() + 48)])
        context = f"{before} {after}"
        if _looks_like_land_area(before, after):
            _set_area(areas, sources, warnings, "land_area_m2", value, "text.land_area_context")
        elif _looks_like_built_area(context):
            _set_area(areas, sources, warnings, "built_area_m2", value, "text.built_area_context")
        elif _looks_like_usable_area(context):
            _set_area(areas, sources, warnings, "usable_area_m2", value, "text.usable_area_context")
            _set_area(areas, sources, warnings, "built_area_m2", value, "text.usable_area_context")
        elif property_type == "apartment" and _looks_like_total_area(context):
            _set_area(areas, sources, warnings, "built_area_m2", value, "text.apartment_total_area")
    _extract_labeled_area_without_unit(normalized, areas=areas, sources=sources, warnings=warnings)
    if "built_area_m2" not in areas:
        built_match = re.search(r"(?:construidos?|edificados?)[^\d/]{0,12}(\d+(?:[.,]\d+)?)", normalized)
        if built_match:
            after = normalized[built_match.end():min(len(normalized), built_match.end() + 24)].strip()
            parsed = _parse_area_number(built_match.group(1))
            if parsed is not None and not after.startswith(("terreno", "sitio", "lote")):
                _set_area(areas, sources, warnings, "built_area_m2", parsed, "text.built_area_without_unit")
    return AreaParseResult(areas=areas, sources=sources, warnings=tuple(sorted(set(warnings))))


def _extract_slash_area_pair(
    normalized: str,
    *,
    property_type: str,
    areas: dict[str, float],
    sources: dict[str, str],
    warnings: list[str],
) -> None:
    for match in _AREA_PAIR_RE.finditer(normalized):
        first = _parse_area_number(match.group("first"))
        second = _parse_area_number(match.group("second"))
        if first is None or second is None or first <= 0 or second <= 0 or first > second:
            continue
        context = normalized[max(0, match.start() - 28):min(len(normalized), match.end() + 28)]
        if not any(
            token in context
            for token in ("m2", "m 2", "mts", "metros", "sup", "superficie", "util", "terreno", "constru")
        ):
            continue
        if property_type == "house":
            _set_area(areas, sources, warnings, "built_area_m2", first, "text.house_slash_area_pair")
            _set_area(areas, sources, warnings, "land_area_m2", second, "text.house_slash_area_pair")
        elif property_type == "apartment":
            _set_area(areas, sources, warnings, "usable_area_m2", first, "text.apartment_slash_area_pair")
            _set_area(areas, sources, warnings, "built_area_m2", second, "text.apartment_slash_area_pair")


def _extract_labeled_area_without_unit(
    normalized: str,
    *,
    areas: dict[str, float],
    sources: dict[str, str],
    warnings: list[str],
) -> None:
    for match in _LAND_AREA_WITHOUT_UNIT_RE.finditer(normalized):
        gap = match.group("gap")
        if _looks_like_code_gap(gap):
            continue
        parsed = _parse_area_number(match.group("num"))
        if parsed is not None:
            _set_area(areas, sources, warnings, "land_area_m2", parsed, "text.land_area_without_unit")
    for match in _LAND_AREA_REVERSE_WITHOUT_UNIT_RE.finditer(normalized):
        parsed = _parse_area_number(match.group("num"))
        if parsed is not None:
            _set_area(areas, sources, warnings, "land_area_m2", parsed, "text.land_area_without_unit")
    for match in _BUILT_AREA_WITHOUT_UNIT_RE.finditer(normalized):
        after = normalized[match.end():min(len(normalized), match.end() + 24)].strip()
        if after.startswith(("terreno", "sitio", "lote")):
            continue
        parsed = _parse_area_number(match.group("num"))
        if parsed is not None:
            _set_area(areas, sources, warnings, "built_area_m2", parsed, "text.built_area_without_unit")


def _looks_like_land_area(before: str, after: str) -> bool:
    after_text = after.strip()
    return after_text.startswith(("terreno", "de terreno", "sitio", "de sitio", "lote", "de lote")) or any(
        token in before
        for token in (
            "terreno",
            "terreno de",
            "sup terreno",
            "superficie terreno",
            "superficie de terreno",
            "superficie total terreno",
            "sitio",
            "lote",
            "m2 terreno",
            "mts2 terreno",
        )
    )


def _looks_like_code_gap(value: str) -> bool:
    return any(token in value for token in ("cod", "codigo", "código", "id", "ref"))


def _looks_like_built_area(context: str) -> bool:
    return any(
        token in context
        for token in (
            "construido",
            "construidos",
            "construida",
            "construidas",
            "edificado",
            "edificada",
            "construccion",
            "construcción",
            "edificacion",
            "edificación",
            "sup construida",
            "superficie construida",
        )
    )


def _looks_like_usable_area(context: str) -> bool:
    return any(token in context for token in ("util", "utiles", "interior"))


def _looks_like_total_area(context: str) -> bool:
    return any(token in context for token in ("total", "totales", "superficie total", "sup total"))


def _parse_optional_area(value: Any) -> float | None:
    if value in (None, ""):
        return None
    parsed = _parse_area_number(str(value))
    if parsed is None:
        return None
    return parsed if parsed > 0 else None


def _first_explicit_area(raw: dict[str, Any], keys: tuple[str, ...]) -> tuple[float | None, str | None]:
    for key in keys:
        parsed = _parse_optional_area(raw.get(key))
        if parsed is not None:
            return parsed, f"raw.{key}"
    return None, None


def _prefer_existing_area(
    current: float | None,
    parsed: float | None,
    sources: dict[str, str],
    field: str,
    parsed_source: str | None,
) -> float | None:
    if current is not None:
        return current
    if parsed is None:
        return None
    if parsed_source is not None:
        sources[field] = parsed_source
    return parsed


def _same_area_value(left: float, right: float) -> bool:
    return abs(float(left) - float(right)) < 0.01


def _set_area(
    areas: dict[str, float],
    sources: dict[str, str],
    warnings: list[str],
    field: str,
    value: float,
    source: str,
) -> None:
    if value <= 0:
        return
    current = areas.get(field)
    if current is not None:
        if current != value:
            warnings.append(f"ignored_{field}_from_{source}")
        return
    areas[field] = value
    sources[field] = source


def _store_area_parse_metadata(
    raw_metadata: dict[str, Any],
    *,
    sources: dict[str, str],
    warnings: tuple[str, ...],
) -> None:
    if not sources and not warnings:
        return
    raw_metadata["area_parse_version"] = _AREA_PARSE_VERSION
    raw_metadata["area_parse_source"] = "mixed" if len(set(sources.values())) > 1 else next(iter(sources.values()), None)
    if warnings:
        existing = raw_metadata.get("area_parse_warnings", [])
        existing_warnings = existing if isinstance(existing, list) else [str(existing)]
        raw_metadata["area_parse_warnings"] = sorted({*existing_warnings, *warnings})
    for area_field in _AREA_FIELDS:
        source = sources.get(area_field)
        if source is not None:
            raw_metadata[f"{area_field.removesuffix('_m2')}_parse_source"] = source


def _parse_area_number(value: str) -> float | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    if "." in cleaned and "," in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "." in cleaned:
        parts = cleaned.split(".")
        if len(parts) > 1 and all(len(part) == 3 for part in parts[1:]) and len(parts[0]) <= 3:
            cleaned = "".join(parts)
    elif "," in cleaned:
        parts = cleaned.split(",")
        if len(parts) > 1 and all(len(part) == 3 for part in parts[1:]) and len(parts[0]) <= 3:
            cleaned = "".join(parts)
        else:
            cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _normalize_area_text(value: str) -> str:
    return _normalize_search_text(value).replace("m 2", "m2")


def _normalize_area_pair_text(value: str) -> str:
    no_accents = "".join(
        ch
        for ch in unicodedata.normalize("NFD", value.lower())
        if unicodedata.category(ch) != "Mn"
    )
    text = re.sub(r"[^a-z0-9/\s]", " ", no_accents)
    return _SPACE_RE.sub(" ", text).strip().replace("m 2", "m2")


def _parse_optional_m2(val: Any, *, title: str, raw: dict[str, Any]) -> float | None:
    parsed = _parse_area_value(val)
    if parsed is not None and parsed > 0:
        return parsed

    haystack = " ".join(
        str(part)
        for part in (
            title,
            raw.get("description"),
            raw.get("descripcion"),
            raw.get("raw_metadata", {}).get("description")
            if isinstance(raw.get("raw_metadata"), dict)
            else None,
        )
        if part
    )
    match = _M2_RE.search(haystack)
    if not match:
        return None
    return _parse_area_number(match.group("num"))


def _parse_area_value(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    if isinstance(value, int | float | Decimal):
        parsed = float(value)
        return parsed if parsed > 0 else None
    return _parse_area_number(str(value))


def _parse_float(val: Any, *, field_name: str) -> float:
    if val is None:
        raise ValidationError(f"Campo requerido ausente: {field_name!r}")
    try:
        return float(val)
    except (TypeError, ValueError) as e:
        raise ValidationError(f"{field_name} no numerico: {val!r}") from e


def _parse_int(val: Any, *, field_name: str) -> int:
    if val is None:
        raise ValidationError(f"Campo requerido ausente: {field_name!r}")
    try:
        return int(float(val))
    except (TypeError, ValueError) as e:
        raise ValidationError(f"{field_name} no entero: {val!r}") from e


def _parse_price(val: Any, *, field_name: str) -> int:
    if val is None:
        raise ValidationError(f"missing_price: {field_name!r}")
    if isinstance(val, bool):
        raise ValidationError(f"{field_name} no puede ser booleano")
    if isinstance(val, int | Decimal | float):
        return int(val)
    s = str(val).strip()
    for noise in ("$", ".", ",", " ", "CLP", "clp"):
        s = s.replace(noise, "")
    try:
        return int(s)
    except ValueError as e:
        raise ValidationError(f"missing_price: {val!r}") from e


def _extract_price_provenance(raw: dict[str, Any], raw_metadata: dict[str, Any]) -> PriceProvenance:
    currency = _normalize_price_currency(
        raw.get("price_currency")
        or raw.get("currency_original")
        or raw.get("currency")
        or raw_metadata.get("price_currency")
        or raw_metadata.get("currency_original")
        or raw_metadata.get("currency")
    )
    price_uf = _parse_decimal_optional(raw.get("price_uf"))
    if price_uf is None:
        price_uf = _parse_decimal_optional(raw_metadata.get("price_uf"))

    metadata: dict[str, Any] = {}
    if currency is not None:
        metadata.setdefault("currency_original", currency)
    if price_uf is not None:
        metadata.setdefault("price_uf", float(price_uf))
        currency = currency or "UF"

    confidence = _optional_str(
        raw.get("price_uf_confidence")
        or raw_metadata.get("price_uf_confidence")
        or raw_metadata.get("price_confidence")
    )
    source = _optional_str(
        raw.get("price_uf_source")
        or raw_metadata.get("price_uf_source")
        or raw_metadata.get("price_source")
    )
    method = _optional_str(
        raw.get("price_recovery_method")
        or raw_metadata.get("price_recovery_method")
    )

    if currency == "UF" and price_uf is not None:
        confidence = confidence or "high"
        source = source or "scraped"
        method = method or ("raw.price_uf" if raw.get("price_uf") is not None else "raw_metadata.price_uf")
    elif currency == "CLP":
        price_uf = None
        source = source or "scraped"
        method = method or "raw_metadata.currency_original"

    return PriceProvenance(
        price_uf=price_uf,
        price_currency=currency,
        price_uf_confidence=confidence,
        price_uf_source=source,
        price_recovery_method=method,
        raw_metadata=metadata,
    )


def _normalize_price_currency(value: Any) -> str | None:
    text = _optional_str(value)
    if not text:
        return None
    normalized = text.upper().replace("$", "CLP").strip()
    if normalized in {"UF", "CLF"}:
        return "UF"
    if normalized in {"CLP", "PESO", "PESOS", "CHILEAN PESO"}:
        return "CLP"
    return normalized[:16]


def _parse_decimal_optional(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value).replace(",", ".").strip())
    except (InvalidOperation, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed.quantize(Decimal("0.01"))


def _parse_coords(lat: Any, lon: Any) -> Coordinates | None:
    if lat is None or lon is None:
        return None
    try:
        return Coordinates(lat=float(lat), lon=float(lon))
    except (TypeError, ValueError) as e:
        raise ValidationError(f"Coordenadas invalidas: lat={lat!r}, lon={lon!r}") from e


def _infer_geocode_precision(
    raw: dict[str, Any],
    *,
    raw_metadata: dict[str, Any],
    coordinates: Coordinates | None,
    comuna: str,
) -> str | None:
    explicit = _optional_str(raw.get("geocode_precision") or raw_metadata.get("geocode_precision"))
    location_hint = " ".join(
        value
        for value in (
            _optional_str(raw.get("address")),
            _optional_str(raw.get("address_label")),
            _optional_str(raw.get("street_hint")),
            _optional_str(raw.get("neighborhood")),
            _optional_str(raw.get("subcomuna")),
            _optional_str(raw_metadata.get("address")),
            _optional_str(raw_metadata.get("address_label")),
            _optional_str(raw_metadata.get("street_hint")),
            _optional_str(raw_metadata.get("neighborhood")),
            _optional_str(raw_metadata.get("subcomuna")),
        )
        if value
    )
    if explicit:
        return normalize_geocode_precision(
            explicit,
            has_coords=coordinates is not None,
            raw_metadata=raw_metadata,
            comuna=comuna,
        )
    if location_hint:
        return "street"
    if coordinates is not None:
        return "address"
    if comuna and comuna != "unknown":
        return "comuna"
    return "unknown"
