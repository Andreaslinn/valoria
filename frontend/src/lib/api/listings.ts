import { apiClient } from "@/lib/api/client";
import type { ListingAnalysisResponse, ListingLookupResponse } from "@/types/listing";

export function lookupListingUrl(url: string) {
  return apiClient.post<ListingLookupResponse>("/api/v1/listings/lookup-url", { url });
}

export function analyzeListingUrl(url: string) {
  return apiClient.post<ListingAnalysisResponse>("/api/v1/listings/analyze-url", { url });
}
