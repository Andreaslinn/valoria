"use client";

import { Bell, CheckCircle2, Loader2, MoreVertical, WalletCards } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Button, ButtonLink } from "@/components/ui/button";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { StatusNote } from "@/components/ui/status-note";
import { ApiError } from "@/lib/api/client";
import { listAlerts, markAlertRead } from "@/lib/api/alerts";
import { formatClp, formatDateTime, formatNumber, formatUf } from "@/lib/formatters";
import type { AlertItem } from "@/types/alerts";

const ALERT_LIMIT = 50;

export function AlertsWorkspace() {
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [markingId, setMarkingId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    void loadAlerts();
  }, []);

  async function loadAlerts() {
    setLoading(true);
    setError(null);
    try {
      setAlerts(await listAlerts(ALERT_LIMIT));
    } catch (caught) {
      setError(errorText(caught, "No pudimos cargar tus alertas."));
    } finally {
      setLoading(false);
    }
  }

  async function markAsRead(alert: AlertItem) {
    setMarkingId(alert.id);
    setError(null);
    setMessage(null);
    try {
      await markAlertRead(alert.id);
      setAlerts((current) => current.filter((item) => item.id !== alert.id));
      setMessage("Alerta marcada como leida.");
    } catch (caught) {
      setError(errorText(caught, "No pudimos marcar esta alerta como leida."));
    } finally {
      setMarkingId(null);
    }
  }

  const priceDrops = useMemo(
    () => alerts.filter((alert) => alert.alert_type === "price_drop").length,
    [alerts],
  );

  return (
    <div className="grid gap-5">
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <CardTitle>Inbox real de alertas</CardTitle>
            <CardDescription>
              Alertas no leidas generadas para propiedades guardadas en tu watchlist.
            </CardDescription>
          </div>
          <span className="rounded-lg border border-brand-500/25 bg-brand-500/10 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-violet-100">
            {loading ? "Cargando" : `${alerts.length} no leida(s)`}
          </span>
        </div>
        <div className="mt-5 grid gap-3 sm:grid-cols-3">
          <SummaryFact label="Fuente" value="GET /api/v1/alerts" />
          <SummaryFact label="Tipo activo" value={priceDrops ? `${priceDrops} baja(s) de precio` : "Sin bajas no leidas"} />
          <SummaryFact label="Accion" value="Marcar como leida" />
        </div>
      </Card>

      {message ? <StatusNote tone="success">{message}</StatusNote> : null}
      {error ? <StatusNote tone="warning">{error}</StatusNote> : null}

      {loading ? (
        <Card>
          <div className="flex min-h-56 items-center justify-center gap-3 text-sm text-muted">
            <Loader2 className="h-5 w-5 animate-spin" aria-hidden />
            Cargando alertas reales...
          </div>
        </Card>
      ) : alerts.length ? (
        <section className="grid gap-4 xl:grid-cols-2">
          {alerts.map((alert) => (
            <AlertCard
              alert={alert}
              key={alert.id}
              marking={markingId === alert.id}
              onMarkRead={() => markAsRead(alert)}
            />
          ))}
        </section>
      ) : (
        <Card>
          <div className="flex min-h-64 items-center justify-center rounded-lg border border-dashed border-line bg-black/20 p-8 text-center">
            <div>
              <Bell className="mx-auto h-9 w-9 text-brand-500" aria-hidden />
              <h3 className="mt-4 text-lg font-semibold text-ink">Sin alertas pendientes</h3>
              <p className="mt-2 max-w-lg text-sm leading-6 text-muted">
                Las alertas aparecen cuando una propiedad guardada cumple una condicion detectada por el backend.
              </p>
              <div className="mt-5">
                <ButtonLink href="/app/portfolio" variant="secondary">
                  <WalletCards className="h-4 w-4" aria-hidden />
                  Ver portfolio
                </ButtonLink>
              </div>
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}

function AlertCard({
  alert,
  marking,
  onMarkRead,
}: {
  alert: AlertItem;
  marking: boolean;
  onMarkRead: () => void;
}) {
  const dropPct = numberValue(alert.payload?.drop_pct);
  const previousUf = ufPayloadValue(alert, "previous");
  const newUf = ufPayloadValue(alert, "new");
  const previousClp = clpPayloadValue(alert, "previous");
  const newClp = clpPayloadValue(alert, "new");
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <Card className="flex min-h-72 flex-col">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            {!alert.is_read ? (
              <span className="h-2 w-2 rounded-full bg-brand-500 shadow-glow lg:hidden" aria-hidden />
            ) : null}
            <h3 className="text-base font-semibold leading-6 text-ink">{alert.title || "Propiedad con alerta"}</h3>
          </div>
          <p className="mt-1 text-sm text-muted">{alert.comuna || "Comuna no disponible"}</p>
        </div>
        <span className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-1 text-xs font-semibold text-amber-100">
          {alertTypeLabel(alert.alert_type)}
        </span>
      </div>

      <p className="mt-4 text-sm leading-6 text-ink">{alert.message || "Nueva alerta de la propiedad."}</p>

      <div className="mt-5 grid gap-3 sm:grid-cols-2">
        <Fact label="Detectada" value={formatDateTime(alert.created_at)} />
        <Fact label="Precio actual" value={formatClp(alert.price_clp ?? newClp)} />
        <Fact label="Cambio" value={dropPct === null ? "No disponible" : `-${formatNumber(dropPct, 2)}%`} />
        <Fact label="UF anterior / nueva" value={`${formatUf(previousUf)} / ${formatUf(newUf)}`} />
        <Fact label="CLP anterior / nuevo" value={`${formatClp(previousClp)} / ${formatClp(newClp)}`} />
      </div>

      <div className="mt-auto hidden flex-wrap gap-3 pt-5 lg:flex">
        <Button disabled={marking || alert.is_read} onClick={onMarkRead} type="button" variant="secondary">
          {marking ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <CheckCircle2 className="h-4 w-4" aria-hidden />}
          {marking ? "Marcando..." : "Marcar como leida"}
        </Button>
        <ButtonLink href="/app/portfolio" variant="secondary">
          <WalletCards className="h-4 w-4" aria-hidden />
          Ver portfolio
        </ButtonLink>
      </div>
      <div className="relative mt-auto flex items-center justify-between gap-3 pt-5 lg:hidden">
        <ButtonLink className="flex-1" href="/app/portfolio" variant="secondary">
          <WalletCards className="h-4 w-4" aria-hidden />
          Portfolio
        </ButtonLink>
        <button
          aria-expanded={menuOpen}
          aria-label="Abrir opciones de alerta"
          className="grid h-11 w-11 shrink-0 place-items-center rounded-lg border border-line bg-white/[0.06] text-ink"
          onClick={() => setMenuOpen((current) => !current)}
          type="button"
        >
          <MoreVertical className="h-5 w-5" aria-hidden />
        </button>
        {menuOpen ? (
          <div className="absolute bottom-14 right-0 z-10 w-56 rounded-lg border border-line bg-[#050914]/95 p-2 shadow-soft backdrop-blur-xl">
            <button
              className="flex min-h-10 w-full items-center gap-2 rounded-lg px-3 text-left text-sm font-semibold text-ink active:bg-white/[0.08] disabled:opacity-50"
              disabled={marking || alert.is_read}
              onClick={() => {
                setMenuOpen(false);
                onMarkRead();
              }}
              type="button"
            >
              {marking ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <CheckCircle2 className="h-4 w-4" aria-hidden />}
              Marcar como leida
            </button>
          </div>
        ) : null}
      </div>
    </Card>
  );
}

function SummaryFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-line bg-white/[0.04] p-3">
      <p className="text-xs font-medium uppercase tracking-wide text-muted">{label}</p>
      <p className="mt-2 text-sm font-semibold text-ink">{value}</p>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-line bg-white/[0.04] p-3">
      <p className="text-xs font-medium uppercase tracking-wide text-muted">{label}</p>
      <p className="mt-2 break-words text-sm font-semibold text-ink">{value}</p>
    </div>
  );
}

function errorText(error: unknown, fallback: string): string {
  if (!(error instanceof ApiError)) return fallback;
  if (error.status === 401 || error.status === 403) return "Tu sesion no esta vigente o no tiene permisos.";
  if (error.status === 404) return "La alerta no existe o ya fue procesada.";
  if (error.status === 422) return "La API no pudo procesar esta accion.";
  if (error.status >= 500) return "La API tuvo un problema cargando alertas.";
  return error.message;
}

function alertTypeLabel(value: string): string {
  const labels: Record<string, string> = {
    price_drop: "Baja de precio",
  };
  return labels[value] ?? value.replaceAll("_", " ");
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function ufPayloadValue(alert: AlertItem, position: "previous" | "new"): number | null {
  const canonicalKey = position === "previous" ? "canonical_previous_price" : "canonical_new_price";
  const legacyKey = position === "previous" ? "previous_price_uf" : "new_price_uf";
  const changeBasis = String(alert.payload?.change_basis ?? "").toLowerCase();
  if (!changeBasis.startsWith("uf")) return numberValue(alert.payload?.[legacyKey]);
  return numberValue(alert.payload?.[canonicalKey]) ?? numberValue(alert.payload?.[legacyKey]);
}

function clpPayloadValue(alert: AlertItem, position: "previous" | "new"): number | null {
  const displayKey = position === "previous" ? "display_previous_price_clp" : "display_new_price_clp";
  const snapshotKey = position === "previous" ? "previous_price_clp_snapshot" : "new_price_clp_snapshot";
  const canonicalKey = position === "previous" ? "canonical_previous_price" : "canonical_new_price";
  const changeBasis = String(alert.payload?.change_basis ?? "").toLowerCase();
  if (changeBasis.startsWith("clp") || changeBasis === "legacy_current") {
    return numberValue(alert.payload?.[canonicalKey]) ?? numberValue(alert.payload?.[snapshotKey]);
  }
  return numberValue(alert.payload?.[displayKey]) ?? numberValue(alert.payload?.[snapshotKey]);
}
