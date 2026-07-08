export type AlertPayload = {
  change_basis?: string | null;
  drop_pct?: number | null;
  previous_price_uf?: number | null;
  new_price_uf?: number | null;
  previous_price_clp_snapshot?: number | null;
  new_price_clp_snapshot?: number | null;
  canonical_previous_price?: number | null;
  canonical_new_price?: number | null;
  display_previous_price_clp?: number | null;
  display_new_price_clp?: number | null;
  [key: string]: unknown;
};

export type AlertItem = {
  id: number;
  listing_id: number;
  alert_type: string;
  message: string;
  payload: AlertPayload;
  created_at: string;
  is_read: boolean;
  title: string | null;
  comuna: string | null;
  price_clp: number | null;
};

export type AlertReadResponse = {
  id: number;
  is_read: boolean;
};
