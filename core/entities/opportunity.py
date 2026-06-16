"""Resultados del motor de tasación y del radar de oportunidades."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from core.assessment.contracts import BetaScopeMetricsPayload, ComparableQualityMetricsPayload
from core.entities.listing import Listing
from core.value_objects.price import Price
from core.value_objects.score import Score


@dataclass
class ValuationResult:
    """Resultado de una tasación por comparables."""

    estimated_price: Price
    price_range_low: Price
    price_range_high: Price
    confidence: Score
    comparables_used: int
    uf_to_clp_rate: Decimal
    reliability_warnings: list[str] = field(default_factory=list)
    reliability_metrics: dict = field(default_factory=dict)
    base_confidence: Score | None = None
    comparable_quality_level: str | None = None
    comparable_quality_flags: list[str] = field(default_factory=list)
    comparable_quality_metrics: ComparableQualityMetricsPayload = field(default_factory=dict)
    beta_scope_status: str | None = None
    beta_scope_flags: list[str] = field(default_factory=list)
    beta_scope_metrics: BetaScopeMetricsPayload = field(default_factory=dict)
    beta_scope_message: str | None = None

    def __post_init__(self) -> None:
        if self.price_range_low > self.estimated_price:
            raise ValueError("price_range_low no puede ser mayor al estimado")
        if self.estimated_price > self.price_range_high:
            raise ValueError("estimated_price no puede ser mayor al price_range_high")


@dataclass
class Opportunity:
    """Publicación detectada como subvaluada vs. el mercado."""

    listing: Listing
    market_price: Price            # precio justo según comparables
    discount_pct: float            # [0, 1] — descuento frente al mercado
    confidence: Score
    comparables_used: int
    valuation_result: ValuationResult | None = None
    price_currency: str | None = None
    price_uf: Decimal | None = None
    price_clp_snapshot: Decimal | None = None
    price_basis_used: str | None = None
    price_data_quality: str | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.discount_pct <= 1.0:
            raise ValueError(f"discount_pct debe estar en [0, 1]: {self.discount_pct}")

    @property
    def ranking_score(self) -> float:
        """Score para ordenar oportunidades: descuento x confianza."""
        return self.discount_pct * self.confidence.value


@dataclass
class RadarResult:
    """Salida del radar: oportunidades + metadata del run.

    low_data_mode se expone para que el UI pueda advertir al usuario que
    las señales son menos confiables por tener poco dataset.
    """

    opportunities: list[Opportunity]
    total_listings_analyzed: int
    low_data_mode: bool
    low_data_by_property_type: dict[str, bool] = field(default_factory=dict)
    total_candidates: int = 0
    processed_candidates: int = 0
    skipped_invalid_area: int = 0
    skipped_validation_error: int = 0
