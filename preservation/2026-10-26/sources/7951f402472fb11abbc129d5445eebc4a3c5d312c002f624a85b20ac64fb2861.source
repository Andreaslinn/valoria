import { ShieldCheck } from "lucide-react";
import { clsx } from "clsx";

import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import type { ValuationResponse } from "@/types/valuation";

import { formatConfidence, formatPercent } from "./formatters";
import { mapWarningCodes, type WarningDetail, type WarningSeverity } from "./warningTaxonomy";

export function ValuationReliabilitySummary({ result }: { result: ValuationResponse }) {
  const confidenceKey = normalizeConfidence(result.confidence_label || result.confidence);
  const warningDetails = mapWarningCodes([
    ...(result.warnings ?? []),
    ...(result.confidence_risk_flags ?? []),
    ...(result.comparable_quality_flags ?? []),
    ...(result.beta_scope_flags ?? []),
  ]);
  const visibleWarnings = warningDetails.slice(0, 4);
  const dataSignals = reliabilitySignals(result, warningDetails);
  const reasons = [
    ...(result.confidence_reasons ?? []),
    ...(result.confidence_risk_flags ?? []),
    ...(result.comparable_quality_flags ?? []),
    ...(result.beta_scope_flags ?? []),
  ];

  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <CardTitle>Confiabilidad del AVM</CardTitle>
          <CardDescription>
            Lectura de calidad basada solo en campos devueltos por la API.
          </CardDescription>
        </div>
        <span
          className={clsx(
            "inline-flex items-center gap-2 rounded-lg border px-3 py-1 text-xs font-semibold uppercase tracking-wide",
            confidenceTone(confidenceKey),
          )}
        >
          <ShieldCheck className="h-4 w-4" aria-hidden />
          {formatConfidence(result.confidence_label || result.confidence)}
        </span>
      </div>

      <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <ReliabilityFact
          label="Score"
          value={result.confidence_score !== null && result.confidence_score !== undefined ? formatPercent(result.confidence_score) : "No disponible"}
        />
        <ReliabilityFact
          label="Comparables"
          value={result.comparable_count !== null && result.comparable_count !== undefined ? String(result.comparable_count) : "No disponible"}
        />
        <ReliabilityFact label="Baja data" value={hasLowDataSignal(warningDetails) ? "Con alertas" : "Sin alerta"} />
        <ReliabilityFact label="Beta scope" value={betaScopeLabel(result)} />
      </div>

      <div className="mt-5 rounded-lg border border-line bg-black/20 p-4">
        <p className="text-sm font-semibold text-ink">Que significa esta confianza</p>
        <p className="mt-2 text-sm leading-6 text-muted">{confidenceExplanation(confidenceKey)}</p>
        {reasons.length ? (
          <div className="mt-3 flex flex-wrap gap-2">
            {reasons.slice(0, 5).map((reason) => (
              <span
                className="rounded-lg border border-line bg-white/[0.05] px-3 py-1 text-xs text-muted"
                key={reason}
              >
                {mapWarningCodes([reason])[0]?.label ?? reason}
              </span>
            ))}
          </div>
        ) : null}
      </div>

      <div className="mt-5 grid gap-3 md:grid-cols-3">
        {dataSignals.map((signal) => (
          <div className="rounded-lg border border-line bg-white/[0.04] p-3" key={signal.label}>
            <p className="text-xs font-medium uppercase tracking-wide text-muted">{signal.label}</p>
            <p className="mt-2 text-sm font-semibold text-ink">{signal.value}</p>
            <p className="mt-1 text-xs leading-5 text-muted">{signal.caption}</p>
          </div>
        ))}
      </div>

      {visibleWarnings.length ? (
        <div className="mt-5 grid gap-2">
          {visibleWarnings.map((warning) => (
            <WarningRow key={warning.code} warning={warning} />
          ))}
        </div>
      ) : (
        <div className="mt-5 rounded-lg border border-line bg-white/[0.04] p-3 text-sm text-muted">
          La API no devolvio warnings tecnicos para esta tasacion.
        </div>
      )}
    </Card>
  );
}

function ReliabilityFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-line bg-white/[0.04] p-3">
      <p className="text-xs font-medium uppercase tracking-wide text-muted">{label}</p>
      <p className="mt-2 text-base font-semibold text-ink">{value}</p>
    </div>
  );
}

function WarningRow({ warning }: { warning: WarningDetail }) {
  return (
    <div
      className={clsx(
        "rounded-lg border p-3 text-sm",
        severityClass(warning.severity),
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-semibold">{warning.label}</p>
        <span className="text-xs uppercase tracking-wide opacity-75">{warning.category}</span>
      </div>
      <p className="mt-1 leading-5 opacity-85">{warning.description}</p>
      {!warning.known ? <p className="mt-1 text-xs opacity-65">Codigo: {warning.code}</p> : null}
    </div>
  );
}

function reliabilitySignals(result: ValuationResponse, warnings: WarningDetail[]) {
  const locationSignals = warnings.filter((warning) => warning.category === "ubicacion");
  const comparableSignals = warnings.filter((warning) => warning.category === "comparables");
  const surfaceSignals = warnings.filter((warning) => warning.category === "superficie");

  return [
    {
      caption: locationSignals.length ? "La API reporto senales de ubicacion/geocoding." : "Sin senales de ubicacion en warnings.",
      label: "Ubicacion",
      value: locationSignals.length ? `${locationSignals.length} senal(es)` : "Sin alerta",
    },
    {
      caption: comparableSignals.length ? "Revisar diversidad, fuente o cantidad de comparables." : "Sin flags especificos de comparables.",
      label: "Comparables",
      value: comparableSignals.length ? `${comparableSignals.length} senal(es)` : "Sin alerta",
    },
    {
      caption: result.surface_adjustment_reason || (surfaceSignals.length ? "Hay senales sobre superficie/precio." : "Sin ajuste reportado."),
      label: "Superficie",
      value: result.surface_adjustment_applied ? "Ajuste aplicado" : surfaceSignals.length ? "Con observacion" : "Sin ajuste",
    },
  ];
}

function normalizeConfidence(value: string | number | null | undefined): "high" | "medium" | "low" | "unknown" {
  if (typeof value === "number") {
    if (value >= 0.75) return "high";
    if (value >= 0.5) return "medium";
    return "low";
  }
  const normalized = String(value ?? "").trim().toLowerCase();
  if (normalized === "high") return "high";
  if (normalized === "medium") return "medium";
  if (normalized === "low" || normalized === "insufficient_data") return "low";
  return "unknown";
}

function confidenceExplanation(confidence: ReturnType<typeof normalizeConfidence>): string {
  if (confidence === "high") {
    return "Alta confianza sugiere buena profundidad de comparables y senales consistentes para esta estimacion.";
  }
  if (confidence === "medium") {
    return "Confianza media indica una estimacion util, pero con limitaciones que conviene revisar antes de decidir.";
  }
  if (confidence === "low") {
    return "Confianza baja debe leerse como resultado exploratorio o con datos insuficientes.";
  }
  return "La API no entrego un nivel de confianza claro; interpreta la tasacion como referencia inicial.";
}

function confidenceTone(confidence: ReturnType<typeof normalizeConfidence>): string {
  if (confidence === "high") return "border-accent-500/30 bg-accent-500/10 text-emerald-100";
  if (confidence === "medium") return "border-amber-500/30 bg-amber-500/10 text-amber-100";
  return "border-danger-500/30 bg-danger-500/10 text-red-100";
}

function severityClass(severity: WarningSeverity): string {
  if (severity === "risk") return "border-danger-500/30 bg-danger-500/10 text-red-100";
  if (severity === "warning") return "border-amber-500/30 bg-amber-500/10 text-amber-100";
  return "border-brand-500/25 bg-brand-500/10 text-violet-100";
}

function hasLowDataSignal(warnings: WarningDetail[]): boolean {
  return warnings.some((warning) =>
    ["low_data", "low_data_mode", "low_comparable_count"].includes(warning.code),
  );
}

function betaScopeLabel(result: ValuationResponse): string {
  if (result.beta_scope_message) return "Con mensaje beta";
  if (result.beta_scope_status) return result.beta_scope_status.replaceAll("_", " ");
  if (result.beta_scope_flags?.length) return "Con flags beta";
  return "No informado";
}
