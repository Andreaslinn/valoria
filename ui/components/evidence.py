"""Compact evidence primitives for Product Lab."""
from __future__ import annotations

from typing import Any

import streamlit as st

from ui.components.theme import html_escape, inject_theme, tone_class


def evidence_chip(label: Any, tone: str | None = "neutral") -> str:
    return f'<span class="avm-evidence-chip {tone_class("avm-evidence-chip", tone)}">{html_escape(label)}</span>'


def stat_cluster(items: list[tuple[str, Any, str | None]]) -> None:
    inject_theme()
    body = "".join(
        f"""
        <div class="avm-evidence-stat">
            <span>{html_escape(label)}</span>
            <strong>{html_escape(value)}</strong>
            {evidence_chip("demo", tone)}
        </div>
        """
        for label, value, tone in items
    )
    st.markdown(f'<div class="avm-evidence-stat-cluster">{body}</div>', unsafe_allow_html=True)


def insight_row(
    title: Any,
    body: Any,
    *,
    value: Any | None = None,
    tone: str | None = "neutral",
    priority: str = "supporting",
) -> None:
    inject_theme()
    value_html = evidence_chip(value, tone) if value is not None else ""
    st.markdown(
        f"""
        <div class="avm-evidence-row avm-evidence-row--{html_escape(priority)}">
            <div>
                <strong>{html_escape(title)}</strong>
                <p>{html_escape(body)}</p>
            </div>
            {value_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def signal_row(signal: dict[str, Any]) -> None:
    evidence = signal.get("evidence") or []
    chips = "".join(evidence_chip(item, "neutral") for item in evidence[:4])
    inject_theme()
    st.markdown(
        f"""
        <div class="avm-evidence-row avm-evidence-row--supporting">
            <div>
                <strong>{html_escape(signal.get("label"))}</strong>
                <p>{html_escape(signal.get("explanation"))}</p>
                <div class="avm-evidence-chip-row">{chips}</div>
                <small>{html_escape(signal.get("suggested_action"))}</small>
            </div>
            {evidence_chip(signal.get("confidence", "demo"), signal.get("tone"))}
        </div>
        """,
        unsafe_allow_html=True,
    )


def timeline_item(date: Any, title: Any, body: Any, *, tone: str | None = "neutral", meta: Any | None = None) -> None:
    inject_theme()
    meta_html = f"<small>{html_escape(meta)}</small>" if meta else ""
    st.markdown(
        f"""
        <div class="avm-evidence-timeline-item">
            <time>{html_escape(date)}</time>
            <div>
                <strong>{html_escape(title)}</strong>
                <p>{html_escape(body)}</p>
                {meta_html}
            </div>
            {evidence_chip("evento", tone)}
        </div>
        """,
        unsafe_allow_html=True,
    )


def metadata_row(items: list[tuple[str, Any]]) -> None:
    body = "".join(
        f"<span><strong>{html_escape(label)}</strong> {html_escape(value)}</span>"
        for label, value in items
    )
    st.markdown(f'<div class="avm-evidence-metadata">{body}</div>', unsafe_allow_html=True)
