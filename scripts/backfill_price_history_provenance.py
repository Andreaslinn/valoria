"""Backfill canonical price fields in price_history and mark UF-rate artifacts.

Dry-run by default. Use --apply to persist changes. The script does not delete
history rows; suspicious historical points are marked as artifacts.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.models import ListingORM, PriceHistoryORM  # noqa: E402

MIN_PLAUSIBLE_UF_RATE = Decimal("34000")
MAX_PLAUSIBLE_UF_RATE = Decimal("43000")
MIN_RATE_ARTIFACT_DELTA_PCT = Decimal("3.0")
MAX_ARTIFACT_DELTA_GAP_PCT = Decimal("0.20")


@dataclass(frozen=True)
class PriceHistoryMigrationSuggestion:
    price_history_id: int
    listing_id: int
    external_id: str | None
    comuna: str
    property_type: str
    observed_at: str
    created_at: str | None
    old_price_clp: str
    current_price_clp: str | None
    current_price_uf: str | None
    current_price_currency: str | None
    implied_uf_rate: str | None
    current_uf_rate: str | None
    change_basis: str
    is_artifact: bool
    artifact_reason: str | None
    would_update: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill price_history provenance.")
    parser.add_argument("--apply", action="store_true", help="Persist changes. Omit for dry-run.")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--examples", type=int, default=30)
    parser.add_argument(
        "--output-dir",
        default="reports/price_history_provenance",
        help="Directory for JSON/Markdown reports.",
    )
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    async with get_session_factory()() as session:
        stmt = (
            select(PriceHistoryORM, ListingORM)
            .join(ListingORM, PriceHistoryORM.listing_id == ListingORM.id)
            .order_by(PriceHistoryORM.id.asc())
        )
        if args.limit:
            stmt = stmt.limit(args.limit)
        rows = list((await session.execute(stmt)).all())
        suggestions = [build_suggestion(history, listing) for history, listing in rows]
        report = build_report(suggestions, apply=args.apply, examples=args.examples)
        write_report(report, Path(args.output_dir))
        print_summary(report)

        if args.apply:
            apply_suggestions(rows, suggestions)
            await session.commit()
        else:
            await session.rollback()
    return 0


def build_suggestion(
    history: PriceHistoryORM,
    listing: ListingORM,
) -> PriceHistoryMigrationSuggestion:
    currency = _canonical_currency(getattr(history, "price_currency", None)) or _canonical_currency(listing.price_currency)
    price_uf = _decimal_or_none(listing.price_uf)
    history_price_clp = _decimal_or_none(history.price_clp)
    current_price_clp = _decimal_or_none(listing.price_clp)
    implied_rate = _rate(history_price_clp, price_uf)
    current_rate = _rate(current_price_clp, price_uf)
    is_artifact = is_uf_rate_artifact(
        history_price_clp=history_price_clp,
        current_price_clp=current_price_clp,
        listing_price_uf=price_uf,
        currency=currency,
    )
    change_basis = _change_basis(currency, is_artifact)
    artifact_reason = "uf_rate_artifact" if is_artifact else None

    would_update = any(
        (
            getattr(history, "price_clp_snapshot", None) != history.price_clp,
            getattr(history, "price_currency", None) != currency,
            getattr(history, "change_basis", None) != change_basis,
            bool(getattr(history, "is_artifact", False)) != is_artifact,
            getattr(history, "artifact_reason", None) != artifact_reason,
            is_artifact and getattr(history, "price_uf", None) != price_uf,
            is_artifact and _decimal_or_none(getattr(history, "uf_rate_used", None)) != implied_rate,
        )
    )

    return PriceHistoryMigrationSuggestion(
        price_history_id=history.id,
        listing_id=listing.id,
        external_id=listing.external_id,
        comuna=listing.comuna,
        property_type=listing.property_type,
        observed_at=_iso(history.observed_at),
        created_at=_iso(getattr(history, "created_at", None)),
        old_price_clp=_decimal_str(history_price_clp),
        current_price_clp=_decimal_str(current_price_clp) if current_price_clp is not None else None,
        current_price_uf=_decimal_str(price_uf) if price_uf is not None else None,
        current_price_currency=currency,
        implied_uf_rate=_decimal_str(implied_rate) if implied_rate is not None else None,
        current_uf_rate=_decimal_str(current_rate) if current_rate is not None else None,
        change_basis=change_basis,
        is_artifact=is_artifact,
        artifact_reason=artifact_reason,
        would_update=would_update,
    )


def is_uf_rate_artifact(
    *,
    history_price_clp: Decimal | None,
    current_price_clp: Decimal | None,
    listing_price_uf: Decimal | None,
    currency: str | None,
) -> bool:
    if currency != "UF" or history_price_clp is None or current_price_clp is None or listing_price_uf is None:
        return False
    if history_price_clp <= 0 or current_price_clp <= 0 or listing_price_uf <= 0:
        return False
    history_rate = history_price_clp / listing_price_uf
    current_rate = current_price_clp / listing_price_uf
    if not (_plausible_rate(history_rate) and _plausible_rate(current_rate)):
        return False
    if history_rate == current_rate:
        return False
    clp_delta_pct = ((current_price_clp - history_price_clp) / history_price_clp) * Decimal("100")
    rate_delta_pct = ((current_rate - history_rate) / history_rate) * Decimal("100")
    if abs(rate_delta_pct) < MIN_RATE_ARTIFACT_DELTA_PCT:
        return False
    return abs(clp_delta_pct - rate_delta_pct) <= MAX_ARTIFACT_DELTA_GAP_PCT


def apply_suggestions(
    rows: list[tuple[PriceHistoryORM, ListingORM]],
    suggestions: list[PriceHistoryMigrationSuggestion],
) -> None:
    by_id = {suggestion.price_history_id: suggestion for suggestion in suggestions}
    for history, listing in rows:
        suggestion = by_id[history.id]
        if not suggestion.would_update:
            continue
        history.price_clp_snapshot = history.price_clp
        history.price_currency = suggestion.current_price_currency
        history.change_basis = suggestion.change_basis
        history.is_artifact = suggestion.is_artifact
        history.artifact_reason = suggestion.artifact_reason
        if suggestion.is_artifact:
            history.price_uf = listing.price_uf
            history.uf_rate_used = _decimal_or_none(suggestion.implied_uf_rate)


def build_report(
    suggestions: list[PriceHistoryMigrationSuggestion],
    *,
    apply: bool,
    examples: int,
) -> dict[str, Any]:
    would_update = [item for item in suggestions if item.would_update]
    artifacts = [item for item in suggestions if item.is_artifact]
    return {
        "mode": "apply" if apply else "dry_run",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total_price_history_rows": len(suggestions),
        "rows_with_changes": len(would_update),
        "artifacts_detected": len(artifacts),
        "by_currency": dict(Counter(item.current_price_currency or "unknown" for item in suggestions)),
        "by_change_basis": dict(Counter(item.change_basis for item in suggestions)),
        "by_artifact_reason": dict(Counter(item.artifact_reason or "none" for item in suggestions)),
        "examples": [asdict(item) for item in would_update[:examples]],
        "artifact_examples": [asdict(item) for item in artifacts[:examples]],
    }


def write_report(report: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = f"price_history_provenance_{report['mode']}_{stamp}"
    json_path = output_dir / f"{stem}.json"
    md_path = output_dir / f"{stem}.md"
    latest_json = output_dir / "price_history_provenance_latest.json"
    latest_md = output_dir / "price_history_provenance_latest.md"
    json_payload = json.dumps(report, ensure_ascii=False, indent=2)
    json_path.write_text(json_payload, encoding="utf-8")
    latest_json.write_text(json_payload, encoding="utf-8")
    md_payload = _markdown_report(report)
    md_path.write_text(md_payload, encoding="utf-8")
    latest_md.write_text(md_payload, encoding="utf-8")


def print_summary(report: dict[str, Any]) -> None:
    print(json.dumps({k: report[k] for k in (
        "mode",
        "total_price_history_rows",
        "rows_with_changes",
        "artifacts_detected",
        "by_change_basis",
    )}, ensure_ascii=False, indent=2))


def _markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Price History Provenance Migration",
        "",
        f"- Mode: {report['mode']}",
        f"- Generated at: {report['generated_at']}",
        f"- Total price_history rows: {report['total_price_history_rows']}",
        f"- Rows with changes: {report['rows_with_changes']}",
        f"- Artifacts detected: {report['artifacts_detected']}",
        "",
        "## By Change Basis",
        "",
        *_counter_lines(report["by_change_basis"]),
        "",
        "## Artifact Examples",
        "",
        "| price_history_id | listing_id | external_id | comuna | old_clp | current_clp | price_uf | implied_rate | reason |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in report["artifact_examples"]:
        lines.append(
            "| {price_history_id} | {listing_id} | {external_id} | {comuna} | {old_price_clp} | "
            "{current_price_clp} | {current_price_uf} | {implied_uf_rate} | {artifact_reason} |".format(**item)
        )
    return "\n".join(lines) + "\n"


def _counter_lines(counter: dict[str, int]) -> list[str]:
    return [f"- {key}: {value}" for key, value in sorted(counter.items())]


def _change_basis(currency: str | None, is_artifact: bool) -> str:
    if is_artifact:
        return "uf_rate_artifact"
    if currency == "UF":
        return "legacy_uf_unknown"
    if currency == "CLP":
        return "clp_legacy"
    return "legacy_unknown"


def _canonical_currency(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    if text in {"UF", "CLF"}:
        return "UF"
    if text in {"CLP", "$", "PESO", "PESOS"}:
        return "CLP"
    return text[:16] or None


def _rate(price_clp: Decimal | None, price_uf: Decimal | None) -> Decimal | None:
    if price_clp is None or price_uf is None or price_uf <= 0:
        return None
    return (price_clp / price_uf).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _plausible_rate(value: Decimal) -> bool:
    return MIN_PLAUSIBLE_UF_RATE <= value <= MAX_PLAUSIBLE_UF_RATE


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _decimal_str(value: Decimal | None) -> str:
    if value is None:
        return ""
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
