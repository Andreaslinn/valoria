from __future__ import annotations

from domain.radar.beta_safety import assess_radar_safety


def test_no_data_opportunity_is_hidden() -> None:
    result = assess_radar_safety(
        beta_scope_status="no_data",
        beta_scope_flags=["no_segment_sample"],
        comparable_quality_level="acceptable",
    )

    assert result.show is False
    assert result.verdict == "no_data"
    assert "no_segment_sample" in result.risk_flags


def test_weak_or_exploratory_scope_is_review_only() -> None:
    result = assess_radar_safety(
        beta_scope_status="exploratory",
        beta_scope_flags=["limited_segment_sample"],
        comparable_quality_level="strong",
    )

    assert result.show is True
    assert result.verdict == "revisar"


def test_legacy_dataset_caution_scope_is_review_only() -> None:
    result = assess_radar_safety(
        beta_scope_status="caution",
        beta_scope_flags=[],
        comparable_quality_level="strong",
    )

    assert result.show is True
    assert result.verdict == "revisar"


def test_poor_or_weak_comparable_quality_is_review_only() -> None:
    result = assess_radar_safety(
        beta_scope_status="beta_supported",
        beta_scope_flags=[],
        comparable_quality_level="weak",
        comparable_quality_flags=["weak_geolocation"],
    )

    assert result.show is True
    assert result.verdict == "revisar"
    assert "weak_geolocation" in result.risk_flags


def test_strong_segment_uses_beta_safe_language_not_buy_language() -> None:
    result = assess_radar_safety(
        beta_scope_status="strong_sample",
        beta_scope_flags=[],
        comparable_quality_level="strong",
    )

    assert result.show is True
    assert result.verdict == "senal_fuerte"
    assert "comprar" not in result.message.lower()
