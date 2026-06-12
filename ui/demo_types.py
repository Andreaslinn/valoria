"""TypedDict contracts for Product Lab demo data.

These improve editor/static safety for known demo keys without changing runtime
behavior. They are not a perfect guardrail: permissive access such as
`.get("unknown_key")` may still evade some type checkers.
"""
from __future__ import annotations

from typing import NotRequired, Required, TypedDict


class DemoSignal(TypedDict):
    type: str
    signal_type: str
    label: str
    explanation: str
    severity: str
    confidence: str
    suggested_action: str
    tone: str


class DemoPriceHistoryPoint(TypedDict):
    date: str
    price_uf: int
    event: str
    previous_price_uf: int | None
    change_uf: int | None
    change_pct: float | None
    source: str
    is_demo: bool


class DemoPortalPresence(TypedDict):
    portal_name: str
    is_active: bool
    first_seen: str
    last_seen: str
    price_seen_uf: int
    listing_url: str
    confidence: str


class DemoListing(TypedDict):
    id: int
    listing_id: int
    title: str
    comuna: str
    property_type: str
    address_label: str
    price_uf: int
    estimated_value_uf: int
    m2: int
    bedrooms: int
    bathrooms: int
    parking_spaces: int
    source: str
    detected_at: str
    days_on_market: int
    confidence: str
    score: float
    status: str
    tags: list[str]
    short_summary: str
    signals: list[DemoSignal]
    price_history: list[DemoPriceHistoryPoint]
    portal_presence: list[DemoPortalPresence]
    price_clp: NotRequired[int]
    estimated_value_clp: NotRequired[int]
    estimated_price_uf: NotRequired[int]
    estimated_price_clp: NotRequired[int]
    dormitorios: NotRequired[int]
    banos: NotRequired[int]
    estacionamientos: NotRequired[int]
    listing_url: NotRequired[str]
    url: NotRequired[str]
    captured_at: NotRequired[str]
    created_at: NotRequired[str]
    listing_status: NotRequired[str]
    history: NotRequired[list[int]]
    discount_pct: NotRequired[float]
    saved_at: NotRequired[str]
    saved_price_uf: NotRequired[int]
    saved_price_clp: NotRequired[int]
    movement_pct: NotRequired[float]
    movement_label: NotRequired[str]
    movement_tone: NotRequired[str]
    alerts: NotRequired[list[str]]


class DemoComparable(TypedDict):
    listing_id: int
    title: str
    comuna: str
    price_uf: int
    price_clp: int
    m2: int
    similarity: float
    url: str


class DemoValuationResult(TypedDict):
    estimated_price_uf: int
    estimated_price_clp: int
    confidence: str
    comparable_count: int
    price_m2_uf: float
    status: str
    warnings: list[str]
    comparables: list[DemoComparable]


class DemoRiskSignal(TypedDict):
    type: str
    tone: str
    label: str


class DemoRiskReport(TypedDict, total=False):
    title: Required[str]
    property: Required[str]
    executive_summary: Required[str]
    risk_score: Required[int]
    total_score: Required[int]
    market_score: Required[int]
    liquidity_score: Required[int]
    legal_score: Required[int]
    data_quality_score: Required[int]
    risk_tone: Required[str]
    liquidity: Required[str]
    legal_signals: Required[str]
    market: Required[str]
    cbr_future: Required[str]
    main_risks: Required[list[str]]
    main_opportunities: Required[list[str]]
    interpretation: Required[str]
    recommendation: Required[str]
    disclaimer: Required[str]
    signals: Required[list[DemoRiskSignal]]
    is_demo: bool
    property_id: int
    property_snapshot: dict[str, object]
    demo_disclaimer: str
    scores: dict[str, int]
    timeline: list[PropertyActivityEvent]
    price_history: list[DemoPriceHistoryPoint]
    comparables: list[dict[str, object]]
    comuna_context: dict[str, object]
    market_context: DemoMarketContext
    portal_presence: list[DemoPortalPresence]
    legal_simulation: dict[str, object]
    autofact_report: AutofactReport
    market_section: dict[str, object]
    negotiation_section: dict[str, object]
    negotiation_signals: dict[str, object]
    sections: dict[str, object]


class DemoRecommendation(TypedDict, total=False):
    strategy: Required[str]
    tone: Required[str]
    label: Required[str]
    conservative_offer: str
    moderate_offer: str
    aggressive_offer: str
    negotiation_rationale: str
    recommendation: str
    rationale: str
    market_conditions: str
    risk_level: str
    confidence: str


class DemoMarketContext(TypedDict, total=False):
    comuna: Required[str]
    label: Required[str]
    market_temperature: Required[str]
    inventory_level: Required[str]
    demand_level: Required[str]
    average_days_on_market: Required[int]
    median_price_uf: Required[int]
    median_price_per_m2_uf: Required[int]
    active_comparables: Required[int]
    recent_price_trend: Required[str]
    liquidity_score: Required[int]
    negotiation_pressure: Required[str]
    buyer_competition: Required[str]
    short_market_summary: Required[str]
    badges: list[str]
    buyer_meaning: str
    owner_meaning: str
    disclaimer: str
    is_demo: bool


class AutofactSeed(TypedDict):
    legal_score: int
    cbr_status: str
    ownership_flags: list[str]
    liens: list[str]
    debt_flags: list[str]
    tax_warning: str | None
    permits_warning: str | None
    liquidity_score: int
    market_score: int
    risk_level: str
    confidence: str
    disclaimer: str


class AutofactReport(AutofactSeed, total=False):
    is_demo: bool
    property_id: int
    property_identity: dict[str, object]
    simulated_cbr_status: str
    ownership_summary: str
    ownership_history: list[dict[str, str]]
    liens_flags: list[dict[str, str]]
    mortgage_flags: list[dict[str, str]]
    prohibition_flags: list[dict[str, str]]
    tax_flags: list[dict[str, str]]
    permits_flags: list[dict[str, str]]
    municipal_flags: list[dict[str, str]]
    building_regularization: dict[str, str]
    data_confidence: str
    legal_timeline: list[dict[str, str]]
    review_recommendations: list[str]
    critical_flags: list[dict[str, str]]
    disclaimers: list[str]


class NegotiationSignal(TypedDict):
    label: str
    explanation: str
    evidence: list[str]
    severity: str
    confidence: str
    suggested_action: str
    tone: str
    disclaimer: str
    is_demo: bool


class OwnerRecommendation(TypedDict):
    recommendation: str
    rationale: str
    market_conditions: str
    risk_level: str
    confidence: str
    tone: str


class PropertyActivityEvent(TypedDict):
    id: str
    property_id: int
    date: str
    event_type: str
    title: str
    description: str
    tone: str
    severity: str
    source: str
    is_demo: bool


class DemoAvmScore(TypedDict):
    estimated_value_uf: float | None
    estimated_value_clp: int | None
    confidence_score: float | None
    confidence_label: str
    discount_pct: float | None
    comparables_used: int
    avm_source: str
    is_demo: bool


class DemoMarketTiming(TypedDict):
    buyer: str
    owner: str
    summary: str
    tone: str


class DemoPropertyComparison(TypedDict):
    property_id: int
    label: str
    price_uf: int
    liquidity_score: int
    legal_score: int
    market_score: int
    fit: str
