import { apiClient } from "@/lib/api/client";

export type RecentTasarActivityEvent = {
  id: string;
  event_type: string;
  title: string;
  description: string;
  occurred_at: string;
  source: string;
  valuation_id?: number | null;
  listing_id?: number | null;
  report_id?: number | null;
  comuna?: string | null;
  property_type?: string | null;
  estimated_value_uf?: number | null;
  range_low_uf?: number | null;
  range_high_uf?: number | null;
  trend_points_uf: number[];
  confidence?: string | null;
  status?: string | null;
  reason?: string | null;
};

export type RecentTasarActivity = {
  status: string;
  user_id: number;
  events_count: number;
  events: RecentTasarActivityEvent[];
  reasons: string[];
  warnings: string[];
};

export function getRecentTasarActivity(limit = 3) {
  return apiClient.get<RecentTasarActivity>(`/api/v1/tasar/activity/recent?limit=${limit}`);
}
