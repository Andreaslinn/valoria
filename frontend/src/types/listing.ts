export type ListingLookupData = {
  listing_id?: number | null;
  title?: string | null;
  comuna?: string | null;
  property_type?: string | null;
  m2?: number | null;
  built_area_m2?: number | null;
  land_area_m2?: number | null;
  usable_area_m2?: number | null;
  dormitorios?: number | null;
  banos?: number | null;
  estacionamientos?: number | null;
  precio_publicado_uf?: number | null;
  precio_publicado_clp?: number | null;
  price_currency?: string | null;
  price_uf_source?: string | null;
  price_uf_confidence?: string | null;
  price_recovery_method?: string | null;
  price_clp_snapshot?: number | null;
  source?: string | null;
  url?: string | null;
};

export type ListingLookupResponse = {
  status: "found_existing" | "parsed_new" | "partial" | string;
  listing_data: ListingLookupData;
  warnings: string[];
  source: string | null;
  url: string;
};
