"""Demo-only real-estate Autofact report builder."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

AUTOFact_DEMO_DISCLAIMERS = [
    "Datos simulados.",
    "No reemplaza estudio de títulos.",
    "No usar para decisiones reales.",
]


def build_demo_autofact_report(listing: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    risk_level = str(base["risk_level"])
    legal_score = int(base["legal_score"])
    report = {
        **deepcopy(base),
        "is_demo": True,
        "property_id": int(listing["listing_id"]),
        "property_identity": _identity(listing),
        "simulated_cbr_status": base["cbr_status"],
        "ownership_summary": _ownership_summary(base, risk_level),
        "ownership_history": _ownership_history(listing, risk_level),
        "liens_flags": _flags("gravamen", base.get("liens") or ["Sin gravámenes simulados visibles"], risk_level),
        "mortgage_flags": _mortgage_flags(risk_level),
        "prohibition_flags": _prohibition_flags(risk_level),
        "tax_flags": _tax_flags(base),
        "permits_flags": _permits_flags(base),
        "municipal_flags": _municipal_flags(risk_level),
        "building_regularization": _regularization(base, risk_level),
        "legal_timeline": _legal_timeline(listing, risk_level),
        "review_recommendations": _recommendations(risk_level),
        "critical_flags": _critical_flags(base, risk_level),
        "legal_score": legal_score,
        "data_confidence": base["confidence"],
        "disclaimer": " ".join(AUTOFact_DEMO_DISCLAIMERS),
        "disclaimers": AUTOFact_DEMO_DISCLAIMERS,
    }
    return report


def _identity(listing: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": listing["title"],
        "comuna": listing["comuna"],
        "address_label": listing["address_label"],
        "property_type": listing["property_type"],
        "m2": listing["m2"],
        "bedrooms": listing["bedrooms"],
        "bathrooms": listing["bathrooms"],
        "parking_spaces": listing["parking_spaces"],
        "source": listing["source"],
        "is_demo": True,
    }


def _ownership_summary(base: dict[str, Any], risk_level: str) -> str:
    if risk_level == "high":
        return "Dominio simulado vigente con antecedentes que requieren revisión profesional."
    if risk_level == "medium":
        return "Dominio simulado vigente con observaciones menores o documentación pendiente."
    return "Dominio simulado vigente sin alertas críticas en el escenario demo."


def _ownership_history(listing: dict[str, Any], risk_level: str) -> list[dict[str, str]]:
    return [
        {
            "date": "2018-03-14",
            "event": "Inscripción simulada",
            "description": f"Primera inscripción demo asociada a {listing['address_label']}.",
            "severity": "neutral",
        },
        {
            "date": "2021-09-02",
            "event": "Modificación",
            "description": "Actualización simulada de antecedente de dominio.",
            "severity": "neutral",
        },
        {
            "date": "2025-11-18",
            "event": "Advertencia municipal" if risk_level == "high" else "Revisión municipal simulada",
            "description": "Registro municipal simulado marcado para revisión." if risk_level == "high" else "Sin observaciones municipales críticas en demo.",
            "severity": "high" if risk_level == "high" else "low",
        },
    ]


def _flags(flag_type: str, labels: list[str], risk_level: str) -> list[dict[str, str]]:
    severity = "high" if risk_level == "high" else "medium" if risk_level == "medium" else "low"
    return [{"type": flag_type, "label": label, "severity": severity} for label in labels]


def _mortgage_flags(risk_level: str) -> list[dict[str, str]]:
    if risk_level == "high":
        return [_flag("mortgage", "Hipoteca simulada por confirmar", "high")]
    return [_flag("mortgage", "Hipoteca alzada en simulación", "low")]


def _prohibition_flags(risk_level: str) -> list[dict[str, str]]:
    if risk_level == "high":
        return [_flag("prohibition", "Posible prohibición simulada por revisar", "high")]
    return [_flag("prohibition", "Sin prohibiciones simuladas visibles", "low")]


def _tax_flags(base: dict[str, Any]) -> list[dict[str, str]]:
    warning = base.get("tax_warning")
    if warning:
        return [_flag("tax", warning, "high")]
    return [_flag("tax", "Contribuciones al día en simulación", "low")]


def _permits_flags(base: dict[str, Any]) -> list[dict[str, str]]:
    warning = base.get("permits_warning")
    if warning:
        return [_flag("permits", warning, "medium")]
    return [_flag("permits", "Permisos sin alertas simuladas", "low")]


def _municipal_flags(risk_level: str) -> list[dict[str, str]]:
    if risk_level == "medium":
        return [_flag("municipal", "Regularización municipal simulada por validar", "medium")]
    if risk_level == "high":
        return [_flag("municipal", "Advertencia municipal simulada", "high")]
    return [_flag("municipal", "Sin observaciones municipales simuladas", "low")]


def _regularization(base: dict[str, Any], risk_level: str) -> dict[str, str]:
    if base.get("permits_warning"):
        return {"status": "pendiente", "summary": base["permits_warning"], "severity": "medium"}
    if risk_level == "high":
        return {"status": "revisar", "summary": "Regularización simulada requiere validación.", "severity": "high"}
    return {"status": "ok_simulado", "summary": "Edificación regularizada en escenario demo.", "severity": "low"}


def _legal_timeline(listing: dict[str, Any], risk_level: str) -> list[dict[str, str]]:
    tax_event = "alerta simulada" if risk_level == "high" else "contribuciones al día"
    tax_severity = "high" if risk_level == "high" else "low"
    return [
        _timeline("2018-03-14", "Inscripción simulada", "Dominio demo inscrito para la propiedad.", "neutral"),
        _timeline("2021-09-02", "Modificación", "Cambio administrativo simulado.", "neutral"),
        _timeline("2023-05-21", "Hipoteca alzada", "Alzamiento hipotecario simulado registrado.", "low"),
        _timeline("2024-07-09", "Permiso regularizado", "Permiso municipal simulado actualizado.", "low" if risk_level != "high" else "medium"),
        _timeline("2025-11-18", "Advertencia municipal", "Observación municipal simulada para revisar." if risk_level != "low" else "Sin advertencia crítica simulada.", "medium" if risk_level != "low" else "low"),
        _timeline("2026-04-30", tax_event, f"Revisión demo de contribuciones para {listing['comuna']}.", tax_severity),
    ]


def _recommendations(risk_level: str) -> list[str]:
    base = [
        "Solicitar estudio de títulos real antes de cualquier decisión.",
        "Validar dominio vigente y certificados reales en CBR.",
        "Confirmar contribuciones, deuda municipal y permisos con fuentes oficiales.",
    ]
    if risk_level == "high":
        return ["Pausar oferta hasta revisión legal real.", *base]
    if risk_level == "medium":
        return ["Avanzar solo con condición de revisión documental.", *base]
    return ["Usar este reporte solo como vista demo de producto.", *base]


def _critical_flags(base: dict[str, Any], risk_level: str) -> list[dict[str, str]]:
    flags: list[dict[str, str]] = []
    if base.get("liens"):
        flags.extend(_flags("gravamen", base["liens"], risk_level))
    if base.get("tax_warning"):
        flags.append(_flag("tax", base["tax_warning"], "high"))
    if base.get("permits_warning"):
        flags.append(_flag("permits", base["permits_warning"], "medium"))
    if risk_level == "high":
        flags.append(_flag("legal", "Riesgo legal simulado alto", "high"))
    return flags or [_flag("general", "Sin flags críticas simuladas", "low")]


def _flag(flag_type: str, label: str, severity: str) -> dict[str, str]:
    return {"type": flag_type, "label": label, "severity": severity}


def _timeline(date: str, event: str, description: str, severity: str) -> dict[str, str]:
    return {"date": date, "event": event, "description": description, "severity": severity}
