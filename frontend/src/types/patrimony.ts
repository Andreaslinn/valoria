export type PropertyValuationSnapshotInput = {
  estimated_value_uf?: number | null;
  estimated_value_clp?: number | null;
  lower_bound_uf?: number | null;
  upper_bound_uf?: number | null;
  lower_bound_clp?: number | null;
  upper_bound_clp?: number | null;
  confidence?: string | null;
  confidence_score?: number | null;
  engine_name?: string | null;
  engine_version?: string | null;
  engine_payload?: Record<string, unknown>;
};

export type PropertyAssetCreateInput = {
  name: string;
  comuna: string;
  property_type?: string | null;
  m2: number;
  built_area_m2?: number | null;
  land_area_m2?: number | null;
  usable_area_m2?: number | null;
  bedrooms?: number | null;
  bathrooms?: number | null;
  parking?: number | null;
  lat?: number | null;
  lon?: number | null;
  characteristics?: Record<string, unknown>;
  valuation?: PropertyValuationSnapshotInput | null;
};

export type PropertyAssetList = {
  items: PropertyAsset[];
};

export type PropertyDeleteResult = {
  id: number;
  deleted: boolean;
};

export type PatrimonyRecommendation =
  | "maintain"
  | "monitor"
  | "prepare_sale"
  | "evaluate_exit"
  | "favorable_market";

export type PatrimonyIntelligence = {
  status: "available" | "insufficient_data" | string;
  property_id: number;
  comuna: string;
  buyer_seller_balance: string | null;
  dynamism: string | null;
  observed_publication_time_days: number | null;
  recent_movement: string | null;
  recommendation: PatrimonyRecommendation | null;
  reasons: string[];
  change_conditions: string[];
  confidence: "low" | "medium" | "high" | string;
  updated_at: string | null;
  signals: Record<string, number | string | null | undefined>;
  territorial_developments: TerritorialDevelopment[];
  territorial_projection_message: string;
};

export type TerritorialDevelopment = {
  id: number;
  name: string;
  development_type: string;
  status: "announced" | "planned" | "confirmed" | "under_construction" | "completed" | "cancelled" | string;
  description: string;
  affected_communes: string[];
  affected_microzones: string[];
  expected_start_date: string | null;
  expected_completion_date: string | null;
  horizon: string;
  source: {
    name: string;
    url: string | null;
    date: string | null;
  };
  confidence: "low" | "medium" | "high" | string;
  methodology: string;
  risks: string[];
  scenarios: {
    conservative_min_pct: number | null;
    conservative_max_pct: number | null;
    central_min_pct: number | null;
    central_max_pct: number | null;
    favorable_max_pct: number | null;
    narrative: string;
  };
  is_active: boolean;
};

export type TerritorialDevelopmentList = {
  items: TerritorialDevelopment[];
};

export type PatrimonyAlert = {
  id: number;
  user_id: number;
  property_asset_id: number | null;
  strategy_id: number | null;
  territorial_development_id: number | null;
  alert_type:
    | "valuation_refresh_due"
    | "property_value_changed"
    | "target_value_reached"
    | "market_recommendation_changed"
    | "market_became_seller_favorable"
    | "territorial_development_updated"
    | "strategy_review_due"
    | string;
  title: string;
  message: string;
  severity: "low" | "medium" | "high" | string;
  metadata: Record<string, unknown>;
  created_at: string;
  read_at: string | null;
  dismissed_at: string | null;
  property_name: string | null;
  strategy_objective: string | null;
  territorial_development_name: string | null;
};

export type PatrimonyAlertList = {
  items: PatrimonyAlert[];
};

export type PatrimonyAlertEvaluation = {
  created: number;
  existing: number;
};

export type StrategyObjective = "maintain" | "sell" | "sell_and_buy" | "buy_to_invest" | "grow_patrimony";

export type PatrimonyStrategyInput = {
  property_asset_id: number;
  objective: StrategyObjective;
  horizon?: string | null;
  target_value_uf?: number | null;
  urgency?: string | null;
  risk_profile?: string | null;
  next_move?: string | null;
  desired_property_type?: string | null;
  desired_communes?: string[];
  desired_budget_uf?: number | null;
};

export type PatrimonyStrategyPatchInput = Partial<PatrimonyStrategyInput>;

export type StrategyRecommendation = {
  status: "available" | "insufficient_data" | string;
  current_recommendation: string | null;
  progress_to_target_pct: number | null;
  latest_valuation_uf: number | null;
  target_value_uf: number | null;
  next_steps: string[];
  action_conditions: string[];
  suggested_next_review: string | null;
  reasons: string[];
};

export type PatrimonyStrategy = {
  id: number;
  user_id: number;
  property_asset_id: number;
  objective: StrategyObjective;
  horizon: string | null;
  target_value_uf: number | null;
  urgency: string | null;
  risk_profile: string | null;
  next_move: string | null;
  desired_property_type: string | null;
  desired_communes: string[];
  desired_budget_uf: number | null;
  recommendation: StrategyRecommendation;
  created_at: string;
  updated_at: string;
};

export type PatrimonyStrategyList = {
  items: PatrimonyStrategy[];
};

export type PatrimonyStrategyDeleteResult = {
  id: number;
  deleted: boolean;
};

export type PropertyValuationSnapshot = {
  id: number;
  estimated_value_uf: number | null;
  estimated_value_clp: number | null;
  lower_bound_uf: number | null;
  upper_bound_uf: number | null;
  lower_bound_clp: number | null;
  upper_bound_clp: number | null;
  confidence: string | null;
  confidence_score: number | null;
  engine_name: string | null;
  engine_version: string | null;
  engine_payload: Record<string, unknown>;
  snapshot_at: string;
  created_at: string;
};

export type PropertyAsset = {
  id: number;
  user_id: number;
  name: string;
  comuna: string;
  property_type: string;
  m2: number;
  built_area_m2: number | null;
  land_area_m2: number | null;
  usable_area_m2: number | null;
  bedrooms: number | null;
  bathrooms: number | null;
  parking: number | null;
  lat: number | null;
  lon: number | null;
  characteristics: Record<string, unknown>;
  latest_valuation: PropertyValuationSnapshot | null;
  valuation_snapshots: PropertyValuationSnapshot[];
  created_at: string;
  updated_at: string;
};
