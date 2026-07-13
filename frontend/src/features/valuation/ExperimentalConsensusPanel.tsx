"use client";

import { BadgeCheck, CircleAlert, CircleSlash, Scale } from "lucide-react";

import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import type { ValuationEngineBreakdown, ValuationResponse, ValuationVerdict } from "@/types/valuation";

import { formatPercent, formatUf } from "./formatters";

const ENGINE_LABELS: Record<string, string> = {
  comparables_canonical_outliers: "Mercado comparable",
  microzone_geo_v1: "Microzona",
  hedonic_baseline_v1: "Atributos",
  land_building_v1: "Terreno y construccion",
  market_trends_v1: "Tendencia de mercado",
  valoria_consensus_v1: "Consenso Valoria",
};

const ENGINE_ROLES: Record<string, string> = {
  market_comparables: "Evidencia de mercado",
  territorial_signal: "Senal territorial",
  structural_signal: "Atributos de la propiedad",
  house_land_building_signal: "Casas con terreno",
  time_trend_signal: "Ajuste temporal",
  experimental_signal: "Juez experimental",
};

export function ExperimentalConsensusPanel({ result }: { result: ValuationResponse }) {
  const verdict = result.valuation_verdict;
  const engines = result.engine_breakdown ?? [];

  if (!verdict && engines.length === 0) {
    return null;
  }

  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <CardTitle>Como llego Valoria a esta estimacion</CardTitle>
          <CardDescription>
            Bloque experimental de motores. La tasacion actual se mantiene si el consenso no esta disponible.
          </CardDescription>
        </div>
        <span className="rounded-lg border border-brand-500/30 bg-brand-500/10 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-violet-100">
          Experimental
        </span>
      </div>

      {verdict ? <VerdictSummary verdict={verdict} /> : null}

      {engines.length ? (
        <div className="mt-5 grid gap-3">
          {engines.map((engine) => (
            <EngineRow key={engine.engine_name} engine={engine} />
          ))}
        </div>
      ) : null}
    </Card>
  );
}

function VerdictSummary({ verdict }: { verdict: ValuationVerdict }) {
  const isConsensus = verdict.source === "consensus_experimental";
  return (
    <div className="mt-5 rounded-lg border border-line bg-black/20 p-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-ink">
            <Scale className="h-4 w-4 text-brand-600" aria-hidden />
            {isConsensus ? "Veredicto Valoria" : "Veredicto actual"}
          </div>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-muted">
            {verdict.explanation || fallbackVerdictExplanation(isConsensus)}
          </p>
        </div>
        <div className="text-right">
          <p className="text-xl font-bold text-ink">{formatUf(verdict.estimate_uf ?? null)}</p>
          <p className="mt-1 text-xs text-muted">{rangeLabel(verdict.low_uf, verdict.high_uf)}</p>
        </div>
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <SmallFact label="Metodo" value={isConsensus ? "Consenso Valoria" : "Tasacion actual"} />
        <SmallFact label="Confianza" value={formatPercent(verdict.confidence ?? null)} />
        <SmallFact label="Estado" value={statusLabel(verdict.status)} />
      </div>
    </div>
  );
}

function EngineRow({ engine }: { engine: ValuationEngineBreakdown }) {
  const state = engineState(engine.status);
  const StateIcon = state.icon;
  return (
    <div className="rounded-lg border border-line bg-white/[0.04] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <StateIcon className={`h-4 w-4 ${state.iconClass}`} aria-hidden />
            <p className="font-semibold text-ink">{engine.label || ENGINE_LABELS[engine.engine_name] || engine.engine_name}</p>
            <span className={`rounded-lg border px-2 py-0.5 text-xs font-semibold ${state.badgeClass}`}>
              {state.label}
            </span>
          </div>
          <p className="mt-1 text-xs text-muted">{roleLabel(engine)}</p>
        </div>
        <div className="grid grid-cols-3 gap-3 text-right text-sm">
          <SmallFact label="UF" value={engine.estimate_uf ? formatUf(engine.estimate_uf) : "No aplica"} />
          <SmallFact label="Peso" value={formatPercent(engine.weight ?? 0)} />
          <SmallFact label="Conf." value={formatPercent(engine.confidence ?? null)} />
        </div>
      </div>
      <p className="mt-3 text-sm leading-6 text-muted">
        {friendlyExplanation(engine)}
      </p>
      {engine.warning_flags?.length ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {engine.warning_flags.slice(0, 3).map((warning) => (
            <span key={warning} className="rounded-lg bg-amber-500/10 px-2 py-1 text-xs font-medium text-amber-100">
              {friendlyWarning(warning)}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function SmallFact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs font-medium uppercase tracking-wide text-muted">{label}</p>
      <p className="mt-1 break-words font-semibold text-ink">{value}</p>
    </div>
  );
}

function engineState(status: string) {
  if (status === "ok" || status === "success") {
    return {
      badgeClass: "border-emerald-500/30 bg-emerald-500/10 text-emerald-100",
      icon: BadgeCheck,
      iconClass: "text-emerald-300",
      label: "Usado",
    };
  }
  if (status === "failed" || status === "error") {
    return {
      badgeClass: "border-rose-500/30 bg-rose-500/10 text-rose-100",
      icon: CircleAlert,
      iconClass: "text-rose-300",
      label: "No disponible",
    };
  }
  return {
    badgeClass: "border-amber-500/30 bg-amber-500/10 text-amber-100",
    icon: CircleSlash,
    iconClass: "text-amber-300",
    label: "Datos insuficientes",
  };
}

function roleLabel(engine: ValuationEngineBreakdown) {
  return ENGINE_ROLES[engine.role || ""] || "Juez experimental";
}

function friendlyExplanation(engine: ValuationEngineBreakdown) {
  if (engine.explanation) {
    return engine.explanation;
  }
  if (engine.status === "ok" || engine.status === "success") {
    return "Aporto una estimacion usable al consenso experimental.";
  }
  if (engine.status === "not_applicable") {
    return "Este motor no aplica para esta propiedad.";
  }
  if (engine.status === "failed" || engine.status === "error") {
    return "No pudo entregar resultado, pero la tasacion principal sigue disponible.";
  }
  return "No tuvo suficientes datos para opinar en esta tasacion.";
}

function friendlyWarning(warning: string) {
  return warning
    .replaceAll("_", " ")
    .replace("insufficient", "datos insuficientes")
    .replace("missing", "falta");
}

function fallbackVerdictExplanation(isConsensus: boolean) {
  return isConsensus
    ? "Consenso Valoria combino los motores experimentales disponibles."
    : "El consenso experimental no entrego un veredicto usable para esta tasacion.";
}

function rangeLabel(low?: number | null, high?: number | null) {
  if (!low || !high) {
    return "Rango no disponible";
  }
  return `${formatUf(low)} - ${formatUf(high)}`;
}

function statusLabel(status?: string | null) {
  if (status === "ok" || status === "success") {
    return "Disponible";
  }
  if (status === "abstained" || status === "insufficient_data" || status === "not_applicable") {
    return "Sin consenso";
  }
  if (status === "failed" || status === "error") {
    return "No disponible";
  }
  return "Actual";
}
