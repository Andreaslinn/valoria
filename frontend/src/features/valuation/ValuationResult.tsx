"use client";

import { BarChart3, Download, Sparkles, TrendingDown, TrendingUp } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { StatusNote } from "@/components/ui/status-note";
import type { ValuationRequest, ValuationResponse } from "@/types/valuation";

import { ComparableCard } from "./ComparableCard";
import { formatClp, formatConfidence, formatPercent, formatUf } from "./formatters";
import { ValuationReliabilitySummary } from "./ValuationReliabilitySummary";

export function ValuationResult({
  payload,
  result,
}: {
  payload: ValuationRequest | null;
  result: ValuationResponse | null;
}) {
  const [showAllComparables, setShowAllComparables] = useState(false);

  if (!result) {
    return (
      <Card className="min-h-[360px]">
        <div className="flex h-full min-h-[320px] items-center justify-center rounded-lg border border-dashed border-line bg-black/20 p-8 text-center">
          <div>
            <Sparkles className="mx-auto h-8 w-8 text-brand-600" aria-hidden />
            <h3 className="mt-4 text-lg font-semibold text-ink">Lista para tasar</h3>
            <p className="mt-2 max-w-md text-sm leading-6 text-muted">
              Ejecuta una tasacion para ver valor estimado, rango, confianza y comparables reales
              devueltos por FastAPI.
            </p>
          </div>
        </div>
      </Card>
    );
  }

  const selectedEngine =
    result.selected_engine_names?.join(", ") ||
    result.consensus?.selected_engine_names?.join(", ") ||
    result.consensus_method ||
    "No disponible";
  const marketSignal = publishedPriceSignal(result, payload);
  const visibleComparables = showAllComparables
    ? result.comparables
    : result.comparables?.slice(0, 4);

  return (
    <div className="grid gap-5">
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <CardTitle>Resultado estimado</CardTitle>
            <CardDescription>Respuesta real de POST /api/v1/valuations.</CardDescription>
          </div>
          <span className="rounded-lg bg-accent-500/10 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-accent-600">
            {result.status || "beta"}
          </span>
        </div>

        <div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          <Metric label="Valor estimado UF" value={formatUf(result.estimated_price_uf)} />
          <Metric label="Valor estimado CLP" value={formatClp(result.estimated_price_clp)} />
          <Metric label="UF/m2" value={formatUf(result.price_m2_uf)} />
          <Metric
            label="Confianza"
            value={formatConfidence(result.confidence_label || result.confidence)}
            caption={result.confidence_score ? formatPercent(result.confidence_score) : undefined}
          />
          <Metric label="Comparables usados" value={String(result.comparable_count ?? "No disponible")} />
          <Metric label="Motor/modelo" value={selectedEngine} />
        </div>

        <div className="mt-6 rounded-lg border border-line bg-black/20 p-4">
          <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-ink">
            <BarChart3 className="h-4 w-4 text-brand-600" aria-hidden />
            Rango de incertidumbre
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <Metric compact label="Minimo" value={formatUf(result.price_range_low_uf)} />
            <Metric compact label="Promedio" value={formatUf(result.estimated_price_uf)} />
            <Metric compact label="Maximo" value={formatUf(result.price_range_high_uf)} />
          </div>
        </div>

        {result.beta_scope_message ? (
          <div className="mt-5">
            <StatusNote tone="info">{result.beta_scope_message}</StatusNote>
          </div>
        ) : null}

        {marketSignal ? (
          <div className="mt-5 rounded-lg border border-line bg-black/20 p-4">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <p className="text-sm font-semibold text-ink">Precio publicado vs estimado</p>
                <p className="mt-1 text-sm leading-6 text-muted">{marketSignal.description}</p>
              </div>
              <span className={`inline-flex items-center gap-2 rounded-lg border px-3 py-1 text-sm font-semibold ${marketSignal.className}`}>
                {marketSignal.kind === "under" ? (
                  <TrendingDown className="h-4 w-4" aria-hidden />
                ) : (
                  <TrendingUp className="h-4 w-4" aria-hidden />
                )}
                {marketSignal.label}
              </span>
            </div>
          </div>
        ) : (
          <div className="mt-5 rounded-lg border border-line bg-white/[0.04] p-4 text-sm leading-6 text-muted">
            Ingresa un precio publicado UF para comparar el valor pedido contra la estimacion.
          </div>
        )}
      </Card>

      <ValuationReliabilitySummary result={result} />

      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <CardTitle>Comparables de soporte</CardTitle>
            <CardDescription>Referencias usadas por el modelo cuando vienen en la respuesta.</CardDescription>
          </div>
          <Button disabled title={reportState(result).title} type="button" variant="secondary">
            <Download className="h-4 w-4" aria-hidden />
            {reportState(result).label}
          </Button>
        </div>
        <div className="mt-4 rounded-lg border border-line bg-white/[0.04] p-3 text-sm leading-6 text-muted">
          {reportState(result).description}
        </div>

        {result.comparables?.length ? (
          <>
            <div className="mt-5 grid gap-4 xl:grid-cols-2">
              {visibleComparables.map((comparable, index) => (
                <ComparableCard
                  key={`${comparable.listing_id ?? "comparable"}-${index}`}
                  comparable={comparable}
                />
              ))}
            </div>
            {result.comparables.length > 4 ? (
              <div className="mt-5 flex justify-center">
                <Button
                  onClick={() => setShowAllComparables((current) => !current)}
                  type="button"
                  variant="secondary"
                >
                  {showAllComparables
                    ? "Ver menos comparables"
                    : `Ver mas comparables (${result.comparables.length})`}
                </Button>
              </div>
            ) : null}
          </>
        ) : (
          <div className="mt-5 rounded-lg border border-dashed border-line bg-black/20 p-6 text-sm leading-6 text-muted">
            No hay comparables para mostrar. La tasacion puede seguir siendo util como referencia,
            pero no devolvio publicaciones revisables en esta respuesta.
          </div>
        )}
      </Card>
    </div>
  );
}

function publishedPriceSignal(result: ValuationResponse, payload: ValuationRequest | null) {
  const estimatedUf = result.estimated_price_uf;
  const publishedUf = payload?.precio_publicado_uf;
  if (!estimatedUf || !publishedUf || estimatedUf <= 0 || publishedUf <= 0) {
    return null;
  }

  const diffPct = ((publishedUf - estimatedUf) / estimatedUf) * 100;
  const formatted = `${Math.abs(diffPct).toFixed(1).replace(".", ",")}%`;
  if (diffPct <= -3) {
    return {
      className: "border-accent-500/30 bg-accent-500/10 text-emerald-100",
      description: `El precio publicado esta ${formatted} bajo la estimacion central. Revisar comparables y condiciones antes de interpretar como oportunidad.`,
      kind: "under" as const,
      label: "Bajo estimado",
    };
  }
  if (diffPct >= 3) {
    return {
      className: "border-amber-500/30 bg-amber-500/10 text-amber-100",
      description: `El precio publicado esta ${formatted} sobre la estimacion central. Puede requerir negociacion o mejor evidencia.`,
      kind: "over" as const,
      label: "Sobre estimado",
    };
  }
  return {
    className: "border-brand-500/30 bg-brand-500/10 text-violet-100",
    description: "El precio publicado esta en linea con la estimacion central del modelo.",
    kind: "over" as const,
    label: "En rango",
  };
}

function reportState(result: ValuationResponse) {
  if (!result.estimated_price_uf && !result.estimated_price_clp) {
    return {
      description: "Ejecuta una tasacion con valor estimado antes de preparar reportes.",
      label: "Reporte no disponible",
      title: "Requiere valor estimado",
    };
  }
  if (!result.comparables?.length) {
    return {
      description: "La tasacion no devolvio comparables revisables; el reporte queda pendiente hasta contar con soporte suficiente.",
      label: "Reporte pendiente",
      title: "Requiere comparables",
    };
  }
  return {
    description: "La descarga de reportes no esta conectada en Next.js todavia. No se genera ningun HTML/PDF desde el frontend.",
    label: "Reporte disponible proximamente",
    title: "Endpoint de reporte pendiente",
  };
}

function Metric({
  caption,
  compact = false,
  label,
  value,
}: {
  caption?: string;
  compact?: boolean;
  label: string;
  value: string;
}) {
  return (
    <div className={compact ? "" : "rounded-lg border border-line bg-white/[0.045] p-4"}>
      <p className="text-xs font-medium uppercase tracking-wide text-muted">{label}</p>
      <p className="mt-2 break-words text-lg font-bold text-ink">{value}</p>
      {caption ? <p className="mt-1 text-xs text-muted">{caption}</p> : null}
    </div>
  );
}
