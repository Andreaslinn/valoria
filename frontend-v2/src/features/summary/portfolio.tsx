"use client";
import { useState } from "react";
import { Info } from "lucide-react";
import { Card, Tabs } from "@/components/ui/primitives";
import { periods, type Period } from "./data";
import { PortfolioChart } from "./portfolio-chart";
import type { SummaryModel } from "./use-summary";
import { historyView, pctText, portfolioView, portfolioFromWatchlist, ufText } from "./view-model";
import { StateNotice, type SummaryActions } from "./state-notice";
export function Portfolio({ model, actions }: { model: SummaryModel; actions: SummaryActions }) {
  const [period, setPeriod] = useState<Period>("90D");
  const fallback = model.sources.portfolio.phase === "error" && model.sources.watchlist.phase === "ready";
  const resource = fallback ? { phase: "ready" as const, data: portfolioFromWatchlist(model.sources.watchlist.data ?? []), error: null } : model.sources.portfolio;
  const metrics = model.fixture?.portfolio ?? (resource.data ? portfolioView(resource.data) : null);
  const chart = resource.data ? historyView(resource.data, period, model.now) : null;
  return <Card label="Tu cartera en perspectiva" className="portfolio-card">
    <div className="card-heading"><h2 className="eyebrow">Tu cartera en perspectiva</h2><Tabs options={periods} value={period} onChange={setPeriod} label="Periodo de evolución de la cartera"/></div>
    {fallback && <button className="source-note" onClick={actions.retry}>Watchlist real · {model.sources.portfolio.error} · reintentar</button>}
    {(!model.fixture && resource.phase !== "ready") || !metrics ? <StateNotice resource={resource} empty="No hay datos de cartera." {...actions}/> : !metrics.count ? <StateNotice resource={resource} empty="Tu cartera está vacía. Guarda una propiedad para comenzar." {...actions}/> : <>
      <div className="portfolio-metrics" title={metrics.note}><div><p className="portfolio-value">{ufText(metrics.total)}</p><p className="muted">{!model.fixture && metrics.covered < metrics.count ? "Valor parcial" : "Valor estimado"} · {metrics.count} propiedades guardadas</p></div><div className="portfolio-change"><p><strong className={chart?.change != null && chart.change < 0 ? "negative" : ""}>{model.fixture?.periods[period].change ?? pctText(chart?.change)}</strong> <span>{model.fixture?.periods[period].label ?? (chart ? "entre snapshots" : "sin historial")}</span></p><p className="muted">Cobertura de valoración: {metrics.covered} de {metrics.count}</p></div></div>
      <div className="chart-container">{chart || model.fixture ? <PortfolioChart period={period} real={chart} visual={model.fixture?.periods[period]}/> : <div className="portfolio-chart chart-empty" role="status">No hay snapshots suficientes para mostrar la evolución en {period}.</div>}</div>
      <div className="portfolio-footer" title={metrics.note}><div><span>{model.fixture ? "Publicación agregada" : `Publicación (${metrics.publishedCount}/${metrics.count})`}</span><strong>{ufText(metrics.published)}</strong></div><div><span>{model.fixture ? "Diferencia estimada" : `Diferencia (${metrics.matchedCount} comparables)`}</span><strong className={metrics.difference != null && metrics.difference < 0 ? "negative" : "accent"}>{pctText(metrics.difference)}</strong></div><div><span>Confianza predominante</span><strong>{metrics.confidence}</strong></div><p><Info size={14}/>Estimaciones, no precios de cierre.</p></div>
    </>}
  </Card>;
}

