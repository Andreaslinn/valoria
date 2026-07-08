"""Adapter layer that connects the Tasar playground to the real valuation flow."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from ui.api_client import ApiError
from ui.components.risk_report_html import (
    build_investment_intelligence_report_data,
    build_listing_risk_report_data,
    build_risk_report_html,
)
from ui.demo_data import get_demo_valuation_result
from ui.redesign.valuation_warnings import (
    ValuationWarningDetail,
    ValuationWarningSummary,
    map_valuation_warnings,
    summarize_valuation_warnings,
)
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
    warning_summary: ValuationWarningSummary
    location_intelligence: TasarLocationIntelligence
    errors: tuple[str, ...]
    payload: dict[str, Any]
    raw: dict[str, Any]

    @property
    def has_result(self) -> bool:
        return self.estimated_value_uf is not None or self.estimated_value_clp is not None


@dataclass(frozen=True)
class TasarRiskReportContract:
    risk_report_available: bool
    risk_report_status: str
    risk_report_html: str | None
    investment_report_html: str | None
    listing_report_html: str | None
    investment_file_name: str | None
    listing_file_name: str | None
    required_data: tuple[str, ...]
    generated_at: str | None
    source: str


@dataclass(frozen=True)
class TasarLocationIntelligence:
    status: str
    comuna: str | None
    address_label: str | None
    coordinates: tuple[float, float] | None
    geocoding_precision: str | None
    microzone_status: str
    comparable_count: int | None
    comparable_location_quality: str | None
    geo_signals: tuple[str, ...]
    location_warnings: tuple[ValuationWarningDetail, ...]
    summary: str
    reasons: tuple[str, ...]


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


def build_tasar_risk_report_contract(
    view_model: TasarValuationViewModel | None,
    *,
    payload: dict[str, Any] | None,
    lookup_result: dict[str, Any] | None = None,
) -> TasarRiskReportContract:
    """Build the Tasar Playground contract for the existing HTML Risk Report."""
    if view_model is None or not view_model.has_result:
        return _risk_report_status("requires_valuation", ("valuation_result",))

    if view_model.is_demo:
        return _risk_report_status("not_available", ("real_valuation_result",))

    valuation_payload = dict(payload or view_model.payload or {})
    required_data = _risk_report_required_data(view_model, valuation_payload)
    if "valuation_result" in required_data:
        return _risk_report_status("requires_valuation", tuple(required_data))
    if "comparables" in required_data:
        return _risk_report_status("requires_comparables", tuple(required_data))
    if "risk_inputs" in required_data:
        return _risk_report_status("requires_risk_inputs", tuple(required_data))

    raw_result = dict(view_model.raw)
    investment_report_data = build_investment_intelligence_report_data(
        raw_result,
        valuation_payload,
        lookup_result or {},
    )
    investment_report_html = build_risk_report_html(investment_report_data)
    listing_report_data = None
    listing_report_html = None
    if _has_listing_context(valuation_payload, lookup_result or {}):
        listing_report_data = build_listing_risk_report_data(
            raw_result,
            valuation_payload,
            lookup_result or {},
        )
        listing_report_html = build_risk_report_html(listing_report_data)

    generated_at = _report_generated_at(investment_report_data)
    return TasarRiskReportContract(
        risk_report_available=True,
        risk_report_status="available",
        risk_report_html=investment_report_html,
        investment_report_html=investment_report_html,
        listing_report_html=listing_report_html,
        investment_file_name=_report_file_name("investment_intelligence_report", investment_report_data),
        listing_file_name=(
            _report_file_name("listing_risk_report", listing_report_data)
            if listing_report_data is not None
            else None
        ),
        required_data=(),
        generated_at=generated_at,
        source="ui.components.risk_report_html",
    )


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
    warnings = tuple(_text_list(data.get("warnings") or data.get("warning") or data.get("messages")))
    location_intelligence = build_location_intelligence(
        data,
        payload=payload,
        comparables=comparables,
        warnings=warnings,
        is_demo=is_demo,
    )

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
        warnings=warnings,
        warning_summary=summarize_valuation_warnings(warnings),
        location_intelligence=location_intelligence,
        errors=tuple(_text_list(data.get("errors") or data.get("error"))),
        payload=dict(payload or {}),
        raw=dict(response),
    )


def map_tasar_error(error: ApiError) -> dict[str, Any]:
    return {"message": error.message, "status_code": error.status_code, "payload": error.payload}


LOCATION_WARNING_CODES = {
    "poor_geocoding_comparables",
    "weak_geolocation",
    "weak_microzone",
    "weak_geocode_quality",
    "low_geocode_precision",
    "surface_adjustment_risk_comuna",
    "surface_adjustment_unavailable",
    "price_surface_low_confidence",
}


def build_location_intelligence(
    data: dict[str, Any],
    *,
    payload: dict[str, Any] | None,
    comparables: tuple[TasarComparableViewModel, ...],
    warnings: tuple[str, ...],
    is_demo: bool,
) -> TasarLocationIntelligence:
    """Build an honest location panel contract from fields already in the valuation response."""
    if is_demo:
        return TasarLocationIntelligence(
            status="not_available",
            comuna=None,
            address_label=None,
            coordinates=None,
            geocoding_precision=None,
            microzone_status="not_available",
            comparable_count=None,
            comparable_location_quality=None,
            geo_signals=(),
            location_warnings=(),
            summary="Inteligencia local no disponible para tasaciones demo/lab.",
            reasons=("demo_data_not_used_as_real_location_intelligence",),
        )

    source_payload = payload or {}
    comparable_count = _pick_int(data, "comparable_count", "comparables_used", "n_comparables")
    if comparable_count is None and comparables:
        comparable_count = len(comparables)
    metrics = _mapping_value(data.get("comparable_quality_metrics"))
    beta_metrics = _mapping_value(data.get("beta_scope_metrics"))
    geo_signals = _geo_signals(data, source_payload)
    location_warnings = tuple(
        detail for detail in map_valuation_warnings(warnings)
        if detail.code in LOCATION_WARNING_CODES or detail.category in {"geocoding", "location"}
    )
    geocoding_precision = _optional_text(
        _pick(data, "geocoding_precision", "geocode_precision", "location_precision")
    )
    coordinates = _coordinates(data, source_payload)
    microzone_status = _microzone_status(data, metrics, beta_metrics, warnings)
    comparable_location_quality = _comparable_location_quality(data, metrics, beta_metrics, warnings)
    comuna = _optional_text(_pick(data, "comuna", "commune") or source_payload.get("comuna"))
    address_label = _optional_text(
        _pick(data, "address_label", "location_query", "address", "direccion")
        or source_payload.get("address_label")
        or source_payload.get("location_query")
    )

    evidence = [
        bool(comuna),
        bool(geocoding_precision),
        coordinates is not None,
        microzone_status != "not_available",
        comparable_count is not None and comparable_count > 0,
        bool(comparable_location_quality),
        bool(geo_signals),
        bool(location_warnings),
    ]
    evidence_count = sum(1 for item in evidence if item)
    has_explicit_location_signal = bool(geocoding_precision) or coordinates is not None or bool(geo_signals)
    if evidence_count >= 3 and has_explicit_location_signal:
        status = "available"
    elif evidence_count > 0:
        status = "partial"
    else:
        status = "not_available"

    reasons = _location_reasons(
        geocoding_precision=geocoding_precision,
        coordinates=coordinates,
        microzone_status=microzone_status,
        geo_signals=geo_signals,
        comparable_count=comparable_count,
        status=status,
    )
    return TasarLocationIntelligence(
        status=status,
        comuna=comuna,
        address_label=address_label,
        coordinates=coordinates,
        geocoding_precision=geocoding_precision,
        microzone_status=microzone_status,
        comparable_count=comparable_count,
        comparable_location_quality=comparable_location_quality,
        geo_signals=geo_signals,
        location_warnings=location_warnings,
        summary=_location_summary(status, comuna, comparable_count, microzone_status),
        reasons=reasons,
    )


def _risk_report_required_data(
    view_model: TasarValuationViewModel,
    payload: dict[str, Any],
) -> list[str]:
    missing: list[str] = []
    if view_model.estimated_value_uf is None and view_model.estimated_value_clp is None:
        missing.append("valuation_result")
    comparable_count = view_model.comparable_count if view_model.comparable_count is not None else len(view_model.comparables)
    if comparable_count <= 0 and not view_model.comparables:
        missing.append("comparables")
    if not str(payload.get("comuna") or "").strip():
        missing.append("risk_inputs")
    if _to_float(payload.get("built_area_m2") or payload.get("m2")) is None:
        missing.append("risk_inputs")
    return list(dict.fromkeys(missing))


def _risk_report_status(status: str, required_data: tuple[str, ...]) -> TasarRiskReportContract:
    return TasarRiskReportContract(
        risk_report_available=False,
        risk_report_status=status,
        risk_report_html=None,
        investment_report_html=None,
        listing_report_html=None,
        investment_file_name=None,
        listing_file_name=None,
        required_data=required_data,
        generated_at=None,
        source="ui.components.risk_report_html",
    )


def _geo_signals(data: dict[str, Any], payload: dict[str, Any]) -> tuple[str, ...]:
    values: list[Any] = []
    for source in (data, payload):
        raw = source.get("geo_signals")
        if isinstance(raw, dict):
            values.extend(_geo_signal_values(raw))
        else:
            values.extend(_list_value(raw))
        microzone = source.get("microzone") or source.get("microzone_id") or source.get("microzone_token")
        if microzone:
            values.append(microzone)
    surface = data.get("price_surface_context") or data.get("surface")
    if isinstance(surface, dict):
        values.extend(_geo_signal_values(surface.get("geo_signals")))
        values.extend(_list_value(surface.get("microzone_token")))
    return _dedupe_strings(values)


def _geo_signal_values(raw: Any) -> list[Any]:
    if not isinstance(raw, dict):
        return _list_value(raw)
    values: list[Any] = []
    for key, value in raw.items():
        if isinstance(value, bool):
            if value:
                values.append(key)
            continue
        if isinstance(value, list | tuple | set):
            values.extend(value)
            continue
        if value not in {None, "", 0}:
            values.append(value)
    return values


def _coordinates(data: dict[str, Any], payload: dict[str, Any]) -> tuple[float, float] | None:
    lat = _pick_float(data, "lat", "latitude") or _pick_float(payload, "lat", "latitude")
    lon = _pick_float(data, "lon", "lng", "longitude") or _pick_float(payload, "lon", "lng", "longitude")
    if lat is None or lon is None:
        return None
    return (lat, lon)


def _microzone_status(
    data: dict[str, Any],
    metrics: dict[str, Any],
    beta_metrics: dict[str, Any],
    warnings: tuple[str, ...],
) -> str:
    explicit = _optional_text(_pick(data, "microzone_status", "microzone_quality"))
    if explicit:
        return explicit
    if _pick(data, "microzone", "microzone_id", "microzone_token"):
        return "available"
    same_microzone_ratio = _to_float(
        _first_present(metrics, "same_microzone_ratio") or _first_present(beta_metrics, "same_microzone_ratio")
    )
    if "weak_microzone" in warnings:
        return "limited"
    if same_microzone_ratio is not None:
        return "available" if same_microzone_ratio >= 0.5 else "limited"
    return "not_available"


def _comparable_location_quality(
    data: dict[str, Any],
    metrics: dict[str, Any],
    beta_metrics: dict[str, Any],
    warnings: tuple[str, ...],
) -> str | None:
    explicit = _optional_text(_pick(data, "comparable_location_quality", "location_quality"))
    if explicit:
        return explicit
    address_ratio = _to_float(
        _first_present(metrics, "address_level_geo_ratio") or _first_present(beta_metrics, "address_level_geo_ratio")
    )
    if address_ratio is not None:
        if address_ratio >= 0.7 and not {"poor_geocoding_comparables", "weak_geolocation"} & set(warnings):
            return "alta"
        if address_ratio >= 0.35:
            return "media"
        return "baja"
    quality_level = _optional_text(data.get("comparable_quality_level"))
    if quality_level in {"strong", "acceptable"}:
        return "media"
    if quality_level in {"weak", "poor"}:
        return "baja"
    return None


def _location_reasons(
    *,
    geocoding_precision: str | None,
    coordinates: tuple[float, float] | None,
    microzone_status: str,
    geo_signals: tuple[str, ...],
    comparable_count: int | None,
    status: str,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not geocoding_precision and coordinates is None:
        reasons.append("no_geocoding_data")
    if microzone_status == "not_available":
        reasons.append("no_microzone_data")
    if not geo_signals:
        reasons.append("no_geo_signals")
    if comparable_count is None or comparable_count <= 0:
        reasons.append("insufficient_location_coverage")
    if status == "not_available" and not reasons:
        reasons.append("no_location_data")
    return tuple(reasons)


def _location_summary(status: str, comuna: str | None, comparable_count: int | None, microzone_status: str) -> str:
    comuna_label = comuna or "comuna no informada"
    if status == "available":
        return f"Ubicacion disponible para {comuna_label} con {comparable_count or 0} comparables."
    if status == "partial":
        if microzone_status == "limited":
            return f"Ubicacion parcialmente disponible para {comuna_label}; microzona limitada."
        return f"Ubicacion parcialmente disponible para {comuna_label}."
    return "Inteligencia local no disponible para esta tasacion."


def _report_generated_at(report_data: dict[str, Any]) -> str:
    header = report_data.get("header") if isinstance(report_data.get("header"), dict) else {}
    generated_at = header.get("generated_at")
    if generated_at:
        return str(generated_at)
    return datetime.now(UTC).isoformat()


def _has_listing_context(payload: dict[str, Any], lookup_result: dict[str, Any]) -> bool:
    listing_data = lookup_result.get("listing_data") if isinstance(lookup_result.get("listing_data"), dict) else {}
    markers = (
        payload.get("url"),
        payload.get("source"),
        payload.get("listing_id"),
        lookup_result.get("url"),
        lookup_result.get("source"),
        lookup_result.get("listing_id"),
        listing_data.get("url"),
        listing_data.get("source"),
        listing_data.get("listing_id"),
    )
    return any(value not in {None, "", 0} for value in markers)


def _report_file_name(prefix: str, report_data: dict[str, Any] | None) -> str:
    header = (report_data or {}).get("header") if isinstance((report_data or {}).get("header"), dict) else {}
    comuna = _slug(str(header.get("headline") or "propiedad"))
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return f"{prefix}_{comuna}_{stamp}.html"


def _slug(value: str) -> str:
    text = "".join(ch.lower() if ch.isalnum() else "_" for ch in value.strip())
    return "_".join(part for part in text.split("_") if part) or "propiedad"


def _mapping_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first_present(source: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = source.get(key)
        if value is not None and value != "":
            return value
    return None


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


def _dedupe_strings(values: list[Any]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        result.append(text)
        seen.add(text)
    return tuple(result)
