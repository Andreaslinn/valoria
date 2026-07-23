import type { ValuationResponse } from "@/types/valuation";

const engineLabels: Record<string, string> = {
  valoria_consensus_v1: "Consenso Valoria",
  valoria_consensus_v1_min_two_families: "Consenso Valoria",
  consensus_v1: "Consenso Valoria",
  comparables_canonical_outliers: "Comparables Valoria",
  comparables_canonical: "Comparables canónicos",
  canonical_outliers_v1: "Comparables Valoria",
  canonical_v1: "Comparables canónicos",
  comparables_legacy: "Comparables Valoria",
  legacy: "Comparables Valoria",
  current: "Comparables Valoria",
  current_valuation: "Comparables Valoria",
  current_engine_fallback: "Comparables Valoria",
  comparables_quality_v2: "Comparables Valoria",
  quality_v2_guarded_challenger_v1: "Comparables Valoria",
  hedonic_baseline_v1: "Modelo hedónico",
  microzone_geo_v1: "Modelo territorial",
  land_building_v1: "Suelo y construcción",
  market_trends_v1: "Tendencia de mercado",
};

export function valuationEngineLabel(identifier: string | null | undefined): string {
  return engineLabels[identifier?.trim().toLowerCase() ?? ""] ?? "Modelo Valoria";
}

export function valuationEngineDisplayName(result: ValuationResponse): string {
  if (result.consensus_used || result.valuation_verdict?.source === "consensus_v1") {
    return "Consenso Valoria";
  }

  const selectedEngine = result.engine_results.find((engine) => engine.selected_for_final)
    ?? result.selected_engine_names[0]
    ?? result.fallback_engine_used
    ?? result.valuation_strategy
    ?? result.consensus_method;

  return valuationEngineLabel(typeof selectedEngine === "string" ? selectedEngine : selectedEngine?.engine_name);
}
