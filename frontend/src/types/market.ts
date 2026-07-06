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

export type DashboardContractStatus = "available" | "empty" | "coming_soon" | "error" | "manual" | string;

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
  name: string;
  score?: number | null;
  change_pct?: number | null;
  status?: string | null;
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
  source: string;
};
