import { apiClient } from "@/lib/api/client";
import type {
  PatrimonyAlert,
  PatrimonyAlertEvaluation,
  PatrimonyAlertList,
  PatrimonyIntelligence,
  PatrimonyStrategy,
  PatrimonyStrategyDeleteResult,
  PatrimonyStrategyInput,
  PatrimonyStrategyList,
  PatrimonyStrategyPatchInput,
  PropertyAsset,
  PropertyAssetCreateInput,
  PropertyAssetList,
  PropertyDeleteResult,
  TerritorialDevelopmentList,
} from "@/types/patrimony";

export function createPatrimonyProperty(payload: PropertyAssetCreateInput) {
  return apiClient.post<PropertyAsset>("/api/v1/patrimony/properties", payload);
}

export function listPatrimonyProperties() {
  return apiClient.get<PropertyAssetList>("/api/v1/patrimony/properties");
}

export function getPatrimonyProperty(propertyId: number) {
  return apiClient.get<PropertyAsset>(`/api/v1/patrimony/properties/${propertyId}`);
}

export function getPatrimonyPropertyIntelligence(propertyId: number) {
  return apiClient.get<PatrimonyIntelligence>(`/api/v1/patrimony/properties/${propertyId}/intelligence`);
}

export function deletePatrimonyProperty(propertyId: number) {
  return apiClient.delete<PropertyDeleteResult>(`/api/v1/patrimony/properties/${propertyId}`);
}

export function listTerritorialDevelopments() {
  return apiClient.get<TerritorialDevelopmentList>("/api/v1/patrimony/developments");
}

export function listPropertyTerritorialDevelopments(propertyId: number) {
  return apiClient.get<TerritorialDevelopmentList>(`/api/v1/patrimony/properties/${propertyId}/developments`);
}

export function listPatrimonyAlerts() {
  return apiClient.get<PatrimonyAlertList>("/api/v1/patrimony/alerts");
}

export function markPatrimonyAlertRead(alertId: number) {
  return apiClient.patch<PatrimonyAlert>(`/api/v1/patrimony/alerts/${alertId}/read`);
}

export function dismissPatrimonyAlert(alertId: number) {
  return apiClient.patch<PatrimonyAlert>(`/api/v1/patrimony/alerts/${alertId}/dismiss`);
}

export function evaluatePatrimonyAlerts() {
  return apiClient.post<PatrimonyAlertEvaluation>("/api/v1/patrimony/alerts/evaluate");
}

export function createPatrimonyStrategy(payload: PatrimonyStrategyInput) {
  return apiClient.post<PatrimonyStrategy>("/api/v1/patrimony/strategies", payload);
}

export function listPatrimonyStrategies() {
  return apiClient.get<PatrimonyStrategyList>("/api/v1/patrimony/strategies");
}

export function getPatrimonyStrategy(strategyId: number) {
  return apiClient.get<PatrimonyStrategy>(`/api/v1/patrimony/strategies/${strategyId}`);
}

export function updatePatrimonyStrategy(strategyId: number, payload: PatrimonyStrategyPatchInput) {
  return apiClient.patch<PatrimonyStrategy>(`/api/v1/patrimony/strategies/${strategyId}`, payload);
}

export function deletePatrimonyStrategy(strategyId: number) {
  return apiClient.delete<PatrimonyStrategyDeleteResult>(`/api/v1/patrimony/strategies/${strategyId}`);
}
