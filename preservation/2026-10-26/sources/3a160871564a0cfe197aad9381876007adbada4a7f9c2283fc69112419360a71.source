"""Deterministic product classification for comparable selection.

The classifier is intentionally conservative. It only uses listing/property
fields already available locally and records the evidence that triggered a
special product class.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from core.entities.listing import Listing, Property
from core.normalization.property_type import normalize_property_type


PRODUCT_STANDARD_RESIDENTIAL = "standard_residential"
PRODUCT_LAND_OR_SITE = "land_or_site"
PRODUCT_DEMOLITION = "demolition_candidate"
PRODUCT_REMODELING = "needs_remodeling"
PRODUCT_COMMERCIAL = "commercial_use"
PRODUCT_INVESTMENT = "investment_or_income"
PRODUCT_MULTI_UNIT = "multi_unit"
PRODUCT_UNKNOWN = "unknown"

SPECIAL_PRODUCT_CLASSES = frozenset(
    {
        PRODUCT_LAND_OR_SITE,
        PRODUCT_DEMOLITION,
        PRODUCT_REMODELING,
        PRODUCT_COMMERCIAL,
        PRODUCT_INVESTMENT,
        PRODUCT_MULTI_UNIT,
    }
)


@dataclass(frozen=True)
class ProductEvidence:
    product_class: str
    strength: str
    terms: tuple[str, ...] = ()
    fields_used: tuple[str, ...] = ()
    reason: str = "no_text"
    normalized_text: str = field(default="", repr=False)

    @property
    def is_strong_special(self) -> bool:
        return self.strength == "strong" and self.product_class in SPECIAL_PRODUCT_CLASSES

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_class": self.product_class,
            "strength": self.strength,
            "terms": list(self.terms),
            "fields_used": list(self.fields_used),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ProductCompatibility:
    compatible: bool
    reason: str
    fallback_used: bool = False


_SPACE_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"[^a-z0-9\s]")

_LAND_STRONG = (
    "sitio",
    "venta sitio",
    "terreno en venta",
    "venta terreno",
    "lote",
    "parcela",
    "solo terreno",
)
_LAND_WEAK = ("terreno",)
_DEMOLITION_STRONG = (
    "demolicion",
    "demoler",
    "para demolicion",
    "para demoler",
    "demolible",
    "solo terreno",
)
_REMODELING_STRONG = (
    "para remodelar",
    "requiere remodelacion",
    "a remodelar",
    "remodelacion completa",
    "mal estado",
)
_REMODELING_WEAK = ("remodelar", "remodelacion")
_COMMERCIAL_STRONG = (
    "local comercial",
    "uso comercial",
    "propiedad comercial",
    "oficina",
    "hostal",
    "hotel",
    "bodega",
)
_COMMERCIAL_WEAK = ("comercial",)
_INVESTMENT_STRONG = (
    "renta mensual",
    "arrendada",
    "con arrendatario",
    "rentabilidad",
    "ideal inversion",
)
_INVESTMENT_WEAK = ("inversion", "renta")
_MULTI_STRONG = (
    "dos casas",
    "2 casas",
    "tres casas",
    "3 casas",
    "multicasa",
    "multi casa",
    "varias viviendas",
    "dos viviendas",
    "casa con departamento interior",
    "departamento interior",
    "cabanas",
)
_MULTI_WEAK = ("varias unidades", "segunda vivienda")


def classify_product(value: Listing | Property | None) -> ProductEvidence:
    """Classify a listing/property into a coarse product class."""

    if value is None:
        return ProductEvidence(PRODUCT_UNKNOWN, "unknown", reason="missing_value")

    property_type = normalize_property_type(value)
    if property_type == "land":
        return ProductEvidence(
            PRODUCT_LAND_OR_SITE,
            "strong",
            terms=("property_type:land",),
            fields_used=("property_type",),
            reason="structured_land_property_type",
        )

    text, fields = _text_from_value(value)
    if not text:
        if property_type in {"apartment", "house"}:
            return ProductEvidence(
                PRODUCT_UNKNOWN,
                "unknown",
                fields_used=tuple(fields),
                reason="no_text_structured_residential",
            )
        return ProductEvidence(PRODUCT_UNKNOWN, "unknown", fields_used=tuple(fields), reason="no_text")

    normalized = _normalize(text)
    checks = (
        (PRODUCT_MULTI_UNIT, _MULTI_STRONG, _MULTI_WEAK),
        (PRODUCT_DEMOLITION, _DEMOLITION_STRONG, ()),
        (PRODUCT_COMMERCIAL, _COMMERCIAL_STRONG, _COMMERCIAL_WEAK),
        (PRODUCT_LAND_OR_SITE, _LAND_STRONG, _LAND_WEAK),
        (PRODUCT_REMODELING, _REMODELING_STRONG, _REMODELING_WEAK),
        (PRODUCT_INVESTMENT, _INVESTMENT_STRONG, _INVESTMENT_WEAK),
    )
    for product_class, strong_terms, weak_terms in checks:
        strong = _matched_terms(normalized, strong_terms)
        if strong and not _is_ambiguous_land_only(product_class, strong, normalized):
            return ProductEvidence(
                product_class,
                "strong",
                terms=strong,
                fields_used=tuple(fields),
                reason="strong_text_signal",
                normalized_text=normalized,
            )
        weak = _matched_terms(normalized, weak_terms)
        if weak and _has_supporting_context(product_class, normalized):
            return ProductEvidence(
                product_class,
                "weak",
                terms=weak,
                fields_used=tuple(fields),
                reason="weak_text_signal_with_context",
                normalized_text=normalized,
            )

    if property_type in {"apartment", "house"}:
        return ProductEvidence(
            PRODUCT_STANDARD_RESIDENTIAL,
            "structured",
            fields_used=tuple(fields),
            reason="structured_residential_without_special_signal",
            normalized_text=normalized,
        )
    return ProductEvidence(PRODUCT_UNKNOWN, "unknown", fields_used=tuple(fields), reason="unclassified")


def product_compatibility(target: ProductEvidence, candidate: ProductEvidence) -> ProductCompatibility:
    """Return whether a candidate product can be compared with the target."""

    if target.product_class == PRODUCT_UNKNOWN:
        if candidate.is_strong_special:
            return ProductCompatibility(False, f"unknown_target_excludes_{candidate.product_class}")
        return ProductCompatibility(True, "unknown_target_allows_standard_or_unknown")

    if target.product_class == PRODUCT_STANDARD_RESIDENTIAL:
        if candidate.is_strong_special:
            return ProductCompatibility(False, f"standard_target_excludes_{candidate.product_class}")
        if candidate.strength == "weak" and candidate.product_class in {
            PRODUCT_REMODELING,
            PRODUCT_INVESTMENT,
            PRODUCT_COMMERCIAL,
            PRODUCT_MULTI_UNIT,
            PRODUCT_LAND_OR_SITE,
        }:
            return ProductCompatibility(False, f"standard_target_excludes_weak_{candidate.product_class}")
        return ProductCompatibility(True, "standard_residential_compatible")

    if target.product_class in SPECIAL_PRODUCT_CLASSES:
        if candidate.product_class == target.product_class:
            return ProductCompatibility(True, "same_special_class")
        if candidate.product_class == PRODUCT_UNKNOWN and not candidate.is_strong_special:
            return ProductCompatibility(True, "special_target_fallback_to_unknown", fallback_used=True)
        return ProductCompatibility(False, f"special_target_excludes_{candidate.product_class}")

    return ProductCompatibility(False, "unsupported_product_class")


def _text_from_value(value: Listing | Property) -> tuple[str, list[str]]:
    metadata = getattr(value, "raw_metadata", None)
    metadata = metadata if isinstance(metadata, dict) else {}
    parts: list[str] = []
    fields: list[str] = []
    for field_name, raw in (
        ("title", getattr(value, "title", None)),
        ("title", metadata.get("title")),
        ("description", metadata.get("description")),
        ("card_text", metadata.get("card_text")),
        ("detail_text", metadata.get("detail_text")),
        ("highlight", metadata.get("highlight")),
        ("product_class_hint", metadata.get("product_class_hint")),
    ):
        if isinstance(raw, str) and raw.strip():
            parts.append(raw)
            fields.append(field_name)
    return " ".join(parts), fields


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value).lower())
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    clean = _TOKEN_RE.sub(" ", ascii_text)
    return f" {_SPACE_RE.sub(' ', clean).strip()} "


def _matched_terms(text: str, terms: tuple[str, ...]) -> tuple[str, ...]:
    found = []
    for term in terms:
        normalized = _normalize(term).strip()
        if f" {normalized} " in text:
            found.append(term)
    return tuple(found)


def _is_ambiguous_land_only(product_class: str, terms: tuple[str, ...], text: str) -> bool:
    if product_class != PRODUCT_LAND_OR_SITE:
        return False
    if terms != ("terreno",):
        return False
    return bool(
        any(phrase in text for phrase in (" amplio terreno ", " gran terreno ", " terreno amplio "))
        and any(kind in text for kind in (" casa ", " vivienda "))
    )


def _has_supporting_context(product_class: str, text: str) -> bool:
    if product_class == PRODUCT_LAND_OR_SITE:
        return any(phrase in text for phrase in (" venta ", " sitio ", " lote ", " solo "))
    if product_class == PRODUCT_REMODELING:
        return any(phrase in text for phrase in (" para ", " requiere ", " estado ", " casa "))
    if product_class == PRODUCT_COMMERCIAL:
        return any(phrase in text for phrase in (" uso ", " local ", " oficina ", " propiedad "))
    if product_class == PRODUCT_INVESTMENT:
        return any(phrase in text for phrase in (" ideal ", " renta ", " arrendada ", " inversion "))
    if product_class == PRODUCT_MULTI_UNIT:
        return any(phrase in text for phrase in (" viviendas ", " casas ", " unidades ", " interior "))
    return False
