import { apiClient } from "./client";
import { downloadAuthenticatedReport } from "./download";
import type { ValuationRequest, ValuationResponse } from "@/types/valuation";

export const createValuation = (payload: ValuationRequest, signal?: AbortSignal) =>
  apiClient.post<ValuationResponse>("/api/v1/valuations", payload, { signal, timeoutMs: 120000 });

export const downloadValuationReport = (payload: ValuationRequest, result: ValuationResponse) =>
  downloadAuthenticatedReport({ endpoint: "/api/v1/reports/valuation?format=html", fallbackFilename: "valoria-tasacion.html", body: { valuation_payload: payload, valuation_result: result } });
