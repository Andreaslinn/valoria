"""Private beta password gate for the Streamlit UI."""
from __future__ import annotations

import hmac
import os
from dataclasses import dataclass
from typing import Any

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

BETA_AUTH_KEY = "avm_beta_auth"
LOCAL_ENVIRONMENTS = {"local", "dev", "development", "test"}


@dataclass(frozen=True)
class BetaPasswordConfig:
    beta_password: str | None
    admin_password: str | None

    @property
    def is_configured(self) -> bool:
        return bool(self.beta_password or self.admin_password)


def render_beta_gate(container: Any = st) -> bool:
    """Render a simple password gate and return True when access is allowed."""
    config = get_beta_password_config()
    if not config.is_configured:
        if is_production_environment():
            container.error(
                "Acceso bloqueado: falta configurar BETA_PASSWORD o ADMIN_PASSWORD en el entorno de producción."
            )
            container.caption("Configura la variable en el hosting o en st.secrets antes de publicar la beta.")
            return False
        st.sidebar.warning("Beta password no configurado. Acceso permitido solo por entorno local.")
        return True

    auth = st.session_state.get(BETA_AUTH_KEY)
    if isinstance(auth, dict) and auth.get("authenticated") is True:
        _render_beta_session(auth)
        return True

    container.title("AVM Chile")
    container.subheader("Acceso beta privada")
    container.caption("Ingresa la contraseña de beta para continuar.")
    with container.form("beta_password_gate"):
        password = st.text_input("Contraseña de acceso", type="password")
        submitted = st.form_submit_button("Entrar", type="primary")

    if not submitted:
        return False
    role = validate_beta_password(password, config)
    if role is None:
        container.error("Contraseña incorrecta.")
        return False
    st.session_state[BETA_AUTH_KEY] = {"authenticated": True, "role": role}
    st.rerun()
    return False


def get_beta_password_config() -> BetaPasswordConfig:
    beta_password = _clean_password(_read_secret_or_env("BETA_PASSWORD"))
    admin_password = _clean_password(_read_secret_or_env("ADMIN_PASSWORD"))
    return BetaPasswordConfig(beta_password=beta_password, admin_password=admin_password)


def validate_beta_password(password: str, config: BetaPasswordConfig) -> str | None:
    candidate = _clean_password(password)
    if not candidate:
        return None
    if config.admin_password and hmac.compare_digest(candidate, config.admin_password):
        return "admin"
    if config.beta_password and hmac.compare_digest(candidate, config.beta_password):
        return "beta"
    return None


def is_production_environment() -> bool:
    environment = os.getenv("ENVIRONMENT") or os.getenv("APP_ENV") or os.getenv("STREAMLIT_ENV")
    if environment is None:
        return True
    return environment.strip().lower() not in LOCAL_ENVIRONMENTS


def _render_beta_session(auth: dict[str, Any]) -> None:
    role = str(auth.get("role") or "beta")
    with st.sidebar.expander("Acceso beta", expanded=False):
        st.caption(f"Acceso activo: {role}")
        if st.button("Salir de beta"):
            st.session_state.pop(BETA_AUTH_KEY, None)
            st.rerun()


def _read_secret_or_env(name: str) -> str | None:
    value = os.getenv(name)
    if value:
        return value
    try:
        secret_value = st.secrets.get(name)
    except Exception:
        return None
    return str(secret_value) if secret_value else None


def _clean_password(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
