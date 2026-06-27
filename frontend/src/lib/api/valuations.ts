import { apiClient } from "@/lib/api/client";
import type { ValuationRequest, ValuationResponse } from "@/types/valuation";

export function createValuation(payload: ValuationRequest) {
  return apiClient.post<ValuationResponse>("/api/v1/valuations", payload);
}
