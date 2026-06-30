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
