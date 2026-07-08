"""Privacy-conscious product usage instrumentation for the beta UI.

Events are written locally as JSON Lines. No third-party analytics, no raw
passwords, no free-text search terms, and no property addresses are stored.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Any
from uuid import uuid4

EVENTS_DIR_ENV = "PRODUCT_ANALYTICS_DIR"
ENABLED_ENV = "PRODUCT_ANALYTICS_ENABLED"
SALT_ENV = "PRODUCT_ANALYTICS_SALT"
DEFAULT_EVENTS_DIR = Path("reports/product_usage")

ALLOWED_EVENT_TYPES = {
    "session_started",
    "page_view",
    "valuation_submitted",
    "valuation_completed",
    "valuation_failed",
    "property_analysis_submitted",
    "property_analysis_completed",
    "property_analysis_failed",
    "radar_requested",
    "radar_completed",
    "radar_failed",
}

SAFE_PROPERTY_KEYS = {
    "page",
    "comuna",
    "property_type",
    "m2",
    "built_area_m2",
    "land_area_m2",
    "bedrooms",
    "bathrooms",
    "parking",
    "precio_publicado_uf",
    "precio_publicado_clp",
    "estimated_value_uf",
    "status",
    "error_status_code",
    "comparables_used",
    "confidence_score",
    "low_data_mode",
    "geocode_precision",
    "radar_limit",
    "radar_view",
    "radar_results_count",
    "radar_comunas_count",
}


@dataclass(frozen=True)
class UsageContext:
    session_id: str
    session_started_at: str
    session_started_monotonic: float
    user_hash: str | None = None
    beta_role: str | None = None


def is_enabled() -> bool:
    return os.getenv(ENABLED_ENV, "true").strip().lower() not in {"0", "false", "no", "off"}


def new_session_context(*, user_identifier: str | None = None, beta_role: str | None = None) -> UsageContext:
    return UsageContext(
        session_id=uuid4().hex,
        session_started_at=datetime.now(UTC).isoformat(),
        session_started_monotonic=monotonic(),
        user_hash=hash_identifier(user_identifier),
        beta_role=_clean_label(beta_role),
    )


def hash_identifier(value: str | None) -> str | None:
    text = (value or "").strip().lower()
    if not text:
        return None
    salt = os.getenv(SALT_ENV, "avm-v2-product-analytics")
    return hashlib.sha256(f"{salt}:{text}".encode()).hexdigest()[:16]


def track_event(
    event_type: str,
    *,
    context: UsageContext,
    properties: dict[str, Any] | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any] | None:
    if not is_enabled():
        return None
    if event_type not in ALLOWED_EVENT_TYPES:
        raise ValueError(f"Unsupported product usage event: {event_type}")

    event = {
        "event_type": event_type,
        "occurred_at": datetime.now(UTC).isoformat(),
        "session_id": context.session_id,
        "session_started_at": context.session_started_at,
        "session_duration_seconds": round(monotonic() - context.session_started_monotonic, 3),
        "user_hash": context.user_hash,
        "beta_role": context.beta_role,
        "properties": sanitize_properties(properties or {}),
    }
    path = _events_path(output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return event


def sanitize_properties(properties: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in properties.items():
        if key not in SAFE_PROPERTY_KEYS:
            continue
        clean[key] = _safe_value(value)
    return clean


def _events_path(output_dir: Path | None) -> Path:
    base = output_dir or Path(os.getenv(EVENTS_DIR_ENV, str(DEFAULT_EVENTS_DIR)))
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return base / f"product_usage_{stamp}.jsonl"


def _safe_value(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return _clean_label(value)
    return str(value)[:120]


def _clean_label(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip().lower()
    return text[:80] if text else None
