export type PropertyType = "apartment" | "house" | "office";

export type ValuationRequest = {
  comuna: string;
  property_type?: PropertyType;
  m2: number;
  built_area_m2?: number;
  land_area_m2?: number | null;
  usable_area_m2?: number | null;
  dormitorios?: number | null;
  banos?: number | null;
  estacionamientos?: number | null;
  precio_publicado_uf?: number | null;
  precio_publicado_clp?: number | null;
};

export type Comparable = {
  listing_id: number | null;
  title: string;
  comuna: string;
  price_uf: number;
  price_clp: number;
  m2: number | null;
  built_area_m2?: number | null;
  land_area_m2?: number | null;
  usable_area_m2?: number | null;
  dormitorios?: number | null;
  banos?: number | null;
  bedrooms?: number | null;
  bathrooms?: number | null;
  similarity: number;
  score?: number | null;
  url: string | null;
};

export type ValuationConsensus = {
  status: string;
  method: string;
  estimate_uf: number | null;
  estimate_clp: number | null;
  range_low_uf: number | null;
  range_high_uf: number | null;
  confidence: number | null;
  selected_engine_names: string[];
  engine_weights: Record<string, number>;
  consensus_used?: boolean;
  valid_engine_count?: number;
  engine_family_count?: number;
  engine_families?: string[];
  fallback_reason?: string | null;
  fallback_engine_used?: string | null;
};

export type ValuationEngineResult = {
  engine_name: string;
  engine_version: string;
  engine_family?: string | null;
  role: string;
  status: string;
  estimate_uf?: number | null;
  estimate_clp?: number | null;
  range_low_uf?: number | null;
  range_high_uf?: number | null;
  confidence?: number | null;
  comparables_count?: number | null;
  selected_for_final: boolean;
  warnings: string[];
  safe_error_message?: string | null;
};

export type ValuationVerdict = {
  estimate_uf?: number | null;
  low_uf?: number | null;
  high_uf?: number | null;
  confidence?: number | null;
  explanation?: string | string[] | null;
  source?: "consensus_v1" | "consensus_experimental" | "current_valuation" | string | null;
  status?: string | null;
};

export type ValuationEngineBreakdown = {
  engine_name: string;
  label?: string | null;
  role?: string | null;
  estimate_uf?: number | null;
  low_uf?: number | null;
  high_uf?: number | null;
  confidence?: number | null;
  weight?: number | null;
  status: string;
  explanation?: string | null;
  warning_flags: string[];
};

export type ValuationConsensusAudit = {
  engines_used: string[];
  engines_abstained: Record<string, string>;
  engines_failed: Record<string, string>;
  disagreement_level?: string | number | null;
  weight_audit: Record<string, unknown>[];
};

export type ValuationResponse = {
  base_estimated_price_uf?: number | null;
  base_estimated_price_clp?: number | null;
  estimated_price_uf: number | null;
  estimated_price_clp: number | null;
  price_range_low_uf?: number | null;
  price_range_high_uf?: number | null;
  price_range_low_clp?: number | null;
  price_range_high_clp?: number | null;
  confidence: string;
  confidence_score?: number | null;
  confidence_label: string;
  confidence_reasons: string[];
  confidence_risk_flags: string[];
  comparable_count: number;
  price_m2_uf: number | null;
  status: string;
  warnings: string[];
  comparable_quality_level?: string | null;
  comparable_quality_flags: string[];
  beta_scope_status?: string | null;
  beta_scope_flags: string[];
  beta_scope_message?: string | null;
  surface_adjustment_applied: boolean;
  surface_adjustment_weight: number;
  surface_adjustment_reason?: string | null;
  comparables: Comparable[];
  consensus?: ValuationConsensus | null;
  engine_results: ValuationEngineResult[];
  selected_engine_names: string[];
  consensus_method?: string | null;
  valuation_verdict?: ValuationVerdict | null;
  engine_breakdown: ValuationEngineBreakdown[];
  consensus_audit?: ValuationConsensusAudit | null;
  weight_audit: Record<string, unknown>[];
  valuation_strategy?: string;
  consensus_used?: boolean;
  consensus_unavailable_reason?: string | null;
  fallback_engine_used?: string | null;
};
