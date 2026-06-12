"""Constantes de negocio. ÚNICA fuente de verdad.

Regla: ningún otro módulo redefine estos valores. Si necesitas una constante
nueva, agrégala acá y refiérela desde donde la uses.
"""
from decimal import Decimal

# ─────────────────────────────────────────────
# Conversión monetaria
# ─────────────────────────────────────────────
# Fallback si la API de mindicador.cl no responde. La tasa real se resuelve
# en runtime vía infrastructure/external/uf_client.py.
LEGACY_UF_ARTIFACT_RATE: Decimal = Decimal("37000")

# ─────────────────────────────────────────────
# Validación de listings ingresados al pipeline
# ─────────────────────────────────────────────
MIN_SALE_PRICE_CLP: int = 10_000_000
MIN_M2: float = 10.0
MAX_M2: float = 1000.0
MAX_BEDROOMS: int = 10
MAX_BATHROOMS: int = 10

# ─────────────────────────────────────────────
# Tasación por comparables
# ─────────────────────────────────────────────
MIN_COMPARABLES: int = 5
TOP_N_COMPARABLES: int = 20                # límite tras ranking por similitud
COMPARABLES_MAX_DISTANCE_KM: float = 5.0
COMPARABLES_M2_TOLERANCE: float = 0.30     # ±30 %

# Pesos del score de comparables. Deben sumar 1.0.
# Nota: "age" se añadirá cuando el scraper lo capture consistentemente.
SCORE_WEIGHTS: dict[str, float] = {
    "m2": 0.40,
    "distance": 0.25,
    "bedrooms": 0.15,
    "bathrooms": 0.10,
    "parking": 0.10,
}
assert abs(sum(SCORE_WEIGHTS.values()) - 1.0) < 1e-9, "SCORE_WEIGHTS debe sumar 1.0"

# ─────────────────────────────────────────────
# Radar de oportunidades
# ─────────────────────────────────────────────
MIN_UNDERVALUATION: float = 0.05          # 5 % por defecto
MIN_UNDERVALUATION_LOW_DATA: float = 0.10  # 10 % cuando hay pocos datos
MIN_RADAR_DATASET_SIZE: int = 10
LOW_DATA_THRESHOLD: int = 50               # <50 listings activos → modo conservador
LISTING_STALE_DAYS: int = 45               # conservador: el scraper no cubre todo el mercado

# ─────────────────────────────────────────────
# Caché (segundos)
# ─────────────────────────────────────────────
UF_CACHE_TTL: int = 86_400                      # 24 h
GEOCODING_CACHE_TTL: int = 60 * 60 * 24 * 30    # 30 días

# ─────────────────────────────────────────────
# Scrapers
# ─────────────────────────────────────────────
# Intervalo mínimo entre requests al mismo host (scraping educado).
# 2 s ≈ 30 req/min — suficientemente lento para no activar rate limiting.
SCRAPER_MIN_REQUEST_INTERVAL_SEC: float = 2.0
SCRAPER_MAX_RETRIES: int = 3
SCRAPER_HTTP_TIMEOUT_SEC: float = 30.0
YAPO_MAX_PAGES: int = 7
YAPO_MAX_PAGES_HARD_LIMIT: int = 10
YAPO_SEARCH_BASE_URL: str = "https://www.yapo.cl/searchresult/bienes-raices-venta-de-propiedades-apartamentos"
YAPO_HOUSE_SEARCH_BASE_URL: str = "https://www.yapo.cl/searchresult/bienes-raices-venta-de-propiedades-casas"
YAPO_APARTMENT_TARGETS: list[dict[str, str | int]] = [
    {
        "label": "general",
        "query": "keyword.departamentos venta",
        "scope": "general",
        "max_pages": 1,
    },
    {
        "label": "santiago",
        "query": "keyword.departamentos venta Santiago",
        "scope": "rm",
        "max_pages": 3,
    },
    {
        "label": "nunoa",
        "query": "keyword.departamentos venta nunoa",
        "scope": "rm",
        "max_pages": 3,
    },
    {
        "label": "providencia",
        "query": "keyword.departamentos venta Providencia",
        "scope": "rm",
        "max_pages": 3,
    },
    {
        "label": "las_condes",
        "query": "keyword.departamentos venta Las Condes",
        "scope": "rm",
        "max_pages": 3,
    },
    {
        "label": "la_reina",
        "query": "keyword.departamentos venta La Reina",
        "scope": "rm",
        "max_pages": 2,
    },
    {
        "label": "macul",
        "query": "keyword.departamentos venta Macul",
        "scope": "rm",
        "max_pages": 2,
    },
    {
        "label": "san_miguel",
        "query": "keyword.departamentos venta San Miguel",
        "scope": "rm",
        "max_pages": 2,
    },
    {
        "label": "la_florida",
        "query": "keyword.departamentos venta La Florida",
        "scope": "rm",
        "max_pages": 3,
    },
    {
        "label": "vitacura",
        "query": "keyword.departamentos venta Vitacura",
        "scope": "rm",
        "max_pages": 3,
    },
    {
        "label": "penalolen",
        "query": "keyword.departamentos venta penalolen",
        "scope": "rm",
        "max_pages": 1,
    },
    {
        "label": "maipu",
        "query": "keyword.departamentos venta Maipu",
        "scope": "rm",
        "max_pages": 3,
    },
    {
        "label": "recoleta",
        "query": "keyword.departamentos venta Recoleta",
        "scope": "rm",
        "max_pages": 3,
    },
    {
        "label": "independencia",
        "query": "keyword.departamentos venta Independencia",
        "scope": "rm",
        "max_pages": 3,
    },
    {
        "label": "estacion_central",
        "query": "keyword.departamentos venta Estacion Central",
        "scope": "rm",
        "max_pages": 3,
    },
]


def _with_property_type(target: dict[str, str | int], property_type: str) -> dict[str, str | int]:
    return {**target, "property_type": str(target.get("property_type") or property_type)}


def _house_target_from_apartment_target(target: dict[str, str | int]) -> dict[str, str | int]:
    label = str(target["label"])
    query_comuna = str(target["query"]).replace("keyword.departamentos venta", "").strip()
    query_suffix = f" {query_comuna}" if query_comuna else ""
    return {
        "label": f"{label}_house",
        "query": f"keyword.casa venta{query_suffix}",
        "scope": target["scope"],
        "max_pages": target["max_pages"],
        "property_type": "house",
        "search_base_url": YAPO_HOUSE_SEARCH_BASE_URL,
    }


YAPO_HOUSE_TARGETS: list[dict[str, str | int]] = [
    _house_target_from_apartment_target(target)
    for target in YAPO_APARTMENT_TARGETS
    if target.get("scope") == "rm"
]

YAPO_TARGETS: list[dict[str, str | int]] = [
    *(_with_property_type(target, "apartment") for target in YAPO_APARTMENT_TARGETS),
    *YAPO_HOUSE_TARGETS,
]
# User-Agent de navegador real: portalinmobiliario.com (y otros) detectan UAs
# no-browser y sirven SPA shell vacía. Usar una cadena Chrome conocida es
# práctica estándar de scraping y permite recibir el HTML SSR completo.
# Combinado con rate limiting (SCRAPER_MIN_REQUEST_INTERVAL_SEC = 2.0) sigue
# siendo scraping educado — el volumen y la cadencia son respetuosos.
SCRAPER_USER_AGENT: str = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

# ─────────────────────────────────────────────
# Ingesta
# ─────────────────────────────────────────────
LISTING_SOURCES: frozenset[str] = frozenset({
    "yapo",
    "portalinmobiliario",
    "app",          # tasación manual desde UI
    "geocoding",    # actualización de coordenadas
})

LISTING_STATUSES: frozenset[str] = frozenset({
    "active",
    "incomplete",
    "inactive",
    "sold",
    "removed",
    "appraisal_result",  # tasación de usuario (no es listing real)
})

PROPERTY_TYPES: frozenset[str] = frozenset({
    "apartment",
    "house",
    "office",
    "land",
    "unknown",
})

# Aliases conservadores para detección de comunas RM antes de validación.
# Las claves se normalizan en data_cleaning (lowercase, sin acentos, sin puntuación).
RM_COMUNA_ALIASES: dict[str, str] = {
    "santiago": "Santiago",
    "stgo": "Santiago",
    "santiago centro": "Santiago",
    "centro de santiago": "Santiago",
    "nunoa": "Ñuñoa",
    "nunoa rm": "Ñuñoa",
    "providencia": "Providencia",
    "providencia rm": "Providencia",
    "las condes": "Las Condes",
    "las condes rm": "Las Condes",
    "vitacura": "Vitacura",
    "la reina": "La Reina",
    "macul": "Macul",
    "penalolen": "Peñalolén",
    "lo barnechea": "Lo Barnechea",
    "huechuraba": "Huechuraba",
    "quilicura": "Quilicura",
    "cerrillos": "Cerrillos",
    "conchali": "Conchalí",
    "quinta normal": "Quinta Normal",
    "lo prado": "Lo Prado",
    "pedro aguirre cerda": "Pedro Aguirre Cerda",
    "pedro aguirre": "Pedro Aguirre Cerda",
    "san joaquin": "San Joaquín",
    "la cisterna": "La Cisterna",
    "el bosque": "El Bosque",
    "san ramon": "San Ramón",
    "la granja": "La Granja",
    "san miguel": "San Miguel",
    "independencia": "Independencia",
    "estacion central": "Estación Central",
    "est central": "Estación Central",
    "recoleta": "Recoleta",
    "maipu": "Maipú",
    "puente alto": "Puente Alto",
    "la florida": "La Florida",
}
