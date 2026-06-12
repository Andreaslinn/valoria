"""Demo-only feedback and lightweight usage metrics for Product Lab."""
from __future__ import annotations

from collections import Counter
from collections.abc import MutableMapping
from datetime import datetime
from typing import Any

DEMO_FEEDBACK_STATE_KEY = "demo_lab_feedback_state"
DEMO_FEEDBACK_OPTIONS = {
    "util": {"label": "Util", "sentiment": "positive"},
    "confuso": {"label": "Confuso", "sentiment": "confusing"},
    "interesante": {"label": "Interesante", "sentiment": "positive"},
    "lo_pagaria": {"label": "Lo pagaria", "sentiment": "premium"},
    "no_me_sirve": {"label": "No me sirve", "sentiment": "negative"},
}
DEMO_FEEDBACK_MODULES = {
    "risk_report": "Risk Report Demo",
    "autofact": "Autofact Demo",
    "offer_simulator": "Simulador de oferta",
    "comparison": "Comparador",
    "checklist": "Checklist",
    "decision_board": "Decision Board",
    "alert_center": "Alert Center",
}
DEMO_LAB_EVENTS = {
    "opened_risk_report",
    "saved_property_demo",
    "generated_offer_demo",
    "opened_autofact_demo",
    "used_checklist_demo",
    "moved_decision_card_demo",
}


def ensure_demo_feedback_state(session_state: MutableMapping[str, Any]) -> dict[str, Any]:
    state = session_state.get(DEMO_FEEDBACK_STATE_KEY)
    if isinstance(state, dict) and state.get("is_demo") is True:
        state.setdefault("feedback", [])
        state.setdefault("events", [])
        return state
    state = {"is_demo": True, "feedback": [], "events": []}
    session_state[DEMO_FEEDBACK_STATE_KEY] = state
    return state


def record_demo_feedback(
    state: dict[str, Any],
    module: str,
    feedback: str,
    *,
    property_id: int | None = None,
    demo_mode: bool = True,
) -> dict[str, Any]:
    if not demo_mode:
        return state
    _assert_state(state)
    if module not in DEMO_FEEDBACK_MODULES:
        raise ValueError(f"Invalid demo feedback module: {module}")
    if feedback not in DEMO_FEEDBACK_OPTIONS:
        raise ValueError(f"Invalid demo feedback: {feedback}")
    state["feedback"].append(
        {
            "module": module,
            "module_label": DEMO_FEEDBACK_MODULES[module],
            "feedback": feedback,
            "feedback_label": DEMO_FEEDBACK_OPTIONS[feedback]["label"],
            "sentiment": DEMO_FEEDBACK_OPTIONS[feedback]["sentiment"],
            "property_id": property_id,
            "created_at": _now(),
            "is_demo": True,
        }
    )
    return state


def record_demo_event(
    state: dict[str, Any],
    event_name: str,
    *,
    module: str | None = None,
    property_id: int | None = None,
    metadata: dict[str, Any] | None = None,
    demo_mode: bool = True,
) -> dict[str, Any]:
    if not demo_mode:
        return state
    _assert_state(state)
    if event_name not in DEMO_LAB_EVENTS:
        raise ValueError(f"Invalid demo lab event: {event_name}")
    if module is not None and module not in DEMO_FEEDBACK_MODULES:
        raise ValueError(f"Invalid demo feedback module: {module}")
    state["events"].append(
        {
            "event_name": event_name,
            "module": module,
            "property_id": property_id,
            "metadata": metadata or {},
            "created_at": _now(),
            "is_demo": True,
        }
    )
    return state


def summarize_demo_feedback(state: dict[str, Any]) -> dict[str, Any]:
    _assert_state(state)
    feedback = list(state.get("feedback", []))
    events = list(state.get("events", []))
    event_modules = Counter(event.get("module") for event in events if event.get("module"))
    positive = Counter(
        item["module"]
        for item in feedback
        if item["feedback"] in {"util", "interesante", "lo_pagaria"}
    )
    confusing = Counter(item["module"] for item in feedback if item["feedback"] == "confuso")
    premium = Counter(item["module"] for item in feedback if item["feedback"] == "lo_pagaria")
    remove = Counter(item["module"] for item in feedback if item["feedback"] == "no_me_sirve")
    return {
        "is_demo": True,
        "total_feedback": len(feedback),
        "total_events": len(events),
        "modules_most_used": _rank(event_modules),
        "modules_positive": _rank(positive),
        "modules_confusing": _rank(confusing),
        "features_premium": _rank(premium),
        "features_to_remove": _rank(remove),
        "event_counts": dict(Counter(event["event_name"] for event in events)),
        "feedback_counts": dict(Counter(item["feedback"] for item in feedback)),
    }


def _rank(counter: Counter[str | None]) -> list[dict[str, Any]]:
    return [
        {
            "module": str(module),
            "module_label": DEMO_FEEDBACK_MODULES.get(str(module), str(module)),
            "count": count,
        }
        for module, count in counter.most_common()
        if module is not None
    ]


def _assert_state(state: dict[str, Any]) -> None:
    if not isinstance(state, dict) or state.get("is_demo") is not True:
        raise ValueError("Demo feedback state is required.")


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()
