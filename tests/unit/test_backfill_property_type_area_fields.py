from __future__ import annotations

from types import SimpleNamespace

from scripts.backfill_property_type_area_fields import apply_suggestion
from scripts.preview_property_type_backfill import BackfillSuggestion


def _suggestion(**overrides) -> BackfillSuggestion:
    values = {
        "listing_id": 1,
        "title": "Casa con terreno",
        "source": "yapo",
        "url": "https://example.com/1",
        "status": "active",
        "comuna": "nunoa",
        "current_property_type": "house",
        "suggested_property_type": "house",
        "reason": "explicit_property_type",
        "confidence": 0.95,
        "current_built_area_m2": 120.0,
        "suggested_built_area_m2": 120.0,
        "current_land_area_m2": 400.0,
        "suggested_land_area_m2": 300.0,
        "current_usable_area_m2": None,
        "suggested_usable_area_m2": None,
        "source_fields": ("title",),
    }
    values.update(overrides)
    return BackfillSuggestion(**values)


def test_backfill_does_not_overwrite_existing_area_without_flag() -> None:
    listing = SimpleNamespace(
        property_type="house",
        built_area_m2=120.0,
        land_area_m2=400.0,
        usable_area_m2=None,
        raw_metadata={},
    )

    changed = apply_suggestion(listing, _suggestion(), apply=True, overwrite=False)

    assert "land_area_m2" not in changed
    assert listing.land_area_m2 == 400.0


def test_backfill_dry_run_reports_changes_without_writing() -> None:
    listing = SimpleNamespace(
        property_type="house",
        built_area_m2=120.0,
        land_area_m2=None,
        usable_area_m2=None,
        raw_metadata={},
    )

    changed = apply_suggestion(
        listing,
        _suggestion(current_land_area_m2=None, suggested_land_area_m2=300.0),
        apply=False,
        overwrite=False,
    )

    assert changed == ["land_area_m2"]
    assert listing.land_area_m2 is None
