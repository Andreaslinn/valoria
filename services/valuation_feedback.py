"""Simple local JSONL feedback loop for private beta valuations."""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.assessment.confidence import confidence_label_for_score

FEEDBACK_DIR_ENV = "VALUATION_FEEDBACK_DIR"
DEFAULT_FEEDBACK_DIR = Path("reports/valuation_feedback")
ALLOWED_FEEDBACK = frozenset({"reasonable", "too_high", "too_low", "unsure"})


def build_valuation_feedback_record(
    *,
    valuation_result: dict[str, Any],
    valuation_payload: dict[str, Any],
    feedback: str,
    comment: str | None = None,
    occurred_at: datetime | None = None,
) -> dict[str, Any]:
    feedback_code = _clean_feedback(feedback)
    if feedback_code not in ALLOWED_FEEDBACK:
        raise ValueError(f"Unsupported valuation feedback: {feedback}")

    return {
        "timestamp": (occurred_at or datetime.now(UTC)).isoformat(),
        "comuna": _safe_text(valuation_payload.get("comuna")),
        "property_type": _safe_text(valuation_payload.get("property_type")),
        "m2": _safe_number(
            valuation_payload.get("built_area_m2")
            or valuation_payload.get("usable_area_m2")
            or valuation_payload.get("m2")
        ),
        "estimated_value_clp": _safe_number(valuation_result.get("estimated_price_clp")),
        "estimated_value_uf": _safe_number(valuation_result.get("estimated_price_uf")),
        "confidence": _confidence_label_text(valuation_result),
        "confidence_score": _safe_number(valuation_result.get("confidence_score") or _numeric_confidence(valuation_result.get("confidence"))),
        "confidence_label": _confidence_label_text(valuation_result),
        "comparable_quality_level": _safe_text(valuation_result.get("comparable_quality_level")),
        "beta_scope_status": _safe_text(valuation_result.get("beta_scope_status")),
        "comparable_count": _safe_number(valuation_result.get("comparable_count")),
        "feedback": feedback_code,
        "comment": _safe_comment(comment),
    }


def record_valuation_feedback(
    record: dict[str, Any],
    *,
    output_dir: Path | None = None,
) -> Path:
    feedback = _clean_feedback(record.get("feedback"))
    if feedback not in ALLOWED_FEEDBACK:
        raise ValueError(f"Unsupported valuation feedback: {record.get('feedback')}")
    path = _feedback_path(output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = _json_safe_record(record)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(clean, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def submit_valuation_feedback(
    *,
    valuation_result: dict[str, Any],
    valuation_payload: dict[str, Any],
    feedback: str,
    comment: str | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    record = build_valuation_feedback_record(
        valuation_result=valuation_result,
        valuation_payload=valuation_payload,
        feedback=feedback,
        comment=comment,
    )
    path = record_valuation_feedback(record, output_dir=output_dir)
    return {"record": record, "path": str(path)}


def _feedback_path(output_dir: Path | None) -> Path:
    base = output_dir or Path(os.getenv(FEEDBACK_DIR_ENV, str(DEFAULT_FEEDBACK_DIR)))
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return base / f"valuation_feedback_{stamp}.jsonl"


def _json_safe_record(record: dict[str, Any]) -> dict[str, Any]:
    return {str(key): _json_safe_value(value) for key, value in record.items()}


def _json_safe_value(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    return str(value)


def _clean_feedback(value: Any) -> str:
    return str(value or "").strip().lower()


def _safe_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:120] if text else None


def _safe_comment(value: str | None) -> str | None:
    text = str(value or "").strip()
    return text[:1000] if text else None


def _safe_number(value: Any) -> float | int | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number.is_integer():
        return int(number)
    return round(number, 4)


def _numeric_confidence(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if 0 <= number <= 1 else None


def _confidence_label_text(valuation_result: dict[str, Any]) -> str | None:
    explicit = _safe_text(valuation_result.get("confidence_label"))
    if explicit:
        return explicit
    numeric = _numeric_confidence(valuation_result.get("confidence"))
    if numeric is not None:
        return confidence_label_for_score(numeric)
    return _safe_text(valuation_result.get("confidence"))
