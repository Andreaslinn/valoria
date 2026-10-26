"""Funcion de similitud entre un target (Property) y un candidato (Listing)."""
from __future__ import annotations

from config.constants import COMPARABLES_MAX_DISTANCE_KM, SCORE_WEIGHTS
from core.entities.listing import Listing, Property
from core.normalization.property_type import normalize_property_type as _property_type
from core.value_objects.score import Score
from domain.geocoding.microzones import microzone_similarity_bonus
from domain.geocoding.quality import has_valid_coordinates, normalized_precision_for

_NEUTRAL_DISTANCE_SCORE = 0.5
_POOR_DISTANCE_SCORE = 0.35
_PRECISION_DISTANCE_IMPACT = {
    "address": 1.0,
    "street": 0.35,
    "comuna": 0.0,
    "comuna_centroid": 0.0,
    "unknown": 0.0,
}


def similarity_score(target: Property, candidate: Listing) -> Score:
    """Calcula cuan similar es candidate a target. [0, 1]."""
    if _property_type(target) != _property_type(candidate):
        return Score.clamped(0.0)

    area_s = _area_score(target, candidate)
    dist_s = _distance_score(target, candidate)
    microzone_bonus, microzone_reasons = _microzone_adjustment(target, candidate)
    bed_s = _discrete_score(target.bedrooms, candidate.bedrooms)
    bath_s = _discrete_score(target.bathrooms, candidate.bathrooms)
    park_s = _discrete_score(target.parking, candidate.parking)

    total = (
        SCORE_WEIGHTS["m2"] * area_s
        + SCORE_WEIGHTS["distance"] * dist_s
        + SCORE_WEIGHTS["bedrooms"] * bed_s
        + SCORE_WEIGHTS["bathrooms"] * bath_s
        + SCORE_WEIGHTS["parking"] * park_s
    )
    if microzone_bonus != 0:
        total += microzone_bonus
        _append_microzone_debug(candidate, microzone_bonus, microzone_reasons)
    return Score.clamped(total)


def _area_score(target: Property, candidate: Listing) -> float:
    target_built = target.built_area_m2 or target.m2
    candidate_built = candidate.built_area_m2 or candidate.m2
    if candidate_built is None:
        return 0.0

    built_score = _m2_score(target_built, candidate_built)
    if _property_type(target) != "house":
        return built_score

    target_land = target.land_area_m2
    candidate_land = candidate.land_area_m2
    if target_land is None or candidate_land is None:
        return built_score * 0.65
    return 0.55 * built_score + 0.45 * _m2_score(target_land, candidate_land)


def _m2_score(target_m2: float, candidate_m2: float) -> float:
    if target_m2 <= 0:
        return 0.0
    diff_ratio = abs(target_m2 - candidate_m2) / target_m2
    return max(0.0, 1.0 - diff_ratio)


def _distance_score(target: Property, candidate: Listing) -> float:
    if target.coordinates is None or candidate.coordinates is None:
        return _NEUTRAL_DISTANCE_SCORE

    impact = min(_distance_impact(target), _distance_impact(candidate))
    if impact <= 0.0:
        return _NEUTRAL_DISTANCE_SCORE

    dist = target.coordinates.distance_km(candidate.coordinates)
    precise_score = max(0.0, 1.0 - dist / COMPARABLES_MAX_DISTANCE_KM)
    if impact < 0.5:
        return _POOR_DISTANCE_SCORE + impact * (precise_score - _POOR_DISTANCE_SCORE)
    return _NEUTRAL_DISTANCE_SCORE + impact * (precise_score - _NEUTRAL_DISTANCE_SCORE)


def _discrete_score(target_val: int, candidate_val: int) -> float:
    return 1.0 / (1.0 + abs(target_val - candidate_val))


def _distance_impact(value: Property | Listing) -> float:
    if not has_valid_coordinates(value):
        return 0.0
    precision = normalized_precision_for(value)
    return _PRECISION_DISTANCE_IMPACT.get(precision, 0.0)


def _microzone_adjustment(target: Property, candidate: Listing) -> tuple[float, list[str]]:
    if normalized_precision_for(target) == "address" and normalized_precision_for(candidate) == "address":
        return 0.0, []
    return microzone_similarity_bonus(target, candidate)


def _append_microzone_debug(candidate: Listing, bonus: float, reasons: list[str]) -> None:
    metadata = getattr(candidate, "raw_metadata", None)
    if not isinstance(metadata, dict):
        return
    metadata["last_microzone_score_bonus"] = round(bonus, 4)
    metadata["last_microzone_score_reasons"] = reasons
