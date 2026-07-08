from __future__ import annotations

from collections import Counter

from core.value_objects.score import Score
from domain.geocoding.hierarchical_microzones import HierarchicalMicrozoneAssignment
from domain.valuation.hierarchical_comparable_diagnostics import (
    diagnose_hierarchical_comparable,
    hierarchy_aware_rerank,
)
from tests.unit.factories import make_listing


def _assignment(
    *,
    level_0: str = "comuna:nunoa",
    level_1: str | None = None,
    level_2: str | None = None,
    level_3: str | None = None,
    level_4: str | None = None,
) -> HierarchicalMicrozoneAssignment:
    levels = {1: level_1, 2: level_2, 3: level_3, 4: level_4, 0: level_0}
    best = max(level for level, key in levels.items() if key)
    return HierarchicalMicrozoneAssignment(
        comuna_key=level_0.split(":", 1)[1],
        level_0_key=level_0,
        level_1_key=level_1,
        level_2_key=level_2,
        level_3_key=level_3,
        level_4_key=level_4,
        level_1_kind="named_area" if level_1 else None,
        level_2_kind="metro_corridor" if level_2 else None,
        level_3_kind="street_microzone" if level_3 else None,
        level_4_kind="geo_500m" if level_4 else None,
        best_available_level=best,
        best_available_key=levels[best],
        confidence="medium" if best else "low",
        matched_signals=(),
        source_fields=("test",),
        warnings=("comuna_fallback_not_real_microzone",) if best == 0 else (),
        is_real_microzone=best >= 1,
        is_fallback_only=best == 0,
    )


def test_same_level_4_gets_stronger_score_than_same_level_2() -> None:
    subject = _assignment(level_2="metro:nunoa:plaza_egana", level_4="geo500:nunoa:1:1")
    level_4 = _assignment(level_2="metro:nunoa:plaza_egana", level_4="geo500:nunoa:1:1")
    level_2 = _assignment(level_2="metro:nunoa:plaza_egana")

    strong = diagnose_hierarchical_comparable(subject, level_4)
    secondary = diagnose_hierarchical_comparable(subject, level_2)

    assert strong.same_level_4 is True
    assert strong.hierarchy_match_score > secondary.hierarchy_match_score


def test_dense_level_2_beats_comuna_only() -> None:
    key = "metro_corridor:nunoa:metro_plaza_egana"
    subject = _assignment(level_2=key)
    comparable = _assignment(level_2=key)
    comuna_only = _assignment()
    density = {2: Counter({(key, "nunoa", "apartment"): 5})}

    level_2 = diagnose_hierarchical_comparable(
        subject,
        comparable,
        density_index=density,
        comparable_comuna="nunoa",
        property_type="apartment",
    )
    fallback = diagnose_hierarchical_comparable(subject, comuna_only)

    assert level_2.density_threshold_met is True
    assert level_2.hierarchy_match_score > fallback.hierarchy_match_score


def test_sparse_level_3_is_hint_not_strong_filter() -> None:
    key = "street_microzone:nunoa:calle_las_dalias"
    subject = _assignment(level_3=key)
    comparable = _assignment(level_3=key)
    density = {3: Counter({(key, "nunoa", "apartment"): 2})}

    diagnostics = diagnose_hierarchical_comparable(
        subject,
        comparable,
        density_index=density,
        comparable_comuna="nunoa",
        property_type="apartment",
    )

    assert diagnostics.same_level_3 is True
    assert diagnostics.density_threshold_met is False
    assert "same_level_3_sparse_hint_only" in diagnostics.reasons


def test_comuna_fallback_is_not_real_microzone_signal() -> None:
    subject = _assignment()
    comparable = _assignment()

    diagnostics = diagnose_hierarchical_comparable(subject, comparable)

    assert diagnostics.comuna_only is True
    assert diagnostics.same_level_2 is False
    assert diagnostics.subject_geo_strength == "comuna_fallback"
    assert diagnostics.hierarchy_match_score < 0


def test_challenger_preserves_candidates_when_microzone_is_missing() -> None:
    subject = _assignment()
    listings = [
        make_listing(fingerprint=f"c-{idx}", comuna="nunoa", property_type="apartment")
        for idx in range(5)
    ]
    assignments = {listing.fingerprint: _assignment() for listing in listings}
    scored = [(Score.clamped(0.5), listing) for listing in listings]

    reranked = hierarchy_aware_rerank(
        scored,
        subject_assignment=subject,
        comparable_assignments=assignments,
        density_index={},
        listing_key_fn=lambda listing: listing.fingerprint,
        top_n=20,
    )

    assert len(reranked) == len(listings)
