"""Recover auditable geographic text signals without geocoding.

This module extracts location hints from Yapo text and stores them as
provenance-rich candidates. It does not create coordinates and does not change
valuation confidence or comparable scoring.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any, Iterable

GEO_SIGNAL_RECOVERY_VERSION = "geo_signal_recovery_v1"

_SPACE_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"[^a-z0-9\s_/.-]")
_FEATURES_RE = re.compile(
    r"\b(?:caracteristicas|característica|características|caracteristicas principales|descripcion|descripción|precio|"
    r"dormitorios?|baños?|banos?|estacionamientos?|bodega|superficie|m2|uf)\b",
    re.IGNORECASE,
)
_STOP_WORD_RE = re.compile(
    r"\b(?:en venta|venta|vende|departamento|depto|dpto|casa|casas|dormitorios?|dorm|"
    r"baños?|banos?|estacionamientos?|estac|bodega|uf|m2|comuna|region metropolitana|"
    r"región metropolitana|chile|propiedades|yapo)\b",
    re.IGNORECASE,
)
_MARKETING_RE = re.compile(
    r"\b(?:amplio|amplia|oportunidad|excelente|vista|vistas|espectacular|espectaculares|"
    r"luminos[oa]|moderno|moderna|remodelad[oa]|tranquil[oa]|equipad[oa]|maravillos[oa]|"
    r"gran|inversion|inversión|seguro|segura|conectad[oa]|precioso|preciosa)\b",
    re.IGNORECASE,
)
_GENERIC_VALUES = {
    "central",
    "centro",
    "sur",
    "norte",
    "oriente",
    "poniente",
    "residencial",
    "residencial consolidado",
    "sector residencial",
    "region metropolitana",
    "metropolitana",
    "santiago",
    "chile",
}

_STREET_MARKER_PATTERN = re.compile(
    r"\b(?P<marker>calle|pasaje|camino|diagonal)\s+(?P<name>[A-Za-zÁÉÍÓÚÑáéíóúñ0-9 .'-]{3,64})",
    re.IGNORECASE,
)
_AVENUE_PATTERN = re.compile(
    r"\b(?P<marker>av\.?|avenida|avda\.?)\s+(?P<name>[A-Za-zÁÉÍÓÚÑáéíóúñ0-9 .'-]{3,64})",
    re.IGNORECASE,
)
_METRO_PATTERN = re.compile(
    r"\b(?:a\s+pasos\s+de\s+|cerca\s+de\s+|cercano\s+a\s+|frente\s+a\s+)?"
    r"(?P<prefix>metro|estaci[oó]n)\s+(?P<name>[A-Za-zÁÉÍÓÚÑáéíóúñ0-9 .'-]{3,50})",
    re.IGNORECASE,
)
_INTERSECTION_PATTERNS = (
    re.compile(
        r"\b(?P<left>[A-Za-zÁÉÍÓÚÑáéíóúñ0-9 .'-]{3,50})\s*/\s*"
        r"(?P<right>[A-Za-zÁÉÍÓÚÑáéíóúñ0-9 .'-]{3,50})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<left>[A-Za-zÁÉÍÓÚÑáéíóúñ0-9 .'-]{3,50})\s+(?:con|esquina)\s+"
        r"(?P<right>[A-Za-zÁÉÍÓÚÑáéíóúñ0-9 .'-]{3,50})\b",
        re.IGNORECASE,
    ),
)
_LANDMARK_PATTERNS = (
    ("plaza", re.compile(r"\bplaza\s+(?P<name>[A-Za-zÁÉÍÓÚÑáéíóúñ0-9 .'-]{3,45})", re.IGNORECASE)),
    ("parque", re.compile(r"\bparque\s+(?P<name>[A-Za-zÁÉÍÓÚÑáéíóúñ0-9 .'-]{3,45})", re.IGNORECASE)),
    ("mall", re.compile(r"\bmall\s+(?P<name>[A-Za-zÁÉÍÓÚÑáéíóúñ0-9 .'-]{3,45})", re.IGNORECASE)),
    ("barrio", re.compile(r"\bbarrio\s+(?P<name>[A-Za-zÁÉÍÓÚÑáéíóúñ0-9 .'-]{3,45})", re.IGNORECASE)),
    ("sector", re.compile(r"\bsector\s+(?P<name>[A-Za-zÁÉÍÓÚÑáéíóúñ0-9 .'-]{3,45})", re.IGNORECASE)),
    ("condominio", re.compile(r"\bcondominio\s+(?P<name>[A-Za-zÁÉÍÓÚÑáéíóúñ0-9 .'-]{3,55})", re.IGNORECASE)),
    ("edificio", re.compile(r"\b(?:edificio|proyecto)\s+(?P<name>[A-Za-zÁÉÍÓÚÑáéíóúñ0-9 .'-]{3,55})", re.IGNORECASE)),
)


@dataclass(frozen=True)
class GeoSignalCandidate:
    value: str
    normalized_value: str
    signal_type: str
    source: str
    confidence: str
    rule: str
    raw_text: str
    created_by_version: str = GEO_SIGNAL_RECOVERY_VERSION

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GeoSignalRecovery:
    candidates: tuple[GeoSignalCandidate, ...]
    rejected: tuple[dict[str, str], ...]


def recover_geo_signals(
    *,
    title: str | None = None,
    raw_metadata: dict[str, Any] | None = None,
    url: str | None = None,
    card_text: str | None = None,
    detail_text: str | None = None,
) -> GeoSignalRecovery:
    """Extract auditable geographic signals from structured and free text."""
    metadata = raw_metadata or {}
    text_sources: list[tuple[str, str | None, str]] = [
        ("metadata_address", _metadata_str(metadata, "address"), "metadata.address"),
        ("metadata_address", _metadata_str(metadata, "address_label"), "metadata.address_label"),
        ("metadata_street_hint", _metadata_str(metadata, "street_hint"), "metadata.street_hint"),
        ("metadata_location_text", _metadata_str(metadata, "location_text"), "metadata.location_text"),
        ("metadata_location_text", _metadata_str(metadata, "location"), "metadata.location"),
        ("metadata_location_text", _metadata_str(metadata, "neighborhood"), "metadata.neighborhood"),
        ("existing_microzone_metadata", _prefixed_metadata(metadata, "nearby_metro", "Metro"), "metadata.nearby_metro"),
        ("existing_microzone_metadata", _prefixed_metadata(metadata, "nearby_avenue", "Avenida"), "metadata.nearby_avenue"),
        ("existing_microzone_metadata", _prefixed_metadata(metadata, "neighborhood_hint", "Sector"), "metadata.neighborhood_hint"),
        ("existing_microzone_metadata", _metadata_str(metadata, "intersection_hint"), "metadata.intersection_hint"),
        ("title", title, "title"),
        ("url_slug", _url_slug_text(url), "url_slug"),
        ("card_text", card_text, "card_text"),
        ("detail_text", detail_text, "detail_text"),
        ("detail_text", _metadata_str(metadata, "description"), "metadata.description"),
    ]
    for label, value in _detail_labeled_values(detail_text):
        text_sources.insert(0, ("detail_exact_address" if label == "direccion_exacta" else "detail_text", value, label))

    candidates: list[GeoSignalCandidate] = []
    rejected: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for source, value, source_rule in text_sources:
        if not value:
            continue
        for candidate, rejection in _extract_candidates_from_text(value, source=source, source_rule=source_rule):
            if rejection is not None:
                rejected.append(rejection)
                continue
            assert candidate is not None
            key = (candidate.signal_type, candidate.normalized_value, candidate.source)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(candidate)
    return GeoSignalRecovery(tuple(candidates), tuple(rejected))


def enrich_raw_metadata_with_geo_signals(
    raw_metadata: dict[str, Any],
    *,
    title: str | None = None,
    url: str | None = None,
    card_text: str | None = None,
    detail_text: str | None = None,
) -> dict[str, Any]:
    """Return metadata with geo_signal_candidates, preserving existing keys."""
    metadata = dict(raw_metadata or {})
    recovery = recover_geo_signals(
        title=title,
        raw_metadata=metadata,
        url=url,
        card_text=card_text,
        detail_text=detail_text,
    )
    existing = _existing_candidates(metadata)
    merged = _merge_candidates(existing, [candidate.as_dict() for candidate in recovery.candidates])
    metadata["geo_signal_candidates"] = merged
    metadata["geo_signal_recovery_version"] = GEO_SIGNAL_RECOVERY_VERSION
    if recovery.rejected:
        metadata["geo_signal_rejected"] = _merge_rejections(
            metadata.get("geo_signal_rejected"),
            [dict(item) for item in recovery.rejected],
        )
    return metadata


def normalize_geo_signal_value(value: str) -> str:
    normalized = _normalize(value)
    normalized = re.sub(r"\b(av|avenida|avda)\b", "avenida", normalized)
    normalized = re.sub(r"\s+", "_", normalized.strip())
    return normalized


def _extract_candidates_from_text(
    text: str,
    *,
    source: str,
    source_rule: str,
) -> Iterable[tuple[GeoSignalCandidate | None, dict[str, str] | None]]:
    clean_text = _clean_raw_text(text)
    if not clean_text:
        return

    for rule, signal_type, pattern in (
        ("street_pattern", "street", _STREET_MARKER_PATTERN),
        ("avenue_pattern", "avenue", _AVENUE_PATTERN),
        ("metro_pattern", "metro", _METRO_PATTERN),
    ):
        for match in pattern.finditer(clean_text):
            marker = match.groupdict().get("marker") or match.groupdict().get("prefix") or signal_type
            value = _clean_candidate_value(f"{marker} {match.group('name')}")
            yield _candidate_or_rejection(value, signal_type, source, confidence_for(source, signal_type), rule, text)

    for pattern in _INTERSECTION_PATTERNS:
        for match in pattern.finditer(clean_text):
            left = _clean_intersection_side(match.group("left"))
            right = _clean_intersection_side(match.group("right"))
            if left and right:
                value = f"{left} y {right}"
                yield _candidate_or_rejection(value, "intersection", source, confidence_for(source, "intersection"), "intersection_pattern", text)

    for signal_type, pattern in _LANDMARK_PATTERNS:
        for match in pattern.finditer(clean_text):
            value = _clean_candidate_value(f"{signal_type} {match.group('name')}")
            yield _candidate_or_rejection(value, signal_type, source, confidence_for(source, signal_type), f"{signal_type}_pattern", text)


def confidence_for(source: str, signal_type: str) -> str:
    if source == "detail_exact_address":
        return "high"
    if source in {"metadata_address", "metadata_street_hint"}:
        return "medium"
    if source == "existing_microzone_metadata":
        return "medium" if signal_type in {"metro", "avenue", "intersection"} else "low"
    if source in {"title", "url_slug"}:
        return "low"
    if signal_type in {"metro", "avenue", "street", "intersection"} and source in {"card_text", "detail_text"}:
        return "medium"
    return "low"


def _candidate_or_rejection(
    value: str,
    signal_type: str,
    source: str,
    confidence: str,
    rule: str,
    raw_text: str,
) -> tuple[GeoSignalCandidate | None, dict[str, str] | None]:
    if not value:
        return None, None
    normalized = normalize_geo_signal_value(value)
    reason = _rejection_reason(value, normalized=normalized, source=source, signal_type=signal_type)
    if reason:
        return None, {
            "value": value,
            "signal_type": signal_type,
            "source": source,
            "rule": rule,
            "reason": reason,
            "created_by_version": GEO_SIGNAL_RECOVERY_VERSION,
        }
    return GeoSignalCandidate(
        value=value,
        normalized_value=normalized,
        signal_type=signal_type,
        source=source,
        confidence=confidence,
        rule=rule,
        raw_text=_trim_raw_text(raw_text),
    ), None


def _clean_raw_text(value: str) -> str:
    value = re.sub(r"([a-záéíóúñ])([A-ZÁÉÍÓÚÑ])", r"\1 \2", str(value))
    value = _FEATURES_RE.split(value, maxsplit=1)[0]
    return _SPACE_RE.sub(" ", value).strip(" ,.-|")


def _clean_candidate_value(value: str) -> str:
    value = _FEATURES_RE.split(value, maxsplit=1)[0]
    value = _STOP_WORD_RE.split(value, maxsplit=1)[0]
    value = re.sub(r"\s+", " ", value).strip(" ,.-/|")
    return value[:80].strip()


def _clean_intersection_side(value: str) -> str:
    value = _FEATURES_RE.split(value, maxsplit=1)[0]
    words = []
    for word in re.split(r"\s+", value.strip(" ,.-/|")):
        normalized = _normalize(word)
        if normalized in {"departamento", "depto", "dpto", "casa", "casas", "venta", "vende", "av", "avenida", "calle"}:
            continue
        words.append(word)
    return _clean_candidate_value(" ".join(words[-4:]))


def _rejection_reason(value: str, *, normalized: str, source: str, signal_type: str) -> str | None:
    compact = normalized.replace("_", " ")
    if compact in _GENERIC_VALUES:
        return "generic_location_signal"
    words = [word for word in compact.split() if word]
    if len(compact) < 3 or not words:
        return "too_short"
    if signal_type in {"street", "avenue", "intersection"} and _MARKETING_RE.search(value):
        return "marketing_text"
    if source == "title" and signal_type in {"condominio", "edificio"} and len(words) <= 2:
        return "weak_title_project_signal"
    return None


def _metadata_str(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _prefixed_metadata(metadata: dict[str, Any], key: str, prefix: str) -> str | None:
    value = _metadata_str(metadata, key)
    if not value:
        return None
    if _normalize(value).startswith(_normalize(prefix)):
        return value
    return f"{prefix} {value}"


def _detail_labeled_values(detail_text: str | None) -> list[tuple[str, str]]:
    if not detail_text:
        return []
    normalized = _space_preserving(detail_text)
    values: list[tuple[str, str]] = []
    label_patterns = (
        ("direccion_exacta", r"(?:Direcci[oó]n exacta|Direccion exacta)\s*:?\s*(.{3,140})"),
        ("localizacion", r"(?:Localizaci[oó]n|Ubicaci[oó]n|Ubicacion)\s*:?\s*(.{3,120})"),
    )
    stop = re.compile(
        r"\b(?:Costos de mantenimiento|Niveles|Piscina|Tipo de pisos|Piso N[uú]mero|"
        r"Descripci[oó]n|Publicado|Precio|Dormitorios|Baños|Banos|Estacionamientos|"
        r"Area construida|Área construida|Localizaci[oó]n)\b",
        re.IGNORECASE,
    )
    for label, pattern in label_patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if not match:
            continue
        value = stop.split(match.group(1), maxsplit=1)[0].strip(" ,.-")
        if value:
            values.append((label, value))
    return values


def _url_slug_text(url: str | None) -> str | None:
    if not url:
        return None
    path = str(url).split("?", 1)[0].rstrip("/")
    slug = path.rsplit("/", 2)[-2] if "/" in path else path
    slug = slug.replace("-", " ").replace("_", " ")
    return slug or None


def _existing_candidates(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    value = metadata.get("geo_signal_candidates")
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _merge_candidates(existing: list[dict[str, Any]], new: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in [*existing, *new]:
        signal_type = str(item.get("signal_type") or "")
        normalized = str(item.get("normalized_value") or normalize_geo_signal_value(str(item.get("value") or "")))
        source = str(item.get("source") or "")
        if not signal_type or not normalized:
            continue
        key = (signal_type, normalized, source)
        if key in seen:
            continue
        seen.add(key)
        merged.append({**item, "normalized_value": normalized})
    return merged


def _merge_rejections(existing: Any, new: list[dict[str, str]]) -> list[dict[str, str]]:
    current = [dict(item) for item in existing if isinstance(item, dict)] if isinstance(existing, list) else []
    seen = {(item.get("value"), item.get("source"), item.get("reason")) for item in current}
    for item in new:
        key = (item.get("value"), item.get("source"), item.get("reason"))
        if key not in seen:
            current.append(item)
            seen.add(key)
    return current[:50]


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value).lower())
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    clean = _TOKEN_RE.sub(" ", ascii_text)
    return _SPACE_RE.sub(" ", clean).strip(" .-/")


def _space_preserving(value: str) -> str:
    return _SPACE_RE.sub(" ", str(value)).strip()


def _trim_raw_text(value: str) -> str:
    return _SPACE_RE.sub(" ", str(value)).strip()[:240]
