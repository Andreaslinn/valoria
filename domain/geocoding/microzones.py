"""Microzone and landmark extraction from listing text.

This module extracts conservative geographic text signals. It never creates
coordinates and must not be interpreted as geocode precision.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from domain.geocoding.geo_signals import enrich_raw_metadata_with_geo_signals

_SPACE_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"[^a-z0-9/\s]")
_METRO_RE = re.compile(r"\bmetro\s+([a-z0-9\s]{2,40})")
_STATION_RE = re.compile(r"\bestaci[oó]n\s+([a-z0-9\s]{2,40})")
_AVENUE_RE = re.compile(r"\b(?:av\.?|avenida)\s+([a-z0-9\s]{2,45})")
_SECTOR_RE = re.compile(r"\b(?:sector|barrio)\s+([a-z0-9\s]{3,35})")
_INTERSECTION_RE = re.compile(
    r"\b([a-z0-9\s]{3,40})\s*(?:/| con | esquina | y )\s*([a-z0-9\s]{3,40})\b"
)

_STOP_AFTER = {
    "con",
    "y",
    "en",
    "venta",
    "vende",
    "depto",
    "departamento",
    "casa",
    "dorm",
    "dormitorio",
    "bano",
    "banio",
    "estac",
    "uf",
    "metro",
    "estacion",
    "region",
    "metropolitana",
    "av",
    "avenida",
    "banos",
    "dormitorios",
    "habitaciones",
    "terreno",
    "piscina",
    "jardin",
}
_GENERIC_TOKENS = {
    "central",
    "comuna",
    "de",
    "excelente",
    "gran",
    "oportunidad",
    "sector",
    "tranquilo",
    "tranquila",
    "propiedad",
    "casa",
    "casas",
    "departamento",
    "depto",
    "metro",
    "calle",
    "avenida",
    "av",
    "estacion",
    "amplia",
    "amplio",
    "residencial",
    "ubicacion",
    "inversion",
}
_MARKETING_PATTERNS = (
    re.compile(r"\bcalle tranquila\b"),
    re.compile(r"\bsector residencial\b"),
    re.compile(r"\bgran oportunidad\b"),
    re.compile(r"\bcasa y piscina\b"),
    re.compile(r"\bamplia casa\b"),
    re.compile(r"\bamplio terreno\b"),
    re.compile(r"\bexcelente ubicacion\b"),
)
_KNOWN_AVENUES = {
    "americo vespucio",
    "av brasil",
    "brasil",
    "consistorial",
    "echequenique",
    "grecia",
    "irrarazaval",
    "las condes",
    "las rejas",
    "macul",
    "ossandon",
    "ossa",
    "pedro de valdivia",
    "portugal",
    "providencia",
    "rodrigo de araya",
    "santa rosa",
    "tomas moro",
    "vicuna mackenna",
    "camino la posada",
    "suarez mujica",
}
_BARE_AVENUES = _KNOWN_AVENUES - {
    "la florida",
    "las condes",
    "macul",
    "providencia",
    "recoleta",
}
_KNOWN_LANDMARKS = {
    "cal y canto",
    "escuela militar",
    "lo ovalle",
    "parque almagro",
    "parque bustamante",
    "parque ohiggins",
    "plaza egaña",
    "plaza egana",
    "rotonda atenas",
    "suarez mujica",
    "camino la posada",
    "tobalaba",
}
_KNOWN_METROS = {
    "cal y canto",
    "central",
    "cerro blanco",
    "ciudad del nino",
    "departamental",
    "dorsal",
    "escuela militar",
    "hospitales",
    "ines de suarez",
    "las rejas",
    "las torres",
    "lo ovalle",
    "macul",
    "manquehue",
    "parque almagro",
    "pedro de valdivia",
    "plaza chacabuco",
    "plaza egana",
    "principe de gales",
    "quilin",
    "rodrigo de araya",
    "simon bolivar",
    "tobalaba",
}


@dataclass(frozen=True)
class MicrozoneSignals:
    nearby_metro: str | None
    nearby_avenue: str | None
    neighborhood_hint: str | None
    intersection_hint: str | None
    landmark_tokens: tuple[str, ...]
    confidence: float
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "nearby_metro": self.nearby_metro,
            "nearby_avenue": self.nearby_avenue,
            "neighborhood_hint": self.neighborhood_hint,
            "intersection_hint": self.intersection_hint,
            "landmark_tokens": list(self.landmark_tokens),
            "confidence": self.confidence,
            "reason": self.reason,
        }


def extract_microzone_signals(
    *,
    title: str | None = None,
    raw_metadata: dict[str, Any] | None = None,
) -> MicrozoneSignals:
    metadata = raw_metadata or {}
    text = " ".join(
        part
        for part in (
            title,
            metadata.get("address_label"),
            metadata.get("street_hint"),
            metadata.get("location_text"),
            metadata.get("location"),
            metadata.get("neighborhood"),
            metadata.get("card_text"),
            metadata.get("description"),
        )
        if isinstance(part, str) and part.strip()
    )
    normalized = _normalize(text)
    if not normalized:
        return MicrozoneSignals(None, None, None, None, (), 0.0, "no_text")
    rejected = _rejection_reason(normalized)

    nearby_metro = _extract_metro(normalized)
    nearby_avenue = _extract_avenue(normalized)
    neighborhood = _extract_neighborhood(normalized)
    intersection = _extract_intersection(normalized)
    landmarks = _extract_landmarks(
        normalized,
        nearby_metro=nearby_metro,
        nearby_avenue=nearby_avenue,
        intersection_hint=intersection,
    )
    confidence = _confidence(nearby_metro, nearby_avenue, neighborhood, intersection, landmarks)
    reason = rejected or ("no_microzone_signal" if confidence == 0 else "text_microzone_signal")
    if rejected and confidence == 0:
        return MicrozoneSignals(None, None, None, None, (), 0.0, reason)
    return MicrozoneSignals(nearby_metro, nearby_avenue, neighborhood, intersection, landmarks, confidence, reason)


def microzone_similarity_bonus(target: Any, candidate: Any) -> tuple[float, list[str]]:
    """Return a small additive bonus and reasons for comparable scoring."""
    target_signals = signals_from_value(target)
    candidate_signals = signals_from_value(candidate)
    if not _usable(target_signals) or not _usable(candidate_signals):
        return 0.0, []

    bonus = 0.0
    reasons: list[str] = []
    if target_signals.nearby_metro and target_signals.nearby_metro == candidate_signals.nearby_metro:
        bonus += 0.05
        reasons.append(f"same_metro:{target_signals.nearby_metro}")
    if target_signals.nearby_avenue and target_signals.nearby_avenue == candidate_signals.nearby_avenue:
        bonus += 0.035
        reasons.append(f"same_avenue:{target_signals.nearby_avenue}")
    shared = set(target_signals.landmark_tokens) & set(candidate_signals.landmark_tokens)
    if shared:
        token = sorted(shared)[0]
        bonus += 0.03
        reasons.append(f"same_landmark:{token}")
    if (
        target_signals.neighborhood_hint
        and target_signals.neighborhood_hint == candidate_signals.neighborhood_hint
    ):
        bonus += 0.025
        reasons.append(f"same_neighborhood:{target_signals.neighborhood_hint}")
    if (
        target_signals.intersection_hint
        and target_signals.intersection_hint == candidate_signals.intersection_hint
    ):
        bonus += 0.045
        reasons.append(f"same_intersection:{target_signals.intersection_hint}")
    if bonus > 0:
        return min(0.08, bonus), reasons

    if _same_known_comuna(target, candidate) and _has_clear_different_microzone(target_signals, candidate_signals):
        return -0.025, ["different_clear_microzone"]
    return 0.0, []


def signals_from_value(value: Any) -> MicrozoneSignals:
    raw_metadata = getattr(value, "raw_metadata", None)
    if isinstance(raw_metadata, dict):
        existing = raw_metadata.get("geo_signals")
        if isinstance(existing, dict):
            return _signals_from_dict(existing)
        if any(key in raw_metadata for key in ("geo_microzone_tokens", "nearby_metro", "nearby_avenue", "intersection_hint")):
            return _signals_from_flat_metadata(raw_metadata)
    return extract_microzone_signals(
        title=getattr(value, "title", None),
        raw_metadata=raw_metadata if isinstance(raw_metadata, dict) else None,
    )


def enrich_raw_metadata_with_microzones(
    raw_metadata: dict[str, Any],
    *,
    title: str | None,
) -> dict[str, Any]:
    metadata = enrich_raw_metadata_with_geo_signals(dict(raw_metadata), title=title)
    signals = extract_microzone_signals(title=title, raw_metadata=metadata)
    metadata["geo_signals"] = signals.as_dict()
    metadata["geo_microzone_tokens"] = list(signals.landmark_tokens)
    metadata["nearby_metro"] = signals.nearby_metro
    metadata["nearby_avenue"] = signals.nearby_avenue
    metadata["neighborhood_hint"] = signals.neighborhood_hint
    metadata["intersection_hint"] = signals.intersection_hint
    metadata["microzone_confidence"] = signals.confidence
    metadata["microzone_reason"] = signals.reason
    return metadata


def _extract_metro(text: str) -> str | None:
    metro_match = _METRO_RE.search(text)
    station_match = _STATION_RE.search(text)
    if not metro_match and not station_match:
        return None
    match = metro_match or station_match
    raw_station = match.group(1).strip()
    known_station = _known_phrase_from(raw_station, _KNOWN_METROS)
    station = known_station or _trim_candidate(raw_station, max_words=4)
    if not station:
        return None
    if station not in _KNOWN_METROS:
        return None
    if station in _GENERIC_TOKENS and not (station == "central" and metro_match is not None):
        return None
    if station == "central" and metro_match is None:
        return None
    return station


def _extract_avenue(text: str) -> str | None:
    match = _AVENUE_RE.search(text)
    if match:
        raw_avenue = match.group(1).strip()
        avenue = _known_phrase_from(raw_avenue, _KNOWN_AVENUES) or _trim_candidate(raw_avenue, max_words=4)
        if _is_usable_avenue(avenue):
            return avenue
    for avenue in sorted(_BARE_AVENUES, key=len, reverse=True):
        if f" {avenue} " in f" {text} ":
            return avenue
    return None


def _extract_neighborhood(text: str) -> str | None:
    match = _SECTOR_RE.search(text)
    if not match:
        return None
    candidate = _trim_candidate(match.group(1), max_words=3)
    if candidate in _GENERIC_TOKENS or len(candidate) < 4:
        return None
    return candidate


def _extract_intersection(text: str) -> str | None:
    for match in _INTERSECTION_RE.finditer(text):
        left = _clean_intersection_side(match.group(1))
        right = _clean_intersection_side(match.group(2))
        if _is_usable_intersection_side(left) and _is_usable_intersection_side(right):
            return " y ".join(sorted((left, right)))
    return None


def _extract_landmarks(
    text: str,
    *,
    nearby_metro: str | None,
    nearby_avenue: str | None,
    intersection_hint: str | None,
) -> tuple[str, ...]:
    tokens: set[str] = set()
    if nearby_metro:
        tokens.add(f"metro:{nearby_metro}")
    if nearby_avenue:
        tokens.add(f"avenue:{nearby_avenue}")
    if intersection_hint:
        tokens.add(f"intersection:{intersection_hint}")
    for landmark in _KNOWN_LANDMARKS:
        if f" {landmark} " in f" {text} ":
            tokens.add(f"landmark:{landmark}")
    return tuple(sorted(tokens))


def _confidence(
    nearby_metro: str | None,
    nearby_avenue: str | None,
    neighborhood: str | None,
    intersection_hint: str | None,
    landmarks: tuple[str, ...],
) -> float:
    score = 0.0
    if nearby_metro:
        score += 0.7
    if nearby_avenue:
        score += 0.55
    if neighborhood:
        score += 0.35
    if intersection_hint:
        score += 0.65
    if landmarks:
        score += 0.55
    return round(min(1.0, score), 3)


def _usable(signals: MicrozoneSignals) -> bool:
    return signals.confidence >= 0.55 and bool(
        signals.nearby_metro or signals.nearby_avenue or signals.landmark_tokens
    )


def _signals_from_dict(value: dict[str, Any]) -> MicrozoneSignals:
    tokens = value.get("landmark_tokens")
    if not isinstance(tokens, list | tuple):
        tokens = []
    return MicrozoneSignals(
        nearby_metro=_optional_str(value.get("nearby_metro")),
        nearby_avenue=_optional_str(value.get("nearby_avenue")),
        neighborhood_hint=_optional_str(value.get("neighborhood_hint")),
        intersection_hint=_optional_str(value.get("intersection_hint")),
        landmark_tokens=tuple(str(token) for token in tokens if str(token).strip()),
        confidence=float(value.get("confidence") or 0.0),
        reason=str(value.get("reason") or ""),
    )


def _signals_from_flat_metadata(value: dict[str, Any]) -> MicrozoneSignals:
    tokens = value.get("geo_microzone_tokens")
    if not isinstance(tokens, list | tuple):
        tokens = []
    return MicrozoneSignals(
        nearby_metro=_optional_str(value.get("nearby_metro")),
        nearby_avenue=_optional_str(value.get("nearby_avenue")),
        neighborhood_hint=_optional_str(value.get("neighborhood_hint")),
        intersection_hint=_optional_str(value.get("intersection_hint")),
        landmark_tokens=tuple(str(token) for token in tokens if str(token).strip()),
        confidence=float(value.get("microzone_confidence") or 0.0),
        reason=str(value.get("microzone_reason") or ""),
    )


def _trim_candidate(value: str, *, max_words: int) -> str:
    words = []
    for word in value.split():
        if word in _STOP_AFTER:
            break
        words.append(word)
        if len(words) >= max_words:
            break
    candidate = " ".join(words).strip()
    return "" if candidate in _GENERIC_TOKENS else candidate


def _is_usable_avenue(value: str) -> bool:
    if not value or value in _GENERIC_TOKENS:
        return False
    if len(value) < 4:
        return False
    return value in _KNOWN_AVENUES


def _is_usable_intersection_side(value: str) -> bool:
    if not value or value in _GENERIC_TOKENS:
        return False
    if value in _KNOWN_AVENUES or value in _KNOWN_LANDMARKS:
        return True
    return False


def _clean_intersection_side(value: str) -> str:
    words = [
        word
        for word in value.split()
        if word not in {"casa", "casas", "departamento", "depto", "dpto", "av", "avenida", "calle"}
    ]
    return _trim_candidate(" ".join(words), max_words=4)


def _known_phrase_from(value: str, known_values: set[str]) -> str | None:
    normalized = f" {_SPACE_RE.sub(' ', value).strip()} "
    for phrase in sorted(known_values, key=len, reverse=True):
        if f" {phrase} " in normalized:
            return phrase
    return None


def _has_clear_different_microzone(target: MicrozoneSignals, candidate: MicrozoneSignals) -> bool:
    pairs = (
        (target.nearby_metro, candidate.nearby_metro),
        (target.nearby_avenue, candidate.nearby_avenue),
        (target.intersection_hint, candidate.intersection_hint),
    )
    return any(left and right and left != right for left, right in pairs)


def _same_known_comuna(target: Any, candidate: Any) -> bool:
    target_comuna = _optional_str(getattr(target, "comuna", None))
    candidate_comuna = _optional_str(getattr(candidate, "comuna", None))
    return bool(target_comuna and candidate_comuna and target_comuna == candidate_comuna)


def _rejection_reason(text: str) -> str | None:
    for pattern in _MARKETING_PATTERNS:
        if pattern.search(text):
            return f"rejected:{pattern.pattern.replace(chr(92) + 'b', '')}"
    return None


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value).lower())
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    clean = _TOKEN_RE.sub(" ", ascii_text)
    return f" {_SPACE_RE.sub(' ', clean).strip()} ".strip()


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
