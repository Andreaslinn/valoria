"""Demo providers and data contracts for AVM Product Lab."""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, cast

from config.constants import MIN_COMPARABLES, TOP_N_COMPARABLES
from core.entities.listing import Listing, Property
from core.exceptions import InsufficientDataError, ValidationError
from core.value_objects.price import Price
from domain.valuation.comparables import filter_candidates, valuate
from domain.valuation.scoring import similarity_score
from services.formatting import confidence_label, price_clp_int, price_uf_float
from ui.demo_activity import build_property_activity
from ui.demo_autofact import build_demo_autofact_report
from ui.demo_data import (
    CLP_PER_UF,
    DEMO_ACTIVITY_DISCLAIMER,
    DEMO_DISCLAIMER,
    DEMO_LISTINGS,
    DEMO_RECOMMENDATIONS,
    DEMO_RISK_REPORT,
)
from ui.demo_market import get_demo_market_context
from ui.demo_negotiation import build_demo_negotiation_report
from ui.demo_types import (
    AutofactReport,
    AutofactSeed,
    DemoAvmScore,
    DemoListing,
    DemoMarketTiming,
    DemoPortalPresence,
    DemoPriceHistoryPoint,
    DemoPropertyComparison,
    DemoRecommendation,
    DemoRiskReport,
    NegotiationSignal,
    OwnerRecommendation,
    PropertyActivityEvent,
)

LAB_DEMO_MIN_COMPARABLES = 2
DEMO_UF_TO_CLP = Decimal(str(CLP_PER_UF))

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


def get_demo_avm_score(listing: DemoListing) -> DemoAvmScore:
    target = _demo_listing_to_domain_listing(listing)
    if target is None:
        return _insufficient_demo_avm()

    target_id = _demo_property_id(listing)
    candidates = [
        candidate
        for raw in DEMO_LISTINGS
        if _demo_property_id(raw) != target_id
        if (candidate := _demo_listing_to_domain_listing(raw)) is not None
    ]

    target_property = _demo_listing_as_property(target)
    strict_candidates = filter_candidates(target_property, candidates)
    if len(strict_candidates) >= MIN_COMPARABLES:
        try:
            valuation = valuate(target_property, candidates, DEMO_UF_TO_CLP)
        except (InsufficientDataError, ValidationError):
            valuation = None
        if valuation is not None:
            estimated_uf = price_uf_float(valuation.estimated_price, DEMO_UF_TO_CLP)
            return {
                "estimated_value_uf": estimated_uf,
                "estimated_value_clp": price_clp_int(valuation.estimated_price),
                "confidence_score": round(valuation.confidence.value, 4),
                "confidence_label": confidence_label(valuation.confidence.value),
                "discount_pct": _demo_discount_pct(estimated_uf, _safe_float(listing.get("price_uf"))),
                "comparables_used": valuation.comparables_used,
                "avm_source": "domain_logic_demo",
                "is_demo": True,
            }

    lab_candidates = _rank_lab_demo_candidates(target_property, candidates)
    if len(lab_candidates) < LAB_DEMO_MIN_COMPARABLES:
        return _insufficient_demo_avm()

    selected = lab_candidates[:TOP_N_COMPARABLES]
    lab_estimated_uf = _weighted_demo_estimate_uf(target_property, selected)
    if lab_estimated_uf is None:
        return _insufficient_demo_avm()
    confidence = _lab_demo_confidence(selected)
    estimated_clp = int((Decimal(str(lab_estimated_uf)) * DEMO_UF_TO_CLP).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return {
        "estimated_value_uf": lab_estimated_uf,
        "estimated_value_clp": estimated_clp,
        "confidence_score": round(confidence, 4),
        "confidence_label": confidence_label(confidence),
        "discount_pct": _demo_discount_pct(lab_estimated_uf, _safe_float(listing.get("price_uf"))),
        "comparables_used": len(selected),
        "avm_source": "domain_logic_demo",
        "is_demo": True,
    }


def _insufficient_demo_avm() -> DemoAvmScore:
    return {
        "estimated_value_uf": None,
        "estimated_value_clp": None,
        "confidence_score": None,
        "confidence_label": "insufficient_demo_comparables",
        "discount_pct": None,
        "comparables_used": 0,
        "avm_source": "domain_logic_demo",
        "is_demo": True,
    }


def _demo_listing_to_domain_listing(raw: DemoListing) -> Listing | None:
    price_uf = _safe_float(raw.get("price_uf"))
    m2 = _safe_float(raw.get("m2"))
    comuna = str(raw.get("comuna") or "").strip()
    if price_uf is None or price_uf <= 0 or m2 is None or m2 <= 0 or not comuna:
        return None
    property_id = _demo_property_id(raw)
    return Listing(
        id=property_id,
        source=str(raw.get("source") or "demo"),
        external_id=str(property_id) if property_id is not None else None,
        title=str(raw.get("title") or "Demo listing"),
        comuna=comuna,
        m2=m2,
        bedrooms=_safe_int(raw.get("bedrooms")) or 0,
        bathrooms=_safe_int(raw.get("bathrooms")) or 0,
        parking=_safe_int(raw.get("parking_spaces") or raw.get("parking")) or 0,
        price=Price(clp=Decimal(str(price_uf)) * DEMO_UF_TO_CLP),
        status=str(raw.get("status") or "active"),
        fingerprint=f"demo-{property_id or raw.get('title') or id(raw)}",
        scraped_at=_demo_datetime(raw.get("detected_at")),
        url=raw.get("url") or raw.get("listing_url"),
    )


def _demo_listing_as_property(listing: Listing) -> Property:
    return Property(
        id=listing.property_id,
        comuna=listing.comuna,
        m2=float(listing.m2 or 0),
        bedrooms=listing.bedrooms,
        bathrooms=listing.bathrooms,
        parking=listing.parking,
        coordinates=listing.coordinates,
    )


def _rank_lab_demo_candidates(target: Property, candidates: list[Listing]) -> list[tuple[float, Listing]]:
    valid = [candidate for candidate in candidates if candidate.is_active and candidate.price.clp > 0 and candidate.m2 and candidate.m2 > 0]
    ranked = [(similarity_score(target, candidate).value, candidate) for candidate in valid]
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return ranked


def _weighted_demo_estimate_uf(target: Property, scored: list[tuple[float, Listing]]) -> float | None:
    total_weight = Decimal("0")
    weighted_ppm2 = Decimal("0")
    for score, listing in scored:
        weight = Decimal(str(max(score, 0.01)))
        price_uf = listing.price.to_uf(DEMO_UF_TO_CLP)
        ppm2 = price_uf / Decimal(str(listing.m2))
        weighted_ppm2 += weight * ppm2
        total_weight += weight
    if total_weight == 0:
        return None
    estimate = (weighted_ppm2 / total_weight) * Decimal(str(target.m2))
    return float(estimate.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _lab_demo_confidence(scored: list[tuple[float, Listing]]) -> float:
    if not scored:
        return 0.0
    avg_similarity = sum(score for score, _ in scored) / len(scored)
    count_factor = min(1.0, len(scored) / MIN_COMPARABLES)
    return float(max(0.0, min(1.0, 0.7 * avg_similarity + 0.3 * count_factor)))


def _demo_discount_pct(estimated_value_uf: float | None, listed_price_uf: float | None) -> float | None:
    if estimated_value_uf is None or estimated_value_uf == 0 or listed_price_uf is None:
        return None
    return round(((estimated_value_uf - listed_price_uf) / estimated_value_uf) * 100, 2)


def _demo_property_id(raw: DemoListing) -> int | None:
    return _safe_int(raw.get("listing_id") or raw.get("id"))


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _demo_datetime(value: Any) -> datetime:
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(UTC)


DEMO_AUTOFACT_REPORTS: dict[int, AutofactSeed] = {
    9101: {
        "legal_score": 84,
        "cbr_status": "CBR simulado: dominio vigente sin gravámenes críticos",
        "ownership_flags": ["Dominio vigente simulado", "Un propietario simulado"],
        "liens": [],
        "debt_flags": ["Sin deuda simulada visible"],
        "tax_warning": None,
        "permits_warning": "Recepción final no verificada en demo",
        "liquidity_score": 86,
        "market_score": 88,
        "risk_level": "low",
        "confidence": "medium",
        "disclaimer": DEMO_DISCLAIMER,
    },
    9102: {
        "legal_score": 78,
        "cbr_status": "CBR simulado: revisar reglamento de copropiedad",
        "ownership_flags": ["Dominio vigente simulado"],
        "liens": [],
        "debt_flags": ["Gastos comunes simulados al día"],
        "tax_warning": None,
        "permits_warning": None,
        "liquidity_score": 91,
        "market_score": 84,
        "risk_level": "low",
        "confidence": "medium",
        "disclaimer": DEMO_DISCLAIMER,
    },
    9104: {
        "legal_score": 80,
        "cbr_status": "CBR simulado: sin alertas relevantes",
        "ownership_flags": ["Dominio vigente simulado"],
        "liens": [],
        "debt_flags": [],
        "tax_warning": None,
        "permits_warning": None,
        "liquidity_score": 83,
        "market_score": 82,
        "risk_level": "low",
        "confidence": "medium",
        "disclaimer": DEMO_DISCLAIMER,
    },
    9105: {
        "legal_score": 72,
        "cbr_status": "CBR simulado: revisar ampliaciones",
        "ownership_flags": ["Dominio vigente simulado", "Ampliación simulada por revisar"],
        "liens": [],
        "debt_flags": ["Contribuciones simuladas sin mora"],
        "tax_warning": None,
        "permits_warning": "Ampliación no verificada en demo",
        "liquidity_score": 68,
        "market_score": 76,
        "risk_level": "medium",
        "confidence": "medium",
        "disclaimer": DEMO_DISCLAIMER,
    },
    9108: {
        "legal_score": 81,
        "cbr_status": "CBR simulado: sin observaciones críticas",
        "ownership_flags": ["Dominio vigente simulado"],
        "liens": [],
        "debt_flags": [],
        "tax_warning": None,
        "permits_warning": None,
        "liquidity_score": 79,
        "market_score": 81,
        "risk_level": "low",
        "confidence": "medium",
        "disclaimer": DEMO_DISCLAIMER,
    },
    9109: {
        "legal_score": 48,
        "cbr_status": "CBR simulado: antecedente legal por revisar",
        "ownership_flags": ["Dominio vigente simulado", "Posible limitación simulada"],
        "liens": ["Hipoteca simulada por confirmar"],
        "debt_flags": ["Contribuciones simuladas por revisar"],
        "tax_warning": "Revisar deuda fiscal simulada",
        "permits_warning": None,
        "liquidity_score": 61,
        "market_score": 72,
        "risk_level": "high",
        "confidence": "low",
        "disclaimer": DEMO_DISCLAIMER,
    },
    9112: {
        "legal_score": 69,
        "cbr_status": "CBR simulado: revisar permisos y deslindes",
        "ownership_flags": ["Dominio vigente simulado"],
        "liens": [],
        "debt_flags": [],
        "tax_warning": None,
        "permits_warning": "Permisos de ampliación simulados pendientes",
        "liquidity_score": 52,
        "market_score": 61,
        "risk_level": "medium",
        "confidence": "medium",
        "disclaimer": DEMO_DISCLAIMER,
    },
}


def _find_listing(property_id: int | None = None) -> DemoListing:
    if property_id is not None:
        for listing in DEMO_LISTINGS:
            if listing["listing_id"] == property_id:
                return listing
    return DEMO_LISTINGS[0]


def _risk_level_from_scores(legal_score: int, liquidity_score: int, market_score: int) -> str:
    average = (legal_score + liquidity_score + market_score) / 3
    if legal_score < 55:
        return "high"
    if average >= 78:
        return "low"
    if average >= 62:
        return "medium"
    return "high"


# REAL IMPLEMENTATION NOTE:
# autofact_report would require CBR, tax, permit and debt integrations. A future
# endpoint could be GET /api/v1/properties/{property_id}/autofact-report.
def get_demo_autofact_report(property_id: int | None = None, *, demo_mode: bool = True) -> AutofactReport | dict[str, Any]:
    if not demo_mode:
        return {}
    listing = _find_listing(property_id)
    report = DEMO_AUTOFACT_REPORTS.get(listing["listing_id"])
    if report is not None:
        return cast(AutofactReport, build_demo_autofact_report(cast(dict[str, Any], listing), cast(dict[str, Any], report)))

    legal_score = 76 if listing["confidence"] != "low" else 58
    liquidity_score = int(min(max(listing["score"], 45), 92))
    market_score = int(min(max(listing["score"] + listing["discount_pct"], 40), 94))
    base = {
        "legal_score": legal_score,
        "cbr_status": "CBR simulado: sin revisión real disponible",
        "ownership_flags": ["Dominio vigente simulado"],
        "liens": [],
        "debt_flags": ["Sin deuda simulada visible"],
        "tax_warning": None,
        "permits_warning": "Permisos no verificados en demo",
        "liquidity_score": liquidity_score,
        "market_score": market_score,
        "risk_level": _risk_level_from_scores(legal_score, liquidity_score, market_score),
        "confidence": listing["confidence"],
        "disclaimer": DEMO_DISCLAIMER,
    }
    return cast(AutofactReport, build_demo_autofact_report(cast(dict[str, Any], listing), base))


# REAL IMPLEMENTATION NOTE:
# risk_report would combine valuation, legal checks, portal deduplication and
# market liquidity. A future endpoint could be GET /api/v1/properties/{property_id}/risk-report.
def get_demo_risk_report(property_id: int | None = None, *, demo_mode: bool = True) -> DemoRiskReport | dict[str, Any]:
    if not demo_mode:
        return {}
    listing = _find_listing(property_id)
    autofact = cast(AutofactReport, get_demo_autofact_report(listing["listing_id"]))
    risk_score = max(1, 100 - int((autofact["legal_score"] + autofact["liquidity_score"] + autofact["market_score"]) / 3))
    total_score = 100 - risk_score
    data_quality_score = 78 if listing["confidence"] == "high" else 64
    price_gap_pct = round(
        ((listing["estimated_value_uf"] - listing["price_uf"]) / listing["estimated_value_uf"]) * 100,
        1,
    )
    legal_simulation = _build_demo_legal_simulation(autofact)
    market_section = _build_demo_market_section(listing, autofact, price_gap_pct)
    negotiation_section = _build_demo_negotiation_section(listing)
    negotiation_report = get_demo_negotiation_report(listing["listing_id"], demo_mode=True)
    comparables = get_demo_property_comparison(listing["listing_id"])
    portal_presence = get_demo_portal_presence(listing["listing_id"])
    events = get_demo_property_activity(listing["listing_id"], demo_mode=True)
    report = {
        **DEMO_RISK_REPORT,
        "is_demo": True,
        "property_id": listing["listing_id"],
        "property": listing["title"],
        "property_snapshot": {
            "title": listing["title"],
            "comuna": listing["comuna"],
            "property_type": listing["property_type"],
            "address_label": listing["address_label"],
            "price_uf": listing["price_uf"],
            "estimated_value_uf": listing["estimated_value_uf"],
            "m2": listing["m2"],
            "bedrooms": listing["bedrooms"],
            "bathrooms": listing["bathrooms"],
            "parking_spaces": listing["parking_spaces"],
            "source": listing["source"],
            "confidence": listing["confidence"],
        },
        "executive_summary": listing["short_summary"],
        "risk_score": risk_score,
        "total_score": total_score,
        "market_score": autofact["market_score"],
        "liquidity_score": autofact["liquidity_score"],
        "legal_score": autofact["legal_score"],
        "data_quality_score": data_quality_score,
        "scores": {
            "total": total_score,
            "market": autofact["market_score"],
            "liquidity": autofact["liquidity_score"],
            "legal_simulated": autofact["legal_score"],
            "data_quality": data_quality_score,
        },
        "risk_tone": "positive" if risk_score < 35 else "warning" if risk_score < 55 else "negative",
        "liquidity": "Alta" if autofact["liquidity_score"] >= 80 else "Media" if autofact["liquidity_score"] >= 62 else "Baja",
        "legal_signals": autofact["cbr_status"],
        "market": f"{listing['comuna']} con señales demo: {', '.join(listing['tags'][:2])}",
        "main_risks": [
            autofact["permits_warning"] or "CBR no conectado",
            "Datos simulados",
            *autofact["liens"],
        ],
        "main_opportunities": [signal["label"] for signal in listing["signals"][:3]],
        "interpretation": f"Demo: {listing['short_summary']}",
        "recommendation": _buyer_recommendation(listing),
        "disclaimer": DEMO_DISCLAIMER,
        "demo_disclaimer": "Risk Report simulado para explorar una experiencia premium futura. No usa CBR, SII ni datos legales reales.",
        "signals": [
            {"type": signal["signal_type"], "tone": signal["tone"], "label": signal["label"]}
            for signal in listing["signals"]
        ],
        "timeline": events,
        "price_history": get_demo_price_history(listing["listing_id"]),
        "comparables": comparables,
        "comuna_context": _build_demo_comuna_context(listing),
        "market_context": get_demo_market_context(listing["comuna"], demo_mode=True),
        "portal_presence": portal_presence,
        "legal_simulation": legal_simulation,
        "autofact_report": autofact,
        "market_section": market_section,
        "negotiation_section": negotiation_section,
        "negotiation_signals": negotiation_report,
        "sections": {
            "executive_summary": listing["short_summary"],
            "legal": legal_simulation,
            "autofact_report": autofact,
            "market": market_section,
            "negotiation": negotiation_section,
            "negotiation_signals": negotiation_report,
            "timeline": events,
            "price_history": get_demo_price_history(listing["listing_id"]),
            "comparables": comparables,
            "comuna_context": _build_demo_comuna_context(listing),
            "market_context": get_demo_market_context(listing["comuna"], demo_mode=True),
            "portal_presence": portal_presence,
        },
    }
    return deepcopy(report)


# REAL IMPLEMENTATION NOTE:
# portal_presence would be fed by listing deduplication across scraper sources and
# could later live behind GET /api/v1/properties/{property_id}/portal-presence.
def get_demo_portal_presence(property_id: int | None = None) -> list[DemoPortalPresence]:
    return deepcopy(_find_listing(property_id).get("portal_presence", []))


# REAL IMPLEMENTATION NOTE:
# negotiation_signals would combine price history, portal permanence, duplicate
# listings and seller behavior. It could be exposed through /signals/negotiation.
def get_demo_negotiation_signals(property_id: int | None = None) -> list[NegotiationSignal]:
    return deepcopy(get_demo_negotiation_report(property_id).get("signals", []))


def get_demo_negotiation_report(property_id: int | None = None, *, demo_mode: bool = True) -> dict[str, Any]:
    if not demo_mode:
        return {}
    return deepcopy(build_demo_negotiation_report(cast(dict[str, Any], _find_listing(property_id)), demo_mode=True))


# REAL IMPLEMENTATION NOTE:
# owner recommendations need market liquidity, rent yields and listing supply.
# A future endpoint could be GET /api/v1/properties/{property_id}/owner-advice.
def get_demo_owner_recommendations(property_id: int | None = None) -> list[OwnerRecommendation]:
    listing = _find_listing(property_id)
    base = DEMO_RECOMMENDATIONS["owner"]
    if any(signal["signal_type"] == "hold" for signal in listing["signals"]):
        ordered = [base[1], base[2], base[0]]
    elif any(signal["signal_type"] == "rental" for signal in listing["signals"]):
        ordered = [base[2], base[1], base[0]]
    else:
        ordered = base
    return deepcopy(
        [
            {
                "recommendation": item["recommendation"],
                "rationale": item["rationale"],
                "market_conditions": item["market_conditions"],
                "risk_level": item["risk_level"],
                "confidence": item["confidence"],
                "tone": item["tone"],
            }
            for item in ordered
        ]
    )


def get_demo_price_history(property_id: int | None = None) -> list[DemoPriceHistoryPoint]:
    return deepcopy(_find_listing(property_id).get("price_history", []))


def get_demo_property_activity(property_id: int | None = None, *, demo_mode: bool = True) -> list[PropertyActivityEvent]:
    if not demo_mode:
        return []
    listing = _find_listing(property_id)
    return cast(list[PropertyActivityEvent], deepcopy(build_property_activity(cast(dict[str, Any], listing))))


def get_demo_activity_disclaimer() -> str:
    return DEMO_ACTIVITY_DISCLAIMER


def get_demo_market_timing(property_id: int | None = None) -> DemoMarketTiming:
    listing = _find_listing(property_id)
    if any(signal["signal_type"] == "overpriced" for signal in listing["signals"]):
        summary = "Mercado demo sugiere esperar o negociar con fuerza antes de comprar."
        buyer = "Esperar o negociar"
        owner = "Ajustar precio si necesitas liquidez"
    elif any(signal["signal_type"] == "rental" for signal in listing["signals"]):
        summary = "Mercado demo favorable para evaluar renta antes de vender."
        buyer = "Comprar con foco renta"
        owner = "Arrendar antes de vender"
    else:
        summary = "Mercado demo con buena liquidez y espacio de negociación disciplinada."
        buyer = "Negociar con disciplina"
        owner = "Vender solo si necesitas liquidez"
    return {"buyer": buyer, "owner": owner, "summary": summary, "tone": "premium"}


def get_demo_alerts(property_id: int | None = None) -> list[str]:
    return [signal["label"] for signal in _find_listing(property_id)["signals"]]


def get_demo_property_comparison(property_id: int | None = None) -> list[DemoPropertyComparison]:
    selected = [_find_listing(property_id)]
    selected.extend(item for item in DEMO_LISTINGS if item["listing_id"] != selected[0]["listing_id"])
    rows: list[DemoPropertyComparison] = []
    for item in selected[:4]:
        report = get_demo_autofact_report(item["listing_id"])
        rows.append(
            {
                "property_id": item["listing_id"],
                "label": item["title"],
                "price_uf": item["price_uf"],
                "liquidity_score": report["liquidity_score"],
                "legal_score": report["legal_score"],
                "market_score": report["market_score"],
                "fit": _comparison_fit(item),
            }
        )
    return rows


def get_demo_recommendation_groups() -> dict[str, list[DemoRecommendation]]:
    return deepcopy(DEMO_RECOMMENDATIONS)


def _buyer_recommendation(listing: DemoListing) -> str:
    if listing["discount_pct"] >= 8:
        return "Avanzar con oferta moderada y revisión legal completa."
    if listing["discount_pct"] < 0:
        return "Esperar rebaja o negociar con comparables."
    return "Revisar antecedentes y ofertar cerca del rango estimado."


def _comparison_fit(listing: DemoListing) -> str:
    signal_types = {signal["signal_type"] for signal in listing["signals"]}
    if "aggressive_negotiation" in signal_types:
        return "Mejor negociación"
    if "rental" in signal_types:
        return "Mejor renta"
    if "liquidity" in signal_types:
        return "Mejor liquidez"
    if "legal_risk" in signal_types:
        return "Revisar legal"
    return "Mantener en observación"


def _build_demo_legal_simulation(autofact: AutofactReport) -> dict[str, Any]:
    risk_level = autofact["risk_level"]
    return {
        "cbr_status": autofact["cbr_status"],
        "simulated_liens": autofact["liens"] or ["Sin gravámenes simulados críticos"],
        "simulated_prohibitions": (
            ["Posible prohibición simulada por revisar"] if risk_level == "high" else ["Sin prohibiciones simuladas visibles"]
        ),
        "simulated_contribution_debt": (
            "Deuda de contribuciones simulada por revisar"
            if risk_level == "high"
            else "Contribuciones simuladas sin mora visible"
        ),
        "permits_regularization": autofact["permits_warning"] or "Permisos/regularización sin alertas simuladas",
        "ownership_flags": autofact["ownership_flags"],
        "debt_flags": autofact["debt_flags"],
        "risk_level": risk_level,
        "disclaimer": "Simulación legal demo. No consulta CBR, SII, municipalidades ni conservadores reales.",
        "is_demo": True,
    }


def _build_demo_market_section(listing: DemoListing, autofact: AutofactReport, price_gap_pct: float) -> dict[str, Any]:
    active_portals = sum(1 for item in listing.get("portal_presence", []) if item["is_active"])
    pressure = "Alta" if listing["days_on_market"] >= 60 else "Media" if listing["days_on_market"] >= 30 else "Baja"
    demand = "Alta" if autofact["liquidity_score"] >= 80 else "Media" if autofact["liquidity_score"] >= 62 else "Baja"
    return {
        "published_price_uf": listing["price_uf"],
        "estimated_price_uf": listing["estimated_value_uf"],
        "difference_uf": listing["estimated_value_uf"] - listing["price_uf"],
        "difference_pct": price_gap_pct,
        "estimated_liquidity": "Alta" if autofact["liquidity_score"] >= 80 else "Media" if autofact["liquidity_score"] >= 62 else "Baja",
        "supply_pressure": pressure,
        "simulated_demand": demand,
        "active_comparables": max(3, min(9, int(listing["score"] // 10))),
        "active_portals": active_portals,
        "days_on_market": listing["days_on_market"],
        "is_demo": True,
    }


def _build_demo_negotiation_section(listing: DemoListing) -> dict[str, Any]:
    report = get_demo_negotiation_report(listing["listing_id"], demo_mode=True)
    strategy = report["suggested_strategy"]
    price = int(listing["price_uf"])
    margin_pct = round(max(0, price - strategy["moderate_offer_uf"]) / price * 100, 1)
    return {
        "suggested_margin_pct": margin_pct,
        "negotiation_score": report["negotiation_score"],
        "strategy": report["strategy"],
        "conservative_strategy": {
            "offer_uf": strategy["conservative_offer_uf"],
            "label": "Entrada prudente basada en heurísticas demo.",
        },
        "moderate_strategy": {
            "offer_uf": strategy["moderate_offer_uf"],
            "label": "Usar señales y comparables demo como argumento.",
        },
        "aggressive_strategy": {
            "offer_uf": strategy["aggressive_offer_uf"],
            "label": "Solo para escenario demo con tolerancia a perder la oportunidad.",
        },
        "estimated_range_uf": strategy["estimated_range_uf"],
        "risk_of_losing_opportunity": strategy["risk_of_losing_opportunity"],
        "explanation": strategy["explanation"],
        "is_demo": True,
    }


def _build_demo_comuna_context(listing: DemoListing) -> dict[str, Any]:
    comuna_listings = [item for item in DEMO_LISTINGS if item["comuna"] == listing["comuna"]]
    avg_price = int(sum(item["price_uf"] for item in comuna_listings) / len(comuna_listings))
    avg_score = round(sum(float(item["score"]) for item in comuna_listings) / len(comuna_listings), 1)
    return {
        "comuna": listing["comuna"],
        "demo_inventory": len(comuna_listings),
        "avg_price_uf": avg_price,
        "avg_score": avg_score,
        "dominant_signals": listing["tags"][:3],
        "summary": f"{listing['comuna']} muestra {len(comuna_listings)} activos demo y score medio {avg_score}.",
        "is_demo": True,
    }
