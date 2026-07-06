"use client";

import Link from "next/link";
import {
  AlertTriangle,
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  Bell,
  Building2,
  CircleDollarSign,
  Clock3,
  Compass,
  Gauge,
  Home,
  LineChart,
  Link2,
  Loader2,
  MapPinned,
  Radar,
  Search,
  ShieldCheck,
  Sparkles,
  WalletCards,
} from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { ButtonLink } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";
import { listAlerts } from "@/lib/api/alerts";
import { me, type User } from "@/lib/api/auth";
import {
  getCurrentUf,
  getLiquiditySummary,
  getMarketBriefing,
  getMicrozonesSummary,
} from "@/lib/api/market";
import { getRadarSummary } from "@/lib/api/radar";
import { getRecentTasarActivity, type RecentTasarActivity } from "@/lib/api/tasar";
import { listWatchlist } from "@/lib/api/watchlist";
import {
  formatClp,
  formatConfidence,
  formatDate,
  formatDateTime,
  formatM2,
  formatPropertyType,
  formatText,
  formatUf,
} from "@/lib/formatters";
import type { AlertItem } from "@/types/alerts";
import type {
  LiquiditySummary,
  MarketBriefing as MarketBriefingContract,
  MarketIndicator,
  MicrozonesSummary,
  UFRate,
} from "@/types/market";
import type { RadarSummary } from "@/types/radar";
import type { WatchlistItem } from "@/types/watchlist";

type LoadState<T> = {
  data: T | null;
  error: string | null;
  loading: boolean;
};

type MetricStatus = "available" | "empty" | "coming_soon" | "error" | "manual";
type Tone = "green" | "orange" | "blue" | "neutral";

const initialState = <T,>(): LoadState<T> => ({
  data: null,
  error: null,
  loading: true,
});

const quickActions = [
  {
    description: "Calcula valor estimado con comparables reales.",
    href: "/app/tasar",
    icon: Home,
    title: "Tasar propiedad",
    tone: "green" as Tone,
  },
  {
    description: "Revisa cualquier aviso soportado.",
    href: "/app/analizar-url",
    icon: Link2,
    title: "Analizar publicacion",
    tone: "blue" as Tone,
  },
  {
    description: "Busca oportunidades cuando lo necesites.",
    href: "/app/radar",
    icon: Search,
    title: "Explorar oportunidades",
    tone: "orange" as Tone,
  },
];

export function DashboardWorkspace() {
  const [user, setUser] = useState<LoadState<User>>(initialState);
  const [watchlist, setWatchlist] = useState<LoadState<WatchlistItem[]>>(initialState);
  const [alerts, setAlerts] = useState<LoadState<AlertItem[]>>(initialState);
  const [uf, setUf] = useState<LoadState<UFRate>>(initialState);
  const [activity, setActivity] = useState<LoadState<RecentTasarActivity>>(initialState);
  const [briefing, setBriefing] = useState<LoadState<MarketBriefingContract>>(initialState);
  const [liquidity, setLiquidity] = useState<LoadState<LiquiditySummary>>(initialState);
  const [microzones, setMicrozones] = useState<LoadState<MicrozonesSummary>>(initialState);
  const [radarSummary, setRadarSummary] = useState<LoadState<RadarSummary>>(initialState);

  useEffect(() => {
    void loadUser();
    void loadWatchlist();
    void loadAlerts();
    void loadUf();
    void loadActivity();
    void loadBriefing();
    void loadLiquidity();
    void loadMicrozones();
    void loadRadarSummary();
  }, []);

  async function loadUser() {
    setUser({ data: null, error: null, loading: true });
    try {
      setUser({ data: await me(), error: null, loading: false });
    } catch {
      setUser({ data: null, error: "Sesion no disponible", loading: false });
    }
  }

  async function loadWatchlist() {
    setWatchlist({ data: null, error: null, loading: true });
    try {
      setWatchlist({ data: await listWatchlist(), error: null, loading: false });
    } catch {
      setWatchlist({ data: null, error: "No se pudo cargar Watchlist", loading: false });
    }
  }

  async function loadAlerts() {
    setAlerts({ data: null, error: null, loading: true });
    try {
      setAlerts({ data: await listAlerts(6), error: null, loading: false });
    } catch {
      setAlerts({ data: null, error: "No se pudo cargar Alertas", loading: false });
    }
  }

  async function loadUf() {
    setUf({ data: null, error: null, loading: true });
    try {
      setUf({ data: await getCurrentUf(), error: null, loading: false });
    } catch {
      setUf({ data: null, error: "UF no disponible", loading: false });
    }
  }

  async function loadActivity() {
    setActivity({ data: null, error: null, loading: true });
    try {
      setActivity({ data: await getRecentTasarActivity(3), error: null, loading: false });
    } catch {
      setActivity({ data: null, error: "Actividad reciente no disponible", loading: false });
    }
  }

  async function loadBriefing() {
    setBriefing({ data: null, error: null, loading: true });
    try {
      setBriefing({ data: await getMarketBriefing(), error: null, loading: false });
    } catch {
      setBriefing({ data: null, error: "Briefing de mercado no disponible", loading: false });
    }
  }

  async function loadLiquidity() {
    setLiquidity({ data: null, error: null, loading: true });
    try {
      setLiquidity({ data: await getLiquiditySummary(), error: null, loading: false });
    } catch {
      setLiquidity({ data: null, error: "Liquidez no disponible", loading: false });
    }
  }

  async function loadMicrozones() {
    setMicrozones({ data: null, error: null, loading: true });
    try {
      setMicrozones({ data: await getMicrozonesSummary(), error: null, loading: false });
    } catch {
      setMicrozones({ data: null, error: "Microzonas no disponibles", loading: false });
    }
  }

  async function loadRadarSummary() {
    setRadarSummary({ data: null, error: null, loading: true });
    try {
      setRadarSummary({ data: await getRadarSummary(), error: null, loading: false });
    } catch {
      setRadarSummary({ data: null, error: "Resumen Radar no disponible", loading: false });
    }
  }

  const watchlistItems = useMemo(() => watchlist.data ?? [], [watchlist.data]);
  const alertItems = useMemo(() => alerts.data ?? [], [alerts.data]);
  const latestValuation = useMemo(
    () => (activity.data?.events ?? []).find((event) => event.estimated_value_uf),
    [activity.data],
  );
  const unreadAlerts = useMemo(() => alertItems.filter((alert) => !alert.is_read), [alertItems]);
  const userName = user.data ? displayName(user.data) : "usuario beta";

  return (
    <div className="space-y-4">
      <section className="grid min-w-0 gap-6 min-[1500px]:grid-cols-[minmax(0,1fr)_minmax(360px,420px)] min-[1800px]:grid-cols-[minmax(0,1fr)_minmax(400px,480px)]">
        <MarketBriefing briefing={briefing} userName={userName} />
        <FeaturedValuation activity={activity} latestValuation={latestValuation ?? null} />
      </section>

      <section className="grid min-w-0 gap-6 min-[1500px]:grid-cols-[minmax(0,1fr)_minmax(360px,420px)] min-[1800px]:grid-cols-[minmax(0,1fr)_minmax(400px,480px)]">
        <div className="min-w-0 space-y-4">
          <div className="grid grid-cols-[repeat(auto-fit,minmax(260px,1fr))] gap-4">
            <MetricCard
              description="Pendiente de contrato."
              icon={<Gauge className="h-5 w-5" aria-hidden />}
              label={briefing.data?.valoria_index.label ?? "Indice AVM"}
              status={toMetricStatus(briefing.data?.valoria_index.status, briefing)}
              title={briefing.data?.valoria_index.confidence_label ?? "En preparacion"}
              visual={<Sparkline status="coming_soon" />}
            />
            <MetricCard
              description={radarSummary.data?.summary ?? "Radar manual."}
              icon={<Radar className="h-5 w-5" aria-hidden />}
              label="Radar"
              status={toMetricStatus(radarSummary.data?.mode ?? radarSummary.data?.status, radarSummary)}
              title={radarSummary.data?.title ?? "Ejecucion manual"}
              visual={<RadarMini />}
            />
            <MetricCard
              description={liquidity.data?.message ?? "Requiere contrato de liquidez."}
              icon={<LineChart className="h-5 w-5" aria-hidden />}
              label={liquidity.data?.label ?? "Liquidez del mercado"}
              status={toMetricStatus(liquidity.data?.status, liquidity)}
              title={liquidity.data?.available ? formatNullableScore(liquidity.data.value, liquidity.data.max) : "Proximamente"}
              visual={<Sparkline status="coming_soon" />}
            />
          </div>
          <QuickActions />
          <div className="grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
            <RadarPanel state={radarSummary} />
            <MicrozonesPanel state={microzones} />
          </div>
        </div>

        <div className="min-w-0 space-y-4">
          <WatchlistPanel items={watchlistItems} state={watchlist} />
          <AlertsPanel alerts={alertItems} state={alerts} unreadCount={unreadAlerts.length} />
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-3">
        <DataStatusCard
          description={ufDescription(uf)}
          icon={<CircleDollarSign className="h-5 w-5" aria-hidden />}
          label="UF"
          status={ufStatus(uf)}
          value={uf.loading ? "Cargando" : uf.error ? "No disponible" : formatClp(uf.data?.rate_clp)}
        />
        <DataStatusCard
          description={watchlist.error || "Fuente: /api/v1/watchlist"}
          icon={<WalletCards className="h-5 w-5" aria-hidden />}
          label="Watchlist"
          status={watchlist.error ? "error" : watchlist.loading ? "empty" : "available"}
          value={watchlist.loading ? "Cargando" : `${watchlistItems.length} guardada${watchlistItems.length === 1 ? "" : "s"}`}
        />
        <DataStatusCard
          description={alerts.error || "Fuente: /api/v1/alerts"}
          icon={<Bell className="h-5 w-5" aria-hidden />}
          label="Alertas"
          status={alerts.error ? "error" : alerts.loading ? "empty" : "available"}
          value={alerts.loading ? "Cargando" : `${unreadAlerts.length} sin leer`}
        />
      </section>
    </div>
  );
}

function MarketBriefing({
  briefing,
  userName,
}: {
  briefing: LoadState<MarketBriefingContract>;
  userName: string;
}) {
  const data = briefing.data;
  const indicators = data?.indicators ?? [];
  return (
    <Card className="overflow-hidden border-white/10 bg-[radial-gradient(circle_at_82%_20%,rgba(61,220,151,0.12),transparent_28rem),linear-gradient(135deg,rgba(255,255,255,0.075),rgba(255,255,255,0.035))] p-0">
      <div className="grid gap-5 p-6 lg:grid-cols-[minmax(0,1fr)_230px]">
        <div>
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-orange-200">
            <Sparkles className="h-4 w-4" aria-hidden />
            Briefing del mercado
          </div>
          <h1 className="mt-5 max-w-2xl text-3xl font-semibold tracking-normal text-ink md:text-4xl">
            {data?.headline ?? "Cockpit Valoria para decidir con mejor evidencia."}
          </h1>
          <p className="mt-4 max-w-2xl text-sm leading-6 text-muted">
            Hola, {userName}. {data?.summary ?? "El briefing de mercado se activara cuando exista un contrato real de mercado, liquidez y tendencia."}
          </p>

          <div className="mt-7 grid gap-3 sm:grid-cols-3">
            <BriefingSignal
              icon={<Building2 className="h-5 w-5" aria-hidden />}
              label={indicatorByKey(indicators, "supply")?.label ?? "Oferta en mercado"}
              status={toMetricStatus(indicatorByKey(indicators, "supply")?.status, briefing)}
              value={indicatorValue(indicatorByKey(indicators, "supply"))}
            />
            <BriefingSignal
              icon={<Clock3 className="h-5 w-5" aria-hidden />}
              label={indicatorByKey(indicators, "time_to_sell")?.label ?? "Tiempo de venta"}
              status={toMetricStatus(indicatorByKey(indicators, "time_to_sell")?.status, briefing)}
              value={indicatorValue(indicatorByKey(indicators, "time_to_sell"))}
            />
            <BriefingSignal
              icon={<Compass className="h-5 w-5" aria-hidden />}
              label={indicatorByKey(indicators, "opportunities")?.label ?? "Oportunidades"}
              status={toMetricStatus(indicatorByKey(indicators, "opportunities")?.status, briefing)}
              value={indicatorValue(indicatorByKey(indicators, "opportunities"))}
            />
          </div>
        </div>
        <div className="flex flex-col items-center justify-center rounded-lg border border-line bg-black/20 p-4">
          <ValoriaGauge value={data?.valoria_index.value ?? null} />
          <p className="mt-3 text-sm font-semibold text-ink">{data?.valoria_index.label ?? "Indice Valoria"}</p>
          <p className="mt-1 text-center text-xs leading-5 text-muted">
            {data?.valoria_index.description ?? "Esperando contrato de mercado para publicar una senal agregada."}
          </p>
        </div>
      </div>
      <div className="border-t border-line bg-black/20 px-6 py-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 items-start gap-3">
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-blue-400/30 bg-blue-400/10 text-blue-200">
              <ShieldCheck className="h-4 w-4" aria-hidden />
            </span>
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-blue-100">
                Insight del dia
              </p>
              <p className="mt-1 text-sm leading-6 text-muted">
                {briefing.error || data?.insight.text || "Sin metricas simuladas: Valoria muestra estados honestos hasta contar con contratos de mercado y microzona."}
              </p>
            </div>
          </div>
          <ButtonLink href="/app/reportes" variant="secondary">
            Ver roadmap
            <ArrowRight className="h-4 w-4" aria-hidden />
          </ButtonLink>
        </div>
      </div>
    </Card>
  );
}

function FeaturedValuation({
  activity,
  latestValuation,
}: {
  activity: LoadState<RecentTasarActivity>;
  latestValuation: RecentTasarActivity["events"][number] | null;
}) {
  if (activity.loading) {
    return (
      <Card className="min-h-[360px] p-6">
        <LoadingLine label="Cargando tasaciones recientes..." />
      </Card>
    );
  }

  if (activity.error || !latestValuation) {
    return (
      <Card className="min-h-[360px] p-6">
        <PanelHeader
          action={<StatusPill status={activity.error ? "error" : "empty"} />}
          kicker="Tasacion destacada"
          title="Aun no tienes tasaciones recientes"
        />
        <p className="mt-4 text-sm leading-6 text-muted">
          Cuando ejecutes una tasacion, Valoria mostrara aqui el ultimo resultado disponible
          con rango, confianza y trazabilidad.
        </p>
        <div className="mt-8 rounded-lg border border-dashed border-line bg-black/20 p-6">
          <RangeBar current={null} max={null} min={null} />
          <MiniTrendChart status="empty" />
        </div>
        <div className="mt-6">
          <ButtonLink href="/app/tasar">
            Tasar propiedad
            <ArrowRight className="h-4 w-4" aria-hidden />
          </ButtonLink>
        </div>
      </Card>
    );
  }

  return (
    <Card className="min-h-[360px] p-6">
      <PanelHeader
        action={<StatusPill status="available" />}
        kicker="Tasacion destacada"
        title={formatText(latestValuation.title, "Tasacion reciente")}
      />
      <p className="mt-1 text-sm text-muted">
        {formatText(latestValuation.comuna)} · {formatPropertyType(latestValuation.property_type)}
      </p>
      <div className="mt-7 grid grid-cols-[1fr_auto] gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted">
            Valor estimado
          </p>
          <p className="mt-2 text-4xl font-semibold tracking-normal text-ink">
            {formatUf(latestValuation.estimated_value_uf)}
          </p>
        </div>
        <div className="rounded-lg border border-line bg-black/20 px-4 py-3 text-right">
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted">
            Confianza
          </p>
          <p className="mt-2 text-xl font-semibold text-emerald-200">
            {formatConfidence(latestValuation.confidence)}
          </p>
        </div>
      </div>
      <div className="mt-7">
        <RangeBar
          current={latestValuation.estimated_value_uf ?? null}
          max={latestValuation.range_high_uf ?? null}
          min={latestValuation.range_low_uf ?? null}
        />
        <MiniTrendChart
          status={latestValuation.trend_points_uf?.length ? "available" : "empty"}
        />
      </div>
      <div className="mt-6">
        <ButtonLink href="/app/tasar" variant="secondary">
          Ver tasacion completa
          <ArrowRight className="h-4 w-4" aria-hidden />
        </ButtonLink>
      </div>
    </Card>
  );
}

function MetricCard({
  description,
  icon,
  label,
  status,
  title,
  visual,
}: {
  description: string;
  icon: ReactNode;
  label: string;
  status: MetricStatus;
  title: string;
  visual: ReactNode;
}) {
  return (
    <Card className="min-h-[150px] min-w-[260px] p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-[180px] flex-1 items-center gap-3">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg border border-line bg-white/[0.06] text-ink">
            {icon}
          </span>
          <div className="min-w-0">
            <p className="break-words text-xs font-semibold uppercase tracking-[0.08em] text-muted">
              {label}
            </p>
            <p className="mt-1 text-lg font-semibold leading-6 text-ink">{title}</p>
          </div>
        </div>
        <StatusPill status={status} />
      </div>
      <div className="mt-5 flex items-end justify-between gap-4">
        <p className="min-w-0 text-sm leading-5 text-muted">{description}</p>
        <div className="shrink-0">{visual}</div>
      </div>
    </Card>
  );
}

function QuickActions() {
  return (
    <Card className="p-4">
      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-muted">
        Acciones rapidas
      </p>
      <div className="mt-4 grid grid-cols-[repeat(auto-fit,minmax(220px,1fr))] gap-3">
        {quickActions.map((action) => {
          const Icon = action.icon;
          return (
            <Link
              className="group flex min-h-20 items-center justify-between gap-4 rounded-lg border border-line bg-black/20 p-4 transition hover:border-emerald-400/35 hover:bg-emerald-400/10"
              href={action.href}
              key={action.href}
            >
              <div className="flex min-w-0 items-center gap-3">
                <span className={`grid h-11 w-11 shrink-0 place-items-center rounded-lg border ${toneClasses(action.tone)}`}>
                  <Icon className="h-5 w-5" aria-hidden />
                </span>
                <span className="min-w-0">
                  <span className="block text-sm font-semibold text-ink">{action.title}</span>
                  <span className="mt-1 block text-xs leading-5 text-muted">{compactActionDescription(action.title)}</span>
                </span>
              </div>
              <ArrowRight className="h-4 w-4 shrink-0 text-muted transition group-hover:translate-x-1 group-hover:text-ink" />
            </Link>
          );
        })}
      </div>
    </Card>
  );
}

function RadarPanel({ state }: { state: LoadState<RadarSummary> }) {
  const data = state.data;
  return (
    <Card className="p-5">
      <PanelHeader
        action={<StatusPill status={toMetricStatus(data?.mode ?? data?.status, state)} />}
        kicker="Radar"
        title={data?.title ?? "Oportunidades bajo demanda"}
      />
      <div className="mt-5 grid items-center gap-5 sm:grid-cols-[150px_1fr]">
        <RadarPulse points={[]} />
        <div>
          <p className="text-4xl font-semibold text-ink">{data?.mode === "manual" ? "Manual" : "Sin datos"}</p>
          <p className="mt-2 text-sm leading-6 text-muted">
            {state.error || data?.summary || "El dashboard no llama automaticamente `/api/v1/radar/opportunities`. Abre Radar para ejecutar la busqueda real."}
          </p>
          <div className="mt-4">
            <ButtonLink href={data?.cta_path ?? "/app/radar"} variant="secondary">
              Ver radar completo
              <ArrowRight className="h-4 w-4" aria-hidden />
            </ButtonLink>
          </div>
        </div>
      </div>
    </Card>
  );
}

function MicrozonesPanel({ state }: { state: LoadState<MicrozonesSummary> }) {
  const rows = ["Microzona", "Score", "Variacion"];
  const data = state.data;
  return (
    <Card className="p-5">
      <PanelHeader
        action={<StatusPill status={toMetricStatus(data?.status, state)} />}
        kicker="Microzonas destacadas"
        title={data?.available ? "Senal territorial activa" : "Senal territorial en preparacion"}
      />
      <div className="mt-5 rounded-lg border border-line bg-black/20">
        <div className="grid grid-cols-[1fr_80px_90px] border-b border-line px-4 py-3 text-xs font-semibold uppercase tracking-[0.12em] text-muted">
          {rows.map((row) => (
            <span key={row}>{row}</span>
          ))}
        </div>
        <div className="p-4">
          {data?.items.length ? (
            <div className="space-y-2">
              {data.items.map((item) => (
                <div className="grid grid-cols-[1fr_80px_90px] text-sm text-ink" key={item.name}>
                  <span>{item.name}</span>
                  <span>{item.score ?? "--"}</span>
                  <span>{item.change_pct == null ? "--" : `${item.change_pct}%`}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="rounded-lg border border-dashed border-line bg-white/[0.03] p-4">
              <p className="text-sm font-semibold text-ink">Microzonas en preparacion</p>
              <p className="mt-2 text-sm leading-6 text-muted">
                {state.error || data?.message || "Se activara cuando exista senal de microzona publicable para el dashboard."}
              </p>
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}

function WatchlistPanel({
  items,
  state,
}: {
  items: WatchlistItem[];
  state: LoadState<WatchlistItem[]>;
}) {
  return (
    <Card className="p-5">
      <PanelHeader
        action={<Link className="text-sm font-semibold text-blue-200 hover:text-ink" href="/app/portfolio">Ver todas</Link>}
        kicker="Watchlist"
        title={state.loading ? "Cargando propiedades" : `${items.length} propiedades guardadas`}
      />
      <div className="mt-4 space-y-3">
        {state.loading ? (
          <LoadingLine label="Cargando watchlist..." />
        ) : state.error ? (
          <EmptyState message={state.error} tone="error" />
        ) : items.length ? (
          items.slice(0, 4).map((item) => <WatchlistRow item={item} key={item.id} />)
        ) : (
          <EmptyState message="Aun no hay propiedades guardadas." tone="neutral" />
        )}
      </div>
    </Card>
  );
}

function AlertsPanel({
  alerts,
  state,
  unreadCount,
}: {
  alerts: AlertItem[];
  state: LoadState<AlertItem[]>;
  unreadCount: number;
}) {
  return (
    <Card className="p-5">
      <PanelHeader
        action={<Link className="text-sm font-semibold text-blue-200 hover:text-ink" href="/app/alerts">Ver todas</Link>}
        kicker="Alertas recientes"
        title={state.loading ? "Cargando alertas" : `${unreadCount} pendientes`}
      />
      <div className="mt-4 space-y-3">
        {state.loading ? (
          <LoadingLine label="Cargando alertas..." />
        ) : state.error ? (
          <EmptyState message={state.error} tone="error" />
        ) : alerts.length ? (
          alerts.slice(0, 4).map((alert) => <AlertRow alert={alert} key={alert.id} />)
        ) : (
          <EmptyState message="Sin alertas recientes." tone="neutral" />
        )}
      </div>
    </Card>
  );
}

function DataStatusCard({
  description,
  icon,
  label,
  status,
  value,
}: {
  description: string;
  icon: ReactNode;
  label: string;
  status: MetricStatus;
  value: string;
}) {
  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-3">
        <span className="grid h-10 w-10 place-items-center rounded-lg border border-line bg-white/[0.05] text-ink">
          {icon}
        </span>
        <StatusPill status={status} />
      </div>
      <p className="mt-4 text-xs font-semibold uppercase tracking-[0.16em] text-muted">{label}</p>
      <p className="mt-1 text-xl font-semibold text-ink">{value}</p>
      <p className="mt-2 text-sm leading-5 text-muted">{description}</p>
    </Card>
  );
}

function BriefingSignal({
  icon,
  label,
  status,
  value,
}: {
  icon: ReactNode;
  label: string;
  status: MetricStatus;
  value: string;
}) {
  return (
    <div className="rounded-lg border border-line bg-black/20 p-4">
      <div className="flex items-center gap-3">
        <span className="grid h-10 w-10 place-items-center rounded-lg border border-emerald-400/20 bg-emerald-400/10 text-emerald-200">
          {icon}
        </span>
        <div>
          <p className="text-xs text-muted">{label}</p>
          <p className="mt-1 text-sm font-semibold text-ink">{value}</p>
        </div>
      </div>
      <div className="mt-3">
        <StatusPill status={status} />
      </div>
    </div>
  );
}

function PanelHeader({
  action,
  kicker,
  title,
}: {
  action?: ReactNode;
  kicker: string;
  title: string;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-[220px] flex-1">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-muted">{kicker}</p>
        <CardTitle>{title}</CardTitle>
      </div>
      <div className="shrink-0">{action}</div>
    </div>
  );
}

function WatchlistRow({ item }: { item: WatchlistItem }) {
  return (
    <div className="grid grid-cols-[44px_minmax(0,1fr)_112px] items-center gap-3 rounded-lg border border-line bg-black/20 p-3">
      <PropertyThumb />
      <div className="min-w-0">
        <p className="line-clamp-1 text-sm font-semibold text-ink">
          {formatText(item.title, "Propiedad guardada")}
        </p>
        <p className="mt-1 truncate text-xs text-muted">
          {formatText(item.comuna)} · {formatPropertyType(item.property_type)}
        </p>
      </div>
      <div className="min-w-0 text-right">
        <p className="text-sm font-semibold text-ink">
          {formatUf(item.price_uf_display ?? item.price_uf ?? item.saved_price_uf)}
        </p>
        <p className="mt-1 text-xs text-muted">{formatM2(item.m2)}</p>
        <Sparkline status="empty" />
      </div>
    </div>
  );
}

function AlertRow({ alert }: { alert: AlertItem }) {
  const isDrop = alert.alert_type.toLowerCase().includes("drop") || Number(alert.payload.drop_pct ?? 0) > 0;
  return (
    <div className="grid grid-cols-[40px_1fr_auto] items-center gap-3 rounded-lg border border-line bg-black/20 p-3">
      <span className={`grid h-10 w-10 place-items-center rounded-lg border ${isDrop ? "border-orange-400/25 bg-orange-400/10 text-orange-200" : "border-emerald-400/25 bg-emerald-400/10 text-emerald-200"}`}>
        {isDrop ? <ArrowDownRight className="h-4 w-4" aria-hidden /> : <ArrowUpRight className="h-4 w-4" aria-hidden />}
      </span>
      <div className="min-w-0">
        <p className="line-clamp-1 text-sm font-semibold text-ink">
          {formatText(alert.message, "Alerta disponible")}
        </p>
        <p className="mt-1 truncate text-xs text-muted">
          {formatText(alert.title)} · {formatText(alert.comuna)}
        </p>
      </div>
      <p className="text-right text-xs text-muted">{relativeTime(alert.created_at)}</p>
    </div>
  );
}

function EmptyState({ message, tone }: { message: string; tone: "error" | "neutral" }) {
  const Icon = tone === "error" ? AlertTriangle : MapPinned;
  return (
    <div className="rounded-lg border border-dashed border-line bg-black/20 p-4">
      <div className="flex items-center gap-3">
        <Icon className={tone === "error" ? "h-4 w-4 text-orange-200" : "h-4 w-4 text-muted"} aria-hidden />
        <p className="text-sm leading-6 text-muted">{message}</p>
      </div>
    </div>
  );
}

function ValoriaGauge({ value }: { value: number | null }) {
  const normalized = value === null ? 0 : Math.max(0, Math.min(100, value));
  const dash = 198;
  const visible = (dash * normalized) / 100;
  return (
    <div className="relative h-36 w-52">
      <svg className="h-full w-full" viewBox="0 0 220 150" role="img" aria-label="Indice Valoria">
        <path
          d="M35 120a75 75 0 0 1 150 0"
          fill="none"
          stroke="rgba(148,163,184,0.18)"
          strokeLinecap="round"
          strokeWidth="10"
        />
        <path
          d="M35 120a75 75 0 0 1 150 0"
          fill="none"
          stroke={value === null ? "rgba(148,163,184,0.28)" : "url(#gaugeGradient)"}
          strokeDasharray={`${visible} ${dash}`}
          strokeLinecap="round"
          strokeWidth="10"
        />
        <defs>
          <linearGradient id="gaugeGradient" x1="30" x2="190" y1="120" y2="45">
            <stop stopColor="#3ddc97" />
            <stop offset="1" stopColor="#86efac" />
          </linearGradient>
        </defs>
      </svg>
      <div className="absolute inset-x-0 bottom-2 text-center">
        <p className="text-4xl font-semibold text-ink">{value === null ? "--" : normalized}</p>
        <p className="text-sm text-muted">/100</p>
      </div>
    </div>
  );
}

function Sparkline({ status }: { status: MetricStatus }) {
  const muted = status !== "available";
  return (
    <svg className="mt-2 h-8 w-24" viewBox="0 0 96 32" aria-hidden>
      <path d="M0 25 C 16 18, 20 22, 32 16 S 56 15, 68 10 S 82 14, 96 6" fill="none" stroke={muted ? "rgba(148,163,184,0.38)" : "#3ddc97"} strokeWidth="2" />
      {muted ? <path d="M0 26 H96" stroke="rgba(148,163,184,0.18)" strokeDasharray="3 4" /> : null}
    </svg>
  );
}

function RadarMini() {
  return (
    <svg className="h-16 w-20" viewBox="0 0 80 64" aria-hidden>
      <circle cx="40" cy="32" fill="none" r="26" stroke="rgba(148,163,184,0.18)" />
      <circle cx="40" cy="32" fill="none" r="15" stroke="rgba(148,163,184,0.14)" />
      <path d="M40 32 L64 20" stroke="rgba(61,220,151,0.45)" />
      <circle cx="40" cy="32" fill="#3ddc97" r="4" />
    </svg>
  );
}

function RadarPulse({ points }: { points: Array<{ x: number; y: number }> }) {
  return (
    <svg className="h-40 w-40" viewBox="0 0 160 160" role="img" aria-label="Radar de oportunidades">
      {[24, 48, 68].map((radius) => (
        <circle cx="80" cy="80" fill="none" key={radius} r={radius} stroke="rgba(148,163,184,0.16)" />
      ))}
      <path d="M80 12 V148 M12 80 H148" stroke="rgba(148,163,184,0.12)" />
      <path d="M80 80 L128 34" stroke="rgba(61,220,151,0.42)" />
      <circle cx="80" cy="80" fill="none" r="18" stroke="rgba(61,220,151,0.32)" />
      <text fill="rgba(248,250,252,0.9)" fontSize="22" fontWeight="700" textAnchor="middle" x="80" y="88">
        --
      </text>
      {points.map((point) => (
        <circle cx={point.x} cy={point.y} fill="#3ddc97" key={`${point.x}-${point.y}`} r="4" />
      ))}
    </svg>
  );
}

function RangeBar({
  current,
  max,
  min,
}: {
  current: number | null;
  max: number | null;
  min: number | null;
}) {
  return (
    <div>
      <div className="flex items-center justify-between text-xs text-muted">
        <span>{min ? formatUf(min) : "Rango pendiente"}</span>
        <span>{max ? formatUf(max) : "Sin historial"}</span>
      </div>
      <div className="mt-3 h-2 rounded-full bg-white/[0.08]">
        <div className="h-2 w-1/2 rounded-full bg-gradient-to-r from-emerald-400 to-emerald-200 opacity-60" />
      </div>
      <p className="mt-2 text-xs text-muted">
        {current ? `Centro actual: ${formatUf(current)}` : "Se completara cuando la actividad exponga rango."}
      </p>
    </div>
  );
}

function MiniTrendChart({ status }: { status: MetricStatus }) {
  return (
    <div className="mt-5">
      <svg className="h-24 w-full" viewBox="0 0 320 96" preserveAspectRatio="none" aria-hidden>
        <defs>
          <linearGradient id="trendFill" x1="0" x2="0" y1="0" y2="1">
            <stop stopColor="rgba(61,220,151,0.32)" />
            <stop offset="1" stopColor="rgba(61,220,151,0)" />
          </linearGradient>
        </defs>
        <path d="M0 72 C 50 70, 70 58, 104 62 S 160 48, 202 54 S 260 42, 320 36 L320 96 L0 96 Z" fill={status === "available" ? "url(#trendFill)" : "rgba(148,163,184,0.08)"} />
        <path d="M0 72 C 50 70, 70 58, 104 62 S 160 48, 202 54 S 260 42, 320 36" fill="none" stroke={status === "available" ? "#3ddc97" : "rgba(148,163,184,0.35)"} strokeWidth="2" />
      </svg>
      <p className="mt-1 text-xs text-muted">Historial de valor: esperando contrato.</p>
    </div>
  );
}

function PropertyThumb() {
  return (
    <span className="grid h-11 w-11 place-items-center rounded-lg border border-line bg-[radial-gradient(circle_at_30%_25%,rgba(61,220,151,0.25),transparent_1.5rem),rgba(255,255,255,0.05)] text-muted">
      <Building2 className="h-5 w-5" aria-hidden />
    </span>
  );
}

function StatusPill({ status }: { status: MetricStatus }) {
  const labels: Record<MetricStatus, string> = {
    available: "Datos reales",
    coming_soon: "En preparacion",
    empty: "Sin datos",
    error: "Error",
    manual: "Manual",
  };
  const classes: Record<MetricStatus, string> = {
    available: "border-emerald-400/25 bg-emerald-400/10 text-emerald-100",
    coming_soon: "border-white/10 bg-white/[0.05] text-muted",
    empty: "border-white/10 bg-black/20 text-muted",
    error: "border-orange-400/30 bg-orange-400/10 text-orange-100",
    manual: "border-blue-400/30 bg-blue-400/10 text-blue-100",
  };
  return (
    <span className={`inline-flex min-h-7 shrink-0 items-center whitespace-nowrap rounded-lg border px-3 text-xs font-semibold ${classes[status]}`}>
      {labels[status]}
    </span>
  );
}

function LoadingLine({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-muted">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
      {label}
    </div>
  );
}

function toneClasses(tone: Tone): string {
  const classes: Record<Tone, string> = {
    blue: "border-blue-400/25 bg-blue-400/10 text-blue-100",
    green: "border-emerald-400/25 bg-emerald-400/10 text-emerald-100",
    neutral: "border-line bg-white/[0.05] text-muted",
    orange: "border-orange-400/25 bg-orange-400/10 text-orange-100",
  };
  return classes[tone];
}

function toMetricStatus(status: string | null | undefined, state?: LoadState<unknown>): MetricStatus {
  if (state?.error) return "error";
  if (state?.loading) return "empty";
  if (status === "available") return "available";
  if (status === "manual") return "manual";
  if (status === "empty") return "empty";
  if (status === "error") return "error";
  return "coming_soon";
}

function indicatorByKey(indicators: MarketIndicator[], key: string): MarketIndicator | null {
  return indicators.find((indicator) => indicator.key === key) ?? null;
}

function indicatorValue(indicator: MarketIndicator | null): string {
  if (!indicator) return "En preparacion";
  if (indicator.value == null) {
    return indicator.status === "manual" ? "Radar manual" : "En preparacion";
  }
  return `${indicator.value}${indicator.unit ? ` ${indicator.unit}` : ""}`;
}

function formatNullableScore(value: number | null, max: number): string {
  return value == null ? "Proximamente" : `${value}/${max}`;
}

function compactActionDescription(title: string): string {
  if (title === "Tasar propiedad") return "Calcula valor estimado.";
  if (title === "Analizar publicacion") return "Revisa un aviso.";
  if (title === "Explorar oportunidades") return "Abre Radar manual.";
  return "";
}

function displayName(user: User): string {
  const local = user.email.split("@")[0] ?? "";
  const clean = local.replace(/[._-]+/g, " ").trim();
  if (!clean) return user.email;
  return clean
    .split(" ")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function ufStatus(state: LoadState<UFRate>): MetricStatus {
  if (state.error) return "error";
  if (state.loading || !state.data) return "empty";
  return "available";
}

function ufDescription(state: LoadState<UFRate>): string {
  if (state.loading) return "Consultando UF.";
  if (state.error || !state.data) return state.error || "UF no disponible.";
  const date = state.data.rate_date ? formatDate(state.data.rate_date) : formatDateTime(state.data.observed_at);
  return `${formatText(state.data.source)} · ${date}`;
}

function relativeTime(value: string): string {
  const time = new Date(value).getTime();
  if (!Number.isFinite(time)) return "Fecha no disponible";
  const diffMinutes = Math.max(0, Math.round((Date.now() - time) / 60000));
  if (diffMinutes < 60) return `Hace ${diffMinutes || 1} min`;
  const diffHours = Math.round(diffMinutes / 60);
  if (diffHours < 24) return `Hace ${diffHours} h`;
  return formatDate(value);
}
