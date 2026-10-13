"""Read-only V2 deployment gate; schema presence is necessary, not behavioral proof."""
import hashlib
import json
from pathlib import Path


REQUIRED_FIELDS = {
    "ValuationRequest": {"target_listing_id", "precio_publicado_uf"},
    "ValuationResponse": {"estimated_price_uf", "comparables", "warnings", "confidence_score"},
    "OpportunityOut": {"last_seen_at", "source", "external_id", "thumbnail"},
    "ListingOut": {"status", "last_seen_at", "thumbnail"},
    "WatchlistItemOut": {"listing_status", "last_seen_at", "thumbnail"},
    "WatchlistStatusOut": {"listing_id", "saved"},
}


def check_v2_contract(schema: dict, capabilities: dict) -> list[str]:
    failures = []
    models = schema.get("components", {}).get("schemas", {})
    for model, required in REQUIRED_FIELDS.items():
        present = models.get(model, {}).get("properties", {})
        for field in sorted(required - present.keys()):
            failures.append(f"{model}.{field} missing")
    paths = schema.get("paths", {})
    for path, method in [("/api/v1/listings/analyze-url", "post"),
                         ("/api/v1/watchlist/{listing_id}/status", "get")]:
        if method not in paths.get(path, {}):
            failures.append(f"{method.upper()} {path} missing")
    if capabilities.get("portal_url_analysis") is not True:
        failures.append("Portal URL analysis capability missing")
    if not capabilities.get("code_fingerprint"):
        failures.append("Deployment code fingerprint missing")
    return failures


def v2_capabilities() -> dict:
    from services.listing_url_lookup import detect_source
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for name in ("api/v1/valuations.py", "api/v1/listings.py", "api/v1/radar.py",
                 "api/v1/watchlist.py", "services/listing_url_lookup.py", "scripts/portal_session.py",
                 "infrastructure/scrapers/portal_acquisition.py", "services/valuation.py",
                 "core/normalization/publication_identity.py", "core/normalization/property_consistency.py",
                 "core/assessment/warning_definitions.json", "services/market_dashboard_overview.py",
                 "infrastructure/db/repositories/alert_repo.py", "alembic/versions/0021_listing_observations.py", "alembic/versions/0022_alert_reads.py",
                 "services/listing_analysis.py", "services/reports.py", "services/radar.py",
                 "domain/radar/detector.py", "services/portfolio.py", "services/portfolio_snapshots.py", "services/patrimony_alerts.py",
                 "api/v1/alerts.py", "api/v1/patrimony.py", "api/v1/health.py",
                 "ui/components/risk_report_html.py", "infrastructure/db/models.py",
                 "core/assessment/warnings.py", "services/v2_contract.py"):
        digest.update(name.encode())
        digest.update((root / name).read_bytes())
    return {"portal_url_analysis": detect_source("https://www.portalinmobiliario.com/MLC-123-test") == "portalinmobiliario",
            "code_fingerprint": digest.hexdigest()}


def schema_fingerprint(schema: dict) -> str:
    return hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest()
