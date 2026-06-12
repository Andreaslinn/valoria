from __future__ import annotations

from types import SimpleNamespace

from scripts.backfill_house_area_corrections import suggest_house_area_correction


def _row(**overrides):
    base = {
        "id": 1,
        "external_id": "ext-1",
        "title": "Casa en venta con terreno de 5.432 m2",
        "comuna": "vitacura",
        "m2": 590.0,
        "built_area_m2": 590.0,
        "land_area_m2": 5.432,
        "raw_metadata": {
            "description": "Casa con 590 m2 construidos y terreno de 5.432 m2.",
            "built_area_parse_source": "raw.built_area_m2",
            "land_area_parse_source": "text.land_area_context",
        },
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_suggestion_repairs_land_area_thousands_separator() -> None:
    suggestion = suggest_house_area_correction(_row())

    assert suggestion.suggested_land_area_m2 == 5432
    assert "land_area_m2" in suggestion.changed_fields
    assert "land_area_reparsed_from_text" in suggestion.reasons
    assert suggestion.suggested_built_area_m2 == 590


def test_suggestion_clears_built_area_when_it_was_land_fallback() -> None:
    suggestion = suggest_house_area_correction(
        _row(
            title="Liquido terreno 1.000 m2 con 3 casas",
            m2=1.0,
            built_area_m2=1.0,
            land_area_m2=1.0,
            raw_metadata={
                "description": "",
                "built_area_parse_source": "raw.m2.fallback",
                "land_area_parse_source": "text.land_area_context",
            },
        )
    )

    assert suggestion.suggested_land_area_m2 == 1000
    assert suggestion.suggested_built_area_m2 is None
    assert suggestion.suggested_m2 is None
    assert set(suggestion.changed_fields) == {"land_area_m2", "built_area_m2", "m2"}
