import { ApiError } from "./client";

type Check = (value: unknown) => boolean;
const text: Check = value => typeof value === "string";
const number: Check = value => typeof value === "number" && Number.isFinite(value);
const boolean: Check = value => typeof value === "boolean";
const record: Check = value => value !== null && typeof value === "object" && !Array.isArray(value);
const nullable = (check: Check): Check => value => value === null || check(value);
const optional = (check: Check): Check => value => value === undefined || check(value);
const array = (check: Check): Check => value => Array.isArray(value) && value.every(check);
const object = (fields: Record<string, Check>): Check => value => record(value) && Object.entries(fields).every(([key, check]) => check((value as Record<string, unknown>)[key]));
const capability = { status: text, available: boolean };

// Validate the fields consumed by Resumen, allowing additional FastAPI fields.
// Sources: api/v1/*.py, domain/portfolio/contracts.py, services/market_dashboard_overview.py.
export const summaryContracts = {
  user: object({ id: number, email: text, role: text, is_active: boolean }),
  login: object({ access_token: text, expires_in: number }),
  portfolio: object({
    user_id: number, tracked_properties: number, unread_alert_count: number,
    items: array(object({
      listing_id: number, watchlist_item_id: number, title: text, comuna: text, property_type: text,
      m2: nullable(number), bedrooms: number, bathrooms: number, published_price_uf: nullable(number),
      published_price_clp: nullable(number), price_basis: text, url: nullable(text), listing_status: text,
      avm: object({ ...capability, estimated_value_uf: nullable(number), confidence: nullable(text), snapshot_created_at: nullable(text) }),
      delta: object({ ...capability, delta_pct: nullable(number), delta_uf: nullable(number) }),
    })),
    history: object({ ...capability, points: array(object({ snapshot_date: text, snapshot_at: text, average_estimated_value_uf: number, coverage_count: number, unavailable_count: number })) }),
    average_avm_variation: object({ ...capability, variation_pct: nullable(number), observation_window_days: nullable(number) }),
    upside: object({ ...capability, total_upside_uf: nullable(number), average_delta_pct: nullable(number) }),
  }),
  watchlist: array(object({ id: number, listing_id: number, status: text, title: text, comuna: text,
    property_type: optional(nullable(text)), m2: nullable(number), dormitorios: number, banos: number,
    price_uf: nullable(number), price_clp: number, price_currency: nullable(text), price_uf_display: nullable(number),
    price_display_basis: text, url: nullable(text), listing_status: text,
  })),
  alerts: array(object({ id: number, listing_id: number, alert_type: text, message: text, payload: record,
    created_at: text, is_read: boolean, title: nullable(text), comuna: nullable(text),
  })),
  patrimonyAlerts: object({ items: array(object({ id: number, title: text, message: text, alert_type: text,
    severity: text, property_name: nullable(text), created_at: text, read_at: nullable(text), dismissed_at: nullable(text),
  })) }),
  uf: object({ rate_clp: number, source: text, is_fallback: boolean, is_stale: boolean, observed_at: text }),
  market: object({ status: text, cutoff_at: text, methodology: text,
    scope: object({ period_days: number, property_type: nullable(text) }),
    communes: array(object({ comuna: text, active_listings: number, new_listings: number, listings_with_price_drop: number, median_price_m2_uf: nullable(number), confidence: text })),
  }),
  marketFlow: object({ status: text, cutoff_at: text, daily_pulse: array(object({ date: text, new_listings: number, removed_or_inactive: number, price_drop_events: number })), overview: object({ new_listings: number, removed_or_inactive: number, listings_with_price_drop: number, price_drop_events: number }), coverage: object({ active_listings: number }) }),
  trend: object({ status: text, change_pct: nullable(number), source: text, warnings: array(text), reasons: array(text),
    points: array(object({ month: text, median_price_m2_uf: number, sample_count: number })),
  }),
  radar: object({ status: text, mode: text, auto_run: boolean, summary: text,
    ready_for_radar_count: nullable(number), requires_manual_run: boolean,
  }),
  opportunities: array(object({ listing_id: nullable(number), title: text, comuna: text, price_uf: number,
    m2: number, usable_area_m2: optional(nullable(number)), built_area_m2: optional(nullable(number)),
    bedrooms: optional(nullable(number)), bathrooms: optional(nullable(number)), estimated_price_uf: number,
    estimated_value_uf: optional(nullable(number)), discount_pct: number, confidence: text,
    confidence_label: text, comparables_used: number, url: nullable(text), warnings: array(text),
    confidence_risk_flags: array(text), radar_verdict_message: text,
  })),
};

export function validateSummaryResponse<T>(key: keyof typeof summaryContracts, value: T): T {
  if (!summaryContracts[key](value)) {
    throw new ApiError(`Contrato incompatible en ${key}: la API no devolvió los campos esperados.`, 502);
  }
  return value;
}
