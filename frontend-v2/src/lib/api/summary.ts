import { apiClient, type RequestOptions } from "./client";
import { validateSummaryResponse, type summaryContracts } from "./summary-contracts";

import type { MarketFlow, PortfolioSummary, SessionUser, MarketOverview, PriceTrend, PatrimonyAlert } from "@/types/summary";
import type { AlertItem } from "@/types/alerts";
import type { UFRate } from "@/types/market";
import type { WatchlistItem } from "@/types/watchlist";
import type { RadarOpportunity, RadarSummary } from "@/types/radar";

const checked = <T>(key: keyof typeof summaryContracts, response: Promise<T>): Promise<T> => response.then(value => validateSummaryResponse(key, value));

// All reads used by the summary are dispatched by useSummary, not by individual cards.
export const summaryApi = {
  user: (options?: RequestOptions) => checked("user", apiClient.get<SessionUser>("/api/v1/auth/me", options)),
  portfolio: (options?: RequestOptions) => checked("portfolio", apiClient.get<PortfolioSummary>("/api/v1/portfolio/summary", options)),
  watchlist: (options?: RequestOptions) => checked("watchlist", apiClient.get<WatchlistItem[]>("/api/v1/watchlist", options)),
  alerts: (options?: RequestOptions) => checked("alerts", apiClient.get<AlertItem[]>("/api/v1/alerts?limit=100", options)),
  patrimonyAlerts: (options?: RequestOptions) => checked("patrimonyAlerts", apiClient.get<{ items: PatrimonyAlert[] }>("/api/v1/patrimony/alerts", options)),
  uf: (options?: RequestOptions) => checked("uf", apiClient.get<UFRate>("/api/v1/market/uf", { ...options, token: null })),
  market: (options?: RequestOptions) => checked("market", apiClient.get<MarketOverview>("/api/v1/market/dashboard?period_days=30&property_type=apartment", options)),
  marketFlow: (options?: RequestOptions) => checked("marketFlow", apiClient.get<MarketFlow>("/api/v1/market/dashboard?period_days=90&property_type=apartment", options)),
  trend: (commune: string, options?: RequestOptions) => checked("trend", apiClient.get<PriceTrend>(`/api/v1/market/trends/price-m2?${new URLSearchParams({ comuna: commune, property_type: "apartment", period_months: "3" })}`, options)),
  radar: (options?: RequestOptions) => checked("radar", apiClient.get<RadarSummary>("/api/v1/radar/summary", options)),
  opportunities: (options?: RequestOptions) => checked("opportunities", apiClient.get<RadarOpportunity[]>("/api/v1/radar/opportunities?limit=2", { ...options, timeoutMs: 120000 })),
  login: (email: string, password: string) => checked("login", apiClient.form<{ access_token: string; expires_in: number }>("/api/v1/auth/login", new URLSearchParams({ username: email, password }), { token: null })),
  readAlert: (id: number) => apiClient.post("/api/v1/alerts/" + id + "/read"),
  readPatrimonyAlert: (id: number) => apiClient.patch("/api/v1/patrimony/alerts/" + id + "/read"),
};
