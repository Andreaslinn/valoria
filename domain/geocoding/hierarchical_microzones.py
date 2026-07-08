"""Read-only hierarchical microzone assignment.

This module turns existing coordinate and text signals into a conservative
hierarchy. It never creates coordinates and does not change productive AVM or
Radar behavior.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from core.normalization.geocode_precision import canonical_geocode_precision
from domain.geocoding.geo_signals import GeoSignalCandidate, recover_geo_signals
from domain.geocoding.geographic_microzones import geographic_microzone_for
from domain.geocoding.microzones import extract_microzone_signals

REAL_GEO_PRECISIONS = frozenset({"address", "street"})
CORRIDOR_SIGNAL_TYPES = frozenset({"avenue", "metro", "barrio", "sector", "plaza", "parque"})
LEVEL_NAMES = {
    0: "level_0",
    1: "level_1",
    2: "level_2",
    3: "level_3",
    4: "level_4",
}

_SPACE_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"[^a-z0-9\s]")
_STREET_MARKER_RE = re.compile(r"\b(calle|pasaje|camino|diagonal)\s+(.+)")
_AVENUE_MARKER_RE = re.compile(r"\b(avenida|av|avda)\s+(.+)")
_INTERSECTION_SPLIT_RE = re.compile(r"\s+(?:con|esquina|y)\s+|/")
_NOISE_WORDS = {
    "departamento",
    "depto",
    "dpto",
    "venta",
    "vende",
    "arriendo",
    "oportunidad",
    "amplio",
    "amplia",
    "luminoso",
    "luminosa",
    "excelente",
    "estacionamiento",
    "estacionamientos",
    "bodega",
    "nuevo",
    "nueva",
    "remodelado",
    "remodelada",
    "inversion",
    "propiedad",
    "casa",
    "casas",
    "cuenta",
    "edificio",
    "emplazado",
    "emplazada",
    "sectorial",
    "tiene",
}
_GENERIC_SIGNALS = {
    "avenida",
    "barrio",
    "calle",
    "cercano",
    "centro",
    "comercio",
    "excelente ubicacion",
    "locomocion",
    "metro",
    "sector",
    "ubicacion",
}
_ABBREVIATIONS = (
    (re.compile(r"\bavda?\b"), "avenida"),
    (re.compile(r"\bpdte\b"), "presidente"),
    (re.compile(r"\bgral\b"), "general"),
    (re.compile(r"\bsta\b"), "santa"),
    (re.compile(r"\bsto\b"), "santo"),
)
_KNOWN_METRO_KEYS = {
    "cal_y_canto",
    "central",
    "cerro_blanco",
    "ciudad_del_nino",
    "departamental",
    "dorsal",
    "escuela_militar",
    "hospitales",
    "ines_de_suarez",
    "las_rejas",
    "las_torres",
    "lo_ovalle",
    "macul",
    "manquehue",
    "parque_almagro",
    "pedro_de_valdivia",
    "plaza_chacabuco",
    "plaza_egana",
    "principe_de_gales",
    "quilin",
    "rodrigo_de_araya",
    "simon_bolivar",
    "tobalaba",
}
_KNOWN_AVENUE_KEYS = {
    "americo_vespucio",
    "brasil",
    "consistorial",
    "echequenique",
    "grecia",
    "irrarazaval",
    "las_condes",
    "las_rejas",
    "macul",
    "ossa",
    "ossandon",
    "pedro_de_valdivia",
    "portugal",
    "providencia",
    "rodrigo_de_araya",
    "santa_rosa",
    "tomas_moro",
    "vicuna_mackenna",
    "camino_la_posada",
    "suarez_mujica",
}


@dataclass(frozen=True)
class HierarchicalMicrozoneAssignment:
    comuna_key: str | None
    level_0_key: str | None
    level_1_key: str | None
    level_2_key: str | None
    level_3_key: str | None
    level_4_key: str | None
    level_1_kind: str | None
    level_2_kind: str | None
    level_3_kind: str | None
    level_4_kind: str | None
    best_available_level: int
    best_available_key: str | None
    confidence: str
    matched_signals: tuple[dict[str, Any], ...]
    source_fields: tuple[str, ...]
    warnings: tuple[str, ...]
    is_real_microzone: bool
    is_fallback_only: bool
    does_not_invent_coordinates: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "comuna_key": self.comuna_key,
            "level_0_key": self.level_0_key,
            "level_1_key": self.level_1_key,
            "level_2_key": self.level_2_key,
            "level_3_key": self.level_3_key,
            "level_4_key": self.level_4_key,
            "level_1_kind": self.level_1_kind,
            "level_2_kind": self.level_2_kind,
            "level_3_kind": self.level_3_kind,
            "level_4_kind": self.level_4_kind,
            "best_available_level": self.best_available_level,
            "best_available_key": self.best_available_key,
            "confidence": self.confidence,
            "matched_signals": [dict(item) for item in self.matched_signals],
            "source_fields": list(self.source_fields),
            "warnings": list(self.warnings),
            "is_real_microzone": self.is_real_microzone,
            "is_fallback_only": self.is_fallback_only,
            "does_not_invent_coordinates": self.does_not_invent_coordinates,
        }


def assign_hierarchical_microzone(value: Any) -> HierarchicalMicrozoneAssignment:
    comuna_key = _normalize_key(_get(value, "comuna"))
    raw_metadata = _raw_metadata(value)
    title = _optional_str(_get(value, "title"))
    url = _optional_str(_get(value, "url"))
    warnings: list[str] = []
    matched_signals: list[dict[str, Any]] = []
    source_fields: set[str] = set()

    level_0_key = f"comuna:{comuna_key}" if comuna_key else None
    if not comuna_key:
        warnings.append("missing_comuna")

    geo = geographic_microzone_for(_geo_value(value))
    level_4_key = None
    level_4_kind = None
    level_4_confidence = "none"
    if geo.microzone is not None and geo.precision in REAL_GEO_PRECISIONS:
        level_4_key = geo.microzone.microzone_id
        level_4_kind = "geo_500m"
        level_4_confidence = geo.microzone.confidence_level
        matched_signals.append(
            _signal_dict(
                level=4,
                kind="geo_500m",
                value=level_4_key,
                source="lat_lon",
                confidence=level_4_confidence,
                field="lat_lon",
            )
        )
        source_fields.add("lat_lon")
    else:
        warnings.append(f"level_4_{geo.reason}")

    recovery = recover_geo_signals(title=title, raw_metadata=raw_metadata, url=url)
    candidates = tuple(_usable_candidates(recovery.candidates, comuna_key=comuna_key))
    signals = extract_microzone_signals(title=title, raw_metadata=raw_metadata)

    level_3 = _level_3(candidates, comuna_key=comuna_key)
    level_2 = _level_2(candidates, signals, comuna_key=comuna_key)
    level_1 = _level_1(candidates, signals, comuna_key=comuna_key)

    for level, selected in ((3, level_3), (2, level_2), (1, level_1)):
        if selected is None:
            continue
        matched_signals.append(
            _signal_dict(
                level=level,
                kind=selected["kind"],
                value=selected["value"],
                source=selected["source"],
                confidence=selected["confidence"],
                field=selected["field"],
            )
        )
        source_fields.add(str(selected["field"]))

    for rejection in _rejection_warnings(recovery.candidates, comuna_key=comuna_key):
        warnings.append(rejection)

    keys_by_level = {
        4: level_4_key,
        3: _selected_key(level_3),
        2: _selected_key(level_2),
        1: _selected_key(level_1),
        0: level_0_key,
    }
    best_level = max((level for level, key in keys_by_level.items() if key), default=-1)
    best_key = keys_by_level.get(best_level)
    confidence = _best_confidence(
        best_level=best_level,
        level_4_confidence=level_4_confidence,
        level_3=level_3,
        level_2=level_2,
        level_1=level_1,
    )

    if best_level == 0:
        warnings.append("comuna_fallback_not_real_microzone")
    if not source_fields and level_0_key:
        source_fields.add("comuna")

    return HierarchicalMicrozoneAssignment(
        comuna_key=comuna_key,
        level_0_key=level_0_key,
        level_1_key=keys_by_level[1],
        level_2_key=keys_by_level[2],
        level_3_key=keys_by_level[3],
        level_4_key=keys_by_level[4],
        level_1_kind=_selected_kind(level_1),
        level_2_kind=_selected_kind(level_2),
        level_3_kind=_selected_kind(level_3),
        level_4_kind=level_4_kind,
        best_available_level=best_level,
        best_available_key=best_key,
        confidence=confidence,
        matched_signals=tuple(matched_signals),
        source_fields=tuple(sorted(source_fields)),
        warnings=tuple(_dedupe(warnings)),
        is_real_microzone=best_level >= 1,
        is_fallback_only=best_level == 0,
        does_not_invent_coordinates=True,
    )


def _level_3(candidates: tuple[GeoSignalCandidate, ...], *, comuna_key: str | None) -> dict[str, str] | None:
    if not comuna_key:
        return None
    intersections = [
        candidate for candidate in candidates
        if candidate.signal_type == "intersection" and _specific_intersection(candidate.normalized_value)
    ]
    if intersections:
        candidate = _best_candidate(intersections)
        confidence = "medium" if candidate.source in {"title", "url_slug"} else candidate.confidence
        return _selected("intersection", comuna_key, candidate.normalized_value, candidate, confidence=confidence)

    streets = [
        candidate for candidate in candidates
        if candidate.signal_type == "street" and _specific_street(candidate.normalized_value)
    ]
    if not streets:
        return None
    candidate = _best_candidate(streets)
    if candidate.source in {"title", "url_slug"} and candidate.confidence == "low":
        return None
    confidence = "high" if candidate.source == "detail_exact_address" else candidate.confidence
    return _selected("street_microzone", comuna_key, candidate.normalized_value, candidate, confidence=confidence)


def _level_2(
    candidates: tuple[GeoSignalCandidate, ...],
    signals: Any,
    *,
    comuna_key: str | None,
) -> dict[str, str] | None:
    if not comuna_key:
        return None
    candidates_by_type: list[tuple[str, GeoSignalCandidate]] = []
    for candidate in candidates:
        if candidate.signal_type == "metro" and _specific_corridor(candidate.normalized_value, comuna_key):
            candidates_by_type.append(("metro_corridor", candidate))
        elif candidate.signal_type == "avenue" and _specific_corridor(candidate.normalized_value, comuna_key):
            candidates_by_type.append(("avenue_corridor", candidate))
        elif candidate.signal_type in {"barrio", "sector", "plaza", "parque"} and _specific_corridor(candidate.normalized_value, comuna_key):
            candidates_by_type.append(("named_corridor", candidate))
    if candidates_by_type:
        kind, candidate = max(
            candidates_by_type,
            key=lambda item: (_confidence_score(item[1].confidence), _corridor_priority(item[0]), item[1].normalized_value),
        )
        confidence = "medium" if candidate.source in {"title", "url_slug"} and candidate.confidence == "low" else candidate.confidence
        return _selected(kind, comuna_key, candidate.normalized_value, candidate, confidence=confidence)

    for kind, value in (
        ("metro_corridor", signals.nearby_metro),
        ("avenue_corridor", signals.nearby_avenue),
        ("named_corridor", signals.neighborhood_hint),
    ):
        normalized = _normalize_key(value)
        if _specific_corridor(normalized, comuna_key):
            return {
                "kind": kind,
                "key": _key(kind, comuna_key, normalized),
                "value": normalized or "",
                "source": "microzone_signals",
                "confidence": _confidence_label(float(signals.confidence or 0.0)),
                "field": "geo_signals",
            }
    return None


def _level_1(
    candidates: tuple[GeoSignalCandidate, ...],
    signals: Any,
    *,
    comuna_key: str | None,
) -> dict[str, str] | None:
    if not comuna_key:
        return None
    named = [
        candidate for candidate in candidates
        if candidate.signal_type in {"barrio", "sector"} and _specific_corridor(candidate.normalized_value, comuna_key)
    ]
    if named:
        candidate = _best_candidate(named)
        return _selected("named_area", comuna_key, candidate.normalized_value, candidate, confidence=candidate.confidence)
    neighborhood = _normalize_key(signals.neighborhood_hint)
    if _specific_corridor(neighborhood, comuna_key):
        return {
            "kind": "named_area",
            "key": _key("named_area", comuna_key, neighborhood),
            "value": neighborhood or "",
            "source": "microzone_signals",
            "confidence": _confidence_label(float(signals.confidence or 0.0)),
            "field": "geo_signals",
        }
    return None


def _usable_candidates(
    candidates: tuple[GeoSignalCandidate, ...],
    *,
    comuna_key: str | None,
) -> list[GeoSignalCandidate]:
    result: list[GeoSignalCandidate] = []
    for candidate in candidates:
        normalized = _normalize_key(candidate.normalized_value or candidate.value)
        normalized = _trim_or_reject_candidate(candidate, normalized, comuna_key=comuna_key)
        if not normalized or _is_generic(normalized, comuna_key):
            continue
        result.append(
            GeoSignalCandidate(
                value=candidate.value,
                normalized_value=normalized,
                signal_type=candidate.signal_type,
                source=candidate.source,
                confidence=candidate.confidence,
                rule=candidate.rule,
                raw_text=candidate.raw_text,
                created_by_version=candidate.created_by_version,
            )
        )
    return result


def _trim_or_reject_candidate(
    candidate: GeoSignalCandidate,
    normalized: str | None,
    *,
    comuna_key: str | None,
) -> str | None:
    if not normalized:
        return None
    words = normalized.split("_")
    if candidate.signal_type == "metro":
        if candidate.source == "metadata_location_text" and normalized in {comuna_key, "metro_central", "estacion_central"}:
            return None
        if len(words) > 5 and candidate.source in {"title", "url_slug", "detail_text", "card_text"}:
            return None
        known = _known_phrase(normalized, _KNOWN_METRO_KEYS)
        if known:
            if known == "central" and comuna_key != "estacion_central":
                return None
            return f"metro_{known}"
        return normalized if len(words) <= 3 else None
    if candidate.signal_type == "avenue":
        known = _known_phrase(normalized, _KNOWN_AVENUE_KEYS)
        if known:
            return f"avenida_{known}"
        return normalized if len(words) <= 5 else None
    if candidate.signal_type in {"street", "intersection"}:
        return "_".join(words[:6]) if len(words) > 6 else normalized
    if candidate.signal_type in {"barrio", "sector", "plaza", "parque"}:
        if len(words) > 5 and candidate.confidence == "low":
            return None
        return "_".join(words[:5]) if len(words) > 5 else normalized
    return normalized


def _known_phrase(value: str, known_values: set[str]) -> str | None:
    padded = f"_{value}_"
    for phrase in sorted(known_values, key=len, reverse=True):
        if f"_{phrase}_" in padded:
            return phrase
    return None


def _rejection_warnings(candidates: tuple[GeoSignalCandidate, ...], *, comuna_key: str | None) -> list[str]:
    warnings = []
    for candidate in candidates:
        normalized = _normalize_key(candidate.normalized_value or candidate.value)
        if normalized is None:
            continue
        if _is_generic(normalized, comuna_key):
            warnings.append(f"rejected_generic_{candidate.signal_type}:{normalized}")
    return warnings[:20]


def _selected(kind: str, comuna_key: str, normalized: str, candidate: GeoSignalCandidate, *, confidence: str) -> dict[str, str]:
    return {
        "kind": kind,
        "key": _key(kind, comuna_key, normalized),
        "value": normalized,
        "source": candidate.source,
        "confidence": confidence,
        "field": _field_from_source(candidate.source),
    }


def _key(kind: str, comuna_key: str, normalized: str) -> str:
    return f"{kind}:{comuna_key}:{normalized}"


def _selected_key(value: dict[str, str] | None) -> str | None:
    return value["key"] if value else None


def _selected_kind(value: dict[str, str] | None) -> str | None:
    return value["kind"] if value else None


def _signal_dict(*, level: int, kind: str, value: str, source: str, confidence: str, field: str) -> dict[str, Any]:
    return {
        "level": LEVEL_NAMES[level],
        "kind": kind,
        "value": value,
        "source": source,
        "field": field,
        "confidence": confidence,
    }


def _specific_intersection(value: str) -> bool:
    parts = [part.strip() for part in _INTERSECTION_SPLIT_RE.split(value) if part.strip()]
    if len(parts) < 2 and "_y_" in value:
        parts = [part.strip() for part in value.split("_y_") if part.strip()]
    return len(parts) >= 2 and all(_specific_corridor(part, None) for part in parts[:2])


def _specific_street(value: str) -> bool:
    value = _normalize_key(value)
    if _is_generic(value, None):
        return False
    match = _STREET_MARKER_RE.search(value.replace("_", " "))
    candidate = match.group(2) if match else value
    words = [word for word in candidate.split("_") if word and word not in _NOISE_WORDS]
    return len(" ".join(words)) >= 4 and not set(words).issubset(_NOISE_WORDS | _GENERIC_SIGNALS)


def _specific_corridor(value: str | None, comuna_key: str | None) -> bool:
    normalized = _normalize_key(value)
    if not normalized or _is_generic(normalized, comuna_key):
        return False
    if normalized == "metro_central" and comuna_key != "estacion_central":
        return False
    plain = normalized.replace("_", " ")
    if plain in {"metro estacion", "estacion metro", "avenida", "av", "avda", "calle", "pasaje", "camino", "diagonal"}:
        return False
    words = [word for word in normalized.split("_") if word not in _NOISE_WORDS]
    return len(" ".join(words)) >= 4


def _is_generic(value: str | None, comuna_key: str | None) -> bool:
    normalized = _normalize_key(value)
    if not normalized:
        return True
    plain = normalized.replace("_", " ")
    if normalized == comuna_key:
        return True
    if plain in _GENERIC_SIGNALS:
        return True
    if plain in {"region metropolitana", "metropolitana", "chile"}:
        return True
    words = set(normalized.split("_"))
    return bool(words and words.issubset(_GENERIC_SIGNALS | _NOISE_WORDS))


def _best_candidate(candidates: list[GeoSignalCandidate]) -> GeoSignalCandidate:
    return max(
        candidates,
        key=lambda item: (_confidence_score(item.confidence), _source_score(item.source), len(item.normalized_value)),
    )


def _best_confidence(
    *,
    best_level: int,
    level_4_confidence: str,
    level_3: dict[str, str] | None,
    level_2: dict[str, str] | None,
    level_1: dict[str, str] | None,
) -> str:
    if best_level == 4:
        return level_4_confidence
    if best_level == 3 and level_3:
        return level_3["confidence"]
    if best_level == 2 and level_2:
        return level_2["confidence"]
    if best_level == 1 and level_1:
        return level_1["confidence"]
    if best_level == 0:
        return "low"
    return "none"


def _confidence_label(value: float) -> str:
    if value >= 0.85:
        return "high"
    if value >= 0.45:
        return "medium"
    if value > 0:
        return "low"
    return "none"


def _confidence_score(value: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(value, 0)


def _source_score(value: str) -> int:
    return {
        "detail_exact_address": 5,
        "metadata_address": 4,
        "metadata_street_hint": 4,
        "card_text": 3,
        "detail_text": 3,
        "existing_microzone_metadata": 3,
        "title": 1,
        "url_slug": 1,
    }.get(value, 0)


def _corridor_priority(kind: str) -> int:
    return {"metro_corridor": 4, "avenue_corridor": 3, "named_corridor": 2}.get(kind, 1)


def _field_from_source(source: str) -> str:
    return {
        "metadata_address": "address_label",
        "metadata_street_hint": "street_hint",
        "metadata_location_text": "location_text",
        "title": "title",
        "url_slug": "url",
        "detail_exact_address": "detail_text",
        "detail_text": "detail_text",
        "card_text": "card_text",
        "existing_microzone_metadata": "raw_metadata",
    }.get(source, source)


def _normalize_key(value: Any) -> str | None:
    if value is None:
        return None
    text = unicodedata.normalize("NFKD", str(value).lower())
    text = text.encode("ascii", "ignore").decode("ascii")
    text = _TOKEN_RE.sub(" ", text)
    for pattern, replacement in _ABBREVIATIONS:
        text = pattern.sub(replacement, text)
    text = _SPACE_RE.sub(" ", text).strip()
    words = [word for word in text.split() if word not in _NOISE_WORDS]
    text = " ".join(words)
    return _SPACE_RE.sub("_", text).strip("_") or None


def _geo_value(value: Any) -> dict[str, Any]:
    lat, lon = _lat_lon(value)
    return {
        "lat": lat,
        "lon": lon,
        "comuna": _get(value, "comuna"),
        "geocode_precision": canonical_geocode_precision(_get(value, "geocode_precision")),
        "raw_metadata": _raw_metadata(value),
    }


def _lat_lon(value: Any) -> tuple[float | None, float | None]:
    coordinates = _get(value, "coordinates")
    if coordinates is not None:
        return _float_or_none(getattr(coordinates, "lat", None)), _float_or_none(getattr(coordinates, "lon", None))
    return _float_or_none(_get(value, "lat")), _float_or_none(_get(value, "lon"))


def _raw_metadata(value: Any) -> dict[str, Any]:
    raw = _get(value, "raw_metadata")
    return raw if isinstance(raw, dict) else {}


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _get(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
