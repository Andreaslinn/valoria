"""Safe metadata/data backfill for house area corrections.

Dry-run by default. Use --apply to persist changes.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from domain.ingestion.data_cleaning import extract_area_fields_with_provenance  # noqa: E402
from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.models import ListingORM  # noqa: E402

REPORT_DIR = Path("reports/data_quality")
MIGRATION_VERSION = "house_area_correction_v1"


@dataclass(frozen=True)
class HouseAreaSuggestion:
    listing_id: int | None
    external_id: str | None
    comuna: str | None
    title: str
    current_m2: float | None
    current_built_area_m2: float | None
    current_land_area_m2: float | None
    suggested_m2: float | None
    suggested_built_area_m2: float | None
    suggested_land_area_m2: float | None
    changed_fields: tuple[str, ...]
    reasons: tuple[str, ...]
    parsed_sources: dict[str, str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill corrected house area fields safely.")
    parser.add_argument("--apply", action="store_true", help="Persist changes. Omit for dry-run.")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--comuna")
    parser.add_argument("--include-inactive", action="store_true")
    parser.add_argument("--overwrite-built", action="store_true", help="Allow built_area overwrite when parser finds explicit built area.")
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    async with get_session_factory()() as session:
        stmt = (
            select(ListingORM)
            .where(ListingORM.property_type == "house")
            .order_by(ListingORM.id)
        )
        if not args.include_inactive:
            stmt = stmt.where(ListingORM.status == "active")
        if args.comuna:
            stmt = stmt.where(ListingORM.comuna == args.comuna)
        if args.limit:
            stmt = stmt.limit(args.limit)
        rows = list((await session.execute(stmt)).scalars().all())
        suggestions = [suggest_house_area_correction(row, overwrite_built=args.overwrite_built) for row in rows]
        changed = [suggestion for suggestion in suggestions if suggestion.changed_fields]
        if args.apply:
            for row, suggestion in zip(rows, suggestions, strict=False):
                if suggestion.changed_fields:
                    apply_suggestion(row, suggestion)
            await session.commit()
        else:
            await session.rollback()

    report = build_report(suggestions, apply=args.apply)
    paths = write_report(report)
    print(json.dumps({"mode": "apply" if args.apply else "dry-run", **report["summary"], **paths}, ensure_ascii=False, indent=2))
    return 0


def suggest_house_area_correction(row: Any, *, overwrite_built: bool = False) -> HouseAreaSuggestion:
    metadata = row.raw_metadata if isinstance(row.raw_metadata, dict) else {}
    description = metadata.get("description") or metadata.get("descripcion") or ""
    raw = {
        "property_type": "house",
        "description": description,
        "raw_metadata": metadata,
    }
    parsed = extract_area_fields_with_provenance(raw, title=str(row.title or ""))
    parsed_land = parsed.areas.get("land_area_m2")
    parsed_built = parsed.areas.get("built_area_m2")
    current_m2 = _float_or_none(row.m2)
    current_built = _float_or_none(row.built_area_m2)
    current_land = _float_or_none(row.land_area_m2)
    suggested_m2 = current_m2
    suggested_built = current_built
    suggested_land = current_land
    changed: list[str] = []
    reasons: list[str] = []

    if parsed_land is not None and _should_update_land(current_land, parsed_land):
        suggested_land = parsed_land
        changed.append("land_area_m2")
        reasons.append("land_area_reparsed_from_text")

    land_for_comparison = suggested_land
    if land_for_comparison is not None and current_built is not None:
        built_source = str(metadata.get("built_area_parse_source") or "")
        has_explicit_built = parsed_built is not None or built_source not in {"", "raw.m2.fallback"}
        built_matches_land = _same_area(current_built, land_for_comparison) or _same_area(current_built, current_land)
        if not has_explicit_built and built_matches_land:
            suggested_built = None
            changed.append("built_area_m2")
            reasons.append("built_area_was_land_area_fallback")
            m2_matches_land = _same_area(current_m2, land_for_comparison) or _same_area(current_m2, current_land)
            if current_m2 is not None and m2_matches_land:
                suggested_m2 = None
                changed.append("m2")
                reasons.append("m2_was_land_area")

    if overwrite_built and parsed_built is not None and not _same_area(current_built, parsed_built):
        suggested_built = parsed_built
        changed.append("built_area_m2")
        reasons.append("built_area_reparsed_from_text")
        if current_m2 is None or _same_area(current_m2, current_built):
            suggested_m2 = parsed_built
            changed.append("m2")
            reasons.append("m2_aligned_to_built_area")

    return HouseAreaSuggestion(
        listing_id=row.id,
        external_id=row.external_id,
        comuna=row.comuna,
        title=str(row.title or ""),
        current_m2=current_m2,
        current_built_area_m2=current_built,
        current_land_area_m2=current_land,
        suggested_m2=suggested_m2,
        suggested_built_area_m2=suggested_built,
        suggested_land_area_m2=suggested_land,
        changed_fields=tuple(dict.fromkeys(changed)),
        reasons=tuple(dict.fromkeys(reasons)),
        parsed_sources=dict(parsed.sources),
    )


def apply_suggestion(row: Any, suggestion: HouseAreaSuggestion) -> None:
    if "m2" in suggestion.changed_fields:
        row.m2 = suggestion.suggested_m2
    if "built_area_m2" in suggestion.changed_fields:
        row.built_area_m2 = suggestion.suggested_built_area_m2
    if "land_area_m2" in suggestion.changed_fields:
        row.land_area_m2 = suggestion.suggested_land_area_m2
    metadata = dict(row.raw_metadata or {})
    metadata["area_correction_version"] = MIGRATION_VERSION
    metadata["area_correction_applied_at"] = datetime.now(UTC).isoformat()
    metadata["area_correction_reasons"] = list(suggestion.reasons)
    row.raw_metadata = metadata


def build_report(suggestions: list[HouseAreaSuggestion], *, apply: bool) -> dict[str, Any]:
    changed = [suggestion for suggestion in suggestions if suggestion.changed_fields]
    return {
        "summary": {
            "generated_at": datetime.now(UTC).isoformat(),
            "mode": "apply" if apply else "dry-run",
            "reviewed": len(suggestions),
            "rows_with_changes": len(changed),
            "land_area_updates": sum("land_area_m2" in item.changed_fields for item in changed),
            "built_area_clears_or_updates": sum("built_area_m2" in item.changed_fields for item in changed),
            "m2_clears_or_updates": sum("m2" in item.changed_fields for item in changed),
            "reasons": dict(Counter(reason for item in changed for reason in item.reasons)),
            "by_comuna": dict(Counter(str(item.comuna or "unknown") for item in changed)),
        },
        "changed_rows": [asdict(item) for item in changed],
    }


def write_report(report: dict[str, Any]) -> dict[str, str]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = REPORT_DIR / f"house_area_corrections_{stamp}.json"
    md_path = REPORT_DIR / f"house_area_corrections_{stamp}.md"
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    json_path.write_text(payload, encoding="utf-8")
    (REPORT_DIR / "house_area_corrections_latest.json").write_text(payload, encoding="utf-8")
    markdown = _markdown(report)
    md_path.write_text(markdown, encoding="utf-8")
    (REPORT_DIR / "house_area_corrections_latest.md").write_text(markdown, encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(md_path)}


def _markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# House Area Corrections",
        "",
        f"- Generated at: {summary['generated_at']}",
        f"- Mode: {summary['mode']}",
        f"- Reviewed: {summary['reviewed']}",
        f"- Rows with changes: {summary['rows_with_changes']}",
        f"- Land area updates: {summary['land_area_updates']}",
        f"- Built area clears/updates: {summary['built_area_clears_or_updates']}",
        f"- m2 clears/updates: {summary['m2_clears_or_updates']}",
        "",
        "## Changed Rows",
        "",
        "| id | comuna | fields | current built | new built | current land | new land | reasons | title |",
        "| ---: | --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for item in report["changed_rows"][:100]:
        lines.append(
            f"| {item['listing_id']} | {item['comuna']} | {','.join(item['changed_fields'])} | "
            f"{item['current_built_area_m2']} | {item['suggested_built_area_m2']} | "
            f"{item['current_land_area_m2']} | {item['suggested_land_area_m2']} | "
            f"{','.join(item['reasons'])} | {str(item['title'])[:80]} |"
        )
    return "\n".join(lines) + "\n"


def _should_update_land(current: float | None, parsed: float) -> bool:
    if parsed <= 0:
        return False
    if current is None:
        return True
    if _same_area(current, parsed):
        return False
    if current < 10 <= parsed:
        return True
    return abs(parsed - current) / max(current, 1.0) >= 0.25


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _same_area(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return False
    return abs(float(left) - float(right)) < 0.01


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
