export type UFRate = {
  rate_clp: number;
  source: string;
  is_fallback: boolean;
  cache_hit: boolean;
  cache_ttl_seconds: number;
  observed_at: string;
  rate_date?: string | null;
  fetched_at?: string | null;
  is_stale: boolean;
  stale_reason?: string | null;
};

export type DashboardContractStatus =
  | "available"
  | "partial"
  | "empty"
  | "coming_soon"
  | "error"
  | "manual"
  | string;

export type MarketIndicator = {
  key: string;
  label: string;
  status: DashboardContractStatus;
  value: number | string | null;
  delta_pct: number | null;
  unit: string | null;
  description: string;
};

export type MarketInsight = {
  status: DashboardContractStatus;
  text: string;
};

export type ValoriaIndexSummary = {
  status: DashboardContractStatus;
  available: boolean;
  value: number | null;
  max: number;
  label: string;
  confidence_label: string;
  description: string;
  source: string;
};

export type MarketBriefing = {
  status: DashboardContractStatus;
  available: boolean;
  market: string;
  headline: string;
  summary: string;
  indicators: MarketIndicator[];
  insight: MarketInsight;
  valoria_index: ValoriaIndexSummary;
  updated_at: string | null;
  source: string;
};

export type MicrozoneSummaryItem = {
  id: string;
  name: string;
  type: "microzone" | "sector_proxy" | "comuna_proxy" | string;
  status: DashboardContractStatus;
  score?: number | null;
  variation_pct?: number | null;
  active_listings: number;
  fresh_listings: number;
  median_price_m2_uf?: number | null;
  confidence: "low" | "medium" | "high" | string;
  note: string;
};

export type MicrozonesSummary = {
  status: DashboardContractStatus;
  available: boolean;
  items: MicrozoneSummaryItem[];
  message: string;
  source: string;
};

export type LiquiditySummary = {
  status: DashboardContractStatus;
  available: boolean;
  value: number | null;
  max: number;
  label: string;
  message: string;
  diagnostics: {
    active_listings?: number | null;
    fresh_listings?: number | null;
    price_changes_30d?: number | null;
    markets_with_depth?: number | null;
    [key: string]: number | null | undefined;
  };
  source: string;
};
