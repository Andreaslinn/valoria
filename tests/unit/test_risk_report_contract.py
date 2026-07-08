from __future__ import annotations

from ui.components.risk_report_contract import (
    AnalysisContext,
    build_risk_report_contract_shadow,
    normalize_evidence_flags,
)


def _codes(items: tuple) -> set[str]:
    return {item.code for item in items}


def _fields(items: tuple) -> set[str]:
    return {item.field for item in items}


def test_property_valuation_manual_shadow_contract_does_not_penalize_listing_absence() -> None:
    result = {
        "estimated_price_uf": 16500.0,
        "estimated_price_clp": 643_500_000,
        "price_range_low_uf": 15400.0,
        "price_range_high_uf": 17600.0,
        "confidence": "medium",
        "comparable_count": 6,
        "price_m2_uf": 74.66,
        "warnings": [
            "published_price_not_provided",
            "low_comparable_count",
            "house_land_area_weak",
            "weak_microzone",
        ],
    }
    payload = {
        "comuna": "vitacura",
        "property_type": "house",
        "m2": 221.0,
        "built_area_m2": 221.0,
        "land_area_m2": 512.0,
    }

    contract = build_risk_report_contract_shadow(valuation_result=result, valuation_payload=payload)

    assert contract.analysis_context == AnalysisContext.PROPERTY_VALUATION.value
    assert contract.report_type == "Investment Intelligence Report"
    assert contract.headline_score_name == "investment_score"
    assert {"published_price", "url", "listing_id", "watchlist_state", "price_history_series"}.issubset(
        _fields(contract.not_applicable)
    )
    assert "published_price" not in _fields(contract.contextual_missing_fields)
    assert "url" not in _fields(contract.contextual_missing_fields)
    assert "listing_id" not in _fields(contract.contextual_missing_fields)
    assert "published_price_missing" not in _codes(contract.evidence_flags)
    assert {"limited_comparable_sample", "limited_land_area_evidence", "weak_microzone_support"}.issubset(
        _codes(contract.evidence_flags)
    )


def test_listing_analysis_shadow_contract_uses_listing_inputs() -> None:
    result = {
        "estimated_price_uf": 5200.0,
        "estimated_price_clp": 205_000_000,
        "confidence": "medium",
        "comparable_count": 5,
        "warnings": [
            "published_price_not_provided",
            "url_missing",
            "legacy_uf_missing_price_uf",
        ],
    }
    payload = {
        "comuna": "nunoa",
        "property_type": "apartment",
        "m2": 75.0,
        "precio_publicado_uf": 4500.0,
        "discount_pct": 13.4,
        "url": "https://example.test/listing/123",
        "source": "portal",
        "listing_id": 123,
        "canonical_price_basis": {"confidence": "medium"},
        "price_history_series": [{"price_uf": 4700.0}, {"price_uf": 4500.0}],
        "watchlist_state": {"saved": True},
    }

    contract = build_risk_report_contract_shadow(valuation_result=result, valuation_payload=payload)

    assert contract.analysis_context == AnalysisContext.LISTING_ANALYSIS.value
    assert contract.report_type == "Listing Risk / Opportunity Report"
    assert contract.headline_score_name == "listing_opportunity_score"
    assert contract.price_opportunity is not None
    assert contract.price_opportunity["published_price"] == 4500.0
    assert contract.price_opportunity["discount_pct"] == 13.4
    assert contract.listing_context is not None
    assert contract.listing_context["url"] == "https://example.test/listing/123"
    assert contract.listing_context["source"] == "portal"
    assert contract.listing_context["listing_id"] == 123
    assert {"published_price_missing", "listing_identity_missing", "published_price_quality_limited"}.issubset(
        _codes(contract.evidence_flags)
    )


def test_normalize_evidence_flags_deduplicates_geographic_precision_codes() -> None:
    normalized = normalize_evidence_flags(
        [
            "poor_geocoding_comparables",
            "weak_geolocation",
            "weak_geocode_quality",
        ],
        AnalysisContext.PROPERTY_VALUATION,
    )

    assert [flag.code for flag in normalized.evidence_flags] == ["limited_geographic_precision"]
    assert normalized.evidence_flags[0].raw_codes == (
        "poor_geocoding_comparables",
        "weak_geolocation",
        "weak_geocode_quality",
    )


def test_technical_warning_codes_are_hidden_from_user_facing_flags() -> None:
    contract = build_risk_report_contract_shadow(
        valuation_result={
            "estimated_price_uf": 5200.0,
            "confidence": "medium",
            "comparable_count": 5,
            "warnings": [
                "engine_not_registered",
                "unexpected_error",
                "consensus_missing_calibrated_weights",
            ],
            "engine_results": [{"engine_name": "internal_engine", "engine_version": "1"}],
            "consensus_summary": {"method": "weighted"},
        },
        valuation_payload={"comuna": "nunoa", "property_type": "apartment", "m2": 75.0},
    )

    assert "engine_or_consensus_diagnostic" not in _codes(contract.evidence_flags)
    assert "engine_or_consensus_diagnostic" in _codes(contract.technical_hidden)
    assert "engine_results" in _codes(contract.technical_hidden)
    assert "consensus_summary" in _codes(contract.technical_hidden)


def test_future_demo_signals_are_excluded_from_shadow_score_inputs() -> None:
    contract = build_risk_report_contract_shadow(
        valuation_result={
            "estimated_price_uf": 5200.0,
            "confidence": "medium",
            "comparable_count": 5,
            "warnings": [],
        },
        valuation_payload={
            "comuna": "nunoa",
            "property_type": "apartment",
            "m2": 75.0,
            "days_on_market": 99,
            "liquidity": 87,
            "legal_external_risk": {"score": 40},
            "market_map_heat_zones": [{"zone": "demo"}],
            "portfolio_avm_delta": {"delta_pct": 5},
            "geographic_microzone": {"microzone_id": "demo"},
        },
    )

    assert contract.score_summary.value is None
    assert {
        "days_on_market",
        "liquidity",
        "legal_external_risk",
        "market_map_heat_zones",
        "portfolio_avm_delta",
        "geographic_microzone",
    }.issubset(set(contract.future_excluded_from_score))
    assert contract.evidence_flags == ()
