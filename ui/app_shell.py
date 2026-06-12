"""Top-level Streamlit shell and navigation."""
from __future__ import annotations

import streamlit as st

from ui.components.theme import html_escape
from ui.feature_flags import (
    BETA_SHOW_ALERTS,
    BETA_SHOW_PORTFOLIO,
    BETA_SHOW_PRODUCT_LAB,
    BETA_SHOW_STATUS,
    beta_hidden_pages,
    is_beta_feature_enabled,
    is_beta_mode,
    is_demo_mode,
    is_tasar_playground_mode,
)

NAV_ITEMS = ["Tasar propiedad", "Radar", "Portafolio", "Alertas", "Estado"]
BETA_NAV_ITEMS = ["Tasar propiedad", "Radar", "Estado"]
DEMO_NAV_ITEMS = [
    "Dashboard Lab",
    "Alertas Lab",
    "Checklist Lab",
    "Decision Board Lab",
    "Lab Feedback",
    "Buyer Journey",
    "Owner Journey",
    "Risk Report",
    "Autofact Demo",
    "Portfolio Demo",
]
LAB_NAV_GROUP_KEY = "avm_lab_nav_group"
LAB_NAV_PAGE_KEY = "avm_lab_nav_page"
LAB_NAV_PREVIOUS_KEY = "avm_lab_previous_page"
LAB_NAV_GROUPS = [
    {
        "id": "dashboard",
        "label": "Dashboard",
        "badge": "Live",
        "caption": "Centro inmobiliario personal.",
        "items": [{"label": "Resumen", "page": "Dashboard Lab", "slug": "dashboard"}],
    },
    {
        "id": "market",
        "label": "Mercado",
        "badge": "Radar",
        "caption": "Explora comunas, senales y oportunidades activas.",
        "items": [
            {"label": "Radar", "page": "Radar", "slug": "radar"},
            {"label": "Propiedad", "page": "Property Experience", "slug": "property"},
        ],
    },
    {
        "id": "portfolio",
        "label": "Portafolio",
        "badge": "Watchlist",
        "caption": "Gestiona propiedades guardadas y due diligence.",
        "items": [
            {"label": "Watchlist", "page": "Portfolio Demo", "slug": "portfolio"},
            {"label": "Decision Board", "page": "Decision Board Lab", "slug": "decision-board"},
            {"label": "Checklist", "page": "Checklist Lab", "slug": "checklist"},
        ],
    },
    {
        "id": "opportunities",
        "label": "Oportunidades",
        "badge": "Workflow",
        "caption": "Convierte senales en siguientes pasos.",
        "items": [
            {"label": "Comprador", "page": "Buyer Journey", "slug": "buyer"},
            {"label": "Propietario", "page": "Owner Journey", "slug": "owner"},
        ],
    },
    {
        "id": "reports",
        "label": "Reports",
        "badge": "Premium",
        "caption": "Riesgo, legal simulado y lectura accionable.",
        "items": [
            {"label": "Risk Report", "page": "Risk Report", "slug": "risk-report"},
            {"label": "Autofact", "page": "Autofact Demo", "slug": "autofact"},
        ],
    },
    {
        "id": "alerts",
        "label": "Alertas",
        "badge": "Feed",
        "caption": "Movimientos recientes y feedback interno del Lab.",
        "items": [
            {"label": "Alert Center", "page": "Alertas Lab", "slug": "alerts"},
            {"label": "Lab Feedback", "page": "Lab Feedback", "slug": "feedback"},
        ],
    },
]
LAB_PAGE_TO_GROUP = {item["page"]: group["id"] for group in LAB_NAV_GROUPS for item in group["items"]}
LAB_PAGE_TO_SLUG = {item["page"]: item["slug"] for group in LAB_NAV_GROUPS for item in group["items"]}
LAB_SLUG_TO_PAGE = {slug: page for page, slug in LAB_PAGE_TO_SLUG.items()}


def render_app_shell() -> str:
    current_user = st.session_state.get("current_user")
    if is_tasar_playground_mode():
        from ui.redesign.tasar_playground import render_top_nav

        return render_top_nav(current_user)
    user_label = "Modo Lab · Demo" if is_demo_mode() else ("Sesión activa" if current_user else "Modo lectura")
    if isinstance(current_user, dict) and current_user.get("email"):
        user_label = f"{current_user['email']}"

    st.markdown(
        f"""
        <div class="avm-app-shell">
            <div>
                <div class="avm-brand">AVM Chile</div>
                <div class="avm-brand-subtitle">Tu centro inmobiliario personal</div>
            </div>
            <div class="avm-user-pill">{html_escape(user_label)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if is_demo_mode() and is_beta_feature_enabled(BETA_SHOW_PRODUCT_LAB):
        return render_lab_navigation()

    return st.radio(
        "Navegación principal",
        get_visible_nav_items(),
        horizontal=True,
        label_visibility="collapsed",
        index=0,
    )


def get_visible_nav_items() -> list[str]:
    if not is_beta_mode():
        return list(NAV_ITEMS)
    items = ["Tasar propiedad", "Radar"]
    if is_beta_feature_enabled(BETA_SHOW_PORTFOLIO):
        items.append("Portafolio")
    if is_beta_feature_enabled(BETA_SHOW_ALERTS):
        items.append("Alertas")
    if is_beta_feature_enabled(BETA_SHOW_STATUS):
        items.append("Estado")
    return items


def get_visible_demo_nav_items() -> list[str]:
    hidden = beta_hidden_pages()
    return [item for item in DEMO_NAV_ITEMS if item not in hidden]


def render_lab_navigation() -> str:
    groups = get_visible_lab_nav_groups()
    if not groups:
        st.info("Product Lab oculto en BETA_MODE. Usa Tasacion, Radar o Estado.")
        return "Tasar propiedad"
    sync_lab_route_from_query()
    current_page = get_current_lab_page()
    current_group = get_lab_group_for_page(current_page)
    group = get_lab_group(current_group)

    st.markdown(
        f"""
        <div class="avm-lab-nav-panel">
            <div class="avm-lab-nav-kicker">Product Lab</div>
            <div class="avm-lab-nav-row">
                <div>
                    <div class="avm-lab-nav-title">{html_escape(str(group["label"]))}</div>
                    <div class="avm-lab-nav-caption">{html_escape(str(group["caption"]))}</div>
                </div>
                <div class="avm-lab-nav-badge">{html_escape(str(group["badge"]))}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    group_options = [item["id"] for item in groups]
    selected_group = st.segmented_control(
        "Sección Lab",
        group_options,
        default=current_group,
        format_func=lambda group_id: str(get_lab_group(group_id)["label"]),
        label_visibility="collapsed",
    )
    if selected_group and selected_group != current_group:
        current_page = set_lab_page(get_lab_group(selected_group)["items"][0]["page"])
        current_group = get_lab_group_for_page(current_page)
        group = get_lab_group(current_group)

    item_options = [item["page"] for item in group["items"]]
    if current_page not in item_options:
        current_page = item_options[0]
    selected_page = st.segmented_control(
        "Vista contextual",
        item_options,
        default=current_page,
        format_func=get_lab_page_label,
        label_visibility="collapsed",
    )
    if selected_page and selected_page != current_page:
        current_page = set_lab_page(selected_page)
        current_group = get_lab_group_for_page(current_page)
        group = get_lab_group(current_group)

    write_lab_route_to_query(current_page)
    render_lab_context_bar(current_page, group)
    return current_page


def render_lab_context_bar(current_page: str, group: dict[str, object]) -> None:
    previous_page = st.session_state.get(LAB_NAV_PREVIOUS_KEY)
    page_label = get_lab_page_label(current_page)
    previous_label = get_lab_page_label(previous_page) if previous_page else ""
    left, right = st.columns([0.74, 0.26], vertical_alignment="center")
    left.markdown(
        f"""
        <div class="avm-lab-breadcrumb">
            Product Lab / {html_escape(str(group["label"]))} / <strong>{html_escape(page_label)}</strong>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if previous_page and previous_page != current_page:
        if right.button(f"Volver a {previous_label}", key="avm-lab-back"):
            set_lab_page(previous_page, track_previous=False)
            st.rerun()
    else:
        right.markdown('<div class="avm-lab-current-indicator">Vista activa</div>', unsafe_allow_html=True)


def sync_lab_route_from_query() -> None:
    query_page = read_lab_page_from_query()
    if not query_page:
        return
    st.session_state[LAB_NAV_PAGE_KEY] = query_page
    st.session_state[LAB_NAV_GROUP_KEY] = get_lab_group_for_page(query_page)


def read_lab_page_from_query() -> str | None:
    try:
        route = st.query_params.get("lab")
    except Exception:
        return None
    if isinstance(route, list):
        route = route[0] if route else None
    if not route:
        return None
    route = str(route)
    visible_pages = set(get_visible_demo_nav_items())
    if route in LAB_SLUG_TO_PAGE and LAB_SLUG_TO_PAGE[route] in visible_pages:
        return LAB_SLUG_TO_PAGE[route]
    if route in LAB_PAGE_TO_GROUP and route in visible_pages:
        return route
    return None


def write_lab_route_to_query(page: str) -> None:
    slug = LAB_PAGE_TO_SLUG.get(page)
    if not slug:
        return
    try:
        if st.query_params.get("lab") != slug:
            st.query_params["lab"] = slug
    except Exception:
        return


def get_current_lab_page() -> str:
    visible_pages = get_visible_demo_nav_items()
    fallback = visible_pages[0] if visible_pages else "Tasar propiedad"
    page = st.session_state.get(LAB_NAV_PAGE_KEY)
    if page in LAB_PAGE_TO_GROUP and page in visible_pages:
        return page
    st.session_state[LAB_NAV_PAGE_KEY] = fallback
    st.session_state[LAB_NAV_GROUP_KEY] = get_lab_group_for_page(fallback)
    return fallback


def set_lab_page(page: str, *, track_previous: bool = True) -> str:
    visible_pages = get_visible_demo_nav_items()
    if page not in LAB_PAGE_TO_GROUP or page not in visible_pages:
        page = visible_pages[0] if visible_pages else "Tasar propiedad"
    previous_page = st.session_state.get(LAB_NAV_PAGE_KEY)
    if track_previous and previous_page in LAB_PAGE_TO_GROUP and previous_page != page:
        st.session_state[LAB_NAV_PREVIOUS_KEY] = previous_page
    st.session_state[LAB_NAV_PAGE_KEY] = page
    st.session_state[LAB_NAV_GROUP_KEY] = get_lab_group_for_page(page)
    return page


def get_lab_group_for_page(page: str) -> str:
    return LAB_PAGE_TO_GROUP.get(page, "dashboard")


def get_lab_group(group_id: str) -> dict[str, object]:
    groups = get_visible_lab_nav_groups()
    for group in groups:
        if group["id"] == group_id:
            return group
    return groups[0] if groups else {"id": "hidden", "label": "Beta", "badge": "Beta", "caption": "", "items": []}


def get_visible_lab_nav_groups() -> list[dict[str, object]]:
    hidden = beta_hidden_pages()
    groups: list[dict[str, object]] = []
    for group in LAB_NAV_GROUPS:
        items = [item for item in group["items"] if item["page"] not in hidden]
        if not items:
            continue
        groups.append({**group, "items": items})
    return groups


def get_lab_page_label(page: str | None) -> str:
    if not page:
        return ""
    for group in LAB_NAV_GROUPS:
        for item in group["items"]:
            if item["page"] == page:
                return str(item["label"])
    return str(page)


def inject_shell_styles() -> None:
    st.markdown(
        """
        <style>
        .avm-app-shell {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            padding: 0.35rem 0 1rem 0;
            margin-bottom: 0.35rem;
            border-bottom: 1px solid var(--avm-border);
        }
        .avm-brand {
            color: var(--avm-text);
            font-size: 1.35rem;
            font-weight: 800;
            letter-spacing: 0;
        }
        .avm-brand-subtitle {
            color: var(--avm-muted);
            font-size: 0.92rem;
            margin-top: 0.12rem;
        }
        .avm-user-pill {
            border: 1px solid var(--avm-border);
            border-radius: 999px;
            color: var(--avm-neutral);
            background: var(--avm-neutral-bg);
            padding: 0.35rem 0.7rem;
            font-size: 0.82rem;
            font-weight: 650;
            white-space: nowrap;
        }
        .avm-lab-nav-panel {
            border: 1px solid var(--avm-border);
            border-radius: 10px;
            background: linear-gradient(135deg, var(--avm-surface) 0%, var(--avm-surface-alt) 100%);
            box-shadow: var(--avm-shadow);
            padding: 0.92rem 1rem;
            margin: 0.35rem 0 0.65rem;
        }
        .avm-lab-nav-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
        }
        .avm-lab-nav-kicker {
            color: var(--avm-premium);
            font-size: 0.72rem;
            font-weight: 800;
            letter-spacing: 0;
            text-transform: uppercase;
            margin-bottom: 0.2rem;
        }
        .avm-lab-nav-title {
            color: var(--avm-text);
            font-size: 1.1rem;
            font-weight: 820;
            line-height: 1.15;
        }
        .avm-lab-nav-caption {
            color: var(--avm-muted);
            font-size: 0.9rem;
            margin-top: 0.18rem;
        }
        .avm-lab-nav-badge,
        .avm-lab-current-indicator {
            display: inline-flex;
            justify-content: center;
            border: 1px solid var(--avm-border);
            border-radius: 999px;
            background: var(--avm-premium-bg);
            color: var(--avm-premium);
            font-size: 0.78rem;
            font-weight: 720;
            padding: 0.28rem 0.66rem;
            white-space: nowrap;
        }
        .avm-lab-breadcrumb {
            color: var(--avm-muted);
            font-size: 0.84rem;
            padding: 0.2rem 0 0.45rem;
        }
        .avm-lab-breadcrumb strong {
            color: var(--avm-text);
            font-weight: 760;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


_render_app_shell = render_app_shell
_render_lab_navigation = render_lab_navigation
_get_visible_nav_items = get_visible_nav_items
_get_visible_demo_nav_items = get_visible_demo_nav_items
_render_lab_context_bar = render_lab_context_bar
_sync_lab_route_from_query = sync_lab_route_from_query
_read_lab_page_from_query = read_lab_page_from_query
_write_lab_route_to_query = write_lab_route_to_query
_get_current_lab_page = get_current_lab_page
_set_lab_page = set_lab_page
_get_lab_group_for_page = get_lab_group_for_page
_get_lab_group = get_lab_group
_get_visible_lab_nav_groups = get_visible_lab_nav_groups
_get_lab_page_label = get_lab_page_label
_inject_shell_styles = inject_shell_styles
