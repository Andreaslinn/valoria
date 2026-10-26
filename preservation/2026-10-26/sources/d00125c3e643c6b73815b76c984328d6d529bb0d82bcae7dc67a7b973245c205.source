"""Complete Yapo UF prices without treating unavailable conversion as invalid data."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from core.exceptions import UFServiceError
from services.uf_rate import validate_real_uf_rate


class YapoPendingUF(UFServiceError):
    """Original price is valid; retain the record until a real UF rate is available."""


def prepare_yapo_price(raw, uf_info=None):
    result = deepcopy(raw)
    metadata = result.get("raw_metadata") or {}
    needs_conversion = metadata.get("price_clp_missing_reason") == "missing_uf_rate"
    converted = metadata.get("price_clp_provenance") == "derived_from_uf_real_rate" and uf_info is not None
    if result.get("source") != "yapo" or not (needs_conversion or converted):
        return result
    try:
        amount = Decimal(str(result.get("price_uf")))
    except (InvalidOperation, ValueError, TypeError):
        return result  # The normal validator still rejects genuinely invalid prices.
    if not amount.is_finite() or amount <= 0:
        return result
    if uf_info is None:
        raise YapoPendingUF("Yapo price retained in UF; real conversion rate unavailable")
    validate_real_uf_rate(uf_info)
    result["price_clp"] = int(amount * uf_info.rate)
    metadata.pop("price_clp_missing_reason", None)
    metadata.update(price_clp_provenance="derived_from_uf_real_rate", uf_rate_used=str(uf_info.rate),
                    uf_rate_source=uf_info.source,
                    uf_rate_date=uf_info.rate_date.isoformat() if uf_info.rate_date else None)
    result["raw_metadata"] = metadata
    return result
