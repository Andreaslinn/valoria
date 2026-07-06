import { apiClient } from "@/lib/api/client";
import type { LiquiditySummary, MarketBriefing, MicrozonesSummary, UFRate } from "@/types/market";

export function getCurrentUf() {
  return apiClient.get<UFRate>("/api/v1/market/uf");
}

export function getMarketBriefing() {
  return apiClient.get<MarketBriefing>("/api/v1/market/briefing");
}

export function getMicrozonesSummary() {
  return apiClient.get<MicrozonesSummary>("/api/v1/market/microzones/summary");
}

export function getLiquiditySummary() {
  return apiClient.get<LiquiditySummary>("/api/v1/market/liquidity/summary");
}
