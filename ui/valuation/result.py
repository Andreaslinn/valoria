"""Valuation result, confidence and comparable display components."""
from __future__ import annotations

from typing import Any

import streamlit as st

from core.assessment.beta_status import beta_status_display_label, is_beta_warning_status
from core.normalization.geocode_precision import canonical_geocode_precision
from ui.components.badges import status_badge
from ui.components.cards import warning_box
from ui.components.layout import empty_state, metric_card
from ui.components.theme import html_escape
from ui.api_client import ApiClient, ApiError
from ui.formatting import format_clp, format_confidence, format_uf

FEEDBACK_OPTIONS = {
    "Se ve razonable": "reasonable",
    "Está muy alta": "too_high",
    "Está muy baja": "too_low",
    "No sé": "unsure",
}


def render_valuation_result(
    result: dict[str, Any],
    payload: dict[str, Any],
    api_client: ApiClient | None = None,
) -> None:
    st.subheader("Resultado estimado")
    st.caption("Lectura rápida del valor, confianza y señal frente al precio publicado.")

    inject_valuation_result_styles()

    confidence = normalize_confidence(result.get("confidence_label") or result.get("confidence"))
    quality = valuation_quality_state(result, payload)
    confidence_label, confidence_tone = confidence_signal(confidence)
    confidence_explanation = confidence_explanation_text(confidence)
    market_label, market_tone, market_delta = market_signal(result, payload)
    data_label, data_tone = data_signal(result)

    render_quality_summary(result, payload, quality)

    c1, c2 = st.columns([1.2, 1], gap="medium")
    with c1:
        metric_card(
            "Valor estimado UF",
            format_uf(result.get("estimated_price_uf")),
            caption="Estimación central del modelo",
            delta=market_delta,
            tone=market_tone,
        )
    with c2:
        metric_card(
            "Valor estimado CLP",
            format_clp(result.get("estimated_price_clp")),
            caption="Conversión aproximada a pesos",
            tone="neutral",
        )

    c3, c4, c5 = st.columns(3, gap="medium")
    with c3:
        metric_card(
            "Confianza",
            format_confidence(result.get("confidence_label") or result.get("confidence")),
            caption=confidence_explanation,
            tone=confidence_tone,
        )
    with c4:
        metric_card(
            "Precio/m²",
            format_uf(result.get("price_m2_uf")),
            caption="UF por metro cuadrado",
            tone="neutral",
        )
    with c5:
        metric_card(
            "Comparables",
            result.get("comparable_count", "—"),
            caption=comparable_count_sentence(result.get("comparable_count")),
            tone=data_tone,
        )

    render_price_range_band(result)
    render_confidence_context(confidence_label, confidence_tone, confidence_explanation, result)

    signal_cols = st.columns(3)
    with signal_cols[0]:
        status_badge(confidence_label, confidence_tone)
    with signal_cols[1]:
        status_badge(market_label, market_tone)
    with signal_cols[2]:
        status_badge(data_label, data_tone)

    warning_box(result.get("warnings"))
    render_valuation_feedback(result, payload, api_client=api_client)
    render_comparables_compact(result.get("comparables", []))


def render_valuation_feedback(
    result: dict[str, Any],
    payload: dict[str, Any],
    api_client: ApiClient | None = None,
) -> None:
    st.subheader("Feedback beta")
    st.caption("Tu lectura ayuda a calibrar si la tasación parece razonable en casos reales.")
    key_suffix = feedback_key_suffix(result, payload)
    with st.form(f"valuation-feedback-{key_suffix}"):
        selected_label = st.radio(
            "¿Cómo ves esta tasación?",
            list(FEEDBACK_OPTIONS),
            horizontal=True,
            key=f"valuation-feedback-choice-{key_suffix}",
        )
        comment = st.text_area(
            "Comentario opcional",
            placeholder="Ej: parece alta para el sector, faltan terminaciones, precio publicado raro...",
            max_chars=1000,
            key=f"valuation-feedback-comment-{key_suffix}",
        )
        submitted = st.form_submit_button("Enviar feedback", type="secondary")
    if not submitted:
        return
    try:
        submit_valuation_feedback_via_api(
            api_client or ApiClient(),
            valuation_result=result,
            valuation_payload=payload,
            feedback=FEEDBACK_OPTIONS[selected_label],
            comment=comment,
        )
    except ApiError as exc:
        st.error(f"No pudimos guardar el feedback: {exc}")
        return
    st.success("Gracias. Feedback guardado para calibrar la beta.")


def submit_valuation_feedback_via_api(
    api_client: ApiClient,
    *,
    valuation_result: dict[str, Any],
    valuation_payload: dict[str, Any],
    feedback: str,
    comment: str | None = None,
) -> dict[str, Any]:
    return api_client.submit_valuation_feedback(
        valuation_result=valuation_result,
        valuation_payload=valuation_payload,
        feedback=feedback,
        comment=comment,
    )


def feedback_key_suffix(result: dict[str, Any], payload: dict[str, Any]) -> str:
    parts = [
        payload.get("comuna"),
        payload.get("property_type"),
        payload.get("built_area_m2") or payload.get("m2"),
        result.get("estimated_price_clp"),
    ]
    clean = "-".join(str(part or "na").strip().replace(" ", "_") for part in parts)
    return "".join(ch for ch in clean if ch.isalnum() or ch in {"-", "_"})[:120]


def render_quality_summary(
    result: dict[str, Any],
    payload: dict[str, Any],
    quality: dict[str, str],
) -> None:
    comparable_count = comparable_count_value(result.get("comparable_count"))
    comparable_label = str(comparable_count) if comparable_count is not None else "No disponible"
    low_data_label = "Activo" if is_low_data_mode(result) else "No activo"
    unknown_type_label = "Si" if has_unknown_property_type(result, payload) else "No"
    approx_geocoding_label = "Si" if has_approx_geocoding(result) else "No"
    property_type = property_type_display(payload.get("property_type"))
    beta_scope_label = beta_scope_display(result.get("beta_scope_status"))
    risk_html = risk_messages_html(valuation_risk_messages(result, payload))

    st.markdown(
        f"""
        <div class="avm-valuation-quality avm-valuation-quality--{html_escape(quality['tone'])}">
            <div class="avm-valuation-quality__header">
                <div>
                    <span>Confiabilidad del AVM</span>
                    <strong>{html_escape(quality['label'])}</strong>
                    <p>{html_escape(quality['description'])}</p>
                </div>
                <div class="avm-valuation-quality__status">
                    <span>Confidence score</span>
                    <strong>{html_escape(confidence_score_text(result.get("confidence_score", result.get("confidence"))))}</strong>
                </div>
            </div>
            <div class="avm-valuation-quality__grid">
                <div><span>Comparables usados</span><strong>{html_escape(comparable_label)}</strong></div>
                <div><span>LOW_DATA_MODE</span><strong>{html_escape(low_data_label)}</strong></div>
                <div><span>Geocoding aproximado</span><strong>{html_escape(approx_geocoding_label)}</strong></div>
                <div><span>Tipo propiedad</span><strong>{html_escape(property_type)}</strong></div>
                <div><span>Property type unknown</span><strong>{html_escape(unknown_type_label)}</strong></div>
                <div><span>Beta scope</span><strong>{html_escape(beta_scope_label)}</strong></div>
            </div>
            {risk_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def risk_messages_html(messages: list[tuple[str, str]]) -> str:
    if not messages:
        return ""
    rows = [
        f'<div class="avm-valuation-risk avm-valuation-risk--{html_escape(tone)}">{html_escape(message)}</div>'
        for tone, message in messages
    ]
    return f'<div class="avm-valuation-quality__risks">{"".join(rows)}</div>'


def valuation_quality_state(result: dict[str, Any], payload: dict[str, Any]) -> dict[str, str]:
    confidence = normalize_confidence(result.get("confidence_label") or result.get("confidence"))
    comparable_count = comparable_count_value(result.get("comparable_count"))
    low_data = is_low_data_mode(result)
    unknown_type = has_unknown_property_type(result, payload)

    if (
        confidence == "insufficient_data"
        or low_data
        or unknown_type
        or (comparable_count is not None and comparable_count < 5)
    ):
        return {
            "label": "Tasación exploratoria",
            "tone": "negative",
            "description": "Resultado visible, pero con base de datos insuficiente o señales críticas de confiabilidad.",
        }
    if confidence == "high":
        return {
            "label": "Alta confianza",
            "tone": "positive",
            "description": "La estimación tiene suficientes comparables y no presenta alertas críticas de entrada.",
        }
    if confidence == "medium":
        return {
            "label": "Confianza media",
            "tone": "warning",
            "description": "La estimación es útil como referencia, con margen de incertidumbre relevante.",
        }
    return {
        "label": "Baja confianza",
        "tone": "negative",
        "description": "La estimación debe leerse como referencial por baja similitud, pocos datos o señales incompletas.",
    }


def valuation_risk_messages(result: dict[str, Any], payload: dict[str, Any]) -> list[tuple[str, str]]:
    messages: list[tuple[str, str]] = []
    comparable_count = comparable_count_value(result.get("comparable_count"))
    if comparable_count is not None and comparable_count < 5:
        messages.append(
            (
                "strong",
                "Menos de 5 comparables elegibles. Resultado exploratorio; no debe usarse como tasación confiable.",
            )
        )
    if is_low_data_mode(result):
        messages.append(("warning", "LOW_DATA_MODE activo: la base de comparables es limitada."))
    if has_approx_geocoding(result):
        messages.append(
            (
                "warning",
                "Ubicación aproximada a nivel de comuna; la distancia no debe interpretarse como exacta.",
            )
        )
    if has_unknown_property_type(result, payload):
        messages.append(("warning", "Tipo de propiedad desconocido: la confiabilidad estructural baja."))
    beta_status = result.get("beta_scope_status")
    beta_message = str(result.get("beta_scope_message") or "").strip()
    if is_beta_warning_status(beta_status):
        messages.append(("warning", beta_message or f"Beta scope: {beta_scope_display(beta_status)}."))
    return messages


def render_price_range_band(result: dict[str, Any]) -> None:
    low = to_float(result.get("price_range_low_uf"))
    estimate = to_float(result.get("estimated_price_uf"))
    high = to_float(result.get("price_range_high_uf"))
    band = range_band_position(low, estimate, high)
    if band is None:
        st.markdown(
            """
            <div class="avm-valuation-band avm-valuation-band--empty">
                <strong>Rango de incertidumbre no disponible</strong>
                <span>El modelo no devolvio banda baja/alta para esta tasacion.</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    marker = band["estimate_pct"]
    st.markdown(
        f"""
        <div class="avm-valuation-band">
            <div class="avm-valuation-band__header">
                <strong>Rango de incertidumbre</strong>
                <span>Low -> estimado -> high</span>
            </div>
            <div class="avm-valuation-band__track">
                <div class="avm-valuation-band__marker" style="left:{marker:.2f}%;">
                    <span>{html_escape(format_uf(estimate))}</span>
                </div>
            </div>
            <div class="avm-valuation-band__labels">
                <span>{html_escape(format_uf(low))}</span>
                <strong>{html_escape(format_uf(estimate))}</strong>
                <span>{html_escape(format_uf(high))}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_confidence_context(
    confidence_label: str,
    confidence_tone: str,
    explanation: str,
    result: dict[str, Any],
) -> None:
    st.markdown(
        f"""
        <div class="avm-valuation-confidence avm-valuation-confidence--{html_escape(confidence_tone)}">
            <div>
                <span>Que significa la confianza</span>
                <strong>{html_escape(confidence_label)}</strong>
                <p>{html_escape(explanation)}</p>
            </div>
            <em>{html_escape(comparable_count_sentence(result.get("comparable_count")))}</em>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_comparables_compact(comparables: list[dict[str, Any]]) -> None:
    st.subheader("Comparables de soporte")
    st.caption("Referencias usadas por el modelo. Son soporte analitico, no el foco principal.")
    if not comparables:
        empty_state(
            "Sin comparables para mostrar",
            "La tasacion no devolvio publicaciones comparables para revisar en detalle.",
        )
        return

    for item in comparables[:12]:
        bedrooms = item.get("bedrooms") or item.get("dormitorios")
        bathrooms = item.get("bathrooms") or item.get("banos")
        program = " / ".join(part for part in [format_rooms(bedrooms, "D"), format_rooms(bathrooms, "B")] if part)
        similarity = to_float(item.get("similarity") or item.get("score"))
        similarity_label = f"{similarity:.2f}" if similarity is not None else "—"
        st.markdown(
            f"""
            <div class="avm-comparable-row">
                <div>
                    <strong>{html_escape(str(item.get("title") or "Comparable"))}</strong>
                    <span>{html_escape(str(item.get("comuna") or "—"))} · {html_escape(format_m2(item.get("m2")))} · {html_escape(program or "Programa no disponible")}</span>
                </div>
                <div>
                    <strong>{html_escape(format_uf(item.get("price_uf")))}</strong>
                    <span>Similitud {html_escape(similarity_label)}</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_comparables(comparables: list[dict[str, Any]]) -> None:
    st.subheader("Comparables de soporte")
    st.caption("Referencias usadas por el modelo. Son soporte analítico, no el foco principal.")
    if not comparables:
        empty_state(
            "Sin comparables para mostrar",
            "La tasación no devolvió publicaciones comparables para revisar en detalle.",
        )
        return

    rows = [
        {
            "ID": item.get("listing_id"),
            "Título": item.get("title"),
            "Comuna": item.get("comuna"),
            "Precio UF": format_uf(item.get("price_uf")),
            "Precio CLP": format_clp(item.get("price_clp")),
            "m²": format_m2(item.get("m2")),
            "Similitud": item.get("similarity"),
            "URL": item.get("url"),
        }
        for item in comparables
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def confidence_signal(confidence: str) -> tuple[str, str]:
    if confidence == "high":
        return "Alta confianza", "positive"
    if confidence == "medium":
        return "Confianza media", "warning"
    if confidence == "low":
        return "Datos limitados", "negative"
    if confidence == "insufficient_data":
        return "Datos insuficientes", "negative"
    return "Confianza disponible", "neutral"


def normalize_confidence(value: Any) -> str:
    if value is None or value == "":
        return "unknown"
    if isinstance(value, int | float):
        if value >= 0.75:
            return "high"
        if value >= 0.5:
            return "medium"
        return "low"
    text = str(value).strip().lower()
    if text in {"high", "medium", "low", "insufficient_data"}:
        return text
    return "unknown"


def confidence_explanation_text(confidence: str) -> str:
    if confidence == "high":
        return "Estimacion basada en comparables suficientes y similares. Alta precision relativa."
    if confidence == "medium":
        return "Estimacion basada en una cantidad moderada de comparables. Puede existir margen de error."
    if confidence == "low":
        return "Pocos comparables o baja similitud. Resultado referencial, no definitivo."
    if confidence == "insufficient_data":
        return "No hay suficientes comparables para una estimacion confiable."
    return "Confianza no disponible."


def comparable_count_sentence(count: Any) -> str:
    if not isinstance(count, int | float):
        return "Cantidad de comparables no disponible."
    if int(count) == 1:
        return "Basado en 1 comparable usado por el modelo."
    return f"Basado en {int(count)} comparables usados por el modelo."


def comparable_count_value(count: Any) -> int | None:
    if isinstance(count, bool):
        return None
    if isinstance(count, int | float):
        return int(count)
    try:
        return int(str(count))
    except (TypeError, ValueError):
        return None


def confidence_score_text(value: Any) -> str:
    if isinstance(value, bool):
        return "No disponible"
    if isinstance(value, int | float):
        return f"{float(value):.2f}".replace(".", ",")
    confidence = normalize_confidence(value)
    if confidence == "high":
        return ">= 0,75"
    if confidence == "medium":
        return "0,50-0,74"
    if confidence == "low":
        return "< 0,50"
    return "No disponible"


def warning_codes(result: dict[str, Any]) -> set[str]:
    warnings = result.get("warnings") or []
    if isinstance(warnings, str):
        warnings = [warnings]
    return {str(item).strip().lower() for item in warnings if item is not None}


def is_low_data_mode(result: dict[str, Any]) -> bool:
    warnings = warning_codes(result)
    value = result.get("low_data_mode")
    return bool(value) or "low_data_mode" in warnings


def has_unknown_property_type(result: dict[str, Any], payload: dict[str, Any]) -> bool:
    property_type = str(payload.get("property_type") or result.get("property_type") or "").strip().lower()
    return property_type == "unknown" or "unknown_property_type" in warning_codes(result)


def has_approx_geocoding(result: dict[str, Any]) -> bool:
    warning_codes_set = warning_codes(result)
    if warning_codes_set & {
        "approximate_geocoding",
        "approximate_location",
        "comuna_centroid",
        "geocoding_comuna_centroid",
        "location_comuna_centroid",
    }:
        return True
    precision = canonical_geocode_precision(result.get("geocode_precision"))
    if precision == "comuna_centroid":
        return True
    for comparable in result.get("comparables") or []:
        if not isinstance(comparable, dict):
            continue
        if canonical_geocode_precision(comparable.get("geocode_precision")) == "comuna_centroid":
            return True
    return False


def property_type_display(value: Any) -> str:
    mapping = {
        "apartment": "Departamento",
        "house": "Casa",
        "office": "Oficina",
        "land": "Terreno",
        "unknown": "Desconocido",
    }
    text = str(value or "unknown").strip().lower()
    return mapping.get(text, text.replace("_", " ").title() if text else "Desconocido")


def beta_scope_display(value: Any) -> str:
    return beta_status_display_label(value)


def range_band_position(low: float | None, estimate: float | None, high: float | None) -> dict[str, float] | None:
    if low is None or estimate is None or high is None:
        return None
    if high <= low:
        return None
    bounded = min(max(estimate, low), high)
    return {"estimate_pct": ((bounded - low) / (high - low)) * 100}


def data_signal(result: dict[str, Any]) -> tuple[str, str]:
    count = result.get("comparable_count")
    if not isinstance(count, int | float):
        return "Comparables por revisar", "neutral"
    if count >= 8:
        return "Buena base de datos", "positive"
    if count >= 3:
        return "Base acotada", "warning"
    return "Datos limitados", "negative"


def market_signal(result: dict[str, Any], payload: dict[str, Any]) -> tuple[str, str, str | None]:
    estimated_uf = to_float(result.get("estimated_price_uf"))
    published_uf = to_float(payload.get("precio_publicado_uf"))
    if estimated_uf is None or published_uf is None or estimated_uf <= 0 or published_uf <= 0:
        return "Sin precio publicado", "neutral", None

    diff_pct = ((published_uf - estimated_uf) / estimated_uf) * 100
    delta = f"{abs(diff_pct):.1f}% vs estimado".replace(".", ",")
    if diff_pct <= -3:
        return "Bajo mercado", "positive", delta
    if diff_pct >= 3:
        return "Sobre mercado", "warning", delta
    return "En línea con mercado", "neutral", delta


def format_m2(value: Any) -> str:
    number = to_float(value)
    if number is None:
        return "—"
    return f"{number:.1f} m²".replace(".", ",")


def format_rooms(value: Any, suffix: str) -> str:
    number = to_float(value)
    if number is None:
        return ""
    return f"{int(number)}{suffix}"


def inject_valuation_result_styles() -> None:
    st.markdown(
        """
        <style>
        .avm-valuation-quality,
        .avm-valuation-band,
        .avm-valuation-confidence,
        .avm-comparable-row {
            border: 1px solid var(--avm-border);
            background: var(--avm-surface);
            border-radius: 12px;
            padding: 0.85rem;
            margin: 0.75rem 0;
        }
        .avm-valuation-quality {
            border-width: 2px;
            display: grid;
            gap: 0.85rem;
        }
        .avm-valuation-quality--positive { border-color: color-mix(in srgb, var(--avm-positive) 56%, var(--avm-border)); }
        .avm-valuation-quality--warning { border-color: color-mix(in srgb, var(--avm-warning) 56%, var(--avm-border)); }
        .avm-valuation-quality--negative { border-color: color-mix(in srgb, var(--avm-negative) 56%, var(--avm-border)); }
        .avm-valuation-quality__header {
            display: grid;
            grid-template-columns: minmax(0, 1fr) minmax(8rem, auto);
            gap: 1rem;
            align-items: start;
        }
        .avm-valuation-quality__header span,
        .avm-valuation-quality__grid span,
        .avm-valuation-quality__status span {
            color: var(--avm-muted);
            display: block;
            font-size: 0.78rem;
            font-weight: 700;
            letter-spacing: 0;
            text-transform: uppercase;
        }
        .avm-valuation-quality__header strong {
            color: var(--avm-text);
            display: block;
            font-size: 1.35rem;
            line-height: 1.15;
            margin-top: 0.1rem;
        }
        .avm-valuation-quality__header p {
            color: var(--avm-muted);
            margin: 0.35rem 0 0;
        }
        .avm-valuation-quality__status {
            border: 1px solid var(--avm-border);
            border-radius: 10px;
            padding: 0.65rem 0.75rem;
            text-align: right;
        }
        .avm-valuation-quality__status strong {
            font-size: 1.05rem;
            margin: 0;
        }
        .avm-valuation-quality__grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 0.55rem;
        }
        .avm-valuation-quality__grid div {
            border: 1px solid var(--avm-border);
            border-radius: 10px;
            padding: 0.6rem;
            min-height: 4.1rem;
        }
        .avm-valuation-quality__grid strong {
            color: var(--avm-text);
            display: block;
            line-height: 1.2;
            margin-top: 0.2rem;
        }
        .avm-valuation-quality__risks {
            display: grid;
            gap: 0.45rem;
        }
        .avm-valuation-risk {
            border: 1px solid color-mix(in srgb, var(--avm-warning) 42%, var(--avm-border));
            border-radius: 10px;
            color: var(--avm-text);
            padding: 0.65rem 0.75rem;
        }
        .avm-valuation-risk--strong {
            border-color: color-mix(in srgb, var(--avm-negative) 62%, var(--avm-border));
            font-weight: 750;
        }
        .avm-valuation-band__header,
        .avm-valuation-band__labels,
        .avm-comparable-row {
            display: flex;
            justify-content: space-between;
            gap: 0.9rem;
            align-items: center;
        }
        .avm-valuation-band__header span,
        .avm-valuation-band__labels span,
        .avm-valuation-confidence span,
        .avm-valuation-confidence em,
        .avm-comparable-row span {
            color: var(--avm-muted);
            font-size: 0.86rem;
            font-style: normal;
        }
        .avm-valuation-band strong,
        .avm-valuation-confidence strong,
        .avm-comparable-row strong {
            color: var(--avm-text);
        }
        .avm-valuation-band__track {
            position: relative;
            height: 0.52rem;
            border-radius: 999px;
            margin: 1.05rem 0 0.75rem;
            background: linear-gradient(90deg, var(--avm-warning), var(--avm-positive), var(--avm-warning));
        }
        .avm-valuation-band__marker {
            position: absolute;
            top: 50%;
            transform: translate(-50%, -50%);
            width: 1rem;
            height: 1rem;
            border-radius: 50%;
            background: var(--avm-positive);
            border: 2px solid var(--avm-surface);
            box-shadow: 0 0 0 4px rgba(45, 212, 191, 0.18);
        }
        .avm-valuation-band__marker span {
            position: absolute;
            top: -1.8rem;
            left: 50%;
            transform: translateX(-50%);
            white-space: nowrap;
            color: var(--avm-text);
            font-weight: 750;
            font-size: 0.82rem;
        }
        .avm-valuation-band--empty {
            display: grid;
            gap: 0.2rem;
            border-style: dashed;
        }
        .avm-valuation-confidence {
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            gap: 0.9rem;
            align-items: center;
        }
        .avm-valuation-confidence p {
            color: var(--avm-muted);
            margin: 0.25rem 0 0;
        }
        .avm-valuation-confidence--positive { border-color: color-mix(in srgb, var(--avm-positive) 34%, var(--avm-border)); }
        .avm-valuation-confidence--warning { border-color: color-mix(in srgb, var(--avm-warning) 34%, var(--avm-border)); }
        .avm-valuation-confidence--negative { border-color: color-mix(in srgb, var(--avm-negative) 34%, var(--avm-border)); }
        .avm-comparable-row div:last-child {
            text-align: right;
            min-width: 8.5rem;
        }
        @media (max-width: 760px) {
            .avm-valuation-quality__header,
            .avm-valuation-quality__grid,
            .avm-valuation-confidence,
            .avm-comparable-row,
            .avm-valuation-band__header,
            .avm-valuation-band__labels {
                display: grid;
                grid-template-columns: 1fr;
            }
            .avm-valuation-quality__status {
                text-align: left;
            }
            .avm-comparable-row div:last-child {
                text-align: left;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


_render_valuation_result = render_valuation_result
_render_valuation_feedback = render_valuation_feedback
_submit_valuation_feedback_via_api = submit_valuation_feedback_via_api
_feedback_key_suffix = feedback_key_suffix
_render_comparables_compact = render_comparables_compact
_render_comparables = render_comparables
_confidence_signal = confidence_signal
_normalize_confidence = normalize_confidence
_confidence_explanation = confidence_explanation_text
_comparable_count_sentence = comparable_count_sentence
_comparable_count_value = comparable_count_value
_confidence_score_text = confidence_score_text
_warning_codes = warning_codes
_is_low_data_mode = is_low_data_mode
_has_unknown_property_type = has_unknown_property_type
_has_approx_geocoding = has_approx_geocoding
_property_type_display = property_type_display
_beta_scope_display = beta_scope_display
_range_band_position = range_band_position
_data_signal = data_signal
_market_signal = market_signal
_format_m2 = format_m2
_format_rooms = format_rooms
_valuation_quality_state = valuation_quality_state
_valuation_risk_messages = valuation_risk_messages
_to_float = to_float
