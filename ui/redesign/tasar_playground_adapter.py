"""Adapter layer that connects the Tasar playground to the real valuation flow."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ui.api_client import ApiError
from ui.demo_data import get_demo_valuation_result
from ui.valuation.form import build_valuation_payload
from ui.valuation.result import normalize_confidence


class ValuationClient(Protocol):
    def create_valuation(self, payload: dict[str, Any], token: str | None = None) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class TasarComparableViewModel:
    title: str
    comuna: str | None
    price_uf: float | None
    price_clp: float | None
    m2: float | None
    bedrooms: int | None
    bathrooms: int | None
    parking_spaces: int | None
    similarity: float | None
    date: str | None
    distance: str | None
    url: str | None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TasarValuationViewModel:
    source: str
    is_demo: bool
    estimated_value_uf: float | None
    estimated_value_clp: float | None
    price_range_low_uf: float | None
    price_range_high_uf: float | None
    price_range_low_clp: float | None
    price_range_high_clp: float | None
    price_m2_uf: float | None
    confidence: Any | None
    confidence_label: str | None
    confidence_key: str
    confidence_score: float | None
    comparable_count: int | None
    comparables: tuple[TasarComparableViewModel, ...]
    warnings: tuple[str, ...]
    errors: tuple[str, ...]
    payload: dict[str, Any]
    raw: dict[str, Any]

    @property
    def has_result(self) -> bool:
        return self.estimated_value_uf is not None or self.estimated_value_clp is not None


def get_tasar_payload_from_form(
    *,
    comuna: str,
    property_type: str,
    built_area_m2: float,
    land_area_m2: float | None,
    dormitorios: int,
    banos: int,
    estacionamientos: int,
    precio_uf: float | None,
    precio_clp: int | None,
) -> dict[str, Any]:
    """Build the exact payload used by the legacy valuation form contract."""
    return build_valuation_payload(
        comuna=comuna,
        property_type=property_type,
        built_area_m2=built_area_m2,
        land_area_m2=land_area_m2,
        dormitorios=dormitorios,
        banos=banos,
        estacionamientos=estacionamientos,
        precio_uf=precio_uf,
        precio_clp=precio_clp,
    )


def run_valuation_for_tasar(
    client: ValuationClient,
    payload: dict[str, Any],
    *,
    token: str | None,
    demo_mode: bool,
) -> dict[str, Any]:
    """Run the playground valuation through the same real/demo contract as legacy."""
    if demo_mode:
        result = dict(get_demo_valuation_result())
        result["is_demo"] = True
        result["source"] = "demo"
        return result

    if not token:
        raise ApiError("Inicia sesion para usar la tasacion real.", status_code=401)

    return client.create_valuation(payload, token=token)


def map_valuation_response_to_view_model(
    response: dict[str, Any] | None,
    *,
    payload: dict[str, Any] | None = None,
    source: str = "real",
) -> TasarValuationViewModel | None:
    if response is None:
        return None

    data = _flatten_response(response)
    source_name = _source_name(data, source)
    is_demo = source_name in {"demo", "lab"} or bool(data.get("is_demo"))
    comparables = tuple(_map_comparable(item) for item in _list_value(data.get("comparables")))
    comparable_count = _pick_int(data, "comparable_count", "comparables_used", "n_comparables")
    if comparable_count is None and comparables:
        comparable_count = len(comparables)

    confidence_value = _pick(data, "confidence_label", "confidence", "reliability")
    confidence_score = _pick_float(data, "confidence_score", "reliability_score")
    if confidence_score is None and isinstance(confidence_value, int | float):
        confidence_score = float(confidence_value)

    confidence_label = str(confidence_value) if confidence_value is not None else None
    confidence_key = normalize_confidence(confidence_value)

    return TasarValuationViewModel(
        source=source_name,
        is_demo=is_demo,
        estimated_value_uf=_pick_float(
            data,
            "estimated_value_uf",
            "estimated_price_uf",
            "valor_estimado_uf",
            "valor_estimado",
            "estimate_uf",
        ),
        estimated_value_clp=_pick_float(
            data,
            "estimated_value_clp",
            "estimated_price_clp",
            "valor_estimado_clp",
            "estimate_clp",
        ),
        price_range_low_uf=_range_value(data, low=True, clp=False),
        price_range_high_uf=_range_value(data, low=False, clp=False),
        price_range_low_clp=_range_value(data, low=True, clp=True),
        price_range_high_clp=_range_value(data, low=False, clp=True),
        price_m2_uf=_pick_float(data, "price_m2_uf", "price_per_m2_uf", "uf_m2", "precio_uf_m2"),
        confidence=confidence_value,
        confidence_label=confidence_label,
        confidence_key=confidence_key,
        confidence_score=confidence_score,
        comparable_count=comparable_count,
        comparables=comparables,
        warnings=tuple(_text_list(data.get("warnings") or data.get("warning") or data.get("messages"))),
        errors=tuple(_text_list(data.get("errors") or data.get("error"))),
        payload=dict(payload or {}),
        raw=dict(response),
    )


def map_tasar_error(error: ApiError) -> dict[str, Any]:
    return {"message": error.message, "status_code": error.status_code, "payload": error.payload}


def _flatten_response(response: dict[str, Any]) -> dict[str, Any]:
    nested = response.get("valuation") or response.get("result") or response.get("data")
    if isinstance(nested, dict):
        return {**response, **nested}
    return dict(response)


def _source_name(data: dict[str, Any], source: str) -> str:
    value = str(data.get("source") or source or "real").strip().lower()
    if value in {"demo", "lab", "real"}:
        return value
    return "demo" if data.get("is_demo") else "real"


def _map_comparable(item: Any) -> TasarComparableViewModel:
    data = item if isinstance(item, dict) else {}
    return TasarComparableViewModel(
        title=str(_pick(data, "title", "address_label", "name") or "Comparable"),
        comuna=_optional_text(_pick(data, "comuna", "commune")),
        price_uf=_pick_float(data, "price_uf", "precio_uf", "published_price_uf"),
        price_clp=_pick_float(data, "price_clp", "precio_clp", "published_price_clp"),
        m2=_pick_float(data, "m2", "built_area_m2", "usable_area_m2"),
        bedrooms=_pick_int(data, "bedrooms", "dormitorios"),
        bathrooms=_pick_int(data, "bathrooms", "banos"),
        parking_spaces=_pick_int(data, "parking_spaces", "estacionamientos"),
        similarity=_pick_float(data, "similarity", "score", "similarity_score"),
        date=_optional_text(_pick(data, "date", "detected_at", "captured_at", "created_at")),
        distance=_optional_text(_pick(data, "distance", "distance_label", "distance_km")),
        url=_optional_text(_pick(data, "url", "listing_url")),
        raw=dict(data),
    )


def _range_value(data: dict[str, Any], *, low: bool, clp: bool) -> float | None:
    prefix = "low" if low else "high"
    suffix = "clp" if clp else "uf"
    direct_keys = (
        f"price_range_{prefix}_{suffix}",
        f"estimated_{'min' if low else 'max'}_{suffix}",
        f"{'min' if low else 'max'}_{suffix}",
        f"valor_{'min' if low else 'max'}_{suffix}",
    )
    direct = _pick_float(data, *direct_keys)
    if direct is not None:
        return direct

    range_data = data.get("price_range") or data.get("range") or data.get("rango")
    if isinstance(range_data, dict):
        return _pick_float(
            range_data,
            prefix,
            "min" if low else "max",
            f"{prefix}_{suffix}",
            f"{'min' if low else 'max'}_{suffix}",
        )
    if isinstance(range_data, list | tuple) and len(range_data) >= 2:
        return _to_float(range_data[0 if low else 1])
    return None


def _pick(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = data.get(key)
        if value is not None and value != "":
            return value
    return None


def _pick_float(data: dict[str, Any], *keys: str) -> float | None:
    return _to_float(_pick(data, *keys))


def _pick_int(data: dict[str, Any], *keys: str) -> int | None:
    value = _pick(data, *keys)
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_text(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _list_value(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _text_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list | tuple | set):
        return [str(item) for item in value if item is not None and item != ""]
    return [str(value)]

