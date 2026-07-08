"""Backend contracts for UI-only future feature surfaces.

These stubs intentionally do not compute product results. They expose honest
backend readiness states so demo/lab UI can be connected later without treating
fixtures as factual data.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class FutureFeatureStatus(StrEnum):
    NOT_CONNECTED = "not_connected"
    COMING_SOON = "coming_soon"
    REQUIRES_DATA = "requires_data"
    REQUIRES_EXTERNAL_DATA = "requires_external_data"
    REQUIRES_PRICE_HISTORY = "requires_price_history"
    REQUIRES_MARKET_TIMESERIES = "requires_market_timeseries"
    REQUIRES_WATCHLIST = "requires_watchlist"
    REQUIRES_WATCHLIST_OR_OWNED_PROPERTIES = "requires_watchlist_or_owned_properties"
    REQUIRES_LISTING_CONTEXT = "requires_listing_context"
    REQUIRES_GEOSPATIAL_DATA = "requires_geospatial_data"
    REQUIRES_USER_PREFERENCES = "requires_user_preferences"
    REQUIRES_ALERT_HISTORY = "requires_alert_history"
    REQUIRES_NOTIFICATION_PROVIDER = "requires_notification_provider"
    REQUIRES_PROPERTY_TYPE_INDEX = "requires_property_type_index"
    REQUIRES_SEVERITY_MODEL = "requires_severity_model"
    NOT_CONFIGURED = "not_configured"
    ADMIN_ONLY = "admin_only"
    NOT_AVAILABLE = "not_available"


LAST_PLACEHOLDER_AUDIT_AT = datetime(2026, 6, 16, tzinfo=UTC)


@dataclass(frozen=True)
class FutureFeatureContract:
    feature_key: str
    title: str
    status: FutureFeatureStatus
    message: str
    required_data: tuple[str, ...]
    next_backend_step: str
    safe_to_show_in_beta: bool
    source: str
    last_checked_at: datetime | None = LAST_PLACEHOLDER_AUDIT_AT
    classification: str = "backend_stub_needed"
    future_fields: tuple[str, ...] = ()
    related_ui_files: tuple[str, ...] = ()
    backend_notes: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "feature_key": self.feature_key,
            "title": self.title,
            "status": self.status.value,
            "message": self.message,
            "required_data": list(self.required_data),
            "next_backend_step": self.next_backend_step,
            "safe_to_show_in_beta": self.safe_to_show_in_beta,
            "source": self.source,
            "last_checked_at": self.last_checked_at.isoformat()
            if self.last_checked_at is not None
            else None,
            "classification": self.classification,
            "future_fields": list(self.future_fields),
            "related_ui_files": list(self.related_ui_files),
            "backend_notes": list(self.backend_notes),
        }


class FutureFeatureRegistry:
    def __init__(self, features: Sequence[FutureFeatureContract]) -> None:
        self._features = {feature.feature_key: feature for feature in features}

    def list_features(self) -> list[FutureFeatureContract]:
        return [self._features[key] for key in sorted(self._features)]

    def get_feature(self, feature_key: str) -> FutureFeatureContract | None:
        return self._features.get(feature_key)

    def feature_keys(self) -> list[str]:
        return sorted(self._features)


DEFAULT_FUTURE_FEATURES: tuple[FutureFeatureContract, ...] = (
    FutureFeatureContract(
        feature_key="tasar_playground_context_panels",
        title="Tasar Playground contextual panels",
        status=FutureFeatureStatus.REQUIRES_DATA,
        message=(
            "Shell especifico para Tasar Playground: los paneles de ubicacion, tendencia, "
            "senales, actividad y riesgo existen en UI, pero aun no tienen agregador backend "
            "factual conectado."
        ),
        required_data=(
            "valuation_result",
            "listing_or_payload_context",
            "market_timeseries_by_comuna",
            "geospatial_context",
            "price_history",
            "alert_events",
        ),
        next_backend_step=(
            "Crear un agregador readonly por tasacion/listing que combine contratos reales "
            "existentes y marque cada bloque como ready o not_connected sin fixtures."
        ),
        safe_to_show_in_beta=False,
        source="backend_stub",
        classification="playground_backend_shell",
        future_fields=(
            "location_intelligence",
            "price_trend",
            "market_signals",
            "recent_activity",
            "risk_summary",
            "market_footer",
        ),
        related_ui_files=(
            "ui/redesign/tasar_playground.py",
            "ui/redesign/tasar_playground_adapter.py",
            "ui/redesign/tasar_playground_data.py",
        ),
        backend_notes=(
            "No conectado a la UI todavia.",
            "La tasacion principal ya consume /api/v1/valuations por el adapter del Playground.",
            "No devuelve numeros fake; solo documenta readiness y datos requeridos.",
        ),
    ),
    FutureFeatureContract(
        feature_key="negotiation_recommendation",
        title="Recomendacion de negociacion",
        status=FutureFeatureStatus.REQUIRES_PRICE_HISTORY,
        message=(
            "Stub preparado: requiere historial de precio real, dias en mercado y "
            "senales verificables antes de sugerir rangos de oferta."
        ),
        required_data=("price_history", "days_on_market", "comparable_delta"),
        next_backend_step="Definir fuente canonica de historial por listing y reglas de oferta.",
        safe_to_show_in_beta=False,
        source="backend_stub",
        future_fields=(
            "suggested_offer_range",
            "negotiation_leverage",
            "price_drop_history",
            "days_on_market",
            "confidence",
        ),
        related_ui_files=(
            "ui/demo_negotiation.py",
            "ui/demo_offer.py",
            "ui/components/negotiation.py",
            "ui/components/offer_simulator.py",
            "ui/redesign/tasar_playground.py",
        ),
    ),
    FutureFeatureContract(
        feature_key="market_context_timeseries",
        title="Contexto de mercado y evolucion de comuna",
        status=FutureFeatureStatus.REQUIRES_MARKET_TIMESERIES,
        message="Coming soon: requiere series temporales de mercado por comuna antes de inferir tendencia.",
        required_data=("market_timeseries_by_comuna", "price_m2_series", "observation_window"),
        next_backend_step="Persistir snapshots agregados por comuna y definir ventanas minimas.",
        safe_to_show_in_beta=False,
        source="backend_stub",
        future_fields=(
            "comuna",
            "trend_direction",
            "price_m2_change",
            "confidence",
            "observation_window",
        ),
        related_ui_files=(
            "ui/demo_market.py",
            "ui/components/market_context.py",
            "ui/redesign/radar_view.py",
            "ui/redesign/portfolio_view.py",
        ),
    ),
    FutureFeatureContract(
        feature_key="role_contribuciones",
        title="Rol y contribuciones",
        status=FutureFeatureStatus.REQUIRES_EXTERNAL_DATA,
        message="No conectado: depende de fuente externa de rol/contribuciones y validacion legal.",
        required_data=("property_role", "municipal_or_tax_source", "source_terms"),
        next_backend_step="Definir proveedor permitido y contrato de ingestion puntual.",
        safe_to_show_in_beta=False,
        source="backend_stub",
        future_fields=("estimated_contribuciones", "annual_range", "source", "confidence"),
        related_ui_files=("ui/demo_autofact.py", "ui/components/autofact.py"),
    ),
    FutureFeatureContract(
        feature_key="listing_explainer_ai",
        title="IA explicadora de listing o tasacion",
        status=FutureFeatureStatus.NOT_CONNECTED,
        message="No conectado: falta contrato de explicacion y guardrails de salida.",
        required_data=("valuation_payload", "valuation_result", "listing_context", "comparables"),
        next_backend_step="Definir prompt/adapter y pruebas de seguridad antes de exponer resumenes.",
        safe_to_show_in_beta=False,
        source="backend_stub",
        future_fields=(
            "summary",
            "strengths",
            "risks",
            "comparable_explanation",
            "confidence",
        ),
        related_ui_files=(
            "ui/valuation/result.py",
            "ui/redesign/tasar_playground.py",
            "ui/redesign/alerts_view.py",
        ),
    ),
    FutureFeatureContract(
        feature_key="portfolio_analytics",
        title="Portfolio analytics",
        status=FutureFeatureStatus.REQUIRES_WATCHLIST_OR_OWNED_PROPERTIES,
        message="Stub preparado: watchlist real existe, pero faltan valuations periodicas de cartera.",
        required_data=("watchlist_or_owned_properties", "valuation_snapshots", "alert_counts"),
        next_backend_step="Crear snapshots AVM por propiedad guardada y agregados de exposicion.",
        safe_to_show_in_beta=False,
        source="backend_stub",
        future_fields=(
            "total_estimated_value",
            "unrealized_gain",
            "risk_level",
            "comuna_exposure",
            "alerts_count",
        ),
        related_ui_files=(
            "ui/pages/tracking.py",
            "ui/pages/lab/tracking_lab.py",
            "ui/redesign/portfolio_adapter.py",
            "ui/redesign/portfolio_view.py",
        ),
        backend_notes=("Base parcial existente: /api/v1/watchlist y /api/v1/alerts.",),
    ),
    FutureFeatureContract(
        feature_key="alert_rules",
        title="Alert rules",
        status=FutureFeatureStatus.NOT_CONFIGURED,
        message=(
            "No configurado: alertas reales existen, pero no hay CRUD de reglas por usuario "
            "para Ver mis reglas o Nueva regla de alerta."
        ),
        required_data=("user_rule_config", "watchlist", "notification_preferences", "rule_state"),
        next_backend_step="Disenar tabla/DTO de reglas y evaluador desacoplado del job actual.",
        safe_to_show_in_beta=False,
        source="backend_stub",
        classification="alerts_playground_backend_shell",
        future_fields=(
            "rule_id",
            "rule_type",
            "comuna",
            "price_threshold",
            "property_type",
            "notification_channel",
            "status",
        ),
        related_ui_files=(
            "ui/redesign/alerts_adapter.py",
            "ui/redesign/alerts_view.py",
            "ui/components/alerts.py",
        ),
        backend_notes=("Base parcial existente: /api/v1/alerts lista alertas persistidas.",),
    ),
    FutureFeatureContract(
        feature_key="alert_notification_settings",
        title="Configuracion de notificaciones de alertas",
        status=FutureFeatureStatus.REQUIRES_NOTIFICATION_PROVIDER,
        message=(
            "Coming soon: el panel visible de settings usa fixtures; falta contrato de "
            "preferencias por usuario y proveedor de notificaciones."
        ),
        required_data=(
            "user_notification_preferences",
            "primary_channel",
            "email_verified",
            "frequency_policy",
            "opt_in_state",
            "notification_provider",
        ),
        next_backend_step=(
            "Definir DTO readonly de preferencias, estado de conexion del proveedor y "
            "frecuencias permitidas antes de conectar la UI."
        ),
        safe_to_show_in_beta=False,
        source="backend_stub",
        classification="alerts_playground_backend_shell",
        future_fields=(
            "primary_channel",
            "email",
            "preferences",
            "frequency",
            "opt_in_state",
            "provider",
            "connection_state",
        ),
        related_ui_files=("ui/redesign/alerts_adapter.py", "ui/redesign/alerts_view.py"),
        backend_notes=(
            "No crea ni envia notificaciones.",
            "No conectado a la UI; documenta el contrato minimo para el panel coming soon.",
        ),
    ),
    FutureFeatureContract(
        feature_key="alert_filter_capabilities",
        title="Capacidades futuras de filtros de alertas",
        status=FutureFeatureStatus.REQUIRES_PROPERTY_TYPE_INDEX,
        message=(
            "Shell para filtros Coming soon: tipo de propiedad y severidad aun no tienen "
            "indice/modelo factual en backend."
        ),
        required_data=(
            "alert_type_taxonomy",
            "comuna_normalization",
            "created_at_range",
            "property_type_index",
            "severity_model",
        ),
        next_backend_step=(
            "Exponer capacidades readonly por filtro y separar filtros ya reales "
            "de filtros bloqueados por datos."
        ),
        safe_to_show_in_beta=False,
        source="backend_stub",
        classification="alerts_playground_backend_shell",
        future_fields=(
            "filter_key",
            "label",
            "enabled",
            "status",
            "required_data",
            "options_source",
        ),
        related_ui_files=("ui/redesign/alerts_adapter.py", "ui/redesign/alerts_view.py"),
        backend_notes=(
            "Tipo, comuna y fecha ya se filtran client-side sobre /api/v1/alerts.",
            "property_type requiere indice por listing; severity requiere modelo o reglas auditables.",
        ),
    ),
    FutureFeatureContract(
        feature_key="alert_trends_history",
        title="Tendencias historicas de alertas",
        status=FutureFeatureStatus.REQUIRES_ALERT_HISTORY,
        message=(
            "Demo/Lab: las tendencias visibles usan fixtures; falta historial agregado por "
            "tipo de alerta, watchlist y ventana temporal."
        ),
        required_data=(
            "alert_history_events",
            "price_drop_events",
            "below_price_events",
            "new_comparable_events",
            "liquidity_change_events",
            "anomaly_events",
            "watchlist_events",
        ),
        next_backend_step=(
            "Crear agregados readonly por tipo de evento y periodo sin reutilizar conteos demo."
        ),
        safe_to_show_in_beta=False,
        source="backend_stub",
        classification="alerts_playground_backend_shell",
        future_fields=(
            "trend_key",
            "title",
            "event_count",
            "delta_pct",
            "observation_window",
            "source_state",
        ),
        related_ui_files=(
            "ui/redesign/alerts_adapter.py",
            "ui/redesign/alerts_data.py",
            "ui/redesign/alerts_view.py",
        ),
        backend_notes=("No calcula metricas; solo declara la dependencia de historial real.",),
    ),
    FutureFeatureContract(
        feature_key="alert_active_zones",
        title="Zonas activas de alertas",
        status=FutureFeatureStatus.REQUIRES_ALERT_HISTORY,
        message=(
            "Demo/Lab: las zonas activas visibles son fixtures; falta agregado real por comuna "
            "y politica de nivel de actividad."
        ),
        required_data=(
            "alert_history_by_comuna",
            "comuna_normalization",
            "activity_level_policy",
            "pct_variation_window",
            "real_or_demo_source_state",
        ),
        next_backend_step=(
            "Definir agregador readonly por comuna con conteo, variacion porcentual y origen factual."
        ),
        safe_to_show_in_beta=False,
        source="backend_stub",
        classification="alerts_playground_backend_shell",
        future_fields=(
            "comuna",
            "alert_count",
            "activity_level",
            "delta_pct",
            "source_state",
            "observation_window",
        ),
        related_ui_files=(
            "ui/redesign/alerts_adapter.py",
            "ui/redesign/alerts_data.py",
            "ui/redesign/alerts_view.py",
        ),
        backend_notes=("No reemplaza los fixtures demo/lab ni conecta UI.",),
    ),
    FutureFeatureContract(
        feature_key="alert_ai_prioritization",
        title="Priorizacion inteligente de alertas",
        status=FutureFeatureStatus.REQUIRES_ALERT_HISTORY,
        message=(
            "Coming soon: el bloque de alertas inteligentes en tiempo real requiere historial, "
            "watchlist y preferencias antes de priorizar alertas."
        ),
        required_data=(
            "alert_history_events",
            "watchlist",
            "user_preferences",
            "severity_model",
            "notification_feedback",
        ),
        next_backend_step=(
            "Definir scoring auditable y salida readonly de prioridad antes de cualquier automatizacion."
        ),
        safe_to_show_in_beta=False,
        source="backend_stub",
        classification="alerts_playground_backend_shell",
        future_fields=(
            "priority",
            "reason",
            "severity",
            "recommended_action",
            "model_state",
            "confidence",
        ),
        related_ui_files=("ui/redesign/alerts_adapter.py", "ui/redesign/alerts_view.py"),
        backend_notes=("No hay modelo conectado ni inferencias generadas por este shell.",),
    ),
    FutureFeatureContract(
        feature_key="risk_report_lab",
        title="Risk Report Lab",
        status=FutureFeatureStatus.REQUIRES_EXTERNAL_DATA,
        message=(
            "Stub preparado: reporte HTML factual existe en tasacion/radar, pero el Lab usa "
            "riesgo legal y mercado simulado."
        ),
        required_data=("listing_context", "price_history", "legal_external_data", "market_context"),
        next_backend_step="Separar reporte factual simple de reporte premium multi-fuente.",
        safe_to_show_in_beta=False,
        source="backend_stub",
        future_fields=(
            "risk_level",
            "market_score",
            "liquidity_score",
            "legal_score",
            "data_quality_score",
            "recommendation",
        ),
        related_ui_files=(
            "ui/pages/lab_reports.py",
            "ui/components/risk_report.py",
            "ui/components/risk_report_html.py",
            "ui/demo_providers.py",
        ),
    ),
    FutureFeatureContract(
        feature_key="decision_cards",
        title="Decision cards",
        status=FutureFeatureStatus.REQUIRES_WATCHLIST,
        message="Stub preparado: requiere persistir decisiones por propiedad y usuario.",
        required_data=("watchlist", "user_decision_state", "property_signals"),
        next_backend_step="Crear modelo de decision por propiedad guardada y eventos de cambio de etapa.",
        safe_to_show_in_beta=False,
        source="backend_stub",
        future_fields=("decision_status", "score", "next_action", "evidence", "updated_at"),
        related_ui_files=(
            "ui/demo_decision_board.py",
            "ui/components/decision_board.py",
            "ui/pages/decision_board_lab.py",
        ),
    ),
    FutureFeatureContract(
        feature_key="buyer_journey",
        title="Buyer Journey",
        status=FutureFeatureStatus.NOT_CONNECTED,
        message="No conectado: flujo y tesis existen solo como estado demo de sesion.",
        required_data=("buyer_profile", "watchlist", "decision_state", "offer_strategy"),
        next_backend_step="Definir contrato de journey y persistencia por usuario.",
        safe_to_show_in_beta=False,
        source="backend_stub",
        future_fields=("profile", "strategy", "thesis", "risks", "next_steps"),
        related_ui_files=("ui/demo_buyer_journey.py", "ui/pages/buyer_journey.py"),
    ),
    FutureFeatureContract(
        feature_key="owner_journey",
        title="Owner Journey",
        status=FutureFeatureStatus.REQUIRES_WATCHLIST_OR_OWNED_PROPERTIES,
        message="No conectado: requiere propiedades propias o watchlist marcada como owned.",
        required_data=("owned_properties", "market_context", "valuation_snapshots"),
        next_backend_step="Definir entidad owned_property y recomendaciones auditables.",
        safe_to_show_in_beta=False,
        source="backend_stub",
        future_fields=("recommendation", "market_timing", "rent_or_sell_signal", "confidence"),
        related_ui_files=("ui/demo_owner_journey.py", "ui/pages/owner_journey.py"),
    ),
    FutureFeatureContract(
        feature_key="autofact_real_estate",
        title="Autofact inmobiliario",
        status=FutureFeatureStatus.REQUIRES_EXTERNAL_DATA,
        message="No conectado: el demo simula CBR, permisos y contribuciones; no hay proveedor real.",
        required_data=("cbr_or_legal_source", "municipal_source", "tax_source", "source_terms"),
        next_backend_step="Seleccionar proveedor legal permitido y crear adapter externo.",
        safe_to_show_in_beta=False,
        source="backend_stub",
        future_fields=("ownership_summary", "debt_flags", "permits_flags", "tax_flags", "confidence"),
        related_ui_files=(
            "ui/demo_autofact.py",
            "ui/components/autofact.py",
            "ui/pages/lab_reports.py",
        ),
    ),
    FutureFeatureContract(
        feature_key="property_experience",
        title="Property Experience",
        status=FutureFeatureStatus.REQUIRES_LISTING_CONTEXT,
        message="Stub preparado: necesita una composicion backend por listing antes de reemplazar el demo.",
        required_data=("listing", "valuation", "alerts", "risk_report", "decision_state"),
        next_backend_step="Crear agregador por propiedad que una contratos reales y stubs futuros.",
        safe_to_show_in_beta=False,
        source="backend_stub",
        future_fields=("identity", "value_summary", "risk_summary", "timeline", "actions"),
        related_ui_files=("ui/components/property_experience.py", "ui/pages/property_experience.py"),
        backend_notes=(
            "Base parcial existente: /api/v1/listings, /api/v1/valuations, /api/v1/alerts.",
        ),
    ),
    FutureFeatureContract(
        feature_key="checklist_lab",
        title="Checklist Lab",
        status=FutureFeatureStatus.NOT_CONNECTED,
        message="No conectado: checklist y notas viven en session_state demo.",
        required_data=("user_checklist_state", "property_context", "risk_items"),
        next_backend_step="Crear DTO y persistencia de tareas por usuario/listing.",
        safe_to_show_in_beta=False,
        source="backend_stub",
        future_fields=("items", "completion_pct", "priority", "status", "notes"),
        related_ui_files=(
            "ui/demo_checklist.py",
            "ui/components/checklist.py",
            "ui/pages/checklist_lab.py",
        ),
    ),
    FutureFeatureContract(
        feature_key="radar_market_map",
        title="Mapa experimental y zonas calientes",
        status=FutureFeatureStatus.REQUIRES_GEOSPATIAL_DATA,
        message="Coming soon: el radar real entrega oportunidades, pero mapa/heatmap usan fixtures.",
        required_data=("listing_coordinates", "microzones", "aggregated_market_metrics"),
        next_backend_step="Crear agregados geoespaciales seguros sin exponer datos insuficientes.",
        safe_to_show_in_beta=False,
        source="backend_stub",
        future_fields=("pins", "heat_zones", "hot_zones", "source_state", "confidence"),
        related_ui_files=(
            "ui/redesign/radar_adapter.py",
            "ui/redesign/radar_data.py",
            "ui/redesign/radar_view.py",
        ),
        backend_notes=("Base real existente: /api/v1/radar/opportunities.",),
    ),
    FutureFeatureContract(
        feature_key="radar_saved_searches",
        title="Busquedas guardadas",
        status=FutureFeatureStatus.NOT_CONFIGURED,
        message="No configurado: no existe persistencia de busquedas o filtros guardados.",
        required_data=("user_id", "search_filters", "notification_preferences"),
        next_backend_step="Definir CRUD de busquedas guardadas y relacion opcional con reglas de alerta.",
        safe_to_show_in_beta=False,
        source="backend_stub",
        future_fields=("name", "filters", "last_result_count", "created_at", "notification_enabled"),
        related_ui_files=("ui/redesign/radar_view.py", "ui/redesign/radar_adapter.py"),
    ),
    FutureFeatureContract(
        feature_key="portfolio_comparison",
        title="Comparacion de propiedades",
        status=FutureFeatureStatus.REQUIRES_WATCHLIST,
        message="Coming soon: comparador existe como demo, sin contrato backend ni persistencia.",
        required_data=("watchlist", "selected_listing_ids", "valuation_snapshots"),
        next_backend_step="Crear contrato de comparacion y criterios ordenables por usuario.",
        safe_to_show_in_beta=False,
        source="backend_stub",
        future_fields=("selected_properties", "comparison_metrics", "ranked_signals", "notes"),
        related_ui_files=(
            "ui/demo_providers.py",
            "ui/pages/lab/tracking_lab.py",
            "ui/redesign/portfolio_view.py",
        ),
    ),
    FutureFeatureContract(
        feature_key="property_activity_timeline",
        title="Timeline de actividad de propiedad",
        status=FutureFeatureStatus.REQUIRES_PRICE_HISTORY,
        message="Stub preparado: el timeline demo combina eventos simulados; falta event sourcing real.",
        required_data=("price_history", "alert_events", "listing_seen_events", "watchlist_events"),
        next_backend_step="Unificar eventos reales de precio, alertas y watchlist por listing.",
        safe_to_show_in_beta=False,
        source="backend_stub",
        future_fields=("events", "event_type", "severity", "source", "observed_at"),
        related_ui_files=("ui/demo_activity.py", "ui/components/activity.py"),
        backend_notes=(
            "Base parcial existente: /api/v1/listings/{listing_id}/price-history y /api/v1/alerts.",
        ),
    ),
    FutureFeatureContract(
        feature_key="lab_feedback",
        title="Lab Feedback",
        status=FutureFeatureStatus.ADMIN_ONLY,
        message="Parcial: existe tracking de uso, pero feedback Lab permanece local en session_state.",
        required_data=("user_id", "feedback_event", "module_key", "session_context"),
        next_backend_step="Decidir si feedback Lab se persiste en usage events o en tabla separada.",
        safe_to_show_in_beta=False,
        source="backend_stub",
        classification="backend_partial",
        future_fields=("module", "feedback", "sentiment", "property_id", "created_at"),
        related_ui_files=(
            "ui/demo_feedback.py",
            "ui/components/feedback.py",
            "ui/pages/lab_feedback.py",
        ),
        backend_notes=("Base parcial existente: /api/v1/usage/events.",),
    ),
)


DEFAULT_FUTURE_FEATURE_REGISTRY = FutureFeatureRegistry(DEFAULT_FUTURE_FEATURES)


def get_default_future_feature_registry() -> FutureFeatureRegistry:
    return DEFAULT_FUTURE_FEATURE_REGISTRY
