"""Observable source geography. Unknown precision is not invalid geometry.

USABLE requires explicit source precision plus a publication-bound origin.
UNCERTAIN points may be studied separately; no meter accuracy is inferred.
This module neither resolves physical identity nor geocodes addresses.
"""

import math
import re

VERSION = "source-geo-v1"


def mlc(value):
    match = re.search(r"MLC[- ]?(\d+)", str(value or ""), re.I)
    return "MLC-" + match.group(1) if match else None


def assess(
    lat,
    lon,
    *,
    precision=None,
    source=None,
    identity_match=None,
    repeated=False,
    approximate=False,
    conflict=False,
    declared_precision=False,
):
    if lat is None and lon is None:
        return {"status": "MISSING", "reason": "no_coordinate_pair"}
    if lat is None or lon is None or isinstance(lat, bool) or isinstance(lon, bool):
        return {"status": "INVALID", "reason": "incomplete_or_boolean_pair"}
    try:
        x, y = float(lat), float(lon)
    except (ValueError, TypeError, OverflowError):
        return {"status": "INVALID", "reason": "non_numeric_pair"}
    if not math.isfinite(x + y) or not (-90 <= x <= 90 and -180 <= y <= 180) or (x, y) == (0, 0):
        return {"status": "INVALID", "reason": "range_nonfinite_or_null_island"}
    if identity_match is False or conflict:
        return {"status": "INVALID", "reason": "publication_or_location_conflict"}
    if repeated or precision in ("comuna", "comuna_centroid"):
        return {
            "status": "UNCERTAIN",
            "reason": "centroid_or_repeated_coordinate",
            "local_eligible": False,
        }
    if (
        approximate
        or not source
        or identity_match is not True
        or not declared_precision
        or precision not in ("address", "street")
    ):
        return {
            "status": "UNCERTAIN",
            "reason": "source_location_accuracy_not_certified",
            "local_eligible": True,
        }
    return {
        "status": "USABLE",
        "reason": "source_bound_coordinate_with_declared_precision",
        "local_eligible": True,
    }


def evidence(raw_lat, raw_lon, *, publication_id, source, observed_at=None, precision="unknown"):
    quality = assess(raw_lat, raw_lon, precision=precision, source=source, identity_match=True)
    valid = quality["status"] not in ("INVALID", "MISSING")
    return {
        "version": VERSION,
        "source": source,
        "source_listing_id": publication_id,
        "original": {"lat": raw_lat, "lon": raw_lon},
        "normalized": {"lat": float(raw_lat), "lon": float(raw_lon)} if valid else None,
        "precision": precision,
        "quality": quality,
        "observed_at": observed_at,
    }


def bind_detail(detail, state, requested_url):
    """Bind the *source* point to independent page identity, never URL alone."""
    from datetime import UTC, datetime

    metadata = detail["raw_metadata"]
    raw = metadata.pop("coordinates_raw", None)
    point_id = mlc(state.get("id"))
    known = [
        mlc(value)
        for value in (
            state.get("id"),
            requested_url,
            detail.get("canonical_url"),
            detail.get("external_id"),
        )
        if mlc(value)
    ]
    bound = bool(point_id and len(set(known)) == 1)
    address_candidate = metadata.pop("address_candidate", None)
    if bound and address_candidate:
        metadata["address_evidence"] = dict(address_candidate,
            source_listing_id=point_id, commune=detail.get("comuna"),
            observed_at=datetime.now(UTC).isoformat())
        from domain.ingestion.location_evidence import candidate_building_key
        key = candidate_building_key(address_candidate.get("original"), detail.get("comuna"))
        if key:
            metadata["building_candidate"] = key
    if raw is None:
        metadata["coordinates_quality"] = {"status": "MISSING", "reason": "no_map_point"}
        return
    ev = evidence(
        raw.get("lat"),
        raw.get("lon"),
        publication_id=point_id,
        source=metadata.get("location_source"),
        observed_at=datetime.now(UTC).isoformat(),
    )
    if not bound:
        ev["quality"] = {
            "status": "INVALID",
            "reason": "unbound_or_conflicting_mlc",
            "local_eligible": False,
        }
        ev["normalized"] = None
        metadata["coordinates_rejection_reason"] = "unbound_or_conflicting_mlc"
    ev["commune"] = detail.get("comuna")
    ev["map_commune"] = raw.get("commune")
    if bound:
        if metadata.get("address_evidence"):
            ev["address_evidence"] = metadata["address_evidence"]
        ev["precision_original"] = raw.get("precision_original") or {}
        metadata["coordinate_provenance"] = {
            "kind": "portal_map_unknown_accuracy", "precision": "unknown",
            "source_listing_id": point_id, "source": ev["source"],
            "precision_original": ev["precision_original"],
        }
    ev = validate_context(ev, detail.get("comuna"))
    from core.value_objects.location import Coordinates

    for alternative in metadata.get("coordinates_alternatives_raw", []):
        other = evidence(
            alternative.get("lat"),
            alternative.get("lon"),
            publication_id=point_id,
            source=alternative.get("source"),
        )
        if ev.get("normalized") and other.get("normalized"):
            first, second = ev["normalized"], other["normalized"]
            if Coordinates(**first).distance_km(Coordinates(**second)) > 0.001:
                ev["quality"] = {
                    "status": "UNCERTAIN",
                    "reason": "source_map_components_conflict",
                    "local_eligible": False,
                }
                ev["alternatives"] = metadata["coordinates_alternatives_raw"]
    metadata.update(
        coordinates_evidence=ev,
        coordinates_quality=ev["quality"],
        geocode_precision="unknown",
        geocode_precision_reason="source_map_accuracy_not_certified",
    )
    if ev.get("normalized") and ev["quality"].get("local_eligible", False):
        metadata.update(ev["normalized"])
    else:
        metadata.pop("lat", None)
        metadata.pop("lon", None)
        metadata.pop("location_source", None)
    from domain.ingestion.observations import json_value

    metadata["coordinates_evidence"] = json_value(ev)


def validate_context(ev, commune):
    """Conservative plausibility checks, not a polygon/geocoding certification."""
    from copy import deepcopy
    from config.comunas import COMUNAS, normalize_comuna
    from core.value_objects.location import Coordinates

    out = deepcopy(ev)
    other = out.get("map_commune") or out.get("commune")
    if other and not isinstance(other, str):
        out["quality"] = {
            "status": "UNCERTAIN",
            "reason": "unparseable_commune_evidence",
            "local_eligible": False,
        }
        return out
    if commune and other and normalize_comuna(commune) != normalize_comuna(other):
        out["quality"] = {
            "status": "INVALID",
            "reason": "commune_evidence_conflict",
            "local_eligible": False,
        }
        return out
    point = out.get("normalized")
    if not point or out["quality"]["status"] == "INVALID":
        return out
    centre = next(
        (c for c in COMUNAS if normalize_comuna(c.name) == normalize_comuna(commune or "")), None
    )
    if centre:
        km = Coordinates(point["lat"], point["lon"]).distance_km(
            Coordinates(centre.lat, centre.lon)
        )
        out["commune_centroid_distance_km"] = round(km, 3)
        # Deliberately broad: identifies gross contradictions, not commune membership.
        if km > 50:
            out["quality"] = {
                "status": "UNCERTAIN",
                "reason": "far_from_declared_commune",
                "local_eligible": False,
            }
        if abs(point["lat"] - centre.lat) < 1e-7 and abs(point["lon"] - centre.lon) < 1e-7:
            out["quality"] = {
                "status": "UNCERTAIN",
                "reason": "known_commune_centroid",
                "local_eligible": False,
            }
    return out


def attach_map_point(card, point, *, observed_at=None):
    """Offline adapter for an already acquired map point; never requests a map."""
    from copy import deepcopy

    out = deepcopy(card)
    expected = mlc(card.get("external_id"))
    actual = mlc(point.get("id"))
    if not expected or actual != expected:
        raise ValueError("Map point MLC mismatch")
    ev = evidence(
        point.get("latitude"),
        point.get("longitude"),
        publication_id=actual,
        source="portal:map_listing_point",
        observed_at=observed_at,
    )
    if ev["normalized"] is None:
        raise ValueError("Invalid map coordinate pair")
    out.update(ev["normalized"], geocode_precision="unknown")
    out.setdefault("raw_metadata", {}).update(
        coordinates_evidence=ev,
        location_source=ev["source"],
        geocode_precision="unknown",
        **ev["normalized"],
    )
    return out
