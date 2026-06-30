import { apiClient } from "@/lib/api/client";
import type { UFRate } from "@/types/market";

export function getCurrentUf() {
  return apiClient.get<UFRate>("/api/v1/market/uf");
}
