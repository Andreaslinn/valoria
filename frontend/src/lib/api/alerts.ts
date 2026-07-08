import { apiClient } from "@/lib/api/client";
import type { AlertItem, AlertReadResponse } from "@/types/alerts";

export function listAlerts(limit = 50) {
  return apiClient.get<AlertItem[]>(`/api/v1/alerts?limit=${limit}`);
}

export function markAlertRead(alertId: number) {
  return apiClient.post<AlertReadResponse>(`/api/v1/alerts/${alertId}/read`);
}
