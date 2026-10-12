import type { PortfolioSummary, PortfolioItem, MarketOverview, PriceTrend, PatrimonyAlert } from "@/types/summary";
import type { WatchlistItem } from "@/types/watchlist";
import type { AlertItem } from "@/types/alerts";
import type { RadarOpportunity } from "@/types/radar";
import { formatCommuneName, formatConfidence, formatNumber } from "@/lib/formatters";
import { safeExternalUrl } from "@/lib/navigation";
import type { Period } from "./data";
import type { Resource } from "./use-summary";

export const numeric = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
export const ufText = (value: number | null | undefined) => numeric(value) ? `${formatNumber(value, 0)} UF` : "—";
export const pctText = (value: number | null | undefined) => numeric(value) ? `${value > 0 ? "+" : ""}${formatNumber(value, 1)}%` : "—";
export const normalizeCommune = (name: string) => name.normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[_-]/g, " ").toLowerCase().trim();
const sum = (values: number[]) => values.length ? values.reduce((a, b) => a + b, 0) : null;

// A deployed API may expose Watchlist before Portfolio. This is real, partial data, not a mock.
export function portfolioFromWatchlist(items: WatchlistItem[]): PortfolioSummary {
  const active = items.filter(item => item.status === "active");
  const unavailable = { status: "not_available", available: false };
  return {
    user_id: 0, tracked_properties: active.length, unread_alert_count: 0,
    items: active.map(item => ({ listing_id: item.listing_id, watchlist_item_id: item.id, title: item.title, comuna: item.comuna, property_type: item.property_type ?? "unknown", m2: item.m2, bedrooms: item.dormitorios, bathrooms: item.banos, published_price_uf: item.price_currency?.trim().toUpperCase() === "UF" ? item.price_uf : null, published_price_clp: item.price_clp, price_basis: item.price_display_basis ?? "unknown", url: item.url, listing_status: item.listing_status,
      avm: { ...unavailable, estimated_value_uf: null, confidence: null, snapshot_created_at: null }, delta: { ...unavailable, delta_pct: null, delta_uf: null } })),
    history: { ...unavailable, points: [] }, average_avm_variation: { ...unavailable, variation_pct: null, observation_window_days: null }, upside: { ...unavailable, total_upside_uf: null, average_delta_pct: null },
  };
}

export function portfolioView(data: PortfolioSummary) {
  const valued = data.items.filter(item => item.avm.available && numeric(item.avm.estimated_value_uf));
  const published = data.items.filter(item => numeric(item.published_price_uf) && item.published_price_uf! > 0);
  const matched = valued.filter(item => numeric(item.published_price_uf) && item.published_price_uf! > 0);
  const matchedPublished = sum(matched.map(item => item.published_price_uf!));
  const matchedEstimated = sum(matched.map(item => item.avm.estimated_value_uf!));
  const counts = new Map<string, number>();
  valued.forEach(item => { if (item.avm.confidence) { const label = formatConfidence(item.avm.confidence); counts.set(label, (counts.get(label) ?? 0) + 1); } });
  const ranking = [...counts].sort((a, b) => b[1] - a[1]);
  const confidence = !ranking.length ? "—" : ranking[0][1] === ranking[1]?.[1] ? "Mixta" : ranking[0][0].replace("Alta confianza", "Alta").replace("Confianza media", "Media");
  const dates = valued.map(item => item.avm.snapshot_created_at).filter((date): date is string => Boolean(date)).sort();
  return {
    total: sum(valued.map(item => item.avm.estimated_value_uf!)), count: data.tracked_properties,
    covered: valued.length, published: sum(published.map(item => item.published_price_uf!)), publishedCount: published.length,
    difference: matchedPublished && matchedEstimated !== null ? (matchedEstimated - matchedPublished) / matchedPublished * 100 : null,
    matchedCount: matched.length, confidence,
    note: `Suma de las últimas valoraciones disponibles (${valued.length}/${data.tracked_properties}).${dates.length ? ` Snapshots: ${dates[0].slice(0, 10)} a ${dates.at(-1)!.slice(0, 10)}.` : ""} Publicación agregada: ${published.length} precios canónicos UF; se excluyen precios CLP sin conversión. Diferencia calculada sobre ${matched.length} propiedades con precio y valoración, con posibles fechas distintas. No representa rentabilidad.`,
  };
}

export type ChartSeries = { values: number[]; timestamps: number[]; min: number; max: number; ticks: number[]; labels: string[]; change: number | null; note: string };
export function historyView(data: PortfolioSummary, period: Period, now: number): ChartSeries | null {
  if (!data.history.available) return null;
  const days = { "30D": 30, "90D": 90, "1A": 365 }[period];
  const points = data.history.points.filter(point => {
    const timestamp = Date.parse(point.snapshot_at);
    return timestamp >= now - days * 86400000 && timestamp <= now && numeric(point.average_estimated_value_uf) && point.coverage_count > 0;
  }).sort((a, b) => Date.parse(a.snapshot_at) - Date.parse(b.snapshot_at));
  if (points.length < 2) return null;
  // Backend exposes average AVM and its coverage, not an aggregate price history.
  const values = points.map(point => point.average_estimated_value_uf * point.coverage_count);
  const low = Math.min(...values), high = Math.max(...values);
  const pad = Math.max((high - low) * .15, high * .005, 1);
  const min = Math.max(0, low - pad), max = high + pad;
  const coverageStable = points.every(point => point.coverage_count === points[0].coverage_count);
  const label = (i: number) => new Date(points[i].snapshot_at).toLocaleDateString("es-CL", { day: "2-digit", month: "short" });
  return {
    values, timestamps: points.map(point => Date.parse(point.snapshot_at)), min, max, ticks: [max, (max + min) / 2, min],
    labels: [label(0), label(Math.floor((points.length - 1) / 2)), label(points.length - 1)],
    change: coverageStable && values[0] > 0 ? (values.at(-1)! / values[0] - 1) * 100 : null,
    note: `${points.length} snapshots disponibles. Total cubierto = valoración media × propiedades valoradas. ${coverageStable ? "La composición puede cambiar; no es rentabilidad." : "Cobertura variable: no se compara el porcentaje de variación."} No hay serie publicada agregada ni banda de confianza histórica en el contrato.`,
  };
}

export function zoneSelection(watchlist: WatchlistItem[] | null, portfolio: PortfolioSummary | null, market: MarketOverview | null) {
  const names = [...new Set((portfolio?.items ?? watchlist?.filter(item => item.status === "active") ?? []).map(item => item.comuna).filter(Boolean))].slice(0, 3);
  return { names: names.length ? names : (market?.communes ?? []).filter(row => row.active_listings > 0)
    .sort((a, b) => b.active_listings - a.active_listings).slice(0, 3).map(row => row.comuna), marketSelection: names.length === 0 };
}
export function zonesView(market: MarketOverview | null, names: string[], trends: Record<string, Resource<PriceTrend>>) {
  const rows = names.map(name => {
    const row = market?.communes.find(item => normalizeCommune(item.comuna) === normalizeCommune(name));
    const resource = trends[normalizeCommune(name)];
    const trend = resource?.data;
    return { name: formatCommuneName(name), value: row?.median_price_m2_uf ?? null, count: row?.active_listings ?? 0,
      change: trend && ["available", "partial"].includes(trend.status) ? trend.change_pct : null,
      trendPhase: resource?.phase ?? "idle", trendError: resource?.error ?? null,
      trendNote: resource?.error ?? (resource?.phase === "loading" ? "Cargando variación mensual…" : trend && ["available", "partial"].includes(trend.status) && trend.points.length >= 2 ? `Variación entre los últimos meses observados (${trend.points.slice(-2).map(p => p.month).join(" → ")}); fuente: ${trend.source}. ${trend.status === "partial" ? "Cobertura parcial. " : ""}${trend.warnings.join(", ")}` : "Variación mensual no disponible: no hay observaciones suficientes para comparar."),
    };
  });
  const max = Math.max(1, ...rows.map(row => row.value ?? 0));
  return rows.map(row => ({ ...row, width: numeric(row.value) ? row.value / max * 85 : 0 }));
}

export type AlertView = { id: number; key: string; source: "watchlist" | "patrimony"; title: string; description: string; detail: string; time: string; timestamp: number; kind: "price" | "valuation" | "listing" | "notice"; previous: string | null; next: string | null; url: string | null };
function relativeDate(date: string, now: number) {
  const elapsed = now - Date.parse(date);
  if (!Number.isFinite(elapsed) || elapsed < 0) return "Fecha no disponible";
  if (elapsed < 3600000) return "Hace unos min";
  if (elapsed < 86400000) return `Hace ${Math.floor(elapsed / 3600000)} h`;
  return `Hace ${Math.floor(elapsed / 86400000)} d`;
}
export function alertsView(alerts: AlertItem[], patrimony: PatrimonyAlert[], watchlist: WatchlistItem[], now: number): AlertView[] {
  const listingAlerts: AlertView[] = alerts.filter(alert => !alert.is_read).map(alert => {
    const ufBasis = String(alert.payload.change_basis ?? "").startsWith("uf");
    const previous = ufBasis ? alert.payload.canonical_previous_price ?? alert.payload.previous_price_uf : alert.payload.canonical_previous_price ?? alert.payload.previous_price_clp_snapshot;
    const next = ufBasis ? alert.payload.canonical_new_price ?? alert.payload.new_price_uf : alert.payload.canonical_new_price ?? alert.payload.new_price_clp_snapshot;
    const price = (value: unknown) => numeric(value) ? ufBasis ? ufText(value) : `$${formatNumber(value, 0)}` : null;
    return { id: alert.id, key: `watchlist-${alert.id}`, source: "watchlist", title: alert.alert_type === "price_drop" ? "Bajó el precio de una propiedad guardada" : "Nueva alerta de tu cartera", description: [alert.title, formatCommuneName(alert.comuna)].filter(Boolean).join(" · "), detail: alert.message, time: relativeDate(alert.created_at, now), timestamp: Date.parse(alert.created_at), kind: alert.alert_type === "price_drop" ? "price" : "notice", previous: price(previous), next: price(next), url: safeExternalUrl(watchlist.find(item => item.listing_id === alert.listing_id)?.url) };
  });
  return [...listingAlerts, ...patrimony.filter(alert => !alert.read_at && !alert.dismissed_at).map((alert): AlertView => ({ id: alert.id, key: `patrimony-${alert.id}`, source: "patrimony", title: alert.title, description: alert.property_name ?? "Patrimonio", detail: alert.message, time: relativeDate(alert.created_at, now), timestamp: Date.parse(alert.created_at), kind: ["valuation_refresh_due", "property_value_changed"].includes(alert.alert_type) ? "valuation" : "notice", previous: null, next: null, url: null }))].sort((a, b) => b.timestamp - a.timestamp);
}

export function opportunityView(item: RadarOpportunity) {
  const rawConfidence = item.confidence_label || item.confidence;
  const confidence = formatConfidence(rawConfidence);
  return { id: item.listing_id, title: item.title || formatCommuneName(item.comuna),
    area: item.usable_area_m2 ?? item.built_area_m2 ?? item.m2,
    bedrooms: item.bedrooms, bathrooms: item.bathrooms, price: ufText(item.price_uf),
    estimate: ufText(item.estimated_value_uf ?? item.estimated_price_uf),
    discount: numeric(item.discount_pct) ? `${formatNumber(Math.abs(item.discount_pct), 1)}% ${item.discount_pct >= 0 ? "bajo" : "sobre"} estimación` : "Sin brecha disponible",
    confidence: confidence === "No disponible" ? rawConfidence || "—" : confidence.replace("Alta confianza", "Alta").replace("Confianza media", "Media"), comparables: item.comparables_used,
    url: safeExternalUrl(item.url), note: [item.radar_verdict_message, ...item.warnings, ...item.confidence_risk_flags].filter(Boolean).join(" · "),
  };
}

export function searchableProperties(portfolio: PortfolioSummary | null, watchlist: WatchlistItem[] | null) {
  return portfolio?.items.map((item: PortfolioItem) => ({ id: item.listing_id, title: item.title, description: `${formatCommuneName(item.comuna)} · ${ufText(item.published_price_uf)}`, url: safeExternalUrl(item.url) })) ?? watchlist?.map(item => ({ id: item.listing_id, title: item.title, description: `${formatCommuneName(item.comuna)} · ${ufText(item.price_uf_display ?? item.price_uf)}`, url: safeExternalUrl(item.url) })) ?? [];
}
