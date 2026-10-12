import type { PropertyType } from "@/types/valuation";

const TASAR_PREFILL_KEY = "valoria_tasar_prefill";

export type ValuationFormPrefill = {
  targetListingId?: number;
  comuna?: string;
  propertyType?: PropertyType;
  reference?: string;
  builtAreaM2?: number;
  landAreaM2?: number;
  usableAreaM2?: number;
  dormitorios?: number;
  banos?: number;
  estacionamientos?: number;
  publishedPriceUf?: number;
  publishedPriceClp?: number;
  sourceUrl?: string;
  importedFrom?: "listing-url";
};

export function consumeTasarPrefill(): ValuationFormPrefill | null {
  if (typeof window === "undefined") {
    return null;
  }

  const raw = window.sessionStorage.getItem(TASAR_PREFILL_KEY);
  window.sessionStorage.removeItem(TASAR_PREFILL_KEY);
  if (!raw) {
    return null;
  }

  try {
    return JSON.parse(raw) as ValuationFormPrefill;
  } catch {
    return null;
  }
}

export function saveTasarPrefill(value: ValuationFormPrefill): void {
  window.sessionStorage.setItem(TASAR_PREFILL_KEY, JSON.stringify(value));
}
