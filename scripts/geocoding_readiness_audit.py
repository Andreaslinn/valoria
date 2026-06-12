"""Offline geocoding readiness audit.

This script does not call external APIs. It estimates how many listings have
recoverable location text that could be used by a future geocoding backfill.

Usage:
    python scripts/geocoding_readiness_audit.py --output-dir reports/geocoding
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.normalization.geocode_precision import canonical_geocode_precision, normalize_geocode_precision  # noqa: E402
from core.normalization.property_type import normalize_property_type  # noqa: E402
from domain.geocoding.microzones import signals_from_value  # noqa: E402
from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.models import ListingORM  # noqa: E402
from scripts.geocode_listings import AddressCandidate, extract_address_candidate  # noqa: E402

DEFAULT_OUTPUT_DIR = Path("reports/geocoding")


@dataclass(frozen=True)
class GeocodingReadiness:
    coords_class: str
    text_class: str
    candidate_text: str | None
    candidate_precision: str
    candidate_source: str
    candidate_reason: str
    nearby_metro: str | None
    nearby_avenue: str | None
    intersection_hint: str | None
    landmark_tokens: tuple[str, ...]
    is_backfill_candidate: bool
    impossible_reason: str | None


def build_geocoding_readiness_report(
    listings: list[dict[str, Any]],
    *,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    now = generated_at or datetime.now(UTC)
    active = [row for row in listings if _norm(row.get("status"), "unknown") == "active"]
    classified = [_classified_row(row) for row in active]
    total = len(classified)
    backfill_candidates = [row for row in classified if row["is_backfill_candidate"]]
    no_address_coords = [row for row in classified if row["coords_class"] != "address_level_coords"]

    summary = {
        "generated_at": now.isoformat(),
        "active_listings": total,
        "address_level_coords": _count(classified, "coords_class", "address_level_coords"),
        "approximate_coords": _count(classified, "coords_class", "approximate_coords"),
        "comuna_centroid_coords": _count(classified, "coords_class", "comuna_centroid_coords"),
        "no_coords": _count(classified, "coords_class", "no_coords"),
        "recoverable_text_address": _count(classified, "text_class", "text_address_recoverable"),
        "probable_street": _count(classified, "text_class", "probable_street"),
        "probable_intersection": _count(classified, "text_class", "probable_intersection"),
        "probable_landmark_or_metro": _count(classified, "text_class", "probable_landmark_or_metro"),
        "impossible_to_geocode_confidently": _count(classified, "text_class", "impossible"),
        "backfill_candidate_count": len(backfill_candidates),
        "backfill_candidate_pct_total": _pct(len(backfill_candidates), total),
        "backfill_candidate_pct_without_address_coords": _pct(len(backfill_candidates), len(no_address_coords)),
        "estimated_address_level_gain_ceiling_pct": _pct(
            sum(row["text_class"] == "text_address_recoverable" for row in no_address_coords),
            total,
        ),
        "estimated_street_or_better_gain_ceiling_pct": _pct(len(backfill_candidates), total),
    }

    return {
        "summary": summary,
        "by_comuna_property_type": _segment_rows(classified, ("comuna", "property_type")),
        "by_comuna": _segment_rows(classified, ("comuna",)),
        "by_property_type": _segment_rows(classified, ("property_type",)),
        "top_recoverable_examples": _examples(backfill_candidates),
        "top_impossible_examples": _examples([row for row in classified if row["text_class"] == "impossible"]),
    }


def classify_listing_readiness(row: dict[str, Any]) -> GeocodingReadiness:
    raw_metadata = row.get("raw_metadata") if isinstance(row.get("raw_metadata"), dict) else {}
    has_coords = _has_coords(row)
    precision = normalize_geocode_precision(
        row.get("geocode_precision"),
        has_coords=has_coords,
        raw_metadata=raw_metadata,
        comuna=row.get("comuna"),
    )
    coords_class = _coords_class(precision, has_coords)
    candidate = extract_address_candidate(
        title=str(row.get("title") or ""),
        description=_description(raw_metadata),
        url=str(row.get("url") or ""),
        comuna=str(row.get("comuna") or ""),
        raw_metadata=raw_metadata,
    )
    signals = _signals_for_row(row)
    full_text = " ".join(
        str(part or "")
        for part in (
            row.get("title"),
            _description(raw_metadata),
            raw_metadata.get("address_label"),
            raw_metadata.get("location_text"),
            raw_metadata.get("street_hint"),
        )
    )
    text_class = classify_textual_readiness(candidate, signals, full_text=full_text)
    is_backfill_candidate = coords_class != "address_level_coords" and text_class != "impossible"
    impossible_reason = None
    if text_class == "impossible":
        impossible_reason = candidate.reason or "no_recoverable_location_text"

    return GeocodingReadiness(
        coords_class=coords_class,
        text_class=text_class,
        candidate_text=candidate.text,
        candidate_precision=canonical_geocode_precision(candidate.precision),
        candidate_source=candidate.source,
        candidate_reason=candidate.reason,
        nearby_metro=signals.nearby_metro,
        nearby_avenue=signals.nearby_avenue,
        intersection_hint=signals.intersection_hint,
        landmark_tokens=tuple(signals.landmark_tokens),
        is_backfill_candidate=is_backfill_candidate,
        impossible_reason=impossible_reason,
    )


def classify_textual_readiness(candidate: AddressCandidate, signals: Any, *, full_text: str | None = None) -> str:
    text = str(candidate.text or "").strip().lower()
    context = f" {str(full_text or '').strip().lower()} "
    precision = str(candidate.precision or "unknown")
    if candidate.text and precision == "street_address":
        return "text_address_recoverable"
    if candidate.text and (_looks_like_intersection(text) or _looks_like_intersection(context)):
        return "probable_intersection"
    if candidate.text and precision in {"street", "street_name"}:
        return "probable_street"
    if candidate.text and precision == "landmark_or_sector":
        return "probable_landmark_or_metro"
    if signals.nearby_metro or signals.landmark_tokens:
        return "probable_landmark_or_metro"
    if signals.nearby_avenue:
        return "probable_street"
    if signals.intersection_hint:
        return "probable_intersection"
    return "impossible"


def write_report(report: dict[str, Any], *, output_dir: Path = DEFAULT_OUTPUT_DIR) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "geocoding_readiness.json"
    md_path = output_dir / "geocoding_readiness.md"
    json_path.write_text(json.dumps(_json_safe(report), ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_markdown_report(report), encoding="utf-8")
    return md_path, json_path


def print_console_report(report: dict[str, Any], *, md_path: Path | None = None, json_path: Path | None = None) -> None:
    print("== AVM Geocoding Readiness ==")
    for key, value in report["summary"].items():
        print(f"{key}\t{value}")
    if md_path and json_path:
        print("\n== Files ==")
        print(f"markdown\t{md_path}")
        print(f"json\t{json_path}")


async def load_listings() -> list[dict[str, Any]]:
    async with get_session_factory()() as session:
        result = await session.execute(select(ListingORM))
        return [_orm_to_dict(row) for row in result.scalars().all()]


def _classified_row(row: dict[str, Any]) -> dict[str, Any]:
    readiness = classify_listing_readiness(row)
    return {
        "id": row.get("id"),
        "title": row.get("title"),
        "comuna": _norm(row.get("comuna"), "unknown"),
        "property_type": normalize_property_type(row.get("property_type")),
        "coords_class": readiness.coords_class,
        "text_class": readiness.text_class,
        "candidate_text": readiness.candidate_text,
        "candidate_precision": readiness.candidate_precision,
        "candidate_source": readiness.candidate_source,
        "candidate_reason": readiness.candidate_reason,
        "nearby_metro": readiness.nearby_metro,
        "nearby_avenue": readiness.nearby_avenue,
        "intersection_hint": readiness.intersection_hint,
        "landmark_tokens": list(readiness.landmark_tokens),
        "is_backfill_candidate": readiness.is_backfill_candidate,
        "impossible_reason": readiness.impossible_reason,
    }


def _segment_rows(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[tuple(row[key] for key in keys)].append(row)
    result = []
    for key_values, items in grouped.items():
        row = {key: value for key, value in zip(keys, key_values, strict=True)}
        row.update(
            {
                "active_listings": len(items),
                "address_level_coords": _count(items, "coords_class", "address_level_coords"),
                "approximate_coords": _count(items, "coords_class", "approximate_coords"),
                "comuna_centroid_coords": _count(items, "coords_class", "comuna_centroid_coords"),
                "no_coords": _count(items, "coords_class", "no_coords"),
                "backfill_candidate_count": sum(item["is_backfill_candidate"] for item in items),
                "backfill_candidate_pct": _pct(sum(item["is_backfill_candidate"] for item in items), len(items)),
                "impossible_pct": _pct(_count(items, "text_class", "impossible"), len(items)),
                "text_address_recoverable": _count(items, "text_class", "text_address_recoverable"),
                "probable_street": _count(items, "text_class", "probable_street"),
                "probable_intersection": _count(items, "text_class", "probable_intersection"),
                "probable_landmark_or_metro": _count(items, "text_class", "probable_landmark_or_metro"),
            }
        )
        result.append(row)
    return sorted(result, key=lambda item: (-item["active_listings"], tuple(str(item[key]) for key in keys)))


def _coords_class(precision: str, has_coords: bool) -> str:
    if not has_coords:
        return "no_coords"
    if precision == "address":
        return "address_level_coords"
    if precision == "street":
        return "approximate_coords"
    if precision == "comuna_centroid":
        return "comuna_centroid_coords"
    return "approximate_coords"


def _signals_for_row(row: dict[str, Any]) -> Any:
    class Value:
        pass

    value = Value()
    value.title = row.get("title")
    value.raw_metadata = row.get("raw_metadata") if isinstance(row.get("raw_metadata"), dict) else {}
    return signals_from_value(value)


def _examples(rows: list[dict[str, Any]], *, limit: int = 30) -> list[dict[str, Any]]:
    return [
        {
            "id": row["id"],
            "comuna": row["comuna"],
            "property_type": row["property_type"],
            "coords_class": row["coords_class"],
            "text_class": row["text_class"],
            "candidate_text": row["candidate_text"],
            "candidate_source": row["candidate_source"],
            "title": row["title"],
        }
        for row in rows[:limit]
    ]


def _description(raw_metadata: dict[str, Any]) -> str:
    values = []
    for key in ("description", "descripcion", "details", "body", "summary", "card_text"):
        value = raw_metadata.get(key)
        if isinstance(value, str) and value.strip():
            values.append(value)
    return " ".join(values)


def _looks_like_intersection(text: str) -> bool:
    return bool(text and (" y " in text or " con " in text or "/" in text))


def _count(rows: list[dict[str, Any]], key: str, value: Any) -> int:
    return sum(row.get(key) == value for row in rows)


def _has_coords(row: dict[str, Any]) -> bool:
    return row.get("lat") is not None and row.get("lon") is not None


def _orm_to_dict(row: ListingORM) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title,
        "url": row.url,
        "comuna": row.comuna,
        "property_type": row.property_type,
        "lat": row.lat,
        "lon": row.lon,
        "geocode_precision": row.geocode_precision,
        "status": row.status,
        "raw_metadata": row.raw_metadata,
    }


def _pct(part: int | float, total: int | float) -> float:
    if not total:
        return 0.0
    return round(float(part) / float(total) * 100, 2)


def _norm(value: Any, default: str) -> str:
    text = str(value or "").strip().lower()
    return text or default


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _markdown_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# AVM Geocoding Readiness",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Active listings: {summary['active_listings']}",
        f"- Address-level coords: {summary['address_level_coords']}",
        f"- Approximate coords: {summary['approximate_coords']}",
        f"- Comuna centroid coords: {summary['comuna_centroid_coords']}",
        f"- No coords: {summary['no_coords']}",
        f"- Text address recoverable: {summary['recoverable_text_address']}",
        f"- Probable street: {summary['probable_street']}",
        f"- Probable intersection: {summary['probable_intersection']}",
        f"- Probable landmark/metro: {summary['probable_landmark_or_metro']}",
        f"- Impossible confidently: {summary['impossible_to_geocode_confidently']}",
        f"- Backfill candidate pct total: {summary['backfill_candidate_pct_total']}%",
        f"- Backfill candidate pct without address coords: {summary['backfill_candidate_pct_without_address_coords']}%",
        f"- Estimated address-level gain ceiling: {summary['estimated_address_level_gain_ceiling_pct']}%",
        f"- Estimated street-or-better gain ceiling: {summary['estimated_street_or_better_gain_ceiling_pct']}%",
        "",
        "## By Comuna + Property Type",
        "",
        _markdown_table(report["by_comuna_property_type"]),
        "",
        "## Recoverable Examples",
        "",
        _markdown_table(report["top_recoverable_examples"]),
        "",
        "## Impossible Examples",
        "",
        _markdown_table(report["top_impossible_examples"]),
    ]
    return "\n".join(lines) + "\n"


def _markdown_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "_No data._"
    columns = list(rows[0])
    lines = ["| " + " | ".join(columns) + " |", "|" + "|".join("---" for _ in columns) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(column)) for column in columns) + " |")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate geocoding readiness audit without external API calls.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Output directory.")
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    listings = await load_listings()
    report = build_geocoding_readiness_report(listings)
    md_path, json_path = write_report(report, output_dir=Path(args.output_dir))
    print_console_report(report, md_path=md_path, json_path=json_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
