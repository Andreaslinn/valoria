"use client";

import {
  AlertTriangle,
  Bell,
  Building2,
  ChevronRight,
  CircleDollarSign,
  Compass,
  Home,
  Loader2,
  Radar,
  TrendingDown,
  TrendingUp,
  WalletCards,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { ButtonLink } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";
import { DashboardFilters } from "@/features/dashboard/DashboardFilters";
import { MarketPulseChart } from "@/features/dashboard/MarketPulseChart";
import { listAlerts } from "@/lib/api/alerts";
import { me, type User } from "@/lib/api/auth";
import { getMarketDashboard } from "@/lib/api/market";
import { listPatrimonyProperties } from "@/lib/api/patrimony";
import { getRadarSummary } from "@/lib/api/radar";
import { getRecentTasarActivity, type RecentTasarActivity } from "@/lib/api/tasar";
import { listWatchlist } from "@/lib/api/watchlist";
import { formatCommuneName, formatConfidence, formatNumber, formatPropertyType, formatUf, pluralizeEs } from "@/lib/formatters";
import type { AlertItem } from "@/types/alerts";
import type { MarketDashboard, MarketDashboardCommune } from "@/types/market";
import type { PropertyAsset } from "@/types/patrimony";
import type { RadarSummary } from "@/types/radar";
import type { WatchlistItem } from "@/types/watchlist";

type Loadable<T> = { data: T | null; loading: boolean; error: string | null };
const pending = <T,>(): Loadable<T> => ({ data: null, loading: true, error: null });

export function DashboardWorkspace() {
  const [market, setMarket] = useState<Loadable<MarketDashboard>>(pending);
  const [user, setUser] = useState<Loadable<User>>(pending);
  const [radar, setRadar] = useState<Loadable<RadarSummary>>(pending);
  const [activity, setActivity] = useState<Loadable<RecentTasarActivity>>(pending);
  const [properties, setProperties] = useState<Loadable<PropertyAsset[]>>(pending);
  const [watchlist, setWatchlist] = useState<Loadable<WatchlistItem[]>>(pending);
  const [alerts, setAlerts] = useState<Loadable<AlertItem[]>>(pending);
  const [periodDays, setPeriodDays] = useState<7 | 30 | 90>(30);
  const [commune, setCommune] = useState("");
  const [selectedCommune, setSelectedCommune] = useState<string | null>(null);

  const loadMarket = useCallback(async (nextSelected: string | null) => {
    setMarket((current) => ({ ...current, loading: true, error: null }));
    try {
      const data = await getMarketDashboard({ commune: commune || null, periodDays, selectedCommune: nextSelected });
      setMarket({ data, loading: false, error: null });
    } catch {
      setMarket((current) => ({ ...current, loading: false, error: "No pudimos actualizar el mercado." }));
    }
  }, [commune, periodDays]);

  useEffect(() => { void loadMarket(null); }, [loadMarket]); // Filters refresh only the market contract.
  useEffect(() => {
    void Promise.all([
      me().then((data) => setUser({ data, loading: false, error: null })).catch(() => setUser({ data: null, loading: false, error: "Sesion no disponible" })),
      getRadarSummary().then((data) => setRadar({ data, loading: false, error: null })).catch(() => setRadar({ data: null, loading: false, error: "Radar no disponible" })),
      getRecentTasarActivity(3).then((data) => setActivity({ data, loading: false, error: null })).catch(() => setActivity({ data: null, loading: false, error: "Tasacion no disponible" })),
      listPatrimonyProperties().then((data) => setProperties({ data: data.items, loading: false, error: null })).catch(() => setProperties({ data: null, loading: false, error: "Patrimonio no disponible" })),
      listWatchlist().then((data) => setWatchlist({ data, loading: false, error: null })).catch(() => setWatchlist({ data: null, loading: false, error: "Watchlist no disponible" })),
      listAlerts(3).then((data) => setAlerts({ data, loading: false, error: null })).catch(() => setAlerts({ data: null, loading: false, error: "Alertas no disponibles" })),
    ]);
  }, []);

  const marketData = market.data;
  const communes = useMemo(() => marketData?.communes.map((item) => item.comuna) ?? [], [marketData]);
  const selected = useMemo(() => {
    if (marketData?.selected_commune?.status === "available") return marketData.selected_commune;
    return marketData?.communes.find((item) => item.comuna === selectedCommune) ?? marketData?.communes[0] ?? null;
  }, [marketData, selectedCommune]);
  const latestValuation = useMemo(() => (activity.data?.events ?? []).find((event) => event.estimated_value_uf != null) ?? null, [activity.data]);
  const unreadAlerts = useMemo(() => (alerts.data ?? []).filter((item) => !item.is_read), [alerts.data]);

  function changeCommune(value: string) {
    setCommune(value);
    setSelectedCommune(null);
  }

  function chooseCommune(value: string) {
    setSelectedCommune(value);
    void loadMarket(value);
  }

  return (
    <div className="mx-auto max-w-[1320px] space-y-2 pb-2">
      <header className="flex flex-col gap-4 pb-3 pt-1 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-ink sm:text-3xl">Buenos dias, {displayName(user.data)}</h1>
          <p className="mt-1 text-sm text-muted">Asi se esta moviendo el mercado inmobiliario hoy.</p>
        </div>
        <DashboardFilters communes={communes} commune={commune} loading={market.loading} onCommuneChange={changeCommune} onPeriodChange={setPeriodDays} periodDays={periodDays} />
      </header>

      {market.error ? <InlineError message={market.error} /> : null}

      <section className="grid min-w-0 gap-2 xl:grid-cols-[minmax(0,2.35fr)_minmax(170px,0.85fr)_minmax(170px,0.85fr)_minmax(170px,0.85fr)]">
        <MarketStatusCard data={marketData} loading={market.loading} />
        <MetricCard accent="blue" icon={<Building2 />} label="Nuevas publicaciones" loading={market.loading} subtitle={`Ultimos ${periodDays} dias`} value={marketData?.overview.new_listings} />
        <MetricCard accent="orange" icon={<TrendingDown />} label="Retiradas del mercado" loading={market.loading} subtitle={`Ultimos ${periodDays} dias`} value={marketData?.overview.removed_or_inactive} />
        <MetricCard accent="green" icon={<TrendingUp />} label="Propiedades con rebaja" loading={market.loading} subtitle={`Ultimos ${periodDays} dias`} value={marketData?.overview.listings_with_price_drop} />
      </section>

      <Card className="min-w-0 p-4 sm:p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div><CardTitle>Pulso del mercado</CardTitle><p className="text-sm text-muted">Movimiento diario de publicaciones</p></div>
          <PeriodTabs onChange={setPeriodDays} periodDays={periodDays} />
        </div>
        {market.loading && !marketData ? <ChartSkeleton /> : <MarketPulseChart data={marketData?.daily_pulse ?? []} />}
        <p className="mt-2 border-t border-line pt-3 text-sm text-muted">{pulseInsight(marketData)}</p>
      </Card>

      <section className="grid min-w-0 gap-2 xl:grid-cols-[minmax(0,1.03fr)_minmax(0,0.97fr)]">
        <CommunesCard communes={marketData?.communes ?? []} loading={market.loading} onSelect={chooseCommune} selected={selected?.comuna ?? null} detail={selected} />
        <BedroomsCard data={marketData?.bedrooms_supply ?? []} loading={market.loading} />
      </section>

      <section className="grid min-w-0 gap-2 xl:grid-cols-2">
        <RadarCard state={radar} />
        <ValuationCard valuation={latestValuation} state={activity} />
      </section>

      <section className="grid min-w-0 gap-2 xl:grid-cols-2">
        <PatrimonyCard properties={properties} />
        <FollowUpCard alerts={unreadAlerts} watchlist={watchlist} />
      </section>
    </div>
  );
}

function MarketStatusCard({ data, loading }: { data: MarketDashboard | null; loading: boolean }) {
  const balance = data?.overview.market_balance;
  const score = Math.max(0, Math.min(100, balance?.score ?? 50));
  const netFlow = (data?.overview.new_listings ?? 0) - (data?.overview.removed_or_inactive ?? 0);
  const activeListings = data?.coverage.active_listings;
  return (
    <Card className="min-w-0 p-4 sm:p-5">
      <CardTitle>Balance del mercado</CardTitle>
      <div className="mt-3 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <p className="text-lg font-semibold text-ink">{balance?.label ?? "Sin datos suficientes"}</p>
        <p className="text-sm font-semibold text-muted">{loading && !data ? "..." : balance?.score ?? "-"} <span className="font-medium">/ 100</span></p>
      </div>

      <div className="mt-5 min-w-0">
        <div className="relative h-3 rounded-full bg-gradient-to-r from-orange-400/70 via-white/20 to-accent-500/70">
          <span className="absolute top-1/2 h-5 w-5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-[#09101a] bg-ink shadow-[0_0_0_2px_rgba(124,92,255,0.8)]" style={{ left: `${score}%` }} />
        </div>
        <div className="mt-2 grid grid-cols-3 text-xs font-medium text-muted">
          <span>Vendedor</span><span className="text-center">Equilibrado</span><span className="text-right">Comprador</span>
        </div>
      </div>

      <div className="mt-5 grid min-w-0 gap-3 sm:grid-cols-3">
        <BalanceFactor label="Oferta neta" value={loading && !data ? "..." : signedNumber(netFlow)} />
        <BalanceFactor label="Rebajas" value={loading && !data ? "..." : formatNumber(data?.overview.listings_with_price_drop, 0)} />
        <BalanceFactor label="Tiempo publicado" value={data?.overview.median_observed_days == null ? "Sin dato" : `${formatNumber(data.overview.median_observed_days, 0)} dias`} />
      </div>

      <p className="mt-4 max-w-3xl text-sm leading-6 text-muted">{balance?.summary ?? "Aun no hay suficientes publicaciones para interpretar el balance del periodo seleccionado."}</p>
      <p className="mt-3 text-xs text-muted">Confianza {confidenceLabel(data?.overview.confidence)}{activeListings != null ? ` · Basado en ${formatNumber(activeListings, 0)} publicaciones` : ""}</p>
    </Card>
  );
}

function BalanceFactor({ label, value }: { label: string; value: string }) { return <div className="min-w-0 border-l border-line pl-3 first:border-l-0 first:pl-0"><p className="text-xs text-muted">{label}</p><p className="mt-1 break-words text-sm font-semibold text-ink">{value}</p></div>; }
function signedNumber(value: number) { return `${value > 0 ? "+" : value < 0 ? "-" : ""}${formatNumber(Math.abs(value), 0)}`; }

function MetricCard({ accent, icon, label, loading, subtitle, value }: { accent: "blue" | "orange" | "green"; icon: React.ReactNode; label: string; loading: boolean; subtitle: string; value: number | undefined }) {
  const tones = { blue: "text-brand-500", orange: "text-orange-300", green: "text-accent-500" };
  return <Card className="min-h-[150px] p-4"><span className={tones[accent]}>{icon}</span><p className="mt-3 text-2xl font-semibold text-ink">{loading && value == null ? "..." : formatNumber(value, 0)}</p><p className="mt-1 text-sm font-medium text-ink">{label}</p><p className="mt-1 text-xs text-muted">{subtitle}</p></Card>;
}

function PeriodTabs({ onChange, periodDays }: { onChange: (value: 7 | 30 | 90) => void; periodDays: 7 | 30 | 90 }) { return <div className="flex rounded-lg border border-line bg-black/20 p-1">{([7, 30, 90] as const).map((value) => <button className={`min-h-7 rounded-md px-3 text-xs font-semibold ${periodDays === value ? "bg-brand-600 text-white" : "text-muted hover:text-ink"}`} key={value} onClick={() => onChange(value)} type="button">{value}D</button>)}</div>; }

function CommunesCard({ communes, detail, loading, onSelect, selected }: { communes: MarketDashboardCommune[]; detail: MarketDashboardCommune | null; loading: boolean; onSelect: (value: string) => void; selected: string | null }) {
  const chartData = communes.slice(0, 6).map((item) => ({ ...item, label: formatCommuneName(item.comuna), score: item.dynamism.score ?? 0 }));
  return <Card className="min-w-0 p-4 sm:p-5"><CardTitle>Comunas en movimiento</CardTitle><div className="mt-3 grid min-w-0 gap-4 lg:grid-cols-[minmax(0,1.15fr)_minmax(190px,0.85fr)]"><div className="h-[190px] min-w-0">{loading && !communes.length ? <ChartSkeleton /> : <ResponsiveContainer height="100%" width="100%"><BarChart data={chartData} layout="vertical" margin={{ left: -8, right: 24 }}><XAxis hide type="number" /><YAxis axisLine={false} dataKey="label" tick={{ fill: "#d7dde8", fontSize: 12 }} tickLine={false} type="category" width={84} /><Tooltip cursor={{ fill: "rgba(255,255,255,0.05)" }} contentStyle={{ background: "#0a101a", border: "1px solid rgba(148,163,184,0.2)", borderRadius: 8 }} formatter={(value) => [formatNumber(Number(value), 0), "Dinamismo"]} /><Bar dataKey="score" onClick={(item) => onSelect(item.comuna)} radius={[0, 3, 3, 0]}>{chartData.map((item) => <Cell cursor="pointer" fill={item.comuna === selected ? "#7891ff" : "#4a61c8"} key={item.comuna} />)}</Bar></BarChart></ResponsiveContainer>}</div><CommuneDetail detail={detail} /></div></Card>;
}

function CommuneDetail({ detail }: { detail: MarketDashboardCommune | null }) { if (!detail) return <div className="border-l border-line pl-4 text-sm text-muted">Selecciona una comuna para ver su detalle.</div>; return <div className="border-l border-line pl-4"><p className="text-lg font-semibold text-ink">{formatCommuneName(detail.comuna)}</p><ul className="mt-2 space-y-1 text-sm text-muted"><li>{formatNumber(detail.median_price_m2_uf, 1)} UF/m²</li><li>{detail.median_observed_days == null ? "Tiempo observado no disponible" : `${detail.median_observed_days} dias publicados`}</li><li>{formatNumber(detail.new_listings, 0)} nuevas en el periodo</li><li>{formatNumber(detail.listings_with_price_drop, 0)} rebajas</li><li>{detail.market_balance.label}</li></ul><ButtonLink className="mt-3 min-h-9 px-3" href="/app/radar" variant="secondary">Ver mercado <ChevronRight className="h-4 w-4" /></ButtonLink></div>; }

function BedroomsCard({ data, loading }: { data: MarketDashboard["bedrooms_supply"]; loading: boolean }) { const labels: Record<string, string> = { "1": "1 dormitorio", "2": "2 dormitorios", "3": "3 dormitorios", "4_plus": "4+ dormitorios" }; const chartData = data.map((item) => ({ ...item, label: labels[item.bucket] })); return <Card className="min-w-0 p-4 sm:p-5"><CardTitle>Oferta disponible</CardTitle><p className="text-sm text-muted">Distribucion por dormitorios</p><div className="mt-4 h-[190px] min-w-0">{loading && !data.length ? <ChartSkeleton /> : <ResponsiveContainer height="100%" width="100%"><BarChart data={chartData} layout="vertical" margin={{ left: 12, right: 20 }}><XAxis hide type="number" /><YAxis axisLine={false} dataKey="label" tick={{ fill: "#d7dde8", fontSize: 12 }} tickLine={false} type="category" width={105} /><Tooltip cursor={{ fill: "rgba(255,255,255,0.05)" }} contentStyle={{ background: "#0a101a", border: "1px solid rgba(148,163,184,0.2)", borderRadius: 8 }} formatter={(value) => [formatNumber(Number(value), 0), "Publicaciones activas"]} /><Bar dataKey="active_listings" fill="#5f75dc" radius={[0, 3, 3, 0]} /></BarChart></ResponsiveContainer>}</div></Card>; }

function RadarCard({ state }: { state: Loadable<RadarSummary> }) { const data = state.data; return <Card className="flex min-w-0 flex-col justify-between gap-4 p-4 sm:flex-row sm:items-center"><div className="flex min-w-0 gap-3"><span className="grid h-11 w-11 shrink-0 place-items-center rounded-full border border-brand-500/35 text-brand-500"><Radar className="h-5 w-5" /></span><div><CardTitle>Radar</CardTitle><p className="mt-1 text-sm text-ink">{state.loading ? "Actualizando resumen..." : `${formatNumber(data?.active_scope_count, 0)} publicaciones monitoreadas.`}</p><p className="text-sm text-muted">{data?.summary ?? state.error ?? "Oportunidades bajo demanda."}</p></div></div><ButtonLink className="shrink-0" href="/app/radar" variant="secondary"><Compass className="h-4 w-4" />Abrir Radar</ButtonLink></Card>; }

function ValuationCard({ state, valuation }: { state: Loadable<RecentTasarActivity>; valuation: RecentTasarActivity["events"][number] | null }) { return <Card className="flex min-w-0 flex-col justify-between gap-4 p-4 sm:flex-row sm:items-center"><div className="flex min-w-0 gap-3"><span className="grid h-11 w-11 shrink-0 place-items-center rounded-full border border-brand-500/35 text-brand-500"><CircleDollarSign className="h-5 w-5" /></span><div><CardTitle>Ultima tasacion</CardTitle>{valuation ? <><p className="mt-1 text-sm text-muted">{formatPropertyType(valuation.property_type)} · {formatCommuneName(valuation.comuna)}</p><p className="text-2xl font-semibold text-ink">{formatUf(valuation.estimated_value_uf)}</p><p className="text-xs text-muted">{valuation.range_low_uf && valuation.range_high_uf ? `${formatUf(valuation.range_low_uf)} - ${formatUf(valuation.range_high_uf)}` : valuation.confidence ? `Confianza: ${formatConfidence(valuation.confidence)}` : ""}</p></> : <p className="mt-1 text-sm text-muted">{state.loading ? "Cargando tasacion..." : state.error ?? "Aun no hay tasaciones guardadas."}</p>}</div></div><ButtonLink className="shrink-0" href="/app/tasar" variant="secondary">{valuation ? "Ver tasacion" : "Tasar propiedad"}</ButtonLink></Card>; }

function PatrimonyCard({ properties }: { properties: Loadable<PropertyAsset[]> }) { const property = properties.data?.[0]; return <Card className="flex min-w-0 flex-col justify-between gap-4 p-4 sm:flex-row sm:items-center"><div className="flex gap-3"><span className="grid h-11 w-11 shrink-0 place-items-center rounded-full border border-accent-500/35 text-accent-500"><Home className="h-5 w-5" /></span><div><CardTitle>Mi patrimonio</CardTitle><p className="mt-1 text-sm text-ink">{properties.loading ? "Cargando propiedad..." : property?.name ?? "Aun no tienes propiedades guardadas."}</p><p className="text-sm text-muted">{property ? "Tu propiedad esta guardada y lista para seguimiento." : "Guarda una tasacion para comenzar."}</p></div></div><ButtonLink className="shrink-0" href="/app/patrimonio" variant="secondary">Abrir Mi patrimonio</ButtonLink></Card>; }

function FollowUpCard({ alerts, watchlist }: { alerts: AlertItem[]; watchlist: Loadable<WatchlistItem[]> }) { return <Card className="flex min-w-0 flex-col justify-between gap-4 p-4 sm:flex-row sm:items-center"><div className="flex gap-3"><span className="grid h-11 w-11 shrink-0 place-items-center rounded-full border border-orange-400/35 text-orange-300"><WalletCards className="h-5 w-5" /></span><div><CardTitle>En seguimiento</CardTitle><p className="mt-1 text-sm text-ink">{watchlist.loading ? "Cargando publicaciones..." : `${formatNumber(watchlist.data?.length, 0)} ${pluralizeEs(watchlist.data?.length, "propiedad guardada", "propiedades guardadas")}.`}</p><p className="text-sm text-muted">{alerts.length ? `${alerts.length} ${pluralizeEs(alerts.length, "alerta reciente", "alertas recientes")}.` : "Sin alertas recientes."}</p></div></div><ButtonLink className="shrink-0" href="/app/portfolio" variant="secondary"><Bell className="h-4 w-4" />Ver Watchlist</ButtonLink></Card>; }

function ChartSkeleton() { return <div className="grid h-full place-items-center text-sm text-muted"><Loader2 className="mr-2 inline h-4 w-4 animate-spin" />Actualizando datos...</div>; }
function InlineError({ message }: { message: string }) { return <div className="flex items-center gap-2 rounded-lg border border-orange-400/30 bg-orange-400/10 px-3 py-2 text-sm text-orange-100"><AlertTriangle className="h-4 w-4" />{message}</div>; }
function displayName(user: User | null) { return user?.email?.split("@")[0] || ""; }
function confidenceLabel(value: string | undefined) { return value === "high" ? "alta" : value === "low" ? "baja" : "media"; }
function pulseInsight(data: MarketDashboard | null) { if (!data) return "Aun no hay suficiente actividad para interpretar el pulso del mercado."; const net = data.overview.new_listings - data.overview.removed_or_inactive; return net > 0 ? `Durante los ultimos ${data.scope.period_days} dias ingresaron mas publicaciones de las que salieron. La oferta disponible esta aumentando.` : net < 0 ? `Durante los ultimos ${data.scope.period_days} dias salieron mas publicaciones de las que ingresaron.` : `Durante los ultimos ${data.scope.period_days} dias, entradas y salidas se mantuvieron equilibradas.`; }
