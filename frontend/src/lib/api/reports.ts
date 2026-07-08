import { downloadAuthenticatedReport } from "@/lib/api/download";
import type { ListingAnalysisResponse } from "@/types/listing";
import type { ValuationRequest, ValuationResponse } from "@/types/valuation";

export function downloadValuationReport({
  payload,
  result,
}: {
  payload: ValuationRequest;
  result: ValuationResponse;
}) {
  return downloadAuthenticatedReport({
    endpoint: "/api/v1/reports/valuation?format=html",
    fallbackFilename: "valoria-tasacion.html",
    body: {
      valuation_payload: payload,
      valuation_result: result,
    },
  });
}

export function downloadListingAnalysisReport(analysis: ListingAnalysisResponse) {
  return downloadAuthenticatedReport({
    endpoint: "/api/v1/reports/listing-analysis?format=html",
    fallbackFilename: "valoria-analisis-publicacion.html",
    body: { analysis },
  });
}
