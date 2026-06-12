"""Canonical comparable engine with product and robust price/m2 filters."""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from decimal import Decimal
from statistics import pstdev
from typing import Any

from config.constants import LEGACY_UF_ARTIFACT_RATE, MIN_COMPARABLES, TOP_N_COMPARABLES
from core.assessment.beta_status import beta_scope_warning_codes
from core.assessment.confidence import build_confidence_contract
from core.entities.listing import Listing, Property
from core.exceptions import InsufficientDataError, ValidationError
from core.normalization.property_type import normalize_property_type
from core.value_objects.price import Price
from core.value_objects.score import Score
from domain.valuation.beta_scope import assess_beta_scope
from domain.valuation.canonical_price import ValuationPriceBasis, valuation_price_basis
from domain.valuation.comparable_quality import assess_comparable_quality
from domain.valuation.comparables import candidate_discard_reason, score_and_rank
from domain.valuation.engines.contracts import EngineComparable, EngineContext, EngineRequest, EngineResult, EngineStatus
from domain.valuation.price_surface import lookup_price_surface, maybe_apply_surface_adjustment, surface_warnings_for_estimate
from domain.valuation.product_classification import PRODUCT_UNKNOWN, ProductEvidence, classify_product, product_compatibility
from domain.valuation.reliability import assess_comparable_reliability
from domain.valuation.robust_price_m2 import RobustFilterConfig, robust_filter_listings
from services.formatting import price_clp_int


@dataclass(frozen=True)
class CanonicalComparableConfig:
    variant: str = "full"
    enable_product_filter: bool = True
    enable_robust_filter: bool = True
    min_comparables: int = MIN_COMPARABLES
    top_n: int = TOP_N_COMPARABLES
    robust_filter: RobustFilterConfig = RobustFilterConfig()

    @classmethod
    def for_variant(cls, variant: str) -> "CanonicalComparableConfig":
        if variant == "price_only":
            return cls(variant=variant, enable_product_filter=False, enable_robust_filter=False)
        if variant == "product":
            return cls(variant=variant, enable_product_filter=True, enable_robust_filter=False)
        if variant == "outliers":
            return cls(variant=variant, enable_product_filter=False, enable_robust_filter=True)
        if variant == "full":
            return cls(variant=variant, enable_product_filter=True, enable_robust_filter=True)
        raise ValueError(f"unknown canonical variant: {variant}")


class ComparablesCanonicalEngine:
    name = "comparables_canonical"
    version = "phase1_canonical_v1"

    def __init__(self, *, name: str | None = None, variant: str = "full") -> None:
        self.name = name or self.name
        self.config = CanonicalComparableConfig.for_variant(variant)

    def valuate(self, request: EngineRequest, context: EngineContext) -> EngineResult:
        try:
            return self._valuate(request, context)
        except InsufficientDataError as exc:
            return _failed(self.name, self.version, EngineStatus.INSUFFICIENT_DATA, "insufficient_data", str(exc))
        except ValidationError as exc:
            return _failed(self.name, self.version, EngineStatus.VALIDATION_ERROR, "validation_error", str(exc))
        except Exception as exc:  # pragma: no cover - defensive engine boundary
            return _failed(self.name, self.version, EngineStatus.ERROR, "unexpected_error", str(exc))

    def _valuate(self, request: EngineRequest, context: EngineContext) -> EngineResult:
        target = context.target
        if not isinstance(target, Property):
            raise ValidationError("comparables_canonical requires EngineContext.target as Property")
        uf_to_clp = _validated_uf_rate(context.uf_to_clp)
        _validate_target(target)

        diagnostics = _Diagnostics()
        candidates = list(context.candidates)
        diagnostics.pool["candidates_loaded"] = len(candidates)
        target_product = classify_product(target)
        diagnostics.product["target_product_class"] = target_product.product_class
        diagnostics.product["target_evidence"] = target_product.to_dict()
        if target_product.product_class == PRODUCT_UNKNOWN:
            diagnostics.warnings.append("target_product_class_unknown")

        structural = self._structural_pool(target, candidates, diagnostics)
        if len(structural) < self.config.min_comparables:
            raise InsufficientDataError(f"Solo {len(structural)} comparables estructurales elegibles; se requieren al menos {self.config.min_comparables}.")

        canonical = self._canonical_price_pool(structural, uf_to_clp, diagnostics)
        if len(canonical) < self.config.min_comparables:
            raise InsufficientDataError(f"Solo {len(canonical)} comparables con precio canonico usable; se requieren al menos {self.config.min_comparables}.")

        estimate_before_product = _safe_estimate(target, score_and_rank(target, [item[0] for item in canonical]))
        product_filtered = self._product_pool(target_product, canonical, diagnostics)
        if len(product_filtered) < self.config.min_comparables:
            raise InsufficientDataError(f"Solo {len(product_filtered)} comparables compatibles por producto; se requieren al menos {self.config.min_comparables}.")
        estimate_after_product = _safe_estimate(target, score_and_rank(target, [item[0] for item in product_filtered]))

        robust_input = [item[0] for item in product_filtered]
        diagnostics.pool["robust_filter_input"] = len(robust_input)
        estimate_before_robust = _safe_estimate(target, score_and_rank(target, robust_input))
        final_pool = self._robust_pool(target, robust_input, diagnostics)
        diagnostics.pool["robust_filter_output"] = len(final_pool)
        if len(final_pool) < self.config.min_comparables:
            raise InsufficientDataError(f"Solo {len(final_pool)} comparables tras filtro robusto; se requieren al menos {self.config.min_comparables}.")

        scored = score_and_rank(target, final_pool)[: self.config.top_n]
        if len(scored) < self.config.min_comparables:
            raise InsufficientDataError(f"Solo {len(scored)} comparables finales; se requieren al menos {self.config.min_comparables}.")
        diagnostics.exclusions["top_n_cutoff"] += max(0, len(final_pool) - len(scored))
        diagnostics.pool["selected_comparables"] = len(scored)

        estimate_before_surface = _weighted_total(target, scored)
        estimated_clp, low_clp, high_clp, confidence, warnings, extra = self._post_process(
            target=target,
            candidates=final_pool,
            scored=scored,
            estimate=estimate_before_surface,
            uf_to_clp=uf_to_clp,
            request=request,
            diagnostics=diagnostics,
        )
        diagnostics.result.update(
            {
                "estimate_before_product_filter": _decimal_float(estimate_before_product),
                "estimate_after_product_filter": _decimal_float(estimate_after_product),
                "estimate_before_robust_filter": _decimal_float(estimate_before_robust),
                "estimate_after_robust_filter": _decimal_float(estimate_before_surface),
                "estimate_after_surface_adjustment": estimated_clp,
                "comparable_weights": _comparable_weights(scored),
                "price_basis_by_comparable": diagnostics.price_basis_by_comparable,
            }
        )
        diagnostics.result.update(extra)

        selected = tuple(
            EngineComparable(
                listing_id=listing.id,
                fingerprint=listing.fingerprint,
                score=round(score.value, 4),
                diagnostics={
                    "source": listing.source,
                    "comuna": listing.comuna,
                    "property_type": normalize_property_type(listing),
                    "canonical_price_clp": float(listing.price.clp),
                    "product_class": diagnostics.product_classes.get(_candidate_key(listing), {}).get("product_class"),
                    "price_basis": diagnostics.price_basis_by_comparable.get(_candidate_key(listing)),
                },
            )
            for score, listing in scored
        )
        return EngineResult(
            engine_name=self.name,
            engine_version=self.version,
            status=EngineStatus.OK,
            estimated_price_clp=estimated_clp,
            estimated_price_uf=_clp_to_uf(estimated_clp, uf_to_clp),
            range_low_clp=low_clp,
            range_high_clp=high_clp,
            confidence=confidence,
            comparables_used=len(scored),
            warnings=tuple(_dedupe(warnings + diagnostics.warnings)),
            diagnostics=diagnostics.to_dict(config=self.config, selected=selected),
            selected_comparables=selected,
            coverage_status=str(extra.get("comparable_quality_level") or ""),
        )

    def _structural_pool(self, target: Property, candidates: Sequence[Listing], diagnostics: "_Diagnostics") -> list[Listing]:
        eligible: list[Listing] = []
        seen: set[str] = set()
        for candidate in candidates:
            key = _dedupe_key(candidate)
            if key in seen:
                diagnostics.add_exclusion("duplicate", candidate)
                continue
            seen.add(key)
            reason = candidate_discard_reason(target, candidate)
            if reason is not None:
                diagnostics.add_exclusion(_canonical_reason(reason, target, candidate), candidate)
                continue
            eligible.append(candidate)
        diagnostics.pool["candidates_structurally_eligible"] = len(eligible)
        return eligible

    def _canonical_price_pool(self, candidates: Sequence[Listing], uf_to_clp: Decimal, diagnostics: "_Diagnostics") -> list[tuple[Listing, ValuationPriceBasis]]:
        result: list[tuple[Listing, ValuationPriceBasis]] = []
        for candidate in candidates:
            basis = valuation_price_basis(candidate, uf_to_clp)
            exclusion = _strict_price_exclusion(candidate, basis, uf_to_clp)
            diagnostics.price_basis_by_comparable[_candidate_key(candidate)] = _basis_payload(candidate, basis, exclusion)
            if exclusion is not None:
                diagnostics.add_exclusion(exclusion, candidate)
                continue
            canonical_clp = (basis.amount_uf * uf_to_clp).quantize(Decimal("1")) if basis.amount_uf is not None else None
            if canonical_clp is None or canonical_clp <= 0:
                diagnostics.add_exclusion("invalid_price", candidate)
                continue
            result.append((replace(candidate, price=Price(clp=canonical_clp)), basis))
        diagnostics.pool["canonical_price_usable"] = len(result)
        return result

    def _product_pool(self, target_product: ProductEvidence, candidates: list[tuple[Listing, ValuationPriceBasis]], diagnostics: "_Diagnostics") -> list[tuple[Listing, ValuationPriceBasis]]:
        if not self.config.enable_product_filter:
            for listing, _ in candidates:
                evidence = classify_product(listing)
                diagnostics.product_classes[_candidate_key(listing)] = evidence.to_dict()
            diagnostics.pool["product_compatible"] = len(candidates)
            return candidates

        kept: list[tuple[Listing, ValuationPriceBasis]] = []
        fallbacks = 0
        for listing, basis in candidates:
            evidence = classify_product(listing)
            diagnostics.product_classes[_candidate_key(listing)] = evidence.to_dict()
            compatibility = product_compatibility(target_product, evidence)
            if not compatibility.compatible:
                diagnostics.add_exclusion("product_incompatible", listing)
                diagnostics.product_exclusions.append(
                    {
                        "candidate": _candidate_key(listing),
                        "candidate_product_class": evidence.product_class,
                        "reason": compatibility.reason,
                    }
                )
                continue
            if compatibility.fallback_used:
                fallbacks += 1
            kept.append((listing, basis))
        diagnostics.pool["product_compatible"] = len(kept)
        if fallbacks:
            diagnostics.product["fallbacks"] = {"unknown_candidates_used": fallbacks}
            diagnostics.warnings.append("product_class_fallback_used")
        return kept

    def _robust_pool(self, target: Property, candidates: list[Listing], diagnostics: "_Diagnostics") -> list[Listing]:
        if not self.config.enable_robust_filter:
            diagnostics.local_reference = {"method": "disabled", "local_sample_count": len(candidates)}
            return candidates
        product_classes = {_candidate_key(listing): classify_product(listing) for listing in candidates}
        result = robust_filter_listings(
            target=target,
            listings=candidates,
            product_classes=product_classes,
            min_comparables=self.config.min_comparables,
            config=self.config.robust_filter,
        )
        diagnostics.local_reference = result.reference.to_dict()
        for listing in result.low_outliers:
            diagnostics.add_exclusion("price_m2_low_outlier", listing)
        for listing in result.high_outliers:
            diagnostics.add_exclusion("price_m2_high_outlier", listing)
        if result.recovered:
            diagnostics.result["comparables_recovered_by_fallback"] = [_candidate_key(item) for item in result.recovered]
            diagnostics.warnings.append("robust_filter_relaxed")
        return list(result.kept)

    def _post_process(
        self,
        *,
        target: Property,
        candidates: Sequence[Listing],
        scored: Sequence[tuple[Score, Listing]],
        estimate: Decimal,
        uf_to_clp: Decimal,
        request: EngineRequest,
        diagnostics: "_Diagnostics",
    ) -> tuple[int, int, int, float, list[str], dict[str, Any]]:
        range_delta = _range_delta(target, scored)
        low = max(Decimal("0"), estimate - range_delta)
        high = estimate + range_delta
        base_confidence = _confidence(scored, target)
        reliability = assess_comparable_reliability(target=target, scored_comparables=scored, base_confidence=base_confidence)
        comparable_quality = assess_comparable_quality(target=target, scored_comparables=scored)
        beta_scope = assess_beta_scope(target=target, candidate_pool=candidates, comparable_quality=comparable_quality)

        base_estimated_clp = price_clp_int(Price(clp=estimate))
        built_area = _built_area(target)
        estimated_price_m2_clp = base_estimated_clp / built_area if built_area else None
        surface = lookup_price_surface(target, list(candidates))
        warnings: list[str] = []
        warnings.extend(reliability.warnings)
        warnings.extend(comparable_quality.risk_flags)
        warnings.extend(beta_scope_warning_codes(beta_scope.status))
        warnings.extend(
            warning
            for warning in surface_warnings_for_estimate(estimated_price_m2=estimated_price_m2_clp, surface=surface)
            if warning != "price_surface_insufficient_data"
        )
        adjustment = maybe_apply_surface_adjustment(base_estimated_clp, surface, target)
        warnings.extend(adjustment.warnings)
        if len(scored) < 8:
            warnings.append("low_data_mode")
        if not request.published_price_provided:
            warnings.append("published_price_not_provided")
        confidence_contract = build_confidence_contract(
            score=_penalized_confidence(reliability.confidence.value, diagnostics=diagnostics, target=target, selected_count=len(scored)),
            base_score=base_confidence,
            reliability_warnings=reliability.warnings,
        )
        adjusted_clp = int(round(adjustment.adjusted_estimate))
        delta_clp = adjusted_clp - base_estimated_clp
        low_clp = max(0, price_clp_int(Price(clp=low)) + delta_clp)
        high_clp = max(low_clp, price_clp_int(Price(clp=high)) + delta_clp)
        extra = {
            "base_estimated_price_clp": base_estimated_clp,
            "base_estimated_price_uf": _clp_to_uf(base_estimated_clp, uf_to_clp),
            "base_confidence": base_confidence.value,
            "confidence_label": confidence_contract.confidence_label,
            "confidence_reasons": list(confidence_contract.confidence_reasons),
            "confidence_risk_flags": list(confidence_contract.confidence_risk_flags),
            "reliability_warnings": list(reliability.warnings),
            "reliability_metrics": dict(reliability.metrics),
            "comparable_quality_level": comparable_quality.level,
            "comparable_quality_flags": list(comparable_quality.risk_flags),
            "comparable_quality_metrics": dict(comparable_quality.metrics),
            "beta_scope_status": beta_scope.status,
            "beta_scope_flags": list(beta_scope.flags),
            "beta_scope_metrics": dict(beta_scope.metrics),
            "beta_scope_message": beta_scope.message,
            "surface_adjustment": {
                "applied": adjustment.adjustment_applied,
                "weight": adjustment.adjustment_weight,
                "reason": adjustment.adjustment_reason,
                "warnings": list(adjustment.warnings),
            },
            "surface": {
                "available": surface.available,
                "level_used": surface.level_used,
                "microzone_token": surface.microzone_token,
                "reason": surface.reason,
                "stats": asdict(surface.stats) if surface.stats else None,
            },
        }
        return adjusted_clp, low_clp, high_clp, confidence_contract.confidence_score, warnings, extra


class _Diagnostics:
    def __init__(self) -> None:
        self.pool: dict[str, Any] = {}
        self.exclusions: Counter[str] = Counter()
        self.exclusion_ids: dict[str, list[str]] = defaultdict(list)
        self.price_basis_by_comparable: dict[str, Any] = {}
        self.product: dict[str, Any] = {}
        self.product_classes: dict[str, dict[str, Any]] = {}
        self.product_exclusions: list[dict[str, Any]] = []
        self.local_reference: dict[str, Any] = {}
        self.result: dict[str, Any] = {}
        self.warnings: list[str] = []

    def add_exclusion(self, reason: str, listing: Listing) -> None:
        self.exclusions[reason] += 1
        bucket = self.exclusion_ids[reason]
        if len(bucket) < 50:
            bucket.append(_candidate_key(listing))

    def to_dict(self, *, config: CanonicalComparableConfig, selected: Sequence[EngineComparable]) -> dict[str, Any]:
        return {
            "engine_config": {
                "version": ComparablesCanonicalEngine.version,
                "variant": config.variant,
                "enable_product_filter": config.enable_product_filter,
                "enable_robust_filter": config.enable_robust_filter,
                "min_comparables": config.min_comparables,
                "top_n": config.top_n,
                "robust_filter": asdict(config.robust_filter),
            },
            "pool": dict(self.pool),
            "exclusions": dict(sorted(self.exclusions.items())),
            "exclusion_ids": dict(self.exclusion_ids),
            "local_reference": dict(self.local_reference),
            "product": {
                **self.product,
                "candidate_product_class": self.product_classes,
                "candidates_excluded_by_class": self.product_exclusions,
            },
            "result": dict(self.result),
            "selected_comparable_fingerprints": [item.fingerprint for item in selected],
        }


def _validated_uf_rate(value: Decimal | int | float | str | None) -> Decimal:
    if value is None:
        raise ValidationError("comparables_canonical requires a real positive UF rate")
    parsed = Decimal(str(value))
    if parsed <= 0:
        raise ValidationError("comparables_canonical requires a real positive UF rate")
    if parsed == LEGACY_UF_ARTIFACT_RATE:
        raise ValidationError("comparables_canonical refuses legacy UF artifact rate 37000")
    return parsed


def _validate_target(target: Property) -> None:
    if not target.comuna:
        raise ValidationError("target.comuna no puede ser vacio")
    built = _built_area(target)
    if built is None or built <= 0:
        raise ValidationError(f"target built area must be positive, received {built}")


def _built_area(value: Property | Listing) -> float | None:
    return getattr(value, "built_area_m2", None) or getattr(value, "usable_area_m2", None) or value.m2


def _weighted_total(target: Property, scored: Sequence[tuple[Score, Listing]]) -> Decimal:
    area = _built_area(target)
    if area is None or area <= 0:
        raise ValidationError("target built area must be positive")
    return _weighted_mean_ppm2(scored) * Decimal(str(area))


def _safe_estimate(target: Property, scored: Sequence[tuple[Score, Listing]]) -> float | None:
    try:
        return _decimal_float(_weighted_total(target, scored[:TOP_N_COMPARABLES]))
    except Exception:
        return None


def _weighted_mean_ppm2(scored: Sequence[tuple[Score, Listing]]) -> Decimal:
    total_weight = Decimal("0")
    weighted_sum = Decimal("0")
    for score, listing in scored:
        area = _built_area(listing)
        if area is None or area <= 0:
            continue
        weight = Decimal(str(score.value))
        weighted_sum += weight * (listing.price.clp / Decimal(str(area)))
        total_weight += weight
    if total_weight == 0:
        raise InsufficientDataError("Pesos de comparables suman 0")
    return weighted_sum / total_weight


def _range_delta(target: Property, scored: Sequence[tuple[Score, Listing]]) -> Decimal:
    area = _built_area(target)
    if area is None or area <= 0:
        return Decimal("0")
    values = [
        float(listing.price.clp / Decimal(str(candidate_area)))
        for _, listing in scored
        if (candidate_area := _built_area(listing)) is not None and candidate_area > 0
    ]
    if len(values) < 2:
        return Decimal("0")
    return Decimal(str(pstdev(values))) * Decimal(str(area))


def _confidence(scored: Sequence[tuple[Score, Listing]], target: Property) -> Score:
    n = len(scored)
    avg_score = sum(score.value for score, _ in scored) / n
    n_factor = min(1.0, n / 15.0)
    confidence = 0.7 * avg_score + 0.3 * n_factor
    if normalize_property_type(target) == "unknown":
        confidence *= 0.65
    if normalize_property_type(target) == "house":
        with_land = sum(1 for _, listing in scored if listing.land_area_m2 is not None)
        confidence *= 0.75 + 0.25 * (with_land / n)
    return Score.clamped(confidence)


def _penalized_confidence(value: float, *, diagnostics: _Diagnostics, target: Property, selected_count: int) -> Score:
    factor = 1.0
    if selected_count < 8:
        factor *= 0.90
    if diagnostics.local_reference.get("method") in {"sample_too_small", "disabled"}:
        factor *= 0.92
    if diagnostics.product.get("target_product_class") == PRODUCT_UNKNOWN:
        factor *= 0.90
    if str(getattr(target, "geocode_precision", "") or "unknown").lower() not in {"address", "street"}:
        factor *= 0.92
    excluded = sum(diagnostics.exclusions.values())
    loaded = diagnostics.pool.get("candidates_loaded") or 0
    if loaded and excluded / loaded > 0.5:
        factor *= 0.93
    return Score.clamped(max(0.0, min(1.0, value * factor)))


def _strict_price_exclusion(listing: Listing, basis: ValuationPriceBasis, uf_to_clp: Decimal) -> str | None:
    source = str(listing.price_uf_source or "").strip().lower()
    method = str(listing.price_recovery_method or "").strip().lower()
    confidence = str(listing.price_uf_confidence or "").strip().lower()
    metadata = listing.raw_metadata if isinstance(listing.raw_metadata, dict) else {}
    provenance = {
        source,
        method,
        confidence,
        str(metadata.get("price_uf_source") or "").strip().lower(),
        str(metadata.get("price_recovery_method") or "").strip().lower(),
        str(metadata.get("price_conversion_source") or "").strip().lower(),
    }
    if "legacy_unrecoverable" in provenance:
        return "legacy_unrecoverable"
    if provenance & {"artifact", "legacy_artifact", "uf_artifact"}:
        return "artifact"
    if basis.exclusion_reason in {"estimated_uf_not_strong", "low_confidence_uf_not_strong"}:
        return "low_confidence_estimated"
    if basis.exclusion_reason == "uf_fallback_not_canonical":
        return "artifact"
    if not basis.is_usable_for_valuation or basis.amount_uf is None:
        return _price_exclusion_bucket(basis.exclusion_reason or basis.quality)
    if listing.price_uf and listing.price.clp > 0:
        ratio = Decimal(str(listing.price.clp)) / Decimal(str(listing.price_uf))
        if abs(ratio - LEGACY_UF_ARTIFACT_RATE) <= Decimal("1") and source not in {"scraped", "recovered_exact", "recovered_high_confidence"}:
            return "artifact"
    if uf_to_clp == LEGACY_UF_ARTIFACT_RATE:
        return "artifact"
    return None


def _price_exclusion_bucket(reason: str | None) -> str:
    if reason in {"legacy_uf_missing_price_uf", "legacy_unrecoverable"}:
        return "legacy_unrecoverable"
    if reason in {"estimated_uf_not_strong", "low_confidence_uf_not_strong"}:
        return "low_confidence_estimated"
    if reason in {"uf_fallback_not_canonical", "fallback_not_canonical"}:
        return "artifact"
    return "invalid_price"


def _canonical_reason(reason: str, target: Property, candidate: Listing) -> str:
    if reason == "area_out_of_range":
        if normalize_property_type(target) == "house" and target.land_area_m2 and candidate.land_area_m2:
            target_built = _built_area(target)
            candidate_built = _built_area(candidate)
            if target_built and candidate_built and abs(target_built - candidate_built) / target_built <= 0.30:
                return "land_outside_tolerance"
        return "area_outside_tolerance"
    if reason == "missing_price":
        return "invalid_price"
    if reason == "too_far":
        return "insufficient_geo"
    return reason


def _basis_payload(listing: Listing, basis: ValuationPriceBasis, exclusion: str | None) -> dict[str, Any]:
    return {
        "currency": listing.price_currency,
        "price_uf": float(listing.price_uf) if listing.price_uf is not None else None,
        "price_clp": float(listing.price.clp),
        "source": listing.price_uf_source,
        "confidence": listing.price_uf_confidence,
        "recovery_method": listing.price_recovery_method,
        "basis_used": basis.basis_used,
        "basis_price_unit": basis.price_unit,
        "basis_quality": basis.quality,
        "basis_amount_uf": float(basis.amount_uf) if basis.amount_uf is not None else None,
        "basis_amount_clp_display": float(basis.amount_clp_display) if basis.amount_clp_display is not None else None,
        "usable": exclusion is None,
        "exclusion_reason": exclusion,
    }


def _comparable_weights(scored: Sequence[tuple[Score, Listing]]) -> dict[str, float]:
    total = sum(score.value for score, _ in scored)
    if total <= 0:
        return {}
    return {_candidate_key(listing): round(score.value / total, 6) for score, listing in scored}


def _candidate_key(listing: Listing) -> str:
    if listing.id is not None:
        return f"id:{listing.id}"
    if listing.fingerprint:
        return f"fp:{listing.fingerprint}"
    if listing.source and listing.external_id:
        return f"ext:{listing.source}:{listing.external_id}"
    return f"obj:{id(listing)}"


def _dedupe_key(listing: Listing) -> str:
    if listing.fingerprint:
        return f"fp:{listing.fingerprint}"
    if listing.source and listing.external_id:
        return f"ext:{listing.source}:{listing.external_id}"
    if listing.url:
        return f"url:{listing.url}"
    return f"obj:{id(listing)}"


def _failed(engine_name: str, engine_version: str, status: str, code: str, message: str) -> EngineResult:
    return EngineResult(
        engine_name=engine_name,
        engine_version=engine_version,
        status=status,
        warnings=(code,),
        diagnostics={},
        error_code=code,
        error_message=message,
    )


def _clp_to_uf(value: int | float | Decimal, uf_to_clp: Decimal) -> float:
    return round(float(Decimal(str(value)) / uf_to_clp), 2)


def _decimal_float(value: Decimal | float | None) -> float | None:
    return float(value) if value is not None else None


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
