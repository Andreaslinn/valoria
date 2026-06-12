"""Versioned configuration for valoria_consensus."""
from __future__ import annotations

from dataclasses import dataclass, field

CONSENSUS_ENGINE_NAME = "valoria_consensus"
CONSENSUS_ENGINE_VERSION = "valoria_consensus_v1"


@dataclass(frozen=True)
class ConsensusConfig:
    version: str = CONSENSUS_ENGINE_VERSION
    expected_engines: tuple[str, ...] = (
        "comparables_legacy",
        "comparables_canonical",
        "hedonic",
        "ml",
        "house_land_building",
    )
    min_confidence: float = 0.20
    min_validation_n: int = 30
    moderate_disagreement_pct: float = 0.12
    weak_disagreement_pct: float = 0.25
    extreme_disagreement_pct: float = 0.35
    blocking_warnings: frozenset[str] = frozenset({
        "artifact_version_mismatch",
        "missing_critical_data",
        "severe_out_of_distribution",
    })
    expected_versions: dict[str, str] = field(default_factory=dict)


DEFAULT_CONFIG = ConsensusConfig()
