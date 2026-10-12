import {apiClient} from "./client";
import type {AlertItem,AlertReadResponse} from "@/types/alerts";
import type {PatrimonyAlert} from "@/types/summary";
export function listAlerts(limit=50){return apiClient.get<AlertItem[]>(`/api/v1/alerts?limit=${limit}`);}
export function markAlertRead(id:number){return apiClient.post<AlertReadResponse>(`/api/v1/alerts/${id}/read`);}
export const alertsApi={
 historyWatchlist:(signal?:AbortSignal)=>apiClient.get<AlertItem[]>("/api/v1/alerts?limit=100&include_read=true",{signal}),
 historyPatrimony:(signal?:AbortSignal)=>apiClient.get<{items:PatrimonyAlert[]}>("/api/v1/patrimony/alerts?include_read=true&include_dismissed=true",{signal}),
 readWatchlist:markAlertRead,
 readPatrimony:(id:number)=>apiClient.patch<PatrimonyAlert>(`/api/v1/patrimony/alerts/${id}/read`),
};
