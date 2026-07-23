import type { Comparable, ValuationResponse } from "@/types/valuation";

const INITIAL_COMPARABLES_COUNT = 4;

type ComparableResponse = Pick<ValuationResponse, "comparable_count" | "comparables">;

export type ComparablePresentation = {
  available: Comparable[];
  availableCount: number;
  initiallyVisible: Comparable[];
  totalUsed: number;
};

/** Keeps the engine count distinct from the cards included in the response. */
export function getComparablePresentation(response: ComparableResponse): ComparablePresentation {
  const available = Array.isArray(response.comparables) ? response.comparables : [];
  const reportedCount = Number.isFinite(response.comparable_count) ? Math.max(0, response.comparable_count) : 0;

  return {
    available,
    availableCount: available.length,
    initiallyVisible: available.slice(0, INITIAL_COMPARABLES_COUNT),
    totalUsed: Math.max(reportedCount, available.length),
  };
}
