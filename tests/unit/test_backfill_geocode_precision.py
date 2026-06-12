from __future__ import annotations

from scripts.backfill_geocode_precision import TARGET_PRECISION, classify_candidate


def test_null_precision_with_coordinates_goes_to_unknown() -> None:
    decision = classify_candidate(geocode_precision=None, lat=-33.4, lon=-70.6)

    assert decision.should_update is True
    assert decision.target_precision == TARGET_PRECISION
    assert decision.group == "null_precision_with_coordinates"


def test_null_precision_without_coordinates_goes_to_unknown() -> None:
    decision = classify_candidate(geocode_precision=None, lat=None, lon=None)

    assert decision.should_update is True
    assert decision.target_precision == TARGET_PRECISION
    assert decision.group == "null_precision_missing_coordinates"


def test_existing_precision_is_not_changed() -> None:
    decision = classify_candidate(geocode_precision="address", lat=-33.4, lon=-70.6)

    assert decision.should_update is False
    assert decision.target_precision is None
    assert decision.group == "already_classified"
