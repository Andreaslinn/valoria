from __future__ import annotations

import streamlit as st

from ui.api_client import ApiError
from ui.auth import _render_authenticated
from ui.state import clear_session


def test_logout_clears_session() -> None:
    st.session_state["access_token"] = "token"
    st.session_state["current_user"] = {"email": "beta@example.com"}

    clear_session()

    assert "access_token" not in st.session_state
    assert "current_user" not in st.session_state


def test_invalid_token_clears_session() -> None:
    st.session_state["access_token"] = "stale-token"
    st.session_state["current_user"] = {"email": "beta@example.com"}
    target = _Target()

    class Client:
        def me(self, token: str) -> dict:
            assert token == "stale-token"
            raise ApiError("No autorizado", status_code=401)

    _render_authenticated(Client(), "stale-token", target)

    assert "access_token" not in st.session_state
    assert "current_user" not in st.session_state
    assert target.warnings == ["Tu sesion expiro o ya no es valida. Inicia sesion nuevamente."]


class _Target:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    def caption(self, message: str) -> None:
        return None

    def warning(self, message: str) -> None:
        self.warnings.append(message)

    def button(self, label: str, *, key: str | None = None) -> bool:
        return False
