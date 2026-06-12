"""Demo-only property activity engine for Product Lab."""
from __future__ import annotations

from typing import Any

DEMO_ACTIVITY_EVENT_TYPES = {
    "first_published",
    "detected_by_avm",
    "price_drop",
    "republished",
    "seen_on_portal",
    "description_changed",
    "uf_price_changed",
    "high_recent_activity",
    "no_changes",
    "stale_listing",
    "snapshot",
    "alert",
    "current_status",
}
DEMO_ACTIVITY_TONES = {"neutral", "positive", "negative", "warning", "premium"}
DEMO_ACTIVITY_SOURCE = "demo_activity_engine"


def build_property_activity(listing: dict[str, Any]) -> list[dict[str, Any]]:
    property_id = int(listing["listing_id"])
    events: list[dict[str, Any]] = []
    history = listing.get("price_history", [])
    if history:
        first = history[0]
        events.append(
            _event(
                property_id,
                first["date"],
                "first_published",
                "Publicada por primera vez",
                f"{listing['source']} publica la propiedad en UF {first['price_uf']:,.0f}.".replace(",", "."),
                "neutral",
                "low",
            )
        )

    detected_date = str(listing.get("detected_at", ""))[:10]
    events.append(
        _event(
            property_id,
            detected_date,
            "detected_by_avm",
            "Detectada por AVM",
            f"AVM incorpora la propiedad al radar demo con confianza {listing['confidence']}.",
            "premium",
            "medium",
        )
    )

    for item in history[1:]:
        event_name = item["event"]
        if event_name == "rebaja":
            change = abs(int(item.get("change_uf") or 0))
            events.append(
                _event(
                    property_id,
                    item["date"],
                    "price_drop",
                    "Rebaja de precio",
                    f"El precio baja a UF {item['price_uf']:,.0f}; ajuste demo de UF {change:,.0f}.".replace(",", "."),
                    "positive",
                    "medium",
                )
            )
        elif event_name == "republicado":
            events.append(
                _event(
                    property_id,
                    item["date"],
                    "republished",
                    "Republicada",
                    "La publicacion vuelve a aparecer activa en el dataset demo.",
                    "warning",
                    "medium",
                )
            )
        elif event_name == "subida":
            events.append(
                _event(
                    property_id,
                    item["date"],
                    "uf_price_changed",
                    "Cambio precio UF",
                    f"El precio sube a UF {item['price_uf']:,.0f} en la simulacion.".replace(",", "."),
                    "warning",
                    "medium",
                )
            )
        elif event_name == "sin cambios":
            events.append(
                _event(
                    property_id,
                    item["date"],
                    "no_changes",
                    "Sin cambios por varios dias",
                    f"El precio se mantiene en UF {item['price_uf']:,.0f}.",
                    "neutral",
                    "low",
                )
            )

    presence = listing.get("portal_presence", [])
    if len(presence) > 1:
        active = sum(1 for item in presence if item["is_active"])
        events.append(
            _event(
                property_id,
                max(item["last_seen"] for item in presence),
                "seen_on_portal",
                "Vista en otro portal",
                f"Aparece en {len(presence)} portales demo; {active} siguen activos.",
                "premium",
                "medium",
            )
        )
    elif presence:
        events.append(
            _event(
                property_id,
                presence[0]["last_seen"],
                "snapshot",
                "Snapshot actualizado",
                f"Ultima captura demo desde {presence[0]['portal_name']}.",
                "neutral",
                "low",
            )
        )

    signal_types = {signal["signal_type"] for signal in listing.get("signals", [])}
    if {"price_drop", "seller_pressure", "aggressive_negotiation"} & signal_types:
        events.append(
            _event(
                property_id,
                detected_date,
                "high_recent_activity",
                "Alta actividad reciente",
                "Rebajas y senales de negociacion elevan la prioridad demo.",
                "warning",
                "high",
            )
        )
    if listing.get("days_on_market", 0) >= 60 or "hold" in signal_types:
        events.append(
            _event(
                property_id,
                detected_date,
                "stale_listing",
                "Posible listing estancado",
                f"Lleva {listing['days_on_market']} dias en mercado dentro de la simulacion.",
                "warning",
                "medium",
            )
        )
    if "legal_risk" in signal_types:
        events.append(
            _event(
                property_id,
                detected_date,
                "alert",
                "Alerta simulada",
                "El motor demo marca revision legal antes de ofertar.",
                "negative",
                "high",
            )
        )

    events.append(
        _event(
            property_id,
            detected_date,
            "current_status",
            "Estado actual",
            f"Estado demo: {listing['status']}; score radar {listing['score']:.1f}.",
            "positive" if listing["status"] == "active" else "neutral",
            "low",
        )
    )
    return sorted(events, key=lambda item: (item["date"], item["id"]), reverse=True)


def _event(
    property_id: int,
    date: str,
    event_type: str,
    title: str,
    description: str,
    tone: str,
    severity: str,
) -> dict[str, Any]:
    if event_type not in DEMO_ACTIVITY_EVENT_TYPES:
        raise ValueError(f"Invalid demo activity event_type: {event_type}")
    if tone not in DEMO_ACTIVITY_TONES:
        raise ValueError(f"Invalid demo activity tone: {tone}")
    safe_date = date or "2026-05-01"
    return {
        "id": f"demo-{property_id}-{safe_date}-{event_type}",
        "property_id": property_id,
        "date": safe_date,
        "event_type": event_type,
        "title": title,
        "description": description,
        "tone": tone,
        "severity": severity,
        "source": DEMO_ACTIVITY_SOURCE,
        "is_demo": True,
    }
