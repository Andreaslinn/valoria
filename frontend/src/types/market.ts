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
  | "unavailable"
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
  reason_codes?: string[];
  metrics_used?: Record<string, number | string | null>;
};

export type MarketBalanceComponent = {
  key: "supply_flow" | "price_reductions" | "observed_time" | "price_trend" | string;
  label: string;
  score: number;
  weight: number;
  status: DashboardContractStatus;
  confidence: "low" | "medium" | "high" | string;
  raw_value: number | string | null;
  description: string;
  direction: "up" | "down" | "flat" | "slower" | "faster" | "unknown" | string;
};

export type MarketBalance = {
  status: DashboardContractStatus;
  score: number | null;
  max: number;
  label: string;
  side: string;
  headline: string;
  summary: string;
  confidence: "low" | "medium" | "high" | string;
  confidence_score: number | null;
  confidence_coverage: number | null;
  components: MarketBalanceComponent[];
  methodology?: string;
};

export type RecentMarketActivity = {
  status: DashboardContractStatus;
  new_24h: number;
  new_7d: number;
  removed_24h: number;
  removed_7d: number;
  price_drops_24h: number;
  price_drops_7d: number;
  price_drops_30d: number;
  unique_listings_with_price_drop_30d: number;
  total_price_drop_events_30d: number;
  net_flow_24h: number;
  net_flow_7d: number;
};

export type ObservedPublicationTime = {
  status: DashboardContractStatus;
  median_days: number | null;
  p25_days: number | null;
  p75_days: number | null;
  sample_size: number;
  usable_timestamp_share: number;
  label: string;
  comparison: {
    status: DashboardContractStatus;
    previous_period_median_days: number | null;
    change_days: number | null;
    direction: string | null;
  };
  methodology?: string;
};

export type FeaturedCommune = {
  status: DashboardContractStatus;
  comuna?: string;
  criterion: string;
  reason_code?: string;
  headline?: string;
  metric_label?: string;
  metric_value?: number;
  active_listings?: number;
  new_7d?: number;
  removed_7d?: number;
  price_drops_30d?: number;
  median_observed_days?: number | null;
  median_price_m2_uf?: number | null;
  confidence?: "low" | "medium" | "high" | string;
};

export type MarketDynamismComponent = {
  key: string;
  value: number;
  normalized: number;
  weight: number;
};

export type MarketDynamism = {
  status: DashboardContractStatus;
  score: number | null;
  max: number;
  label: string;
  summary: string;
  confidence: "low" | "medium" | "high" | string;
  components: MarketDynamismComponent[];
  raw_metrics: {
    active_listings: number;
    new_7d: number;
    removed_7d: number;
    price_drops_30d: number;
    communes_with_activity: number;
    [key: string]: number;
  };
  market?: string;
  updated_at?: string | null;
  methodology?: string;
};

export type MarketCoverage = {
  active_listings: number;
  eligible_for_flow: number;
  eligible_for_observed_time: number;
  eligible_for_price_changes: number;
  communes_with_minimum_sample: number;
};

export type CommuneSummaryItem = {
  comuna: string;
  active_listings: number;
  new_24h: number;
  new_7d: number;
  removed_7d: number;
  net_flow_7d: number;
  price_drops_30d: number;
  price_drop_share_30d: number;
  median_observed_days: number | null;
  observed_time_sample: number;
  median_price_m2_uf: number | null;
  price_m2_sample: number;
  price_history_sample: number;
  market_balance_score: number;
  market_balance_label: string;
  buyer_seller_balance: string;
  confidence: "low" | "medium" | "high" | string;
};

export type CommunesSummary = {
  status: DashboardContractStatus;
  market: string;
  updated_at: string | null;
  items: CommuneSummaryItem[];
  sort: string;
  minimum_sample: {
    active_listings: number;
    observed_time: number;
    price_history: number;
  };
};

export type DynamismSummary = MarketDynamism;

export type MarketPulse = {
  status: DashboardContractStatus;
  market: string;
  property_type: string;
  updated_at: string | null;
  market_balance: MarketBalance;
  recent_activity: RecentMarketActivity;
  observed_publication_time: ObservedPublicationTime;
  featured_commune: FeaturedCommune;
  market_dynamism: MarketDynamism;
  insight: MarketInsight;
  coverage: MarketCoverage;
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
  diagnostics: {
    active_apartments?: number | null;
    fresh_apartments?: number | null;
    stale_listings?: number | null;
    removed_or_inactive?: number | null;
    missing_url?: number | null;
    new_listings_24h?: number | null;
    new_listings_7d?: number | null;
    removed_7d?: number | null;
    price_changes_30d?: number | null;
    [key: string]: number | null | undefined;
  };
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
    new_listings_7d?: number | null;
    removed_7d?: number | null;
    price_changes_30d?: number | null;
    comunas_with_depth?: number | null;
    [key: string]: number | null | undefined;
  };
  source: string;
};
