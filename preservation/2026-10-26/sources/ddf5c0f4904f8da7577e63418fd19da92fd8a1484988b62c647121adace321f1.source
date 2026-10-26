"""Canonical beta status vocabulary and compatibility mappings.

Runtime valuation uses the canonical ``BetaStatus`` values. Historical coverage
reports can keep their legacy ``DatasetBetaStatus`` values while exposing an
explicit canonical mapping.
"""
from __future__ import annotations

from typing import Any


class BetaStatus:
    NO_DATA = "no_data"
    WEAK_DATA = "weak_data"
    EXPLORATORY = "exploratory"
    BETA_SUPPORTED = "beta_supported"
    STRONG_SAMPLE = "strong_sample"


BETA_STATUS_CODES = frozenset(
    {
        BetaStatus.NO_DATA,
        BetaStatus.WEAK_DATA,
        BetaStatus.EXPLORATORY,
        BetaStatus.BETA_SUPPORTED,
        BetaStatus.STRONG_SAMPLE,
    }
)

BETA_WARNING_STATUS_CODES = frozenset(
    {
        BetaStatus.NO_DATA,
        BetaStatus.WEAK_DATA,
        BetaStatus.EXPLORATORY,
    }
)


class DatasetBetaStatus:
    BETA_READY = "beta_ready"
    CAUTION = "caution"
    HIDE_IN_BETA = "hide_in_beta"


DATASET_BETA_STATUS_CODES = frozenset(
    {
        DatasetBetaStatus.BETA_READY,
        DatasetBetaStatus.CAUTION,
        DatasetBetaStatus.HIDE_IN_BETA,
    }
)

DATASET_TO_CANONICAL_BETA_STATUS = {
    DatasetBetaStatus.HIDE_IN_BETA: BetaStatus.WEAK_DATA,
    DatasetBetaStatus.CAUTION: BetaStatus.EXPLORATORY,
    DatasetBetaStatus.BETA_READY: BetaStatus.BETA_SUPPORTED,
}

BETA_STATUS_ALIASES = {
    **DATASET_TO_CANONICAL_BETA_STATUS,
    "none": BetaStatus.NO_DATA,
    "no_sample": BetaStatus.NO_DATA,
    "insufficient_data": BetaStatus.WEAK_DATA,
    "weak": BetaStatus.WEAK_DATA,
    "limited": BetaStatus.EXPLORATORY,
    "ready": BetaStatus.BETA_SUPPORTED,
    "supported": BetaStatus.BETA_SUPPORTED,
    "strong": BetaStatus.STRONG_SAMPLE,
}

BETA_DISPLAY_LABELS = {
    BetaStatus.NO_DATA: "Sin datos",
    BetaStatus.WEAK_DATA: "Datos debiles",
    BetaStatus.EXPLORATORY: "Exploratorio",
    BetaStatus.BETA_SUPPORTED: "Beta soportado",
    BetaStatus.STRONG_SAMPLE: "Muestra fuerte",
    DatasetBetaStatus.HIDE_IN_BETA: "Ocultar en beta",
    DatasetBetaStatus.CAUTION: "Cautela beta",
    DatasetBetaStatus.BETA_READY: "Beta listo",
}

BETA_STATUS_MESSAGES = {
    BetaStatus.NO_DATA: "Sin muestra util para este segmento; mostrar solo como diagnostico.",
    BetaStatus.WEAK_DATA: "Muestra muy baja; resultado referencial y no apto para decisiones.",
    BetaStatus.EXPLORATORY: "Hay datos, pero la muestra/calidad requiere lectura exploratoria.",
    BetaStatus.BETA_SUPPORTED: "Segmento razonable para beta privada con advertencias visibles.",
    BetaStatus.STRONG_SAMPLE: "Segmento con muestra fuerte para beta, sin implicar precision garantizada.",
}

BETA_STATUS_TONES = {
    BetaStatus.NO_DATA: "negative",
    BetaStatus.WEAK_DATA: "warning",
    BetaStatus.EXPLORATORY: "warning",
    BetaStatus.BETA_SUPPORTED: "premium",
    BetaStatus.STRONG_SAMPLE: "positive",
}

COVERAGE_WEAK_BETA_STATUS_CODES = frozenset(
    {
        DatasetBetaStatus.HIDE_IN_BETA,
        DatasetBetaStatus.CAUTION,
        BetaStatus.NO_DATA,
        BetaStatus.WEAK_DATA,
        BetaStatus.EXPLORATORY,
    }
)


class PropertyTypeCoverageStatus:
    INVIABLE = "inviable"
    BETA_CANDIDATE = "beta_candidate"
    LIMITED_BETA_CANDIDATE = "limited_beta_candidate"
    BROAD_BETA_CANDIDATE = "broad_beta_candidate"


def normalize_beta_status(value: Any, *, default: str = BetaStatus.NO_DATA) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return default
    if text in BETA_STATUS_CODES:
        return text
    return BETA_STATUS_ALIASES.get(text, default)


def dataset_beta_status_to_canonical(value: Any) -> str:
    return normalize_beta_status(value, default=BetaStatus.WEAK_DATA)


def beta_status_display_label(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in BETA_DISPLAY_LABELS:
        return BETA_DISPLAY_LABELS[text]
    canonical = normalize_beta_status(text, default="")
    return BETA_DISPLAY_LABELS.get(canonical, "No disponible")


def beta_status_message(value: Any) -> str:
    return BETA_STATUS_MESSAGES.get(normalize_beta_status(value), "Estado de cobertura no disponible.")


def beta_status_tone(value: Any) -> str:
    return BETA_STATUS_TONES.get(normalize_beta_status(value, default=""), "neutral")


def is_beta_warning_status(value: Any) -> bool:
    return normalize_beta_status(value) in BETA_WARNING_STATUS_CODES


def beta_scope_warning_codes(status: Any) -> list[str]:
    canonical = normalize_beta_status(status, default="")
    if canonical in BETA_WARNING_STATUS_CODES:
        return [f"beta_scope_{canonical}"]
    return []

