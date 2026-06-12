from __future__ import annotations

from core.assessment.beta_status import (
    BetaStatus,
    beta_scope_warning_codes,
    beta_status_display_label,
    dataset_beta_status_to_canonical,
    normalize_beta_status,
)


def test_canonical_beta_statuses_pass_through() -> None:
    assert normalize_beta_status("strong_sample") == BetaStatus.STRONG_SAMPLE
    assert normalize_beta_status("beta_supported") == BetaStatus.BETA_SUPPORTED


def test_legacy_dataset_statuses_map_to_canonical_statuses() -> None:
    assert dataset_beta_status_to_canonical("hide_in_beta") == BetaStatus.WEAK_DATA
    assert dataset_beta_status_to_canonical("caution") == BetaStatus.EXPLORATORY
    assert dataset_beta_status_to_canonical("beta_ready") == BetaStatus.BETA_SUPPORTED


def test_display_labels_accept_canonical_and_legacy_statuses() -> None:
    assert beta_status_display_label("weak_data") == "Datos debiles"
    assert beta_status_display_label("hide_in_beta") == "Ocultar en beta"


def test_warning_codes_are_canonicalized() -> None:
    assert beta_scope_warning_codes("caution") == ["beta_scope_exploratory"]
    assert beta_scope_warning_codes("beta_ready") == []

