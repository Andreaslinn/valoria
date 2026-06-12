"""Datos canónicos de comunas de Santiago.

ÚNICA fuente de verdad para:
    · nombres con forma canónica (con tildes)
    · slugs ASCII para claves de BD
    · coordenadas lat/lon del centroide

Los datos duplicados que había en main.py, geocoding.py y app.py deben
consultarse exclusivamente desde este módulo.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class Comuna:
    name: str   # forma canónica con tildes (p.ej. "Ñuñoa")
    slug: str   # ASCII lowercase, underscores (p.ej. "nunoa")
    lat: float
    lon: float


# Catálogo urbano de la Región Metropolitana de Santiago.
# Coordenadas = centroide aproximado de cada comuna (usado para distance_km
# en el motor de comparables). Excluimos comunas rurales (Alhué, María Pinto,
# San Pedro, etc.) porque prácticamente no tienen mercado de departamentos.
COMUNAS: tuple[Comuna, ...] = (
    # Sector oriente
    Comuna("Las Condes",          "las_condes",         -33.4172, -70.5476),
    Comuna("Vitacura",            "vitacura",           -33.3829, -70.5703),
    Comuna("Providencia",         "providencia",        -33.4263, -70.6114),
    Comuna("Ñuñoa",               "nunoa",              -33.4569, -70.5969),
    Comuna("La Reina",            "la_reina",           -33.4428, -70.5386),
    Comuna("Peñalolén",           "penalolen",          -33.4875, -70.5393),
    Comuna("Macul",               "macul",              -33.4869, -70.5989),
    Comuna("Lo Barnechea",        "lo_barnechea",       -33.3500, -70.5167),

    # Centro
    Comuna("Santiago",            "santiago",           -33.4489, -70.6693),
    Comuna("Independencia",       "independencia",      -33.4178, -70.6653),
    Comuna("Recoleta",            "recoleta",           -33.4072, -70.6378),
    Comuna("Estación Central",    "estacion_central",   -33.4569, -70.6833),
    Comuna("Quinta Normal",       "quinta_normal",      -33.4350, -70.7008),

    # Sur
    Comuna("San Miguel",          "san_miguel",         -33.4947, -70.6517),
    Comuna("San Joaquín",         "san_joaquin",        -33.5067, -70.6394),
    Comuna("La Cisterna",         "la_cisterna",        -33.5333, -70.6667),
    Comuna("La Granja",           "la_granja",          -33.5403, -70.6258),
    Comuna("La Florida",          "la_florida",         -33.5228, -70.5989),
    Comuna("La Pintana",          "la_pintana",         -33.5828, -70.6333),
    Comuna("El Bosque",           "el_bosque",          -33.5611, -70.6750),
    Comuna("San Ramón",           "san_ramon",          -33.5400, -70.6436),
    Comuna("Pedro Aguirre Cerda", "pedro_aguirre_cerda", -33.4867, -70.6739),
    Comuna("Lo Espejo",           "lo_espejo",          -33.5181, -70.6889),
    Comuna("Puente Alto",         "puente_alto",        -33.6108, -70.5769),
    Comuna("San Bernardo",        "san_bernardo",       -33.5928, -70.6989),

    # Poniente
    Comuna("Maipú",               "maipu",              -33.5111, -70.7581),
    Comuna("Cerrillos",           "cerrillos",          -33.4906, -70.7158),
    Comuna("Cerro Navia",         "cerro_navia",        -33.4225, -70.7275),
    Comuna("Lo Prado",            "lo_prado",           -33.4431, -70.7214),
    Comuna("Pudahuel",            "pudahuel",           -33.4411, -70.7569),
    Comuna("Renca",               "renca",              -33.4014, -70.7281),

    # Norte
    Comuna("Conchalí",            "conchali",           -33.3839, -70.6744),
    Comuna("Huechuraba",          "huechuraba",         -33.3697, -70.6400),
    Comuna("Quilicura",           "quilicura",          -33.3650, -70.7281),
    Comuna("Colina",              "colina",             -33.2089, -70.6711),
)

_BY_SLUG: dict[str, Comuna] = {c.slug: c for c in COMUNAS}
_BY_NAME_LOWER: dict[str, Comuna] = {c.name.lower(): c for c in COMUNAS}


def normalize_comuna(raw: str) -> str:
    """Convierte un nombre libre a slug canónico (ASCII, lowercase, underscores).

    Ejemplos:
        "Ñuñoa"       → "nunoa"
        "LAS CONDES"  → "las_condes"
        " peñalolen " → "penalolen"
    """
    if not raw:
        return ""
    cleaned = raw.strip().lower()
    no_accents = "".join(
        ch for ch in unicodedata.normalize("NFD", cleaned)
        if unicodedata.category(ch) != "Mn"
    )
    return no_accents.replace(" ", "_").replace("-", "_")


def find_comuna(raw: str) -> Comuna | None:
    """Busca por slug, o por nombre canónico si el slug no calza."""
    slug = normalize_comuna(raw)
    if slug in _BY_SLUG:
        return _BY_SLUG[slug]
    return _BY_NAME_LOWER.get(raw.strip().lower())


def get_coordinates(raw: str) -> tuple[float, float] | None:
    """Retorna (lat, lon) del centroide de la comuna, o None si no se reconoce."""
    comuna = find_comuna(raw)
    return (comuna.lat, comuna.lon) if comuna else None


def is_known_comuna(raw: str) -> bool:
    return find_comuna(raw) is not None
