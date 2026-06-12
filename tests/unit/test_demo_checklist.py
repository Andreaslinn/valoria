from __future__ import annotations

import pytest

from ui.demo_checklist import (
    DEMO_CHECKLIST_CATEGORIES,
    DEMO_CHECKLIST_STATUSES,
    build_demo_due_diligence_checklist,
    calculate_demo_checklist_progress,
    ensure_demo_checklist_state,
    hydrate_demo_checklist,
    set_demo_checklist_item_note,
    set_demo_checklist_item_status,
)
from ui.demo_data import get_demo_listings
from ui.demo_providers import get_demo_autofact_report, get_demo_risk_report


def test_checklist_is_generated_with_all_categories() -> None:
    listing = get_demo_listings()[0]
    checklist = build_demo_due_diligence_checklist(
        listing,
        risk_report=get_demo_risk_report(int(listing["listing_id"]), demo_mode=True),
        autofact_report=get_demo_autofact_report(int(listing["listing_id"]), demo_mode=True),
    )

    assert checklist["is_demo"] is True
    assert {item["category"] for item in checklist["items"]} == set(DEMO_CHECKLIST_CATEGORIES)
    for item in checklist["items"]:
        assert set(item) >= {
            "title",
            "description",
            "priority",
            "status",
            "related_signal",
            "action_hint",
        }
        assert item["status"] in DEMO_CHECKLIST_STATUSES


def test_checklist_progress_is_calculated() -> None:
    listing = get_demo_listings()[1]
    checklist = build_demo_due_diligence_checklist(listing)
    checklist["items"][0]["status"] = "revisado"
    checklist["items"][1]["status"] = "no aplica"
    checklist["items"][2]["status"] = "riesgo"

    progress = calculate_demo_checklist_progress(checklist)

    assert progress["total_items"] == len(checklist["items"])
    assert progress["completed_items"] == 2
    assert progress["completion_pct"] > 0
    assert progress["risks_pending"] >= 1


def test_checklist_state_status_and_notes_are_hydrated() -> None:
    listing = get_demo_listings()[0]
    checklist = build_demo_due_diligence_checklist(listing)
    session: dict[str, object] = {}
    state = ensure_demo_checklist_state(session, checklist)
    item_id = checklist["items"][0]["id"]

    set_demo_checklist_item_status(state, int(listing["listing_id"]), item_id, "revisado")
    set_demo_checklist_item_note(state, int(listing["listing_id"]), item_id, "Pedir respaldo real.")
    hydrated = hydrate_demo_checklist(checklist, state)

    assert hydrated["items"][0]["status"] == "revisado"
    assert hydrated["items"][0]["note"] == "Pedir respaldo real."
    assert hydrated["progress"]["completed_items"] >= 1


def test_invalid_status_is_rejected() -> None:
    listing = get_demo_listings()[0]
    checklist = build_demo_due_diligence_checklist(listing)
    state = ensure_demo_checklist_state({}, checklist)

    with pytest.raises(ValueError):
        set_demo_checklist_item_status(state, int(listing["listing_id"]), checklist["items"][0]["id"], "listo")


def test_checklist_is_demo_only() -> None:
    assert build_demo_due_diligence_checklist(get_demo_listings()[0], demo_mode=False) == {}
