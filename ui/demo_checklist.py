"""Demo-only due diligence checklist for Product Lab."""
from __future__ import annotations

from collections.abc import MutableMapping
from copy import deepcopy
from typing import Any

DEMO_CHECKLIST_STATE_KEY = "demo_due_diligence_checklist_state"
DEMO_CHECKLIST_DISCLAIMER = "Checklist simulada. No reemplaza asesoria legal ni estudio de titulos."
DEMO_CHECKLIST_STATUSES = {"pendiente", "revisado", "riesgo", "no aplica"}
DEMO_CHECKLIST_PRIORITIES = {"baja", "media", "alta", "critica"}
DEMO_CHECKLIST_CATEGORIES = [
    "precio y mercado",
    "documentos",
    "CBR simulado",
    "contribuciones",
    "comunidad/gastos comunes",
    "permisos/regularizacion",
    "banco/financiamiento",
    "visita fisica",
    "negociacion",
]


def build_demo_due_diligence_checklist(
    listing: dict[str, Any],
    *,
    risk_report: dict[str, Any] | None = None,
    autofact_report: dict[str, Any] | None = None,
    demo_mode: bool = True,
) -> dict[str, Any]:
    if not demo_mode:
        return {}
    items = _base_items(listing)
    _apply_risk_context(items, risk_report or {}, autofact_report or {})
    return {
        "is_demo": True,
        "property_id": int(listing["listing_id"]),
        "property_title": listing["title"],
        "categories": DEMO_CHECKLIST_CATEGORIES,
        "items": items,
        "disclaimer": DEMO_CHECKLIST_DISCLAIMER,
    }


def ensure_demo_checklist_state(
    session_state: MutableMapping[str, Any],
    checklist: dict[str, Any],
) -> dict[str, Any]:
    state = session_state.get(DEMO_CHECKLIST_STATE_KEY)
    if isinstance(state, dict) and state.get("is_demo") is True:
        state.setdefault("items", {})
        return state
    state = {"is_demo": True, "items": {}}
    session_state[DEMO_CHECKLIST_STATE_KEY] = state
    return state


def hydrate_demo_checklist(checklist: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    _assert_state(state)
    hydrated = deepcopy(checklist)
    property_id = int(checklist["property_id"])
    for item in hydrated["items"]:
        saved = _saved_item(state, property_id, item["id"])
        if saved:
            item["status"] = saved.get("status", item["status"])
            item["note"] = saved.get("note", "")
        else:
            item["note"] = ""
    hydrated["progress"] = calculate_demo_checklist_progress(hydrated)
    return hydrated


def set_demo_checklist_item_status(
    state: dict[str, Any],
    property_id: int,
    item_id: str,
    status: str,
) -> dict[str, Any]:
    _assert_state(state)
    if status not in DEMO_CHECKLIST_STATUSES:
        raise ValueError(f"Invalid demo checklist status: {status}")
    item = _ensure_item_state(state, property_id, item_id)
    item["status"] = status
    return state


def set_demo_checklist_item_note(
    state: dict[str, Any],
    property_id: int,
    item_id: str,
    note: str,
) -> dict[str, Any]:
    _assert_state(state)
    item = _ensure_item_state(state, property_id, item_id)
    item["note"] = note.strip()
    return state


def calculate_demo_checklist_progress(checklist: dict[str, Any]) -> dict[str, Any]:
    items = checklist.get("items", [])
    total = len(items)
    done = sum(1 for item in items if item["status"] in {"revisado", "no aplica"})
    risks_pending = sum(1 for item in items if item["status"] == "riesgo")
    critical_pending = sum(
        1
        for item in items
        if item["priority"] == "critica" and item["status"] in {"pendiente", "riesgo"}
    )
    return {
        "total_items": total,
        "completed_items": done,
        "completion_pct": round((done / total) * 100) if total else 0,
        "risks_pending": risks_pending,
        "critical_pending": critical_pending,
    }


def _base_items(listing: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _item("precio-mercado", "precio y mercado", "Contrastar precio publicado", f"Comparar UF {listing['price_uf']:,} con estimacion demo y comparables activos.".replace(",", "."), "alta", "pendiente", "Brecha vs estimacion", "Revisar Risk Report Demo y comparables."),
        _item("historial-precio", "precio y mercado", "Revisar historial de precio", "Confirmar si las rebajas demo cambian la tesis de negociacion.", "media", "pendiente", "Rebajas detectadas", "Mirar timeline y price history."),
        _item("titulos", "documentos", "Solicitar carpeta documental", "Preparar lista de documentos reales que deberian validarse fuera del Lab.", "critica", "pendiente", "Documentacion pendiente", "Pedir estudio de titulos real."),
        _item("cbr-dominio", "CBR simulado", "Validar dominio vigente", "El CBR Demo solo muestra una simulacion de dominio y gravamenes.", "critica", "pendiente", "CBR simulado", "Confirmar con CBR real antes de decidir."),
        _item("contribuciones", "contribuciones", "Revisar contribuciones", "Confirmar deuda, exenciones o pagos pendientes con fuente oficial.", "alta", "pendiente", "Contribuciones", "Validar con certificado real."),
        _item("gastos-comunes", "comunidad/gastos comunes", "Pedir gastos comunes y actas", "Entender costos recurrentes, morosidad y acuerdos de la comunidad.", "media", "pendiente", "Costo recurrente", "Solicitar ultimas liquidaciones y actas."),
        _item("regularizacion", "permisos/regularizacion", "Validar permisos y recepcion", "Revisar si ampliaciones, estacionamientos o bodegas estan regularizados.", "alta", "pendiente", "Permisos municipales", "Pedir documentos municipales reales."),
        _item("financiamiento", "banco/financiamiento", "Validar financiamiento", "Simular restricciones de banco, pie y tasacion bancaria.", "media", "pendiente", "Financiamiento", "Confirmar preaprobacion fuera del demo."),
        _item("visita", "visita fisica", "Agendar visita fisica", "Revisar estado real, ruido, orientacion, humedad y entorno inmediato.", "alta", "pendiente", "Inspeccion presencial", "Preparar pauta de visita."),
        _item("oferta", "negociacion", "Preparar argumento de oferta", "Alinear oferta, senales de negociacion y riesgo de perder oportunidad.", "alta", "pendiente", "Estrategia de oferta", "Usar Simulador de oferta Lab."),
    ]


def _apply_risk_context(
    items: list[dict[str, Any]],
    risk_report: dict[str, Any],
    autofact_report: dict[str, Any],
) -> None:
    scores = risk_report.get("scores", {})
    legal_score = int(scores.get("legal_simulated") or autofact_report.get("legal_score") or 100)
    total_score = int(scores.get("total") or 100)
    risk_level = str(autofact_report.get("risk_level") or "low")
    for item in items:
        if item["category"] in {"CBR simulado", "documentos"} and (legal_score < 70 or risk_level == "high"):
            item["status"] = "riesgo"
            item["priority"] = "critica"
            item["related_signal"] = "Riesgo legal simulado"
        if item["category"] == "contribuciones" and any("contrib" in str(flag).lower() for flag in autofact_report.get("tax_flags", [])):
            item["priority"] = "critica" if risk_level == "high" else item["priority"]
        if item["category"] == "permisos/regularizacion" and risk_level in {"medium", "high"}:
            item["status"] = "riesgo"
            item["related_signal"] = "Regularizacion por revisar"
        if item["category"] == "precio y mercado" and total_score < 65:
            item["status"] = "riesgo"
            item["related_signal"] = "Riesgo de mercado demo"


def _item(
    item_id: str,
    category: str,
    title: str,
    description: str,
    priority: str,
    status: str,
    related_signal: str,
    action_hint: str,
) -> dict[str, Any]:
    if category not in DEMO_CHECKLIST_CATEGORIES:
        raise ValueError(f"Invalid demo checklist category: {category}")
    if priority not in DEMO_CHECKLIST_PRIORITIES:
        raise ValueError(f"Invalid demo checklist priority: {priority}")
    if status not in DEMO_CHECKLIST_STATUSES:
        raise ValueError(f"Invalid demo checklist status: {status}")
    return {
        "id": item_id,
        "category": category,
        "title": title,
        "description": description,
        "priority": priority,
        "status": status,
        "related_signal": related_signal,
        "action_hint": action_hint,
        "is_demo": True,
    }


def _ensure_item_state(state: dict[str, Any], property_id: int, item_id: str) -> dict[str, str]:
    key = f"{int(property_id)}:{item_id}"
    items = state.setdefault("items", {})
    item = items.setdefault(key, {"status": "pendiente", "note": ""})
    return item


def _saved_item(state: dict[str, Any], property_id: int, item_id: str) -> dict[str, str] | None:
    return state.get("items", {}).get(f"{int(property_id)}:{item_id}")


def _assert_state(state: dict[str, Any]) -> None:
    if not isinstance(state, dict) or state.get("is_demo") is not True:
        raise ValueError("Demo checklist state is required.")
