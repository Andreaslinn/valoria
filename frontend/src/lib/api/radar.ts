import { apiClient } from "@/lib/api/client";
import type { RadarOpportunity, RadarOpportunityFilters, RadarSummary } from "@/types/radar";

export function getRadarSummary() {
  return apiClient.get<RadarSummary>("/api/v1/radar/summary");
}

export function listRadarOpportunities(filters: RadarOpportunityFilters = {}) {
  const params = new URLSearchParams();
  params.set("limit", String(filters.limit ?? 20));

  if (filters.bedroomsMin != null) {
    params.set("bedrooms_min", String(filters.bedroomsMin));
  }

  if (filters.bedroomsMax != null) {
    params.set("bedrooms_max", String(filters.bedroomsMax));
  }

  return apiClient.get<RadarOpportunity[]>(`/api/v1/radar/opportunities?${params.toString()}`);
}
