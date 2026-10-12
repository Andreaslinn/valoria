import type { MarketFlow, MarketOverview } from "@/types/summary";

export type MarketMetric = "Entradas" | "Salidas" | "Rebajas";
export type MarketWidgetView = {
  total: number; previous: number | null; change: number | null;
  points: { date: string; value: number }[];
  communes: { name: string; value: number }[];
  active: number;
};
const field = { Entradas: "new_listings", Salidas: "removed_or_inactive", Rebajas: "price_drop_events" } as const;

export function marketWidgetView(flow: MarketFlow, market: MarketOverview | null, metric: MarketMetric): MarketWidgetView | null {
  // The API bins complete Chilean calendar days; UTC is used only to iterate date labels.
  const today = (flow.scope.period_end_at ?? flow.cutoff_at).slice(0, 10);
  const end = Date.parse(`${today}T00:00:00Z`);
  if (!Number.isFinite(end) || flow.status === "empty") return null;
  const day = 86400000;
  const series = new Map(flow.daily_pulse.map(point => [point.date, point[field[metric]]]));
  const window = (offset: number) => Array.from({ length: 30 }, (_, index) => {
    const date = new Date(end - (offset + 30 - index) * day).toISOString().slice(0, 10);
    return { date, value: series.get(date) };
  });
  const current = window(0), prior = window(30);
  if (current.some(point => point.value == null)) return null;
  const total = current.reduce((sum, point) => sum + point.value!, 0);
  const previous = prior.some(point => point.value == null) ? null : prior.reduce((sum, point) => sum + point.value!, 0);
  return {
    total, previous, change: previous != null && previous > 0 ? (total / previous - 1) * 100 : null,
    points: current as { date: string; value: number }[], active: flow.coverage.active_listings,
    communes: metric === "Salidas" || flow.scope.period_end_at !== market?.scope.period_end_at ? [] : (market?.communes ?? []).map(row => ({ name: row.comuna, value: metric === "Entradas" ? row.new_listings : row.price_drop_events ?? 0 })).filter(row => row.value > 0).sort((a, b) => b.value - a.value).slice(0, 5),
  };
}
