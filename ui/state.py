"""Session-state helpers for the Streamlit UI."""
from __future__ import annotations

import streamlit as st

from ui.api_client import DEFAULT_API_BASE_URL, get_default_base_url
from ui.feature_flags import is_demo_mode as feature_demo_mode
from ui.feature_flags import set_demo_mode as set_feature_demo_mode

TOKEN_KEY = "access_token"
API_BASE_URL_KEY = "api_base_url"


def get_token() -> str | None:
    token = st.session_state.get(TOKEN_KEY)
    return token if isinstance(token, str) and token else None


def set_token(token: str) -> None:
    st.session_state[TOKEN_KEY] = token


def clear_session() -> None:
    st.session_state.pop(TOKEN_KEY, None)
    st.session_state.pop("current_user", None)


def is_authenticated() -> bool:
    return get_token() is not None


def get_api_base_url() -> str:
    value = st.session_state.get(API_BASE_URL_KEY)
    if isinstance(value, str) and value:
        return value
    return get_default_base_url() or DEFAULT_API_BASE_URL


def set_api_base_url(url: str) -> None:
    st.session_state[API_BASE_URL_KEY] = url.rstrip("/")


def is_demo_mode() -> bool:
    return feature_demo_mode()


def set_demo_mode(enabled: bool) -> None:
    set_feature_demo_mode(enabled)
