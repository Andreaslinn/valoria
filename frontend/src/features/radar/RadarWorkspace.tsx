"use client";

import {
  ArrowRight,
  ExternalLink,
  Loader2,
  Radar,
  Search,
  ShieldCheck,
  WalletCards,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { Button, ButtonLink } from "@/components/ui/button";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { StatusNote } from "@/components/ui/status-note";
import { ApiError } from "@/lib/api/client";
import { listRadarOpportunities } from "@/lib/api/radar";
import { saveToWatchlist } from "@/lib/api/watchlist";
import {
  formatClp,
  formatConfidence,
  formatM2,
  formatNumber,
  formatPropertyType,
  formatText,
  formatUf,
} from "@/lib/formatters";
import type { RadarOpportunity } from "@/types/radar";

type SaveState = "saving" | "saved" | "error";

const LIMIT_OPTIONS = [10, 20, 50, 100];
const BEDROOM_OPTIONS = ["Todos", "1+", "2+", "3+", "4+"] as const;

export function RadarWorkspace() {
  const [items, setItems] = useState<RadarOpportunity[]>([]);
  const [hasSearched, setHasSearched] = useState(false);
  const [loading, setLoading] = useState(false);
  const [slow, setSlow] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [limit, setLimit] = useState(20);
  const [bedroomsMin, setBedroomsMin] = useState<number | null>(null);
  const [saveState, setSaveState] = useState<Record<number, SaveState>>({});
  const loadingRef = useRef(false);

  useEffect(() => {
    if (!loading) {
      setSlow(false);
      return;
    }
    const timer = window.setTimeout(() => setSlow(true), 5000);
    return () => window.clearTimeout(timer);
  }, [loading]);

  async function search() {
    if (loadingRef.current) return;
    loadingRef.current = true;
    setLoading(true);
    setHasSearched(true);
    setError(null);
    setMessage(null);
    try {
      const result = await listRadarOpportunities({ bedroomsMin, limit });
      setItems(result);
    } catch (caught) {
      setItems([]);
      setError(errorText(caught, "No pudimos ejecutar Radar."));
    } finally {
      loadingRef.current = false;
      setLoading(false);
    }
  }

  async function save(item: RadarOpportunity) {
    if (!item.listing_id) return;
    setSaveState((current) => ({ ...current, [item.listing_id as number]: "saving" }));
    setError(null);
    setMessage(null);
    try {
      await saveToWatchlist(item.listing_id);
      setSaveState((current) => ({ ...current, [item.listing_id as number]: "saved" }));
      setMessage("Propiedad guardada en Watchlist.");
    } catch (caught) {
      setSaveState((current) => ({ ...current, [item.listing_id as number]: "error" }));
      setError(errorText(caught, "No pudimos guardar esta propiedad."));
    }
  }

  const summary = useMemo(() => buildSummary(items), [items]);

  return (
    <div className="grid gap-5">
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <CardTitle>Radar beta conectado</CardTitle>
            <CardDescription>
              Radar analiza publicaciones recientes y busca precios bajo el valor estimado por Valoria.
            </CardDescription>
          </div>
          <span className="rounded-lg border border-accent-500/25 bg-accent-500/10 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-emerald-100">
            Solo departamentos
          </span>
        </div>

        <div className="mt-5 grid gap-3 sm:grid-cols-3">
          <SummaryFact label="Fuente" value="GET /api/v1/radar/opportunities" />
          <SummaryFact label="Ejecucion" value="Manual con boton" />
          <SummaryFact label="Resultados" value={hasSearched ? `${items.length} oportunidad(es)` : "Sin buscar"} />
        </div>

        <div className="mt-5 grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
          <label className="grid gap-2 text-sm text-muted">
            Limite
            <select
              className="min-h-11 rounded-lg border border-line bg-black/25 px-3 text-sm font-semibold text-ink outline-none transition focus:border-brand-500/60"
              disabled={loading}
              onChange={(event) => setLimit(Number(event.target.value))}
              value={limit}
            >
              {LIMIT_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option} resultados
                </option>
              ))}
            </select>
          </label>

          <label className="grid gap-2 text-sm text-muted">
            Dormitorios
            <select
              className="min-h-11 rounded-lg border border-line bg-black/25 px-3 text-sm font-semibold text-ink outline-none transition focus:border-brand-500/60"
              disabled={loading}
              onChange={(event) => setBedroomsMin(bedroomsValue(event.target.value))}
              value={bedroomsMin === null ? "Todos" : `${bedroomsMin}+`}
            >
              {BEDROOM_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>

          <Button className="self-end" disabled={loading} onClick={search} type="button">
            {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Search className="h-4 w-4" aria-hidden />}
            {loading ? "Buscando..." : "Buscar oportunidades"}
          </Button>
        </div>
      </Card>

      <StatusNote>
        Las oportunidades se filtran por publicaciones confirmadas recientemente en la base de datos. Beta: Valoria no reemplaza una tasacion profesional ni garantiza disponibilidad en tiempo real.
      </StatusNote>

      <StatusNote tone="info">
        Filtros avanzados proximamente. En esta beta solo se envian filtros soportados por el endpoint: limite y dormitorios.
      </StatusNote>

      {slow ? (
        <StatusNote tone="warning">
          Radar puede tardar mientras calcula oportunidades reales. Seguimos esperando la respuesta del backend.
        </StatusNote>
      ) : null}
      {message ? <StatusNote tone="success">{message}</StatusNote> : null}
      {error ? <StatusNote tone="warning">{error}</StatusNote> : null}

      {hasSearched && items.length ? (
        <Card>
          <div className="grid gap-3 sm:grid-cols-4">
            <SummaryFact label="Score mediano" value={summary.score} />
            <SummaryFact label="Descuento mediano" value={summary.discount} />
            <SummaryFact label="Precio mediano" value={summary.price} />
            <SummaryFact label="Comunas" value={summary.comunas} />
          </div>
        </Card>
      ) : null}

      {loading ? (
        <Card>
          <div className="flex min-h-56 items-center justify-center gap-3 text-sm text-muted">
            <Loader2 className="h-5 w-5 animate-spin" aria-hidden />
            Ejecutando Radar con datos reales...
          </div>
        </Card>
      ) : hasSearched && items.length ? (
        <section className="grid gap-4 xl:grid-cols-2">
          {items.map((item, index) => (
            <OpportunityCard
              item={item}
              key={item.listing_id ?? `${item.title}-${index}`}
              onSave={() => save(item)}
              rank={index + 1}
              saveState={item.listing_id ? saveState[item.listing_id] : undefined}
            />
          ))}
        </section>
      ) : hasSearched ? (
        <Card>
          <div className="flex min-h-64 items-center justify-center rounded-lg border border-dashed border-line bg-black/20 p-8 text-center">
            <div>
              <Radar className="mx-auto h-9 w-9 text-brand-500" aria-hidden />
              <h3 className="mt-4 text-lg font-semibold text-ink">Sin oportunidades para estos parametros</h3>
              <p className="mt-2 max-w-lg text-sm leading-6 text-muted">
                El backend respondio sin resultados. Puedes ampliar el limite o quitar el filtro de dormitorios.
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
      ) : (
        <Card>
          <div className="flex min-h-64 items-center justify-center rounded-lg border border-dashed border-line bg-black/20 p-8 text-center">
            <div>
              <ShieldCheck className="mx-auto h-9 w-9 text-accent-500" aria-hidden />
              <h3 className="mt-4 text-lg font-semibold text-ink">Radar listo para ejecutar</h3>
              <p className="mt-2 max-w-lg text-sm leading-6 text-muted">
                La busqueda no se dispara al cargar esta pantalla. Presiona el boton para consultar oportunidades reales.
              </p>
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}

function OpportunityCard({
  item,
  onSave,
  rank,
  saveState,
}: {
  item: RadarOpportunity;
  onSave: () => void;
  rank: number;
  saveState?: SaveState;
}) {
  const estimatedUf = item.estimated_value_uf ?? item.estimated_price_uf;
  const area = item.usable_area_m2 ?? item.built_area_m2 ?? item.m2;
  const program = [
    programPart(item.bedrooms, "D"),
    programPart(item.bathrooms, "B"),
    programPart(item.parking, "E"),
  ].filter(Boolean);

  return (
    <Card className="flex min-h-96 flex-col">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-wide text-brand-500">Oportunidad #{rank}</p>
          <h3 className="mt-2 text-base font-semibold leading-6 text-ink">{item.title || "Oportunidad Radar"}</h3>
          <p className="mt-1 text-sm text-muted">
            {formatText(item.comuna)} · {formatPropertyType(item.property_type)}
          </p>
        </div>
        <div className="rounded-lg border border-accent-500/25 bg-accent-500/10 px-3 py-2 text-right">
          <p className="text-xs text-emerald-100">Score</p>
          <p className="text-lg font-bold text-ink">{formatScore(item.score)}</p>
        </div>
      </div>

      <div className="mt-5 grid gap-3 sm:grid-cols-2">
        <Fact label="Precio publicado" value={`${formatUf(item.price_uf)} / ${formatClp(item.price_clp)}`} />
        <Fact label="Valor estimado" value={`${formatUf(estimatedUf)} / ${formatClp(item.estimated_value_clp)}`} />
        <Fact label="Brecha estimada" value={formatDiscount(item.discount_pct, estimatedUf - item.price_uf)} />
        <Fact label="Superficie" value={formatM2(area)} />
        <Fact label="Programa" value={program.length ? program.join(" / ") : "No disponible"} />
        <Fact label="Confianza" value={formatConfidence(item.confidence_score ?? item.confidence_label ?? item.confidence)} />
        <Fact label="Comparables" value={formatNumber(item.comparables_used, 0)} />
        <Fact label="Calidad precio" value={formatText(item.price_data_quality || item.price_basis_used)} />
        <Fact label="Fuente precio" value={formatText(item.price_uf_source || item.price_currency)} />
        <Fact label="Estado beta" value={formatText(item.radar_scope_label || item.beta_scope_status || item.radar_verdict)} />
      </div>

      {item.radar_verdict_message || item.beta_scope_message ? (
        <p className="mt-4 rounded-lg border border-line bg-white/[0.04] px-3 py-2 text-sm leading-6 text-muted">
          {item.radar_verdict_message || item.beta_scope_message}
        </p>
      ) : null}

      <div className="mt-auto flex flex-wrap gap-3 pt-5">
        {item.url ? (
          <a
            className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-line bg-white/[0.06] px-4 py-2 text-sm font-semibold text-ink transition hover:border-brand-500/45 hover:bg-brand-500/10"
            href={item.url}
            rel="noreferrer"
            target="_blank"
          >
            <ExternalLink className="h-4 w-4" aria-hidden />
            Abrir publicacion
          </a>
        ) : null}
        {item.listing_id ? (
          <Button disabled={saveState === "saving" || saveState === "saved"} onClick={onSave} type="button" variant="secondary">
            {saveState === "saving" ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <WalletCards className="h-4 w-4" aria-hidden />}
            {saveLabel(saveState)}
          </Button>
        ) : null}
        <ButtonLink href="/app/portfolio" variant="ghost">
          <ArrowRight className="h-4 w-4" aria-hidden />
          Portfolio
        </ButtonLink>
      </div>
    </Card>
  );
}

function SummaryFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-line bg-white/[0.04] p-3">
      <p className="text-xs font-medium uppercase tracking-wide text-muted">{label}</p>
      <p className="mt-2 break-words text-sm font-semibold text-ink">{value}</p>
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

function bedroomsValue(value: string): number | null {
  if (value === "Todos") return null;
  return Number(value.replace("+", ""));
}

function programPart(value: number | null | undefined, suffix: string): string | null {
  return typeof value === "number" && Number.isFinite(value) ? `${formatNumber(value, 0)}${suffix}` : null;
}

function formatDiscount(discountPct: number, savingsUf: number): string {
  const discount = Number.isFinite(discountPct) ? `${formatNumber(discountPct, 1)}%` : "No disponible";
  const savings = Number.isFinite(savingsUf) && savingsUf > 0 ? ` · ${formatUf(savingsUf)} bajo estimacion` : "";
  return `${discount}${savings}`;
}

function formatScore(score: number): string {
  if (!Number.isFinite(score)) return "N/D";
  return score <= 1 ? formatNumber(score * 100, 0) : formatNumber(score, 0);
}

function saveLabel(state: SaveState | undefined): string {
  if (state === "saving") return "Guardando...";
  if (state === "saved") return "Guardado";
  if (state === "error") return "Reintentar guardar";
  return "Guardar";
}

function buildSummary(items: RadarOpportunity[]) {
  return {
    score: formatMedian(items.map((item) => (item.score <= 1 ? item.score * 100 : item.score))),
    discount: formatMedian(items.map((item) => item.discount_pct), "%"),
    price: formatUf(median(items.map((item) => item.price_uf))),
    comunas: String(new Set(items.map((item) => item.comuna).filter(Boolean)).size),
  };
}

function formatMedian(values: number[], suffix = ""): string {
  const value = median(values);
  return value == null ? "No disponible" : `${formatNumber(value, 1)}${suffix}`;
}

function median(values: number[]): number | null {
  const clean = values.filter((value) => Number.isFinite(value)).sort((a, b) => a - b);
  if (!clean.length) return null;
  const mid = Math.floor(clean.length / 2);
  return clean.length % 2 ? clean[mid] : (clean[mid - 1] + clean[mid]) / 2;
}

function errorText(error: unknown, fallback: string): string {
  if (!(error instanceof ApiError)) return fallback;
  if (error.status === 0) return "No pudimos conectar con la API de Valoria. Revisa que FastAPI este corriendo.";
  if (error.status === 401 || error.status === 403) return "Tu sesion no esta vigente o no tiene permisos para Radar.";
  if (error.status === 404) return "El endpoint de Radar no esta disponible en esta API.";
  if (error.status === 400 || error.status === 422) return "Los parametros enviados a Radar no son validos.";
  if (error.status >= 500) return "Radar tuvo un problema en el backend. Intenta nuevamente mas tarde.";
  return error.message;
}
