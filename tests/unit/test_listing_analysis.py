from __future__ import annotations

from dataclasses import dataclass

import pytest

from services.listing_analysis import analyze_listing_lookup


@dataclass(frozen=True)
class _Valuation:
    estimated_price_uf: float | None
    estimated_price_clp: int | None = 200_000_000
    price_range_low_uf: float | None = 4500
    price_range_high_uf: float | None = 5500
    confidence_score: float | None = 0.72
    confidence_label: str | None = "medium"
    comparable_count: int = 12
    warnings: list[str] | None = None


class _ValuationService:
    def __init__(self, valuation: _Valuation) -> None:
        self.valuation = valuation
        self.inputs = []

    async def valuate_property(self, valuation_input):
        self.inputs.append(valuation_input)
        return self.valuation


def _listing(price_uf: float | None = 4500) -> dict:
    return {
        "listing_id": 123,
        "title": "Depto test",
        "url": "https://www.yapo.cl/test/123",
        "comuna": "nunoa",
        "property_type": "apartment",
        "m2": 70,
        "built_area_m2": 70,
        "usable_area_m2": 70,
        "land_area_m2": None,
        "dormitorios": 2,
        "banos": 2,
        "estacionamientos": 1,
        "precio_publicado_uf": price_uf,
        "precio_publicado_clp": 175_500_000,
        "price_currency": "UF" if price_uf is not None else "CLP",
        "price_uf_source": "scraped" if price_uf is not None else None,
        "price_uf_confidence": "high" if price_uf is not None else None,
        "price_recovery_method": "raw.price_uf" if price_uf is not None else None,
    }


@pytest.mark.asyncio
async def test_listing_analysis_detects_under_market() -> None:
    service = _ValuationService(_Valuation(estimated_price_uf=5000))

    result = await analyze_listing_lookup(_listing(price_uf=4300), valuation_service=service)

    assert result.price_analysis["verdict"] == "under_market"
    assert result.price_analysis["difference_uf"] == 700
    assert result.price_analysis["difference_pct"] == 14
    assert result.report_status["listing_risk_report_available"] is False
    assert service.inputs[0].precio_publicado_uf == 4300


@pytest.mark.asyncio
async def test_listing_analysis_detects_in_range() -> None:
    result = await analyze_listing_lookup(
        _listing(price_uf=4700),
        valuation_service=_ValuationService(_Valuation(estimated_price_uf=5000)),
    )

    assert result.price_analysis["verdict"] == "in_range"
    assert result.price_analysis["verdict_label"] == "En rango"


@pytest.mark.asyncio
async def test_listing_analysis_detects_over_market() -> None:
    result = await analyze_listing_lookup(
        _listing(price_uf=5600),
        valuation_service=_ValuationService(_Valuation(estimated_price_uf=5000)),
    )

    assert result.price_analysis["verdict"] == "over_market"
    assert result.price_analysis["difference_pct"] == -12


@pytest.mark.asyncio
async def test_listing_analysis_does_not_derive_uf_from_clp() -> None:
    result = await analyze_listing_lookup(
        _listing(price_uf=None),
        valuation_service=_ValuationService(_Valuation(estimated_price_uf=5000)),
    )

    assert result.price_analysis["verdict"] == "insufficient_data"
    assert result.price_analysis["explanation"] == "No hay precio publicado UF confiable para comparar."
    assert "Precio UF confiable no disponible." in result.signals["risks"]


@pytest.mark.asyncio
async def test_listing_analysis_is_insufficient_without_estimate_or_confidence() -> None:
    no_estimate = await analyze_listing_lookup(
        _listing(price_uf=4500),
        valuation_service=_ValuationService(_Valuation(estimated_price_uf=None)),
    )
    low_confidence = await analyze_listing_lookup(
        _listing(price_uf=4500),
        valuation_service=_ValuationService(_Valuation(estimated_price_uf=5000, confidence_score=0.2)),
    )

    assert no_estimate.price_analysis["verdict"] == "insufficient_data"
    assert low_confidence.price_analysis["verdict"] == "insufficient_data"
