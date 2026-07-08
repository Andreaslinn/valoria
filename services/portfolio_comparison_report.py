"""Standalone HTML report builder for Portfolio comparisons."""
from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any


def build_portfolio_comparison_report_html(payload: dict[str, Any]) -> str:
    comparison = payload.get("comparison") if isinstance(payload.get("comparison"), dict) else {}
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    title = _text(comparison.get("title"), "Comparacion de Portafolio")
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = "\n".join(_row(item) for item in items if isinstance(item, dict))
    cards = "\n".join(_card(item) for item in items if isinstance(item, dict))
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escape(title)} | Comparados Valoria</title>
<style>{_css()}</style>
</head>
<body>
<main>
  <header>
    <span>Comparados Valoria beta</span>
    <h1>{escape(title)}</h1>
    <p>Generado {escape(generated_at)}. Reporte informativo con datos reales disponibles; no constituye recomendacion de compra.</p>
  </header>
  <section class="cards">{cards}</section>
  <section class="panel">
    <h2>Tabla comparativa</h2>
    <table>
      <thead>
        <tr>
          <th>Propiedad</th><th>Comuna</th><th>Tipo</th><th>m2</th><th>D/B</th>
          <th>Precio publicado</th><th>UF/m2</th><th>AVM Valoria</th><th>Delta</th>
          <th>Confidence</th><th>Alertas</th><th>Frescura</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </section>
  <footer>Sin ranking automatico, sin score inventado y sin metricas demo. Los campos faltantes se muestran como No disponible.</footer>
</main>
</body>
</html>
"""


def _card(item: dict[str, Any]) -> str:
    return f"""
    <article>
      <strong>{escape(_text(item.get("title"), "Propiedad"))}</strong>
      <span>{escape(_text(item.get("comuna"), "No disponible"))}</span>
      <b>{escape(_text(item.get("published_price_label"), "No disponible"))}</b>
      <small>AVM: {escape(_text(item.get("avm_label"), "No disponible"))}</small>
    </article>
    """


def _row(item: dict[str, Any]) -> str:
    return f"""
    <tr>
      <td>{escape(_text(item.get("title"), "Propiedad"))}</td>
      <td>{escape(_text(item.get("comuna"), "No disponible"))}</td>
      <td>{escape(_text(item.get("property_type_label"), "No disponible"))}</td>
      <td>{escape(_text(item.get("m2_label"), "No disponible"))}</td>
      <td>{escape(_text(item.get("rooms_label"), "No disponible"))}</td>
      <td>{escape(_text(item.get("published_price_label"), "No disponible"))}</td>
      <td>{escape(_text(item.get("price_m2_label"), "No disponible"))}</td>
      <td>{escape(_text(item.get("avm_label"), "No disponible"))}</td>
      <td>{escape(_text(item.get("delta_label"), "No disponible"))}</td>
      <td>{escape(_text(item.get("confidence"), "No disponible"))}</td>
      <td>{escape(_text(item.get("alerts_label"), "No disponible"))}</td>
      <td>{escape(_text(item.get("data_freshness_status"), "No disponible"))}</td>
    </tr>
    """


def _text(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    return text or fallback


def _css() -> str:
    return """
    :root { color-scheme: dark; font-family: Inter, Arial, sans-serif; background:#07111f; color:#e5edf8; }
    body { margin:0; background:#07111f; }
    main { max-width:1180px; margin:0 auto; padding:32px; }
    header { border:1px solid #334155; border-radius:10px; padding:24px; background:#0f172a; }
    header span { color:#67e8f9; font-size:12px; font-weight:800; text-transform:uppercase; }
    h1 { margin:8px 0; font-size:30px; }
    p, footer { color:#94a3b8; }
    .cards { display:grid; grid-template-columns:repeat(auto-fit, minmax(220px, 1fr)); gap:12px; margin:18px 0; }
    article, .panel { border:1px solid #334155; border-radius:8px; background:#0b1220; padding:16px; }
    article strong, article b, article span, article small { display:block; }
    article span, article small { color:#94a3b8; margin-top:6px; }
    table { width:100%; border-collapse:collapse; font-size:13px; }
    th, td { border-bottom:1px solid #1e293b; padding:10px; text-align:left; vertical-align:top; }
    th { color:#93c5fd; font-size:11px; text-transform:uppercase; }
    footer { margin-top:18px; font-size:12px; }
    """
