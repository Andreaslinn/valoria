import { apiClient } from "@/lib/api/client";
import type {
  CommunesSummary,
  DynamismSummary,
  LiquiditySummary,
  MarketBriefing,
  MarketPulse,
  MicrozonesSummary,
  UFRate,
} from "@/types/market";

export function getCurrentUf() {
  return apiClient.get<UFRate>("/api/v1/market/uf");
}

export function getMarketPulse() {
  return apiClient.get<MarketPulse>("/api/v1/market/pulse");
}

export function getCommunesSummary() {
  return apiClient.get<CommunesSummary>("/api/v1/market/communes/summary");
}

export function getMarketDynamismSummary() {
  return apiClient.get<DynamismSummary>("/api/v1/market/dynamism/summary");
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
