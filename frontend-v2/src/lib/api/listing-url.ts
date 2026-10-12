import { apiClient } from "./client";
import { downloadAuthenticatedReport } from "./download";
import type { ListingLookupResponse, ListingAnalysisResponse, ListingFreshnessMetadata } from "@/types/listing";

export const listingUrlApi = {
  savedStatus: (id: number, signal?: AbortSignal) => apiClient.get<{saved:boolean}>(`/api/v1/watchlist/${id}/status`,{signal}),
  lookup: (url: string, signal?: AbortSignal) => apiClient.post<ListingLookupResponse>("/api/v1/listings/lookup-url", {url}, {signal, timeoutMs:120000}),
  analyze: (url: string, signal?: AbortSignal) => apiClient.post<ListingAnalysisResponse>("/api/v1/listings/analyze-url", {url}, {signal, timeoutMs:120000}),
  save: (id: number, signal?: AbortSignal) => apiClient.post<ListingFreshnessMetadata>(`/api/v1/watchlist/${id}`,undefined,{signal}),
  report: (analysis: ListingAnalysisResponse) => downloadAuthenticatedReport({endpoint:"/api/v1/reports/listing-analysis?format=html",fallbackFilename:"valoria-analisis-publicacion.html",body:{analysis}}),
};
