import { apiClient, type RequestOptions } from "./client";
import { validateSummaryResponse } from "./summary-contracts";
import type { RadarOpportunity } from "@/types/radar";
export const getRadarOpportunities = (options?: RequestOptions) => apiClient.get<RadarOpportunity[]>("/api/v1/radar/opportunities?limit=20", { ...options, timeoutMs: 120000 }).then(data => validateSummaryResponse("opportunities", data));
