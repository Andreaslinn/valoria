import { apiClient } from "@/lib/api/client";
import type { ListingLookupResponse } from "@/types/listing";

export function lookupListingUrl(url: string) {
  return apiClient.post<ListingLookupResponse>("/api/v1/listings/lookup-url", { url });
}
