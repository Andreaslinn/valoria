"""Transactional, additive Portal geography; never changes prices or identity."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from domain.geocoding.source_quality import mlc, validate_context, assess
from domain.ingestion.observations import identify, json_value
from infrastructure.db.models import ListingObservationORM
from infrastructure.db.observation_history import append_observation

STATE_KEY = "portal_geo_enrichment"


def apply_original_address(row, address):
    """Add source-bound address evidence without touching valuation inputs."""
    if not isinstance(address, dict) or not mlc(row.external_id) or mlc(address.get("source_listing_id")) != mlc(row.external_id):
        return False
    if address.get("source") not in {
        "portal:location.map_info.item_address", "portal:location_and_points.map_info.item_address",
        "portal:location.map_info.location", "portal:location_and_points.map_info.location"}:
        return False
    if not isinstance(address.get("original"), str) or not address["original"].strip():
        return False
    from config.comunas import normalize_comuna, is_known_comuna
    declared = address.get("commune")
    if not declared:
        declared = next((part.strip() for part in address["original"].split(",")
                         if is_known_comuna(part.strip())), None)
    if declared and normalize_comuna(declared) != normalize_comuna(row.comuna):
        return False
    metadata = deepcopy(row.raw_metadata or {})
    metadata["address_evidence"] = deepcopy(address)
    from domain.ingestion.location_evidence import candidate_building_key
    building = candidate_building_key(address["original"], row.comuna)
    if building:
        metadata["building_candidate"] = building
    else:
        metadata.pop("building_candidate", None)
    row.raw_metadata = metadata
    return True


def eligible(row):
    if row.source != "portalinmobiliario" or row.status != "active":
        return False
    quality = assess(row.lat, row.lon)
    return quality["status"] in {"INVALID", "MISSING"} or row.geocode_precision in {
        "comuna",
        "comuna_centroid",
    } or (row.geocode_precision == "unknown" and not
          ((row.raw_metadata or {}).get("address_evidence") or {}).get("original"))


def candidate_evidence(detail):
    return (detail.get("raw_metadata") or {}).get("coordinates_evidence")


def recover_metadata(metadata, external_id):
    """Only recover publication-bound evidence, never an arbitrary lat/lon JSON."""
    metadata = metadata or {}
    ev = metadata.get("coordinates_evidence")
    if isinstance(ev, dict) and mlc(ev.get("source_listing_id")) == mlc(external_id):
        # Invalid/quarantined evidence cannot become eligible merely by replay.
        if (ev.get("quality") or {}).get("local_eligible") is False or ev.get("precision") in {
            "comuna",
            "comuna_centroid",
        }:
            return None
        if (ev.get("quality") or {}).get("reason") in {
            "unbound_or_conflicting_mlc",
            "source_map_components_conflict",
        }:
            return None
        # Do not trust old normalized/quality fields without revalidation.
        from domain.geocoding.source_quality import evidence

        original = ev.get("original") or {}
        validated = evidence(
            original.get("lat"),
            original.get("lon"),
            publication_id=mlc(external_id),
            source=ev.get("source"),
            observed_at=ev.get("observed_at"),
        )
        validated.update(commune=ev.get("commune"), map_commune=ev.get("map_commune"))
        for key in ("address_evidence", "precision_original"):
            if key in ev:
                validated[key] = deepcopy(ev[key])
        return validated
    # Already stored detail components from the evidence-preservation pipeline.
    raw = (metadata.get("source_evidence") or {}).get("raw") or {}
    if not raw:
        raw = metadata.get("portal_detail_raw") or {}
    if mlc(raw.get("platform_id")) != mlc(external_id):
        return None
    # Replay already archived components through the same parser/binder. This
    # retains multiple-point conflict checks and avoids a second geo extractor.
    import json
    from infrastructure.scrapers.portalinmobiliario import parse_listing_detail_portal

    payload = {
        "appProps": {
            "pageProps": {
                "initialState": {
                    "id": raw["platform_id"],
                    "components": raw.get("components") or {},
                }
            }
        }
    }
    html = '<script id="__NORDIC_RENDERING_CTX__">' + json.dumps(payload) + "</script>"
    detail = parse_listing_detail_portal(
        html, "https://www.portalinmobiliario.com/" + mlc(external_id)
    )
    ev = candidate_evidence(detail)
    if ev:
        ev["observed_at"] = (metadata.get("source_evidence") or {}).get("observed_at")
    return ev


async def archived_evidence(session, row):
    ev = recover_metadata(row.raw_metadata, row.external_id)
    if ev:
        return ev
    from config import get_settings

    if not get_settings().ingestion_observation_history_enabled:
        return None
    # No market observation is fabricated by replaying these historical documents.
    docs = await session.scalars(
        select(ListingObservationORM.document)
        .where(
            ListingObservationORM.source == row.source,
            ListingObservationORM.external_id == row.external_id,
            ListingObservationORM.event_kind == "listing_seen",
        )
        .order_by(ListingObservationORM.observed_at.desc())
    )
    for doc in docs:
        raw = doc.get("raw_state") or {}
        meta = dict(raw.get("raw_metadata") or {})
        meta["source_evidence"] = raw.get("_source_evidence") or {}
        ev = recover_metadata(meta, row.external_id)
        if ev:
            if not ev.get("commune"):
                ev["commune"] = raw.get("comuna") or (doc.get("parsed_state") or {}).get("comuna")
            return ev
    return None


async def apply_geography(
    session, row, ev, *, recovered_at=None, origin="detail", acquisition=None
):
    """Caller owns commit. Same transaction for canonical point + history."""
    if ev and ev.get("source") not in {
        "portal:location.map_info.location",
        "portal:location_and_points.map_info.location",
        "portal:map_listing_point",
    }:
        return "unbound"
    if (
        not ev
        or not mlc(row.external_id)
        or mlc(ev.get("source_listing_id")) != mlc(row.external_id)
    ):
        return "unbound"
    ev = json_value(validate_context(ev, row.comuna))
    # Recheck raw values even for an archived/externally prepared plan.
    original = ev.get("original") or {}
    if assess(original.get("lat"), original.get("lon"))["status"] in {"INVALID", "MISSING"}:
        return "invalid"
    xy = ev.get("normalized")
    if xy and xy != {"lat": float(original["lat"]), "lon": float(original["lon"])}:
        return "invalid"
    if (
        not xy
        or ev["quality"]["status"] == "INVALID"
        or not ev["quality"].get("local_eligible", False)
    ):
        return "rejected"
    if not eligible(row):
        return "already_geolocated"
    before = {"lat": row.lat, "lon": row.lon, "geocode_precision": row.geocode_precision}
    now = recovered_at or datetime.now(UTC)
    row.lat, row.lon, row.geocode_precision = xy["lat"], xy["lon"], "unknown"
    metadata = deepcopy(row.raw_metadata or {})
    metadata.update(
        lat=row.lat,
        lon=row.lon,
        geocode_precision="unknown",
        location_source=ev["source"],
        coordinates_evidence=ev,
        coordinates_quality=ev["quality"],
        geocode_precision_reason="source_map_accuracy_not_certified",
    )
    metadata["coordinate_provenance"] = {
        "kind": "portal_map_unknown_accuracy", "precision": "unknown",
        "source_listing_id": ev["source_listing_id"], "source": ev["source"],
        "precision_original": ev.get("precision_original") or {},
    }
    if origin == "archive":
        metadata["coordinates_recovery"] = {
            "recovered_at": now.isoformat(),
            "original_observed_at": ev.get("observed_at"),
            "origin": origin,
        }
    row.raw_metadata = metadata
    apply_original_address(row, ev.get("address_evidence"))
    document = identify(
        {
            "schema_version": "listing_observation_v2",
            "event_kind": "geo_recovered" if origin == "archive" else "geo_enriched",
            "listing_id": row.id,
            "source": row.source,
            "external_id": row.external_id,
            "observed_at": now.isoformat(),
            "raw_state": {
                "coordinates": ev.get("original"),
                "_source_evidence": (acquisition or {}).get("_source_evidence"),
            },
            "parsed_state": {"coordinates_evidence": ev, "detail": acquisition},
            "persisted_state": {"lat": row.lat, "lon": row.lon, "geocode_precision": "unknown"},
            "provenance": {
                "origin": origin,
                "is_listing_seen": False,
                "previous": before,
                "original_observed_at": ev.get("observed_at"),
            },
        }
    )
    await append_observation(session, document)
    await session.flush()
    return "recovered" if origin == "archive" else "enriched"


async def claim(session, row, *, now, max_attempts=3, cooldown_hours=24):
    """Row must be locked by caller (PostgreSQL SKIP LOCKED); reserve before I/O."""
    state = (row.raw_metadata or {}).get(STATE_KEY) or {}
    if not eligible(row) or state.get("attempts", 0) >= max_attempts:
        return False
    until = state.get("next_attempt_at")
    if until and datetime.fromisoformat(until).astimezone(UTC) > now:
        return False
    # A failed/crashed attempt consumes quota; no unbounded in-flight retries.
    state = dict(
        state,
        attempts=state.get("attempts", 0) + 1,
        last_attempt_at=now.isoformat(),
        next_attempt_at=(now + timedelta(hours=cooldown_hours)).isoformat(),
        outcome="in_flight",
    )
    row.raw_metadata = dict(row.raw_metadata or {}, **{STATE_KEY: state})
    await session.flush()
    return True


async def outcome(session, row, result, *, max_attempts=3, evidence=None, acquisition=None):
    metadata = deepcopy(row.raw_metadata or {})
    state = dict(metadata.get(STATE_KEY) or {})
    state["outcome"] = result
    state["exhausted"] = state.get("attempts", 0) >= max_attempts and result not in {
        "enriched",
        "recovered",
    }
    metadata[STATE_KEY] = state
    if evidence:
        metadata["coordinates_candidate_evidence"] = json_value(evidence)
    row.raw_metadata = metadata
    if result not in {"enriched", "recovered"} and state.get("last_attempt_at"):
        await append_observation(
            session,
            identify(
                {
                    "schema_version": "listing_observation_v2",
                    "event_kind": "geo_enrichment_result",
                    "listing_id": row.id,
                    "source": row.source,
                    "external_id": row.external_id,
                    "observed_at": state["last_attempt_at"],
                    "raw_state": {"_source_evidence": (acquisition or {}).get("_source_evidence")},
                    "parsed_state": {"result": result, "evidence": evidence},
                    "persisted_state": {"lat": row.lat, "lon": row.lon},
                    "provenance": {"origin": "bounded_geo_detail", "is_listing_seen": False},
                }
            ),
        )
    await session.flush()
