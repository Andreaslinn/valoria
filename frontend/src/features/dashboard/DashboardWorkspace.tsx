"use client";

import {
  ArrowRight,
  Bell,
  FileText,
  Gauge,
  Link2,
  Loader2,
  Radar,
  Settings,
  WalletCards,
} from "lucide-react";
import { useEffect, useState } from "react";

import { ButtonLink } from "@/components/ui/button";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { StatusNote } from "@/components/ui/status-note";
import { listAlerts } from "@/lib/api/alerts";
import { me, type User } from "@/lib/api/auth";
import { getCurrentUf } from "@/lib/api/market";
import { listWatchlist } from "@/lib/api/watchlist";
import { formatClp, formatDate, formatDateTime, formatText } from "@/lib/formatters";
import type { AlertItem } from "@/types/alerts";
import type { UFRate } from "@/types/market";
import type { WatchlistItem } from "@/types/watchlist";

type LoadState<T> = {
  data: T | null;
  error: string | null;
  loading: boolean;
};

const initialState = <T,>(): LoadState<T> => ({
  data: null,
  error: null,
  loading: true,
});

const moduleCards = [
  {
    title: "Tasar propiedad",
    description: "Estimacion real con rango, confianza y comparables cuando hay soporte suficiente.",
    href: "/app/tasar",
    icon: Gauge,
    status: "Conectado",
  },
  {
    title: "Analizar publicacion",
    description: "Lookup real de URL y puente hacia Tasar con datos compatibles.",
    href: "/app/analizar-url",
    icon: Link2,
    status: "Conectado basico",
  },
  {
    title: "Radar",
    description: "Busca oportunidades recientes bajo valor estimado.",
    href: "/app/radar",
    icon: Radar,
    status: "Conectado, ejecucion manual",
  },
  {
    title: "Watchlist",
    description: "Propiedades guardadas desde endpoints reales.",
    href: "/app/portfolio",
    icon: WalletCards,
    status: "Conectado",
  },
  {
    title: "Alertas",
    description: "Inbox real de alertas para propiedades guardadas.",
    href: "/app/alerts",
    icon: Bell,
    status: "Conectado",
  },
  {
    title: "Reportes",
    description: "Area preparada para reportes autenticados cuando el flujo quede expuesto.",
    href: "/app/reportes",
    icon: FileText,
    status: "Pendiente",
  },
  {
    title: "Settings",
    description: "Preferencias y estado tecnico de entorno para la beta.",
    href: "/app/settings",
    icon: Settings,
    status: "Preparacion",
  },
];

export function DashboardWorkspace() {
  const [user, setUser] = useState<LoadState<User>>(initialState);
  const [watchlist, setWatchlist] = useState<LoadState<WatchlistItem[]>>(initialState);
  const [alerts, setAlerts] = useState<LoadState<AlertItem[]>>(initialState);
  const [uf, setUf] = useState<LoadState<UFRate>>(initialState);

  useEffect(() => {
    void loadUser();
    void loadWatchlist();
    void loadAlerts();
    void loadUf();
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
      setAlerts({ data: await listAlerts(50), error: null, loading: false });
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

  return (
    <div className="grid gap-6">
      <section className="grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
        <Card className="overflow-hidden">
          <div className="flex flex-col gap-5 md:flex-row md:items-center md:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-brand-500">
                {user.loading ? "Validando sesion" : `Hola, ${user.data?.email ?? "usuario beta"}`}
              </p>
              <h2 className="mt-2 text-2xl font-semibold text-ink">Cockpit beta privado</h2>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-muted">
                Valoria esta en beta privada. Las estimaciones y oportunidades usan datos reales,
                pero pueden tener cobertura limitada.
              </p>
            </div>
            <ButtonLink href="/app/tasar">
              Tasar propiedad
              <ArrowRight size={17} />
            </ButtonLink>
          </div>
        </Card>

        <Card>
          <CardTitle>Estado general</CardTitle>
          <CardDescription>
            El cockpit resume solo endpoints reales ya disponibles en el frontend.
          </CardDescription>
          <div className="mt-4">
            <StatusNote>Sin KPIs simulados ni metricas proyectadas.</StatusNote>
          </div>
        </Card>
      </section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <DataCard
          actionHref="/app/portfolio"
          actionLabel="Ver Watchlist"
          detail={watchlistDetail(watchlist)}
          label="Watchlist"
          loading={watchlist.loading}
          status={watchlist.error ?? "Disponible"}
          value={watchlist.loading ? "Cargando" : watchlist.error ? "No disponible" : `${watchlist.data?.length ?? 0} guardada(s)`}
        />
        <DataCard
          actionHref="/app/alerts"
          actionLabel="Ver Alertas"
          detail={alertsDetail(alerts)}
          label="Alertas"
          loading={alerts.loading}
          status={alerts.error ?? "Disponible"}
          value={alerts.loading ? "Cargando" : alerts.error ? "No disponible" : `${alerts.data?.length ?? 0} no leida(s)`}
        />
        <DataCard
          detail={ufDetail(uf)}
          label="UF actual"
          loading={uf.loading}
          status={uf.error ?? ufStatus(uf.data)}
          value={uf.loading ? "Cargando" : uf.error ? "No disponible" : formatClp(uf.data?.rate_clp)}
        />
        <DataCard
          actionHref="/app/radar"
          actionLabel="Abrir Radar"
          detail="Radar no se ejecuta desde este dashboard."
          label="Radar"
          status="Ejecucion manual"
          value="Conectado"
        />
      </section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {moduleCards.map((action) => {
          const Icon = action.icon;
          return (
            <Card className="flex min-h-60 flex-col" key={action.href}>
              <div className="mb-5 flex items-start justify-between gap-3">
                <div className="grid h-11 w-11 place-items-center rounded-lg border border-brand-500/25 bg-brand-500/10 text-brand-500">
                  <Icon size={20} />
                </div>
                <span className="rounded-lg border border-line bg-white/[0.05] px-3 py-1 text-xs font-semibold text-muted">
                  {action.status}
                </span>
              </div>
              <CardTitle>{action.title}</CardTitle>
              <CardDescription>{action.description}</CardDescription>
              <div className="mt-auto pt-5">
                <ButtonLink className="w-full" href={action.href} variant="secondary">
                  Abrir
                </ButtonLink>
              </div>
            </Card>
          );
        })}
      </section>
    </div>
  );
}

function DataCard({
  actionHref,
  actionLabel,
  detail,
  label,
  loading = false,
  status,
  value,
}: {
  actionHref?: string;
  actionLabel?: string;
  detail: string;
  label: string;
  loading?: boolean;
  status: string;
  value: string;
}) {
  return (
    <Card className="flex min-h-52 flex-col">
      <div className="flex items-start justify-between gap-3">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted">{label}</p>
        <span className="rounded-lg border border-line bg-white/[0.05] px-3 py-1 text-xs font-semibold text-muted">
          {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : status}
        </span>
      </div>
      <p className="mt-4 text-2xl font-semibold text-ink">{value}</p>
      <p className="mt-2 text-sm leading-6 text-muted">{detail}</p>
      {actionHref && actionLabel ? (
        <div className="mt-auto pt-5">
          <ButtonLink className="w-full" href={actionHref} variant="secondary">
            {actionLabel}
          </ButtonLink>
        </div>
      ) : null}
    </Card>
  );
}

function watchlistDetail(state: LoadState<WatchlistItem[]>): string {
  if (state.loading) return "Consultando /api/v1/watchlist.";
  if (state.error) return state.error;
  const latest = state.data?.[0];
  if (!latest) return "No hay propiedades guardadas.";
  return `Ultima visible: ${formatText(latest.title)} (${formatText(latest.comuna)}).`;
}

function alertsDetail(state: LoadState<AlertItem[]>): string {
  if (state.loading) return "Consultando /api/v1/alerts.";
  if (state.error) return state.error;
  const latest = state.data?.[0];
  if (!latest) return "No hay alertas pendientes.";
  return `Mas reciente: ${formatText(latest.message)}.`;
}

function ufDetail(state: LoadState<UFRate>): string {
  if (state.loading) return "Consultando /api/v1/market/uf.";
  if (state.error || !state.data) return "UF no disponible.";
  const date = state.data.rate_date ? formatDate(state.data.rate_date) : formatDateTime(state.data.observed_at);
  return `${formatText(state.data.source)} · ${date}`;
}

function ufStatus(data: UFRate | null): string {
  if (!data) return "No disponible";
  if (data.is_stale) return "Stale";
  if (data.is_fallback) return "Fallback";
  return "Disponible";
}
