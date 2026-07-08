"""Read-only hierarchy-aware comparable diagnostics.

The helpers in this module are intentionally detached from productive AVM
selection. They score and reorder comparable candidates for offline benchmarks
without writing assignments or changing the valuation engine.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from core.value_objects.score import Score
from domain.geocoding.hierarchical_microzones import HierarchicalMicrozoneAssignment

DensityKey = tuple[str, str, str]
DensityIndex = Mapping[int, Counter[DensityKey]]


@dataclass(frozen=True)
class HierarchicalComparableDiagnostics:
    same_level_4: bool
    same_level_3: bool
    same_level_2: bool
    same_level_1: bool
    comuna_only: bool
    no_shared_location_signal: bool
    comparable_geo_strength: str
    subject_geo_strength: str
    hierarchy_match_level: int
    hierarchy_match_score: float
    hierarchy_density: int
    density_threshold_met: bool
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "same_level_4": self.same_level_4,
            "same_level_3": self.same_level_3,
            "same_level_2": self.same_level_2,
            "same_level_1": self.same_level_1,
            "comuna_only": self.comuna_only,
            "no_shared_location_signal": self.no_shared_location_signal,
            "comparable_geo_strength": self.comparable_geo_strength,
            "subject_geo_strength": self.subject_geo_strength,
            "hierarchy_match_level": self.hierarchy_match_level,
            "hierarchy_match_score": self.hierarchy_match_score,
            "hierarchy_density": self.hierarchy_density,
            "density_threshold_met": self.density_threshold_met,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class HierarchyAdjustedComparable:
    original_score: Score
    adjusted_score: Score
    listing_key: str
    diagnostics: HierarchicalComparableDiagnostics


def diagnose_hierarchical_comparable(
    subject: HierarchicalMicrozoneAssignment,
    comparable: HierarchicalMicrozoneAssignment,
    *,
    density_index: DensityIndex | None = None,
    comparable_comuna: str | None = None,
    property_type: str | None = None,
) -> HierarchicalComparableDiagnostics:
    """Describe shared hierarchy signal between a subject and one comparable."""
    match_level = hierarchy_match_level(subject, comparable)
    density = hierarchy_density(
        comparable,
        match_level,
        density_index=density_index,
        comuna=comparable_comuna,
        property_type=property_type,
    )
    dense_level_3 = match_level == 3 and density >= 3
    dense_level_2 = match_level == 2 and density >= 5
    reasons: list[str] = []

    if match_level == 4:
        score = 0.24
        reasons.append("same_level_4_strong_bonus")
    elif match_level == 3:
        if dense_level_3:
            score = 0.14
            reasons.append("same_level_3_dense_bonus")
        else:
            score = 0.03
            reasons.append("same_level_3_sparse_hint_only")
    elif match_level == 2:
        if dense_level_2:
            score = 0.16
            reasons.append("same_level_2_dense_bonus")
        else:
            score = 0.08
            reasons.append("same_level_2_secondary_bonus")
    elif match_level == 1:
        score = 0.04
        reasons.append("same_level_1_light_bonus")
    elif match_level == 0:
        score = -0.03
        reasons.append("comuna_only_light_penalty")
    else:
        score = -0.08
        reasons.append("no_shared_location_signal_penalty")

    if subject.is_fallback_only:
        score -= 0.03
        reasons.append("subject_comuna_fallback_penalty")
    if comparable.is_fallback_only:
        score -= 0.04
        reasons.append("comparable_comuna_fallback_penalty")
    if subject.best_available_level < 2:
        score -= 0.02
        reasons.append("subject_weak_geo_strength")
    if comparable.best_available_level < 2:
        score -= 0.02
        reasons.append("comparable_weak_geo_strength")

    return HierarchicalComparableDiagnostics(
        same_level_4=match_level == 4,
        same_level_3=match_level == 3,
        same_level_2=match_level == 2,
        same_level_1=match_level == 1,
        comuna_only=match_level == 0,
        no_shared_location_signal=match_level < 0,
        comparable_geo_strength=geo_strength(comparable),
        subject_geo_strength=geo_strength(subject),
        hierarchy_match_level=match_level,
        hierarchy_match_score=round(score, 4),
        hierarchy_density=density,
        density_threshold_met=(dense_level_2 or dense_level_3 or match_level == 4),
        reasons=tuple(reasons),
    )


def hierarchy_aware_rerank(
    scored_comparables: Sequence[tuple[Score, object]],
    *,
    subject_assignment: HierarchicalMicrozoneAssignment,
    comparable_assignments: Mapping[str, HierarchicalMicrozoneAssignment],
    density_index: DensityIndex | None = None,
    listing_key_fn,
    top_n: int,
) -> list[tuple[Score, object, HierarchicalComparableDiagnostics]]:
    """Return the same candidates with hierarchy-adjusted scores and ordering."""
    adjusted: list[tuple[Score, object, HierarchicalComparableDiagnostics]] = []
    for original_score, listing in scored_comparables:
        key = listing_key_fn(listing)
        assignment = comparable_assignments[key]
        diagnostics = diagnose_hierarchical_comparable(
            subject_assignment,
            assignment,
            density_index=density_index,
            comparable_comuna=getattr(listing, "comuna", None),
            property_type=str(getattr(listing, "property_type", "") or ""),
        )
        adjusted_score = Score.clamped(original_score.value + diagnostics.hierarchy_match_score)
        adjusted.append((adjusted_score, listing, diagnostics))

    adjusted.sort(
        key=lambda item: (
            item[0].value,
            item[2].hierarchy_match_level,
            item[2].hierarchy_density,
            str(getattr(item[1], "fingerprint", "")),
        ),
        reverse=True,
    )
    return adjusted[:top_n]


def hierarchy_match_level(
    subject: HierarchicalMicrozoneAssignment,
    comparable: HierarchicalMicrozoneAssignment,
) -> int:
    for level in (4, 3, 2, 1):
        if _same_level(subject, comparable, level):
            return level
    if subject.level_0_key and subject.level_0_key == comparable.level_0_key:
        return 0
    return -1


def geo_strength(assignment: HierarchicalMicrozoneAssignment) -> str:
    if assignment.best_available_level == 4:
        return "level_4_geo_500m"
    if assignment.best_available_level == 3:
        return "level_3_street_microzone"
    if assignment.best_available_level == 2:
        return "level_2_corridor"
    if assignment.best_available_level == 1:
        return "level_1_named_area"
    if assignment.best_available_level == 0:
        return "comuna_fallback"
    return "none"


def hierarchy_density(
    assignment: HierarchicalMicrozoneAssignment,
    match_level: int,
    *,
    density_index: DensityIndex | None,
    comuna: str | None,
    property_type: str | None,
) -> int:
    if density_index is None or match_level < 1:
        return 0
    key = getattr(assignment, f"level_{match_level}_key", None)
    if not key:
        return 0
    counter = density_index.get(match_level)
    if counter is None:
        return 0
    return int(counter[(key, str(comuna or ""), str(property_type or ""))])


def _same_level(
    subject: HierarchicalMicrozoneAssignment,
    comparable: HierarchicalMicrozoneAssignment,
    level: int,
) -> bool:
    key = getattr(subject, f"level_{level}_key", None)
    return bool(key and key == getattr(comparable, f"level_{level}_key", None))
