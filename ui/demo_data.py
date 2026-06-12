"""Centralized mock data for AVM Vision Demo Mode and Product Lab."""
from __future__ import annotations

from copy import deepcopy
from typing import cast

from ui.demo_types import (
    DemoListing,
    DemoPortalPresence,
    DemoPriceHistoryPoint,
    DemoRecommendation,
    DemoRiskReport,
    DemoSignal,
    DemoValuationResult,
)

CLP_PER_UF = 38_000
DEMO_DISCLAIMER = (
    "Datos simulados para visualizar la experiencia. No representan tasaciones reales."
)
DEMO_ACTIVITY_DISCLAIMER = (
    "Actividad simulada para explorar la experiencia futura del producto."
)


def _clp(uf: int) -> int:
    return uf * CLP_PER_UF


def _signal(
    signal_type: str,
    label: str,
    explanation: str,
    severity: str,
    confidence: str,
    suggested_action: str,
    tone: str,
) -> DemoSignal:
    return {
        "type": signal_type,
        "signal_type": signal_type,
        "label": label,
        "explanation": explanation,
        "severity": severity,
        "confidence": confidence,
        "suggested_action": suggested_action,
        "tone": tone,
    }


DEMO_SIGNALS: list[DemoSignal] = [
    _signal(
        "below_market",
        "Bajo mercado vs comparables",
        "El precio publicado está por debajo del valor estimado demo.",
        "medium",
        "high",
        "Revisar documentos y preparar oferta rápida.",
        "positive",
    ),
    _signal(
        "price_drop",
        "Precio reducido 2 veces en 30 días",
        "El historial demo muestra rebajas consecutivas recientes.",
        "medium",
        "high",
        "Usar las rebajas como argumento de negociación.",
        "warning",
    ),
    _signal(
        "seller_pressure",
        "Posible vendedor apurado",
        "Alta permanencia y ajustes de precio sugieren mayor apertura.",
        "high",
        "medium",
        "Probar una oferta inicial agresiva pero documentada.",
        "warning",
    ),
    _signal(
        "liquidity",
        "Alta liquidez esperada",
        "Comuna y tipología con demanda activa en el dataset demo.",
        "low",
        "high",
        "Priorizar si buscas salida futura más rápida.",
        "positive",
    ),
    _signal(
        "rental",
        "Mercado favorable para arriendo",
        "Ticket, ubicación y programa calzan con perfil inversionista demo.",
        "low",
        "medium",
        "Evaluar renta estimada antes de comprar.",
        "premium",
    ),
    _signal(
        "hold",
        "Esperar antes de vender",
        "El mercado demo no premia una venta inmediata sin urgencia.",
        "low",
        "medium",
        "Monitorear inventario y tasas antes de publicar.",
        "neutral",
    ),
    _signal(
        "legal_risk",
        "Riesgo legal simulado",
        "El Autofact inmobiliario demo marca antecedentes por revisar.",
        "high",
        "medium",
        "Solicitar estudio de títulos antes de ofertar.",
        "negative",
    ),
    _signal(
        "overpriced",
        "Sobrevalorada vs comparables",
        "El precio supera la estimación demo y reduce margen de seguridad.",
        "medium",
        "high",
        "Esperar rebaja o negociar con comparables.",
        "warning",
    ),
    _signal(
        "portal_presence",
        "Visible en múltiples portales",
        "La misma propiedad aparece en varias fuentes demo.",
        "low",
        "medium",
        "Comparar precios por portal antes de contactar.",
        "premium",
    ),
    _signal(
        "aggressive_negotiation",
        "Candidato para negociación agresiva",
        "Rebajas, permanencia y brecha estimada permiten una oferta más baja.",
        "high",
        "medium",
        "Abrir 7% a 9% bajo publicación si la revisión legal avanza.",
        "positive",
    ),
]


def _presence(
    portal: str,
    active: bool,
    first_seen: str,
    last_seen: str,
    price_uf: int,
    property_id: int,
    confidence: str = "medium",
) -> DemoPortalPresence:
    slug = portal.lower().replace(" ", "-")
    return {
        "portal_name": portal,
        "is_active": active,
        "first_seen": first_seen,
        "last_seen": last_seen,
        "price_seen_uf": price_uf,
        "listing_url": f"https://demo.avm.local/{slug}/{property_id}",
        "confidence": confidence,
    }


def _history(events: list[tuple[str, int, str]]) -> list[DemoPriceHistoryPoint]:
    rows: list[DemoPriceHistoryPoint] = []
    previous_price: int | None = None
    for date, price, event in events:
        change_uf = None if previous_price is None else price - previous_price
        change_pct = (
            None
            if previous_price is None or previous_price == 0 or change_uf is None
            else round((change_uf / previous_price) * 100, 2)
        )
        rows.append(
            {
                "date": date,
                "price_uf": price,
                "event": event,
                "previous_price_uf": previous_price,
                "change_uf": change_uf,
                "change_pct": change_pct,
                "source": "demo_activity_engine",
                "is_demo": True,
            }
        )
        previous_price = price
    return rows


DEMO_LISTINGS: list[DemoListing] = [
    {
        "id": 9101,
        "listing_id": 9101,
        "title": "Departamento luminoso cercano a Plaza Ñuñoa",
        "comuna": "nunoa",
        "property_type": "departamento",
        "address_label": "Sector Plaza Ñuñoa, dirección simulada",
        "price_uf": 4250,
        "estimated_value_uf": 4780,
        "m2": 62,
        "bedrooms": 2,
        "bathrooms": 2,
        "parking_spaces": 1,
        "source": "Yapo",
        "detected_at": "2026-05-05T10:30:00",
        "days_on_market": 46,
        "confidence": "high",
        "score": 88.4,
        "status": "active",
        "tags": ["bajo mercado", "rebaja reciente", "negociación"],
        "short_summary": "Buen candidato demo para oferta disciplinada en Ñuñoa.",
        "signals": [DEMO_SIGNALS[0], DEMO_SIGNALS[1], DEMO_SIGNALS[9]],
        "price_history": _history(
            [
                ("2026-03-21", 4520, "publicado"),
                ("2026-04-18", 4400, "rebaja"),
                ("2026-05-04", 4250, "rebaja"),
            ]
        ),
        "portal_presence": [
            _presence("PortalInmobiliario", True, "2026-03-21", "2026-05-06", 4250, 9101, "high"),
            _presence("Yapo", True, "2026-03-24", "2026-05-05", 4320, 9101),
            _presence("Toctoc", False, "2026-03-21", "2026-04-20", 4520, 9101),
        ],
    },
    {
        "id": 9102,
        "listing_id": 9102,
        "title": "Depto remodelado en Providencia con metro cercano",
        "comuna": "providencia",
        "property_type": "departamento",
        "address_label": "Eje Pedro de Valdivia, dirección simulada",
        "price_uf": 6100,
        "estimated_value_uf": 6420,
        "m2": 74,
        "bedrooms": 3,
        "bathrooms": 2,
        "parking_spaces": 1,
        "source": "PortalInmobiliario",
        "detected_at": "2026-05-04T16:20:00",
        "days_on_market": 28,
        "confidence": "high",
        "score": 81.3,
        "status": "active",
        "tags": ["alta liquidez", "metro", "familia"],
        "short_summary": "Activo estable con alta liquidez esperada y margen moderado.",
        "signals": [DEMO_SIGNALS[3], DEMO_SIGNALS[8]],
        "price_history": _history(
            [
                ("2026-04-06", 6250, "publicado"),
                ("2026-04-28", 6180, "rebaja"),
                ("2026-05-04", 6100, "rebaja"),
            ]
        ),
        "portal_presence": [
            _presence("PortalInmobiliario", True, "2026-04-06", "2026-05-06", 6100, 9102, "high"),
            _presence("MercadoLibre", True, "2026-04-12", "2026-05-04", 6150, 9102),
        ],
    },
    {
        "id": 9103,
        "listing_id": 9103,
        "title": "Vista despejada en Las Condes",
        "comuna": "las_condes",
        "property_type": "departamento",
        "address_label": "Sector Escuela Militar, dirección simulada",
        "price_uf": 8750,
        "estimated_value_uf": 8420,
        "m2": 91,
        "bedrooms": 3,
        "bathrooms": 3,
        "parking_spaces": 2,
        "source": "Toctoc",
        "detected_at": "2026-05-02T12:45:00",
        "days_on_market": 18,
        "confidence": "medium",
        "score": 54.2,
        "status": "active",
        "tags": ["sobrevalorada", "premium medio", "esperar"],
        "short_summary": "Buena propiedad demo, pero sin margen claro al precio publicado.",
        "signals": [DEMO_SIGNALS[7], DEMO_SIGNALS[5]],
        "price_history": _history(
            [
                ("2026-04-14", 8750, "publicado"),
                ("2026-04-28", 8750, "sin cambios"),
                ("2026-05-02", 8750, "sin cambios"),
            ]
        ),
        "portal_presence": [_presence("Toctoc", True, "2026-04-14", "2026-05-05", 8750, 9103)],
    },
    {
        "id": 9104,
        "listing_id": 9104,
        "title": "Unidad compacta con buena conectividad en Macul",
        "comuna": "macul",
        "property_type": "departamento",
        "address_label": "Sector Camino Agrícola, dirección simulada",
        "price_uf": 3150,
        "estimated_value_uf": 3520,
        "m2": 48,
        "bedrooms": 2,
        "bathrooms": 1,
        "parking_spaces": 0,
        "source": "Yapo",
        "detected_at": "2026-05-01T09:10:00",
        "days_on_market": 37,
        "confidence": "high",
        "score": 84.8,
        "status": "active",
        "tags": ["arriendo", "bajo mercado", "ticket bajo"],
        "short_summary": "Oportunidad demo para inversionista orientado a arriendo.",
        "signals": [DEMO_SIGNALS[0], DEMO_SIGNALS[4], DEMO_SIGNALS[3]],
        "price_history": _history(
            [
                ("2026-03-25", 3290, "publicado"),
                ("2026-04-22", 3220, "rebaja"),
                ("2026-05-01", 3150, "rebaja"),
            ]
        ),
        "portal_presence": [
            _presence("Yapo", True, "2026-03-25", "2026-05-06", 3150, 9104),
            _presence("ChilePropiedades", True, "2026-04-01", "2026-05-03", 3180, 9104),
        ],
    },
    {
        "id": 9105,
        "listing_id": 9105,
        "title": "Casa familiar en La Reina con patio",
        "comuna": "la_reina",
        "property_type": "casa",
        "address_label": "Sector Príncipe de Gales, dirección simulada",
        "price_uf": 9800,
        "estimated_value_uf": 10_150,
        "m2": 148,
        "bedrooms": 4,
        "bathrooms": 3,
        "parking_spaces": 2,
        "source": "PortalInmobiliario",
        "detected_at": "2026-04-29T18:05:00",
        "days_on_market": 64,
        "confidence": "medium",
        "score": 72.5,
        "status": "active",
        "tags": ["casa familiar", "negociación moderada", "liquidez media"],
        "short_summary": "Casa demo con margen acotado y buena lectura para familias.",
        "signals": [DEMO_SIGNALS[2], DEMO_SIGNALS[8]],
        "price_history": _history(
            [
                ("2026-02-25", 10_400, "publicado"),
                ("2026-04-10", 10_100, "rebaja"),
                ("2026-04-29", 9800, "rebaja"),
            ]
        ),
        "portal_presence": [
            _presence("PortalInmobiliario", True, "2026-02-25", "2026-05-06", 9800, 9105),
            _presence("Toctoc", True, "2026-03-02", "2026-05-05", 9900, 9105),
        ],
    },
    {
        "id": 9106,
        "listing_id": 9106,
        "title": "Inversión céntrica en Santiago",
        "comuna": "santiago",
        "property_type": "departamento",
        "address_label": "Centro histórico, dirección simulada",
        "price_uf": 2850,
        "estimated_value_uf": 3150,
        "m2": 39,
        "bedrooms": 1,
        "bathrooms": 1,
        "parking_spaces": 0,
        "source": "MercadoLibre",
        "detected_at": "2026-04-27T11:40:00",
        "days_on_market": 52,
        "confidence": "medium",
        "score": 76.6,
        "status": "active",
        "tags": ["inversión", "arriendo", "ticket bajo"],
        "short_summary": "Ticket bajo demo con señales favorables para renta.",
        "signals": [DEMO_SIGNALS[4], DEMO_SIGNALS[9]],
        "price_history": _history(
            [
                ("2026-03-06", 2920, "publicado"),
                ("2026-04-01", 2920, "sin cambios"),
                ("2026-04-27", 2850, "rebaja"),
            ]
        ),
        "portal_presence": [
            _presence("MercadoLibre", True, "2026-03-06", "2026-05-05", 2850, 9106),
            _presence("Yapo", False, "2026-03-07", "2026-04-12", 2920, 9106),
        ],
    },
    {
        "id": 9107,
        "listing_id": 9107,
        "title": "Penthouse sobrio en Vitacura",
        "comuna": "vitacura",
        "property_type": "departamento",
        "address_label": "Sector Alonso de Córdova, dirección simulada",
        "price_uf": 14_500,
        "estimated_value_uf": 14_200,
        "m2": 142,
        "bedrooms": 4,
        "bathrooms": 4,
        "parking_spaces": 3,
        "source": "PortalInmobiliario",
        "detected_at": "2026-04-25T14:35:00",
        "days_on_market": 73,
        "confidence": "medium",
        "score": 58.0,
        "status": "active",
        "tags": ["premium", "lenta en vender", "esperar"],
        "short_summary": "Propiedad premium demo con liquidez menor y precio exigente.",
        "signals": [DEMO_SIGNALS[7], DEMO_SIGNALS[5]],
        "price_history": _history(
            [
                ("2026-02-11", 14_800, "publicado"),
                ("2026-04-02", 14_500, "rebaja"),
                ("2026-04-25", 14_500, "sin cambios"),
            ]
        ),
        "portal_presence": [_presence("PortalInmobiliario", True, "2026-02-11", "2026-05-06", 14_500, 9107)],
    },
    {
        "id": 9108,
        "listing_id": 9108,
        "title": "Townhouse familiar en Peñalolén",
        "comuna": "penalolen",
        "property_type": "casa",
        "address_label": "Sector Consistorial, dirección simulada",
        "price_uf": 7200,
        "estimated_value_uf": 7650,
        "m2": 118,
        "bedrooms": 3,
        "bathrooms": 3,
        "parking_spaces": 2,
        "source": "ChilePropiedades",
        "detected_at": "2026-05-03T08:55:00",
        "days_on_market": 21,
        "confidence": "high",
        "score": 79.9,
        "status": "active",
        "tags": ["familia", "alta liquidez", "submercado"],
        "short_summary": "Casa demo líquida con precio razonable para familia joven.",
        "signals": [DEMO_SIGNALS[3], DEMO_SIGNALS[0]],
        "price_history": _history(
            [
                ("2026-04-12", 7350, "publicado"),
                ("2026-04-26", 7200, "rebaja"),
                ("2026-05-03", 7200, "sin cambios"),
            ]
        ),
        "portal_presence": [
            _presence("ChilePropiedades", True, "2026-04-12", "2026-05-06", 7200, 9108),
            _presence("Toctoc", True, "2026-04-14", "2026-05-03", 7280, 9108),
        ],
    },
    {
        "id": 9109,
        "listing_id": 9109,
        "title": "Departamento con alerta legal simulada en Santiago",
        "comuna": "santiago",
        "property_type": "departamento",
        "address_label": "Sector Santa Isabel, dirección simulada",
        "price_uf": 3400,
        "estimated_value_uf": 3820,
        "m2": 54,
        "bedrooms": 2,
        "bathrooms": 2,
        "parking_spaces": 1,
        "source": "Yapo",
        "detected_at": "2026-04-22T15:10:00",
        "days_on_market": 80,
        "confidence": "low",
        "score": 63.4,
        "status": "active",
        "tags": ["riesgo legal", "descuento", "revisar títulos"],
        "short_summary": "Descuento atractivo demo, condicionado a revisión legal.",
        "signals": [DEMO_SIGNALS[0], DEMO_SIGNALS[6], DEMO_SIGNALS[2]],
        "price_history": _history(
            [
                ("2026-02-01", 3700, "publicado"),
                ("2026-03-20", 3550, "rebaja"),
                ("2026-04-22", 3400, "rebaja"),
            ]
        ),
        "portal_presence": [
            _presence("Yapo", True, "2026-02-01", "2026-05-04", 3400, 9109),
            _presence("MercadoLibre", True, "2026-02-10", "2026-05-02", 3450, 9109),
        ],
    },
    {
        "id": 9110,
        "listing_id": 9110,
        "title": "Departamento 2D2B sector Irarrázaval",
        "comuna": "nunoa",
        "property_type": "departamento",
        "address_label": "Sector Irarrázaval, dirección simulada",
        "price_uf": 4920,
        "estimated_value_uf": 5050,
        "m2": 66,
        "bedrooms": 2,
        "bathrooms": 2,
        "parking_spaces": 1,
        "source": "Toctoc",
        "detected_at": "2026-05-06T13:20:00",
        "days_on_market": 9,
        "confidence": "high",
        "score": 70.4,
        "status": "active",
        "tags": ["comparable", "liquidez", "precio justo"],
        "short_summary": "Comparable demo sano para calibrar tasación en Ñuñoa.",
        "signals": [DEMO_SIGNALS[3]],
        "price_history": _history(
            [
                ("2026-04-27", 4920, "publicado"),
                ("2026-05-06", 4920, "sin cambios"),
            ]
        ),
        "portal_presence": [_presence("Toctoc", True, "2026-04-27", "2026-05-06", 4920, 9110)],
    },
    {
        "id": 9111,
        "listing_id": 9111,
        "title": "Unidad remodelada cerca de metro Chile España",
        "comuna": "nunoa",
        "property_type": "departamento",
        "address_label": "Sector Chile España, dirección simulada",
        "price_uf": 5050,
        "estimated_value_uf": 5120,
        "m2": 68,
        "bedrooms": 2,
        "bathrooms": 2,
        "parking_spaces": 1,
        "source": "PortalInmobiliario",
        "detected_at": "2026-05-05T09:35:00",
        "days_on_market": 14,
        "confidence": "high",
        "score": 69.1,
        "status": "active",
        "tags": ["comparable", "metro", "remodelado"],
        "short_summary": "Comparable demo con buena liquidez y baja brecha.",
        "signals": [DEMO_SIGNALS[3], DEMO_SIGNALS[8]],
        "price_history": _history(
            [
                ("2026-04-21", 5080, "publicado"),
                ("2026-05-05", 5050, "rebaja"),
            ]
        ),
        "portal_presence": [
            _presence("PortalInmobiliario", True, "2026-04-21", "2026-05-05", 5050, 9111),
            _presence("Yapo", True, "2026-04-22", "2026-05-04", 5080, 9111),
        ],
    },
    {
        "id": 9112,
        "listing_id": 9112,
        "title": "Casa con jardín en Las Condes",
        "comuna": "las_condes",
        "property_type": "casa",
        "address_label": "Sector Los Dominicos, dirección simulada",
        "price_uf": 18_200,
        "estimated_value_uf": 17_350,
        "m2": 238,
        "bedrooms": 5,
        "bathrooms": 4,
        "parking_spaces": 3,
        "source": "ChilePropiedades",
        "detected_at": "2026-04-18T12:00:00",
        "days_on_market": 110,
        "confidence": "medium",
        "score": 49.8,
        "status": "active",
        "tags": ["premium", "sobrevalorada", "lenta"],
        "short_summary": "Casa premium demo con baja urgencia de compra al precio actual.",
        "signals": [DEMO_SIGNALS[7], DEMO_SIGNALS[5]],
        "price_history": _history(
            [
                ("2026-01-18", 18_200, "publicado"),
                ("2026-03-18", 18_200, "sin cambios"),
                ("2026-04-18", 18_200, "republicado"),
            ]
        ),
        "portal_presence": [_presence("ChilePropiedades", True, "2026-01-18", "2026-05-05", 18_200, 9112)],
    },
    {
        "id": 9113,
        "listing_id": 9113,
        "title": "Loft premium compacto en Vitacura",
        "comuna": "vitacura",
        "property_type": "departamento",
        "address_label": "Sector Nueva Costanera, dirección simulada",
        "price_uf": 8900,
        "estimated_value_uf": 9050,
        "m2": 72,
        "bedrooms": 1,
        "bathrooms": 2,
        "parking_spaces": 2,
        "source": "Toctoc",
        "detected_at": "2026-05-01T17:40:00",
        "days_on_market": 32,
        "confidence": "medium",
        "score": 67.0,
        "status": "active",
        "tags": ["premium", "arriendo ejecutivo", "liquidez media"],
        "short_summary": "Activo premium demo con posible estrategia de arriendo ejecutivo.",
        "signals": [DEMO_SIGNALS[4], DEMO_SIGNALS[8]],
        "price_history": _history(
            [
                ("2026-03-30", 9100, "publicado"),
                ("2026-04-20", 8900, "rebaja"),
                ("2026-05-01", 8900, "sin cambios"),
            ]
        ),
        "portal_presence": [
            _presence("Toctoc", True, "2026-03-30", "2026-05-06", 8900, 9113),
            _presence("PortalInmobiliario", False, "2026-04-01", "2026-04-26", 9100, 9113),
        ],
    },
    {
        "id": 9114,
        "listing_id": 9114,
        "title": "Departamento familiar en Providencia sobrevalorado",
        "comuna": "providencia",
        "property_type": "departamento",
        "address_label": "Sector Manuel Montt, dirección simulada",
        "price_uf": 7600,
        "estimated_value_uf": 7050,
        "m2": 82,
        "bedrooms": 3,
        "bathrooms": 2,
        "parking_spaces": 1,
        "source": "MercadoLibre",
        "detected_at": "2026-04-30T10:25:00",
        "days_on_market": 58,
        "confidence": "high",
        "score": 52.1,
        "status": "active",
        "tags": ["sobrevalorada", "esperar", "comparar"],
        "short_summary": "Buen producto demo, pero precio publicado exige cautela.",
        "signals": [DEMO_SIGNALS[7], DEMO_SIGNALS[5]],
        "price_history": _history(
            [
                ("2026-03-03", 7450, "publicado"),
                ("2026-04-10", 7600, "subida"),
                ("2026-04-30", 7600, "sin cambios"),
            ]
        ),
        "portal_presence": [_presence("MercadoLibre", True, "2026-03-03", "2026-05-05", 7600, 9114)],
    },
]


def _prepare_listing(item: DemoListing) -> DemoListing:
    listing = cast(DemoListing, dict(item))
    listing["price_clp"] = _clp(listing["price_uf"])
    listing["estimated_value_clp"] = _clp(listing["estimated_value_uf"])
    listing["estimated_price_uf"] = listing["estimated_value_uf"]
    listing["estimated_price_clp"] = listing["estimated_value_clp"]
    listing["dormitorios"] = listing["bedrooms"]
    listing["banos"] = listing["bathrooms"]
    listing["estacionamientos"] = listing["parking_spaces"]
    listing["listing_url"] = f"https://demo.avm.local/listings/{listing['listing_id']}"
    listing["url"] = listing["listing_url"]
    listing["captured_at"] = listing["detected_at"]
    listing["created_at"] = listing["detected_at"]
    listing["listing_status"] = listing["status"]
    listing["history"] = [event["price_uf"] for event in listing["price_history"]]
    listing["discount_pct"] = round(
        ((listing["estimated_value_uf"] - listing["price_uf"]) / listing["estimated_value_uf"]) * 100,
        1,
    )
    return listing


DEMO_LISTINGS = [_prepare_listing(item) for item in DEMO_LISTINGS]

DEMO_OPPORTUNITIES: list[DemoListing] = sorted(
    [item for item in DEMO_LISTINGS if item["discount_pct"] >= 2.5],
    key=lambda item: item["score"],
    reverse=True,
)

DEMO_PORTFOLIO: list[DemoListing] = [
    {
        **item,
        "saved_at": saved_at,
        "saved_price_uf": saved_price,
        "saved_price_clp": _clp(saved_price),
        "movement_pct": round(((item["price_uf"] - saved_price) / saved_price) * 100, 1),
        "movement_label": (
            "Bajó desde guardado"
            if item["price_uf"] < saved_price
            else "Subió desde guardado"
            if item["price_uf"] > saved_price
            else "Estable"
        ),
        "movement_tone": (
            "positive"
            if item["price_uf"] < saved_price
            else "warning"
            if item["price_uf"] > saved_price
            else "neutral"
        ),
        "alerts": [signal["label"] for signal in item["signals"]],
    }
    for item, saved_at, saved_price in [
        (DEMO_LISTINGS[0], "2026-04-18T09:00:00", 4520),
        (DEMO_LISTINGS[1], "2026-04-21T13:20:00", 6250),
        (DEMO_LISTINGS[2], "2026-04-12T08:15:00", 8750),
        (DEMO_LISTINGS[3], "2026-04-19T18:30:00", 3290),
        (DEMO_LISTINGS[8], "2026-03-25T11:10:00", 3550),
        (DEMO_LISTINGS[12], "2026-04-05T12:00:00", 9100),
    ]
]

DEMO_VALUATION_RESULT: DemoValuationResult = {
    "estimated_price_uf": 4820,
    "estimated_price_clp": _clp(4820),
    "confidence": "high",
    "comparable_count": 9,
    "price_m2_uf": 74.15,
    "status": "ok",
    "warnings": ["Demo: resultado simulado para visualizar experiencia"],
    "comparables": [
        {
            "listing_id": item["listing_id"],
            "title": item["title"],
            "comuna": item["comuna"],
            "price_uf": item["price_uf"],
            "price_clp": item["price_clp"],
            "m2": item["m2"],
            "similarity": similarity,
            "url": item["url"],
        }
        for item, similarity in [
            (DEMO_LISTINGS[0], 0.91),
            (DEMO_LISTINGS[9], 0.88),
            (DEMO_LISTINGS[10], 0.84),
        ]
    ],
}


DEMO_RISK_REPORT: DemoRiskReport = {
    "title": "Risk Report Demo",
    "property": "Departamento Ñuñoa 2D2B",
    "executive_summary": "Activo demo con descuento, liquidez alta y riesgo legal simulado bajo.",
    "risk_score": 28,
    "total_score": 82,
    "market_score": 88,
    "liquidity_score": 86,
    "legal_score": 82,
    "data_quality_score": 79,
    "risk_tone": "positive",
    "liquidity": "Alta",
    "legal_signals": "Sin alertas simuladas críticas",
    "market": "Comuna con demanda activa y bajo inventario relativo",
    "cbr_future": "Integración CBR futura",
    "main_risks": ["CBR no conectado", "Datos simulados", "Verificar gastos comunes"],
    "main_opportunities": ["Descuento vs comparables", "Rebaja reciente", "Alta liquidez esperada"],
    "interpretation": "Demo: activo con riesgo bajo-medio y buena liquidez esperada.",
    "recommendation": "Avanzar con revisión documental antes de ofertar.",
    "disclaimer": DEMO_DISCLAIMER,
    "signals": [
        {"type": "risk", "tone": "positive", "label": "Riesgo bajo en simulación"},
        {"type": "liquidity", "tone": "positive", "label": "Alta liquidez relativa"},
        {"type": "legal", "tone": "warning", "label": "CBR futuro, no conectado"},
    ],
}


DEMO_RECOMMENDATIONS: dict[str, list[DemoRecommendation]] = {
    "buyer": [
        {
            "strategy": "Conservadora",
            "conservative_offer": "UF 4.180",
            "moderate_offer": "UF 4.050",
            "aggressive_offer": "UF 3.890",
            "negotiation_rationale": "Usar rebajas recientes y comparables para sostener el rango.",
            "tone": "neutral",
            "label": "Ofertar cerca del valor estimado y exigir documentación completa.",
        },
        {
            "strategy": "Negociación moderada",
            "conservative_offer": "UF 4.250",
            "moderate_offer": "UF 4.100",
            "aggressive_offer": "UF 3.950",
            "negotiation_rationale": "La permanencia en portales demo permite pedir descuento sin romper conversación.",
            "tone": "positive",
            "label": "Partir 4% bajo publicación y usar rebajas recientes como argumento.",
        },
        {
            "strategy": "Agresiva",
            "conservative_offer": "UF 4.100",
            "moderate_offer": "UF 3.980",
            "aggressive_offer": "UF 3.850",
            "negotiation_rationale": "Solo usar si Autofact y títulos simulados se ven limpios.",
            "tone": "warning",
            "label": "Ofertar 8% bajo publicación solo si hay urgencia comprobable.",
        },
    ],
    "owner": [
        {
            "recommendation": "sell_now",
            "strategy": "Vender ahora",
            "rationale": "La demanda demo en la comuna se mantiene activa.",
            "market_conditions": "Inventario bajo y buena liquidez relativa.",
            "risk_level": "medium",
            "confidence": "medium",
            "tone": "positive",
            "label": "Si necesitas liquidez, el mercado demo muestra demanda activa.",
        },
        {
            "recommendation": "wait",
            "strategy": "Esperar",
            "rationale": "Esperar puede capturar mejor precio si no hay urgencia.",
            "market_conditions": "Mercado estable, pero sensible a tasas.",
            "risk_level": "low",
            "confidence": "medium",
            "tone": "neutral",
            "label": "Si no hay urgencia, monitorear inventario y tasas próximas.",
        },
        {
            "recommendation": "rent",
            "strategy": "Arrendar",
            "rationale": "La demanda de arriendo demo permite evaluar renta antes de vender.",
            "market_conditions": "Buen flujo de arriendo para unidades 2D2B.",
            "risk_level": "low",
            "confidence": "medium",
            "tone": "premium",
            "label": "Buen escenario demo para evaluar renta antes de vender.",
        },
    ],
}


def get_demo_listings() -> list[DemoListing]:
    return deepcopy(DEMO_LISTINGS)


def get_demo_opportunities() -> list[DemoListing]:
    return deepcopy(DEMO_OPPORTUNITIES)


def get_demo_portfolio() -> list[DemoListing]:
    return deepcopy(DEMO_PORTFOLIO)


def get_demo_valuation_result() -> DemoValuationResult:
    return deepcopy(DEMO_VALUATION_RESULT)


def get_demo_risk_report() -> DemoRiskReport:
    return deepcopy(DEMO_RISK_REPORT)


def get_demo_recommendations() -> dict[str, list[DemoRecommendation]]:
    return deepcopy(DEMO_RECOMMENDATIONS)
