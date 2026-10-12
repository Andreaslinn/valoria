import { apiClient } from "@/lib/api/client";
import type { WatchlistItem, WatchlistStatus } from "@/types/watchlist";

export function listWatchlist() {
  return apiClient.get<WatchlistItem[]>("/api/v1/watchlist");
}

export function saveToWatchlist(listingId: number) {
  return apiClient.post<WatchlistItem>(`/api/v1/watchlist/${listingId}`);
}

export function removeFromWatchlist(listingId: number) {
  return apiClient.delete<WatchlistStatus>(`/api/v1/watchlist/${listingId}`);
}

export function getWatchlistStatus(listingId: number) {
  return apiClient.get<WatchlistStatus>(`/api/v1/watchlist/${listingId}/status`);
}
