"""Layout components for AVM's Streamlit UI."""
from __future__ import annotations

import streamlit as st

from ui.components.theme import html_escape, inject_theme, tone_class
from ui.formatting import format_uf
from ui.lab_focus import clear_focus_property, navigate_to_decision_board, truncate_title


def section_header(title: str, subtitle: str | None = None) -> None:
    inject_theme()
    subtitle_html = ""
    if subtitle:
        subtitle_html = f"<p>{html_escape(subtitle)}</p>"
    st.markdown(
        f"""
        <div class="avm-section-header">
            <h1>{html_escape(title)}</h1>
            {subtitle_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def metric_card(
    label: str,
    value: object,
    caption: str | None = None,
    delta: str | None = None,
    tone: str = "neutral",
) -> None:
    inject_theme()
    caption_html = f'<div class="avm-metric-card__caption">{html_escape(caption)}</div>' if caption else ""
    delta_html = f'<div class="avm-metric-card__delta">{html_escape(delta)}</div>' if delta else ""
    st.markdown(
        f"""
        <div class="avm-card avm-metric-card {tone_class("avm-metric-card", tone)}">
            <div class="avm-metric-card__label">{html_escape(label)}</div>
            <div class="avm-metric-card__value">{html_escape(value)}</div>
            {caption_html}
            {delta_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def empty_state(title: str, body: str, action_label: str | None = None) -> None:
    inject_theme()
    action_html = ""
    if action_label:
        action_html = f'<div class="avm-empty-state__body">{html_escape(action_label)}</div>'
    st.markdown(
        f"""
        <div class="avm-empty-state">
            <div class="avm-empty-state__title">{html_escape(title)}</div>
            <div class="avm-empty-state__body">{html_escape(body)}</div>
            {action_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def premium_feature_card(title: str, description: str, status: str = "soon") -> None:
    inject_theme()
    st.markdown(
        f"""
        <div class="avm-card avm-premium-card">
            <div class="avm-premium-card__status">{html_escape(status)}</div>
            <div class="avm-premium-card__title">{html_escape(title)}</div>
            <div class="avm-premium-card__description">{html_escape(description)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_focus_property_bar(listing: dict | None) -> None:
    if listing is None or "avm_global_focus_property_id" not in st.session_state:
        return
    inject_theme()
    title = truncate_title(listing.get("title"), max_len=45)
    comuna = str(listing.get("comuna") or "Comuna demo").title()
    price = format_uf(listing.get("price_uf"))
    score = listing.get("score")
    source = st.session_state.get("avm_global_focus_source") or "Lab"
    score_html = ""
    if score is not None:
        score_html = f'<span class="avm-focus-bar__badge">Score {html_escape(score)}</span>'

    st.markdown(
        f"""
        <div class="avm-focus-bar">
            <div class="avm-focus-bar__main">
                <span>Foco activo</span>
                <strong>{html_escape(title)}</strong>
            </div>
            <div class="avm-focus-bar__meta">
                <span class="avm-focus-bar__badge">{html_escape(comuna)}</span>
                <span class="avm-focus-bar__badge">{html_escape(price)}</span>
                {score_html}
                <span class="avm-focus-bar__source">{html_escape(source)}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    left, right, spacer = st.columns([0.18, 0.16, 0.66], gap="small")
    if left.button("Ver Decision Board", key="avm-focus-open-decision-board"):
        navigate_to_decision_board()
        st.rerun()
    if right.button("Limpiar foco", key="avm-focus-clear"):
        clear_focus_property()
        st.rerun()
    spacer.empty()
    _inject_focus_bar_styles()


def _inject_focus_bar_styles() -> None:
    st.markdown(
        """
        <style>
        .avm-focus-bar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.75rem;
            border: 1px solid var(--avm-border);
            border-radius: 12px;
            background: var(--avm-surface);
            padding: 0.7rem 0.85rem;
            margin: 0.25rem 0 0.75rem;
        }
        .avm-focus-bar__main {
            min-width: 0;
        }
        .avm-focus-bar__main span,
        .avm-focus-bar__source {
            color: var(--avm-muted);
            font-size: 0.74rem;
            font-weight: 760;
            text-transform: uppercase;
        }
        .avm-focus-bar__main strong {
            color: var(--avm-text);
            display: block;
            font-size: 0.98rem;
            line-height: 1.2;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .avm-focus-bar__meta {
            align-items: center;
            display: flex;
            flex-wrap: wrap;
            gap: 0.35rem;
            justify-content: flex-end;
        }
        .avm-focus-bar__badge {
            border: 1px solid var(--avm-border);
            border-radius: 999px;
            color: var(--avm-premium);
            background: var(--avm-premium-bg);
            font-size: 0.78rem;
            font-weight: 700;
            padding: 0.24rem 0.55rem;
            white-space: nowrap;
        }
        @media (max-width: 760px) {
            .avm-focus-bar {
                align-items: flex-start;
                flex-direction: column;
            }
            .avm-focus-bar__meta {
                justify-content: flex-start;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
