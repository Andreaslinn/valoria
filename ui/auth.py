"""Authentication widgets for the Streamlit UI."""
from __future__ import annotations

from typing import Any

import streamlit as st

from ui.api_client import ApiClient, ApiError
from ui.components.theme import html_escape
from ui.state import clear_session, get_token, set_token


def _safe_rerun() -> None:
    try:
        st.rerun()
    except Exception:
        st.experimental_rerun()


def render_auth(
    client: ApiClient,
    container: Any | None = None,
    *,
    form_key: str = "auth_login_form",
) -> None:
    target = container or st.sidebar
    token = get_token()
    target.subheader("Sesion")

    if token:
        _render_authenticated(client, token, target)
        return

    mode = target.radio(
        "Acceso",
        ("Iniciar sesion", "Crear cuenta"),
        horizontal=True,
        key=f"{form_key}_mode",
    )
    if mode == "Crear cuenta":
        _render_signup_form(client, target, form_key=form_key)
        return

    with target.form(key=form_key):
        email = st.text_input("Email", key=f"{form_key}_email")
        password = st.text_input("Password", type="password", key=f"{form_key}_password")
        submitted = st.form_submit_button("Iniciar sesion")

    if submitted:
        if not email or not password:
            target.warning("Ingresa email y password.")
            return

        try:
            result = client.login(email, password)
            access_token = result.get("access_token")

            if not access_token:
                target.error("La API no devolvio un token valido.")
                return

            set_token(access_token)
            target.success("Sesion iniciada.")
            _safe_rerun()

        except ApiError as e:
            target.error(
                "Credenciales invalidas"
                if e.status_code == 401
                else e.message
            )


def _render_signup_form(client: ApiClient, target: Any, *, form_key: str) -> None:
    with target.form(key=f"{form_key}_signup"):
        email = st.text_input("Email", key=f"{form_key}_signup_email")
        password = st.text_input("Password", type="password", key=f"{form_key}_signup_password")
        confirm_password = st.text_input(
            "Confirmar password",
            type="password",
            key=f"{form_key}_signup_confirm_password",
        )
        submitted = st.form_submit_button("Crear cuenta")

    if not submitted:
        return

    email = email.strip()
    if not email:
        target.warning("Ingresa email.")
        return
    if len(password) < 8:
        target.warning("El password debe tener al menos 8 caracteres.")
        return
    if password != confirm_password:
        target.warning("Los passwords no coinciden.")
        return

    try:
        client.register(email, password)
        target.success("Cuenta creada. Ahora puedes iniciar sesion.")
    except ApiError as e:
        target.error(e.message)


def _render_authenticated(client: ApiClient, token: str, target: Any) -> None:
    try:
        user = client.me(token)
        st.session_state["current_user"] = user
        target.caption(f"Conectado como {user.get('email', 'usuario')}")
        target.caption(f"Rol: {user.get('role', '-')}")
    except ApiError as e:
        if e.status_code == 401:
            clear_session()
            target.warning("Tu sesion expiro o ya no es valida. Inicia sesion nuevamente.")
            return
        target.warning(e.message)

    if target.button("Cerrar sesion", key="auth_logout_button"):
        clear_session()
        _safe_rerun()

    if st.session_state.get("current_user", {}).get("role") == "admin":
        _render_admin_panel(client, token, target)


def _render_admin_panel(client: ApiClient, token: str, target: Any) -> None:
    target.divider()
    target.subheader("Usuarios beta")

    with target.form(key="create_beta_user_form"):
        email = st.text_input("Email beta", key="create_beta_email")
        password = st.text_input("Password inicial", type="password", key="create_beta_password")
        submitted = st.form_submit_button("Crear beta_user")

    if submitted:
        try:
            client.create_user(token, email, password, "beta_user")
            target.success("Usuario creado.")
            _safe_rerun()
        except ApiError as e:
            target.error(e.message)

    try:
        users = client.list_users(token)
    except ApiError as e:
        target.warning(e.message)
        return

    for user in users:
        user_id = int(user["id"])
        active = bool(user.get("is_active"))
        email = user.get("email", "usuario")
        role = user.get("role", "-")
        status_label = "activo" if active else "inactivo"
        status_class = "active" if active else "inactive"
        target.markdown(
            f"""
            <div class="avm-admin-user-row">
                <div class="avm-admin-user-head">
                    <div class="avm-admin-user-email">{html_escape(email)}</div>
                    <span class="avm-admin-user-status avm-admin-user-status--{status_class}">
                        {html_escape(status_label)}
                    </span>
                </div>
                <div class="avm-admin-user-meta">Rol: {html_escape(role)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        try:
            if active:
                clicked = target.button("Desactivar", key=f"deactivate-user-{user_id}")
                if clicked:
                    client.deactivate_user(token, user_id)
                    _safe_rerun()
            else:
                clicked = target.button("Activar", key=f"activate-user-{user_id}")
                if clicked:
                    client.activate_user(token, user_id)
                    _safe_rerun()
        except ApiError as e:
            target.error(e.message)
