"""Demo Risk Report presentation components."""
from __future__ import annotations

from typing import Any

import streamlit as st

from ui.components.autofact import render_demo_autofact_report
from ui.components.feedback import record_lab_event, render_lab_feedback_widget
from ui.components.market_context import render_demo_market_context
from ui.components.negotiation import render_demo_negotiation_signals
from ui.components.theme import html_escape, inject_theme, tone_class
from ui.formatting import format_uf


def render_demo_risk_report(
    report: dict[str, Any],
    *,
    expanded: bool = False,
    use_expander: bool = True,
    key_suffix: str = "",
) -> None:
    if not report or report.get("is_demo") is not True:
        return
    inject_theme()
    property_id = _property_id(report)
    record_lab_event("opened_risk_report", module="risk_report", property_id=property_id)
    title = f"Risk Report Demo / {report.get('property', 'Propiedad demo')}"
    if use_expander:
        with st.expander(title, expanded=expanded):
            _render_risk_report_content(
                report,
                property_id=property_id,
                key_suffix=key_suffix,
                use_detail_expander=False,
            )
        return
    st.markdown(f"#### {html_escape(title)}")
    with st.container(border=True):
        _render_risk_report_content(
            report,
            property_id=property_id,
            key_suffix=key_suffix,
            use_detail_expander=True,
        )


def _render_risk_report_content(
    report: dict[str, Any],
    *,
    property_id: int | None,
    key_suffix: str,
    use_detail_expander: bool,
) -> None:
    st.caption(report["demo_disclaimer"])
    _render_summary(report)
    _render_scores(report["scores"])
    _render_signal_lists(report)
    _render_market(report["market_section"])
    _render_negotiation(report["negotiation_section"])
    _render_timeline(report["timeline"])
    _render_price_history(report["price_history"])
    _render_comparables(report["comparables"])

    st.markdown("#### Detalle premium demo")
    if use_detail_expander:
        st.caption("Detalle terciario compacto; se mantiene inline para evitar expanders anidados en Lab.")
    _render_deep_detail(report, property_id=property_id, key_suffix=key_suffix)

    st.info(report["recommendation"])
    render_lab_feedback_widget("risk_report", property_id=property_id, key_prefix=f"risk-feedback-{key_suffix}")


def _render_deep_detail(report: dict[str, Any], *, property_id: int | None, key_suffix: str) -> None:
        render_demo_autofact_report(
            report.get("autofact_report", {}),
            expanded=False,
            key_suffix=f"risk-{property_id or 'property'}-{key_suffix}",
            use_expander=False,
        )
        _render_legal(report["legal_simulation"])
        render_demo_negotiation_signals(report.get("negotiation_signals", {}), expanded=True, use_expander=False)
        render_demo_market_context(report.get("market_context", {}), expanded=True, use_expander=False)
        _render_comuna_context(report["comuna_context"])
        _render_portal_presence(report["portal_presence"])


def _property_id(report: dict[str, Any]) -> int | None:
    try:
        return int(report.get("property_id"))
    except (TypeError, ValueError):
        return None


def _render_summary(report: dict[str, Any]) -> None:
    st.markdown(
        f"""
        <div class="avm-lab-primary-insight">
            <div style="display:flex; justify-content:space-between; gap:0.75rem; align-items:flex-start;">
                <div>
                    <div class="avm-lab-primary-insight__label">Primary insight</div>
                    <div class="avm-lab-primary-insight__title">Executive Summary</div>
                    <div class="avm-lab-primary-insight__body">{html_escape(report["executive_summary"])}</div>
                </div>
                {_badge_html("DEMO", "premium")}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_scores(scores: dict[str, Any]) -> None:
    st.markdown(
        _stat_cluster(
            [
                ("Total", f"{scores['total']}/100", "premium"),
                ("Mercado", f"{scores['market']}/100", "positive"),
                ("Liquidez", f"{scores['liquidity']}/100", "positive"),
                ("Legal sim.", f"{scores['legal_simulated']}/100", "warning"),
                ("Data quality", f"{scores['data_quality']}/100", "neutral"),
            ]
        ),
        unsafe_allow_html=True,
    )


def _render_signal_lists(report: dict[str, Any]) -> None:
    st.subheader("Lectura principal")
    _evidence_group(
        [
            ("Senales", [item["label"] for item in report["signals"]], "premium"),
            ("Riesgos", report["main_risks"], "warning"),
            ("Oportunidades", report["main_opportunities"], "positive"),
        ]
    )


def _render_legal(legal: dict[str, Any]) -> None:
    st.subheader("Legal simulado")
    st.warning(legal["disclaimer"])
    _evidence_group(
        [
            ("CBR y dominio", [legal["cbr_status"], *legal["ownership_flags"]], "warning"),
            (
                "Cargas simuladas",
                [
                    *legal["simulated_liens"],
                    *legal["simulated_prohibitions"],
                    legal["simulated_contribution_debt"],
                    legal["permits_regularization"],
                ],
                "negative" if legal["risk_level"] == "high" else "neutral",
            ),
        ]
    )


def _render_market(market: dict[str, Any]) -> None:
    st.subheader("Mercado")
    st.markdown(
        _stat_cluster(
            [
                ("Publicado", _uf(market["published_price_uf"]), "neutral"),
                ("Estimado", _uf(market["estimated_price_uf"]), "premium"),
                ("Diferencia", f"{market['difference_pct']}%", "positive"),
                ("Liquidez", market["estimated_liquidity"], "positive"),
            ]
        ),
        unsafe_allow_html=True,
    )
    _evidence_group(
        [
            (
                "Evidencia mercado",
                [
                    f"Presion oferta: {market['supply_pressure']}",
                    f"Demanda simulada: {market['simulated_demand']}",
                    f"Comparables activos: {market['active_comparables']}",
                    f"Portales activos: {market['active_portals']}",
                    f"Dias en mercado: {market['days_on_market']}",
                ],
                "neutral",
            )
        ]
    )


def _render_negotiation(negotiation: dict[str, Any]) -> None:
    st.subheader("Negociacion")
    st.caption(f"Margen sugerido demo: {negotiation['suggested_margin_pct']}%")
    st.markdown(
        _stat_cluster(
            [
                ("Conservadora", _uf(negotiation["conservative_strategy"]["offer_uf"]), "neutral"),
                ("Moderada", _uf(negotiation["moderate_strategy"]["offer_uf"]), "positive"),
                ("Agresiva", _uf(negotiation["aggressive_strategy"]["offer_uf"]), "warning"),
            ]
        ),
        unsafe_allow_html=True,
    )
    st.info(negotiation["explanation"])


def _render_timeline(events: list[dict[str, Any]]) -> None:
    st.subheader("Timeline de eventos")
    for event in events[:6]:
        _insight_row(event["title"], event["description"], event["date"], event.get("tone", "neutral"))


def _render_price_history(history: list[dict[str, Any]]) -> None:
    st.subheader("Historial de precio")
    for item in history[:4]:
        tone = "positive" if item["event"] == "rebaja" else "neutral"
        _insight_row(item["date"], item["event"], _uf(item["price_uf"]), tone)


def _render_comparables(comparables: list[dict[str, Any]]) -> None:
    st.subheader("Comparables demo")
    for item in comparables[:4]:
        _insight_row(
            item["label"],
            f"Liquidez {item['liquidity_score']}/100 | Legal {item['legal_score']}/100 | {item['fit']}",
            _uf(item["price_uf"]),
            "premium",
        )


def _render_comuna_context(context: dict[str, Any]) -> None:
    st.subheader("Contexto de comuna")
    st.markdown(
        _stat_cluster(
            [
                ("Inventario", context["demo_inventory"], "neutral"),
                ("Precio medio", _uf(context["avg_price_uf"]), "premium"),
                ("Score medio", context["avg_score"], "positive"),
            ]
        ),
        unsafe_allow_html=True,
    )
    st.caption(context["summary"])
    st.markdown(" ".join(_badge_html(tag, "premium") for tag in context["dominant_signals"]), unsafe_allow_html=True)


def _render_portal_presence(presence: list[dict[str, Any]]) -> None:
    st.subheader("Presencia multiportal")
    for item in presence:
        tone = "positive" if item["is_active"] else "neutral"
        state = "Activo" if item["is_active"] else "No activo"
        _insight_row(
            item["portal_name"],
            f"Primero visto {item['first_seen']} | Ultimo visto {item['last_seen']}",
            f"{state} | {_uf(item['price_seen_uf'])}",
            tone,
        )


def _evidence_group(groups: list[tuple[str, list[str], str]]) -> None:
    body = ""
    for title, items, tone in groups:
        list_html = "".join(f"<span>{html_escape(item)}</span>" for item in items if item)
        body += f"""
            <div class="avm-lab-insight-row">
                <div>
                    <strong>{html_escape(title)}</strong>
                    <div class="avm-lab-quiet-list">{list_html}</div>
                </div>
                {_badge_html("demo", tone)}
            </div>
        """
    st.markdown(f'<div class="avm-lab-evidence-group">{body}</div>', unsafe_allow_html=True)


def _insight_row(title: Any, body: Any, value: Any, tone: str) -> None:
    st.markdown(
        f"""
        <div class="avm-lab-insight-row">
            <div>
                <strong>{html_escape(title)}</strong>
                <p>{html_escape(body)}</p>
            </div>
            {_badge_html(str(value), tone)}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _stat_cluster(items: list[tuple[str, Any, str]]) -> str:
    stats = "".join(
        f"""
        <div class="avm-lab-stat {tone_class("avm-lab-stat", tone)}">
            <span>{html_escape(label)}</span>
            <strong>{html_escape(value)}</strong>
        </div>
        """
        for label, value, tone in items
    )
    return f'<div class="avm-lab-stat-cluster">{stats}</div>'


def _badge_html(label: Any, tone: str = "neutral") -> str:
    return f'<span class="avm-badge {tone_class("avm-badge", tone)}">{html_escape(label)}</span>'


def _uf(value: Any) -> str:
    return "-" if value is None else format_uf(value)
