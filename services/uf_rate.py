"""Helpers for requiring a real UF rate in productive flows."""
from __future__ import annotations

from decimal import Decimal

from config.constants import LEGACY_UF_ARTIFACT_RATE
from core.exceptions import UFServiceError
from core.ports.uf_service import UFRateInfo, UFService


async def require_real_uf_rate(uf_service: UFService) -> UFRateInfo:
    """Return a verified real UF rate or fail explicitly.

    This helper must be used by productive flows before converting between UF
    and CLP. It never returns the legacy artifact rate and never accepts a
    fallback-marked source.
    """
    info = await uf_service.get_current_rate_info()
    validate_real_uf_rate(info)
    return info


def validate_real_uf_rate(info: UFRateInfo) -> None:
    if info.is_fallback:
        raise UFServiceError("UF real no disponible: fuente fallback rechazada")
    source = str(info.source or "").strip().lower()
    if source in {"fallback", "legacy_fallback", "legacy_artifact"}:
        raise UFServiceError("UF real no disponible: fuente historica rechazada")
    if info.rate <= 0:
        raise UFServiceError("UF real no disponible: tasa invalida")
    if _same_rate(info.rate, LEGACY_UF_ARTIFACT_RATE):
        raise UFServiceError("UF real no disponible: tasa coincide con artefacto historico 37000")


def _same_rate(left: Decimal, right: Decimal) -> bool:
    return left.quantize(Decimal("0.01")) == right.quantize(Decimal("0.01"))
