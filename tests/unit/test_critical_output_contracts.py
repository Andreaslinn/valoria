from __future__ import annotations

from api.v1.valuations import ValuationResponse
from core.assessment.confidence import build_confidence_contract
from core.value_objects.score import Score
from domain.valuation.beta_scope import assess_beta_scope
from domain.valuation.comparable_quality import assess_comparable_quality
from scripts.beta_readiness_report import build_beta_readiness_report
from services.radar import OpportunityDTO
from services.valuation import ComparableDTO, ValuationDTO
from tests.unit.factories import make_listing, make_property


def test_confidence_contract_payload_keeps_canonical_and_legacy_keys() -> None:
    payload = build_confidence_contract(
        score=Score.clamped(0.72),
        base_score=Score.clamped(0.9),
        reliability_warnings=["high_price_m2_dispersion"],
    ).to_payload()

    assert set(payload) == {
        "confidence",
        "confidence_score",
        "confidence_label",
        "confidence_reasons",
        "confidence_risk_flags",
    }
    assert payload["confidence"] == payload["confidence_label"] == "medium"
    assert payload["confidence_score"] == 0.72
    assert payload["confidence_risk_flags"] == ["high_price_m2_dispersion"]


def test_comparable_quality_and_beta_scope_metrics_have_stable_keys() -> None:
    target = make_property(m2=75, built_area_m2=75)
    listings = [
        make_listing(fingerprint=f"contract-{idx}", m2=75, built_area_m2=75, price_clp=180_000_000 + idx)
        for idx in range(8)
    ]
    scored = [(Score.clamped(0.82), listing) for listing in listings]

    quality = assess_comparable_quality(target=target, scored_comparables=scored)
    beta = assess_beta_scope(target=target, candidate_pool=listings, comparable_quality=quality)

    assert {
        "n_comparables",
        "price_per_m2_dispersion",
        "address_level_geo_ratio",
        "property_type_consistency",
        "target_m2_bucket",
    } <= set(quality.metrics)
    assert {
        "segment_sample_count",
        "m2_bucket_sample_count",
        "comparable_quality_level",
        "n_comparables",
        "price_per_m2_dispersion",
    } <= set(beta.metrics)
    assert "comparable_quality" not in quality.metrics
    assert "beta_scope_status" not in beta.metrics


def test_valuation_response_accepts_typed_service_dto_without_losing_legacy_fields() -> None:
    dto = ValuationDTO(
        base_estimated_price_uf=4800.0,
        base_estimated_price_clp=180_000_000,
        estimated_price_uf=4810.0,
        estimated_price_clp=181_000_000,
        price_range_low_uf=4500.0,
        price_range_high_uf=5100.0,
        price_range_low_clp=169_000_000,
        price_range_high_clp=191_000_000,
        confidence="high",
        confidence_score=0.84,
        confidence_label="high",
        confidence_reasons=[],
        confidence_risk_flags=[],
        comparable_count=12,
        price_m2_uf=64.13,
        status="ok",
        warnings=[],
        comparable_quality_level="strong",
        comparable_quality_flags=[],
        comparable_quality_metrics={"n_comparables": 12, "price_per_m2_dispersion": 12.5},
        beta_scope_status="beta_supported",
        beta_scope_flags=[],
        beta_scope_metrics={"segment_sample_count": 80, "n_comparables": 12},
        beta_scope_message="Segmento soportado para beta.",
        surface_adjustment_applied=False,
        surface_adjustment_weight=0.0,
        surface_adjustment_reason="surface_unavailable",
        comparables=[
            ComparableDTO(
                listing_id=1,
                title="Depto test",
                comuna="nunoa",
                price_uf=4800.0,
                price_clp=180_000_000,
                m2=75,
                built_area_m2=75,
                land_area_m2=None,
                usable_area_m2=75,
                similarity=0.92,
                url=None,
            )
        ],
        valuation_verdict={
            "estimate_uf": 4810.0,
            "low_uf": 4500.0,
            "high_uf": 5100.0,
            "confidence": 0.72,
            "source": "consensus_experimental",
        },
        engine_breakdown=[
            {
                "engine_name": "microzone_geo_v1",
                "label": "Microzona",
                "role": "territorial_signal",
                "estimate_uf": 4800.0,
                "confidence": 0.7,
                "weight": 0.25,
                "status": "success",
                "warning_flags": [],
            }
        ],
        consensus_audit={
            "engines_used": ["microzone_geo_v1"],
            "engines_abstained": {},
            "engines_failed": {},
            "disagreement_level": "low",
            "weight_audit": [],
        },
    )

    response = ValuationResponse.model_validate(dto, from_attributes=True).model_dump()

    assert response["confidence"] == "high"
    assert response["confidence_score"] == 0.84
    assert response["comparable_quality_metrics"]["n_comparables"] == 12
    assert response["beta_scope_metrics"]["segment_sample_count"] == 80
    assert response["valuation_verdict"]["source"] == "consensus_experimental"
    assert response["engine_breakdown"][0]["engine_name"] == "microzone_geo_v1"
    assert response["consensus_audit"]["disagreement_level"] == "low"
    assert dto.to_payload()["comparables"][0]["similarity"] == 0.92


def test_radar_opportunity_contract_uses_lists_not_optional_flag_payloads() -> None:
    opportunity = OpportunityDTO(
        listing_id=1,
        title="Oportunidad",
        comuna="nunoa",
        price_uf=4300.0,
        price_clp=160_000_000,
        m2=75,
        estimated_price_uf=4800.0,
        discount_pct=10.0,
        score=0.8,
        confidence="medium",
        confidence_score=0.7,
        confidence_label="medium",
        confidence_reasons=[],
        confidence_risk_flags=[],
        comparables_used=8,
        url=None,
        warnings=[],
        radar_verdict="mostrar",
        radar_verdict_message="Visible en beta.",
        risk_flags=[],
    )

    payload = opportunity.to_payload()

    assert payload["comparable_quality_flags"] == []
    assert payload["beta_scope_flags"] == []
    assert payload["confidence"] == payload["confidence_label"] == "medium"


def test_beta_readiness_report_contract_has_typed_sections() -> None:
    report = build_beta_readiness_report({}, generated_at="2026-05-27T00:00:00+00:00")

    assert report["generated_at"] == "2026-05-27T00:00:00+00:00"
    assert {"pipeline_health", "dataset_coverage", "feedback"} <= set(report["sections"])
    for section in report["sections"].values():
        assert {"status", "summary", "flags", "blocking_risks", "critical_risks", "limitations"} <= set(section)
