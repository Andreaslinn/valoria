from ui.demo_data import get_demo_listings
from ui.lab_focus import (
    GLOBAL_FOCUS_PROPERTY_ID_KEY,
    GLOBAL_FOCUS_SOURCE_KEY,
    clear_focus_property,
    get_focused_demo_listing,
    set_focus_property,
    truncate_title,
)


def test_truncate_title_short_and_long() -> None:
    assert truncate_title("Casa demo", max_len=45) == "Casa demo"
    assert truncate_title("Departamento familiar amplio en Providencia", max_len=18) == "Departamento fami…"


def test_set_and_clear_focus_property() -> None:
    state: dict[str, object] = {}

    set_focus_property("101", source="Radar", state=state)

    assert state[GLOBAL_FOCUS_PROPERTY_ID_KEY] == 101
    assert state[GLOBAL_FOCUS_SOURCE_KEY] == "Radar"

    clear_focus_property(state)

    assert GLOBAL_FOCUS_PROPERTY_ID_KEY not in state
    assert GLOBAL_FOCUS_SOURCE_KEY not in state


def test_get_focused_demo_listing_returns_none_for_invalid_id() -> None:
    state: dict[str, object] = {GLOBAL_FOCUS_PROPERTY_ID_KEY: -999}

    assert get_focused_demo_listing(state) is None
    assert GLOBAL_FOCUS_PROPERTY_ID_KEY not in state


def test_get_focused_demo_listing_returns_listing() -> None:
    expected_id = int(get_demo_listings()[0]["listing_id"])
    state: dict[str, object] = {GLOBAL_FOCUS_PROPERTY_ID_KEY: expected_id}

    listing = get_focused_demo_listing(state)

    assert listing is not None
    assert listing["listing_id"] == expected_id
