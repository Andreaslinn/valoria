"""Streamlit helpers for product usage metrics via FastAPI."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import Any
from uuid import uuid4

import streamlit as st

from ui.api_client import ApiClient
from ui.state import get_api_base_url, get_token

_log = logging.getLogger(__name__)

ENABLED_ENV = "PRODUCT_ANALYTICS_ENABLED"
CONTEXT_KEY = "product_usage_context"
LAST_PAGE_KEY = "product_usage_last_page"
SESSION_STARTED_KEY = "product_usage_session_started"


@dataclass(frozen=True)
class UsageContext:
    session_id: str
    session_started_at: str
    session_started_monotonic: float


def track_session() -> None:
    if st.session_state.get(SESSION_STARTED_KEY):
        return
    if get_token() is None:
        return
    context = get_usage_context()
    _track_event_safely("session_started", context=context)
    st.session_state[SESSION_STARTED_KEY] = True


def track_page_view(page: str) -> None:
    if get_token() is None:
        return
    context = get_usage_context()
    if st.session_state.get(LAST_PAGE_KEY) == page:
        return
    _track_event_safely("page_view", context=context, feature=page, properties={"page": page})
    st.session_state[LAST_PAGE_KEY] = page


def track_usage_event(event_type: str, properties: dict[str, Any] | None = None) -> None:
    token = get_token()
    if token is None:
        return
    _track_event_safely(
        event_type,
        context=get_usage_context(),
        feature=_feature_from_properties(properties),
        properties=properties,
        token=token,
    )


def _track_event_safely(
    event_type: str,
    *,
    context: UsageContext,
    feature: str | None = None,
    properties: dict[str, Any] | None = None,
    token: str | None = None,
) -> None:
    if not is_enabled():
        return
    token = token or get_token()
    if token is None:
        return
    metadata = {
        **(properties or {}),
        "session_id": context.session_id,
        "session_started_at": context.session_started_at,
        "session_duration_seconds": round(monotonic() - context.session_started_monotonic, 3),
    }
    try:
        ApiClient(base_url=get_api_base_url()).track_usage_event(
            event_type,
            token=token,
            feature=feature,
            metadata=metadata,
        )
    except Exception as e:
        _log.warning("Product usage event skipped: %s (%s)", event_type, e)


def get_usage_context() -> UsageContext:
    existing = st.session_state.get(CONTEXT_KEY)
    if isinstance(existing, UsageContext):
        return existing
    context = UsageContext(
        session_id=uuid4().hex,
        session_started_at=datetime.now(UTC).isoformat(),
        session_started_monotonic=monotonic(),
    )
    st.session_state[CONTEXT_KEY] = context
    return context


def is_enabled() -> bool:
    return os.getenv(ENABLED_ENV, "true").strip().lower() not in {"0", "false", "no", "off"}


def _feature_from_properties(properties: dict[str, Any] | None) -> str | None:
    if not isinstance(properties, dict):
        return None
    for key in ("page", "radar_view", "ui_version"):
        value = properties.get(key)
        if value:
            return str(value)
    return None
