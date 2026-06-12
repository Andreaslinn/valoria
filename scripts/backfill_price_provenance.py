"""Backfill controlled price_uf provenance for legacy UF listings.

Dry-run by default. Use --apply to persist canonical price fields.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.models import ListingORM  # noqa: E402

PRICE_RECOVERY_VERSION = "price_provenance_v1"
PRICE_UF_SOURCES = {
    "scraped",
    "recovered_exact",
    "recovered_high_confidence",
    "estimated",
    "legacy_unrecoverable",
}
TITLE_UF_PATTERNS = (
    re.compile(r"(?i)\bUF\s*([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]{1,2})?|[0-9]{3,6})\b"),
    re.compile(r"(?i)\b([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]{1,2})?|[0-9]{3,6})\s*UF\b"),
)
MIN_PLAUSIBLE_UF_RATE = Decimal("34000")
MAX_PLAUSIBLE_UF_RATE = Decimal("43000")
INTEGER_UF_TOLERANCE = Decimal("0.05")


@dataclass(frozen=True)
class PriceProvenanceSuggestion:
    listing_id: int
    external_id: str | None
    title: str
    comuna: str
    property_type: str
    price_clp: str
    scraped_at: str
    current_price_uf: str | None
    current_price_currency: str | None
    suggested_price_uf: str | None
    suggested_price_currency: str | None
    suggested_price_uf_confidence: str | None
    suggested_price_uf_source: str
    suggested_price_recovery_method: str
    recovery_rate: str | None
    recovery_note: str
    would_update: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill listing price provenance.")
    parser.add_argument("--apply", action="store_true", help="Persist changes. Omit for dry-run.")
    parser.add_argument("--dry-run", action="store_true", help="Preview only. This is the default.")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--examples", type=int, default=20)
    parser.add_argument(
        "--include-legacy-unrecoverable",
        action="store_true",
        help="Also mark unrecoverable UF rows as legacy_unrecoverable.",
    )
    parser.add_argument(
        "--include-clp",
        action="store_true",
        help="Also populate price_currency=CLP for CLP rows.",
    )
    parser.add_argument(
        "--output-dir",
        default="reports/price_provenance",
        help="Directory for JSON/Markdown reports.",
    )
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    if args.apply and args.dry_run:
        raise SystemExit("--apply and --dry-run are mutually exclusive")

    async with get_session_factory()() as session:
        stmt = select(ListingORM).order_by(ListingORM.id)
        if args.limit:
            stmt = stmt.limit(args.limit)
        listings = list((await session.execute(stmt)).scalars().all())
        suggestions = build_suggestions(
            listings,
            include_legacy_unrecoverable=args.include_legacy_unrecoverable,
            include_clp=args.include_clp,
        )
        report = build_report(suggestions, apply=args.apply, examples=args.examples)
        write_report(report, Path(args.output_dir))
        print_summary(report)

        if args.apply:
            apply_suggestions(listings, suggestions)
            await session.commit()
        else:
            await session.rollback()
    return 0


def build_suggestions(
    listings: list[ListingORM],
    *,
    include_legacy_unrecoverable: bool = False,
    include_clp: bool = False,
) -> list[PriceProvenanceSuggestion]:
    rates_by_date = observed_rates_by_date(listings)
    suggestions: list[PriceProvenanceSuggestion] = []
    for listing in listings:
        metadata = _metadata(listing)
        currency = _currency(metadata)
        if currency == "CLP":
            if include_clp:
                suggestions.append(_clp_suggestion(listing))
            continue
        if currency != "UF":
            continue

        suggestion = _uf_suggestion(listing, rates_by_date)
        if suggestion.suggested_price_uf_source == "legacy_unrecoverable" and not include_legacy_unrecoverable:
            continue
        suggestions.append(suggestion)
    return suggestions


def observed_rates_by_date(listings: list[ListingORM]) -> dict[str, Counter[Decimal]]:
    rates: dict[str, Counter[Decimal]] = defaultdict(Counter)
    for listing in listings:
        metadata = _metadata(listing)
        if _currency(metadata) != "UF":
            continue
        price_clp = _decimal_or_none(listing.price_clp)
        if price_clp is None or price_clp <= 0:
            continue
        scraped_date = _scraped_date(listing)
        raw_price_uf = _decimal_or_none(metadata.get("price_uf"))
        if raw_price_uf and raw_price_uf > 0:
            rate = _quantize_rate(price_clp / raw_price_uf)
            if _plausible_rate(rate):
                rates[scraped_date][rate] += 1
        for title_price_uf in extract_title_price_ufs(listing.title):
            rate = _quantize_rate(price_clp / title_price_uf)
            if _plausible_rate(rate):
                rates[scraped_date][rate] += 1
    return dict(rates)


def extract_title_price_ufs(title: str | None) -> list[Decimal]:
    values: list[Decimal] = []
    for pattern in TITLE_UF_PATTERNS:
        for match in pattern.finditer(title or ""):
            value = _parse_human_number(match.group(1))
            if value is not None and Decimal("100") <= value <= Decimal("100000"):
                values.append(value)
    return values


def _uf_suggestion(
    listing: ListingORM,
    rates_by_date: dict[str, Counter[Decimal]],
) -> PriceProvenanceSuggestion:
    metadata = _metadata(listing)
    current_price_uf = _decimal_or_none(getattr(listing, "price_uf", None))
    raw_price_uf = _decimal_or_none(metadata.get("price_uf"))
    if raw_price_uf is not None and raw_price_uf > 0:
        return _suggestion(
            listing,
            price_uf=raw_price_uf,
            currency="UF",
            confidence="high",
            source="scraped",
            method="raw_metadata.price_uf",
            rate=_rate_for(listing, raw_price_uf),
            note="price_uf already captured by scraper metadata",
            current_price_uf=current_price_uf,
        )

    title_recovery = _recover_from_title(listing)
    if title_recovery is not None:
        price_uf, rate = title_recovery
        return _suggestion(
            listing,
            price_uf=price_uf,
            currency="UF",
            confidence="high",
            source="recovered_exact",
            method="title_explicit_uf",
            rate=rate,
            note="explicit UF amount found in listing title",
            current_price_uf=current_price_uf,
        )

    rate_recovery = _recover_from_same_day_rate(listing, rates_by_date)
    if rate_recovery is not None:
        price_uf, rate, round_error, evidence_count = rate_recovery
        if round_error <= INTEGER_UF_TOLERANCE:
            return _suggestion(
                listing,
                price_uf=price_uf,
                currency="UF",
                confidence="high",
                source="recovered_high_confidence",
                method="same_day_observed_rate_integer",
                rate=rate,
                note=f"price_clp divided by observed same-day rate; evidence_count={evidence_count}",
                current_price_uf=current_price_uf,
            )
        return _suggestion(
            listing,
            price_uf=price_uf,
            currency="UF",
            confidence="low",
            source="estimated",
            method="same_day_observed_rate_decimal",
            rate=rate,
            note=f"non-integer UF estimate; round_error={round_error}; evidence_count={evidence_count}",
            current_price_uf=current_price_uf,
        )

    return _suggestion(
        listing,
        price_uf=None,
        currency="UF",
        confidence="unknown",
        source="legacy_unrecoverable",
        method="no_raw_price_or_observed_rate",
        rate=None,
        note="missing raw price text/html and no same-day rate evidence",
        current_price_uf=current_price_uf,
    )


def _clp_suggestion(listing: ListingORM) -> PriceProvenanceSuggestion:
    return _suggestion(
        listing,
        price_uf=None,
        currency="CLP",
        confidence=None,
        source="scraped",
        method="raw_metadata.currency_original",
        rate=None,
        note="listing was published in CLP; price_uf is not canonical",
        current_price_uf=_decimal_or_none(getattr(listing, "price_uf", None)),
    )


def _recover_from_title(listing: ListingORM) -> tuple[Decimal, Decimal] | None:
    price_clp = _decimal_or_none(listing.price_clp)
    if price_clp is None or price_clp <= 0:
        return None
    candidates: list[tuple[Decimal, Decimal, Decimal]] = []
    for price_uf in extract_title_price_ufs(listing.title):
        if price_uf <= 0:
            continue
        rate = _quantize_rate(price_clp / price_uf)
        if _plausible_rate(rate):
            distance_from_nominal = abs(rate - Decimal("40695.38"))
            candidates.append((distance_from_nominal, price_uf, rate))
    if not candidates:
        return None
    _, price_uf, rate = min(candidates, key=lambda item: item[0])
    return price_uf, rate


def _recover_from_same_day_rate(
    listing: ListingORM,
    rates_by_date: dict[str, Counter[Decimal]],
) -> tuple[Decimal, Decimal, Decimal, int] | None:
    price_clp = _decimal_or_none(listing.price_clp)
    if price_clp is None or price_clp <= 0:
        return None
    rates = rates_by_date.get(_scraped_date(listing))
    if not rates:
        return None

    candidates: list[tuple[Decimal, int, Decimal, Decimal, Decimal]] = []
    for rate, evidence_count in rates.items():
        if rate <= 0:
            continue
        estimated = price_clp / rate
        rounded = estimated.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        round_error = abs(estimated - rounded)
        candidates.append((round_error, -evidence_count, rate, rounded, estimated))
    if not candidates:
        return None
    round_error, negative_count, rate, rounded, estimated = min(candidates, key=lambda item: (item[0], item[1]))
    price_uf = rounded if round_error <= INTEGER_UF_TOLERANCE else estimated.quantize(Decimal("0.01"))
    return price_uf, rate, round_error.quantize(Decimal("0.0001")), -negative_count


def _suggestion(
    listing: ListingORM,
    *,
    price_uf: Decimal | None,
    currency: str,
    confidence: str | None,
    source: str,
    method: str,
    rate: Decimal | None,
    note: str,
    current_price_uf: Decimal | None,
) -> PriceProvenanceSuggestion:
    if source not in PRICE_UF_SOURCES:
        raise ValueError(f"unknown price_uf_source={source}")
    current_currency = getattr(listing, "price_currency", None)
    current_confidence = getattr(listing, "price_uf_confidence", None)
    current_source = getattr(listing, "price_uf_source", None)
    current_method = getattr(listing, "price_recovery_method", None)
    would_update = (
        _money_str(current_price_uf) != _money_str(price_uf)
        or current_currency != currency
        or current_confidence != confidence
        or current_source != source
        or current_method != method
    )
    return PriceProvenanceSuggestion(
        listing_id=int(listing.id),
        external_id=listing.external_id,
        title=listing.title,
        comuna=listing.comuna,
        property_type=listing.property_type,
        price_clp=str(listing.price_clp),
        scraped_at=_datetime_iso(listing.scraped_at),
        current_price_uf=_money_str(current_price_uf),
        current_price_currency=current_currency,
        suggested_price_uf=_money_str(price_uf),
        suggested_price_currency=currency,
        suggested_price_uf_confidence=confidence,
        suggested_price_uf_source=source,
        suggested_price_recovery_method=method,
        recovery_rate=_rate_str(rate),
        recovery_note=note,
        would_update=would_update,
    )


def apply_suggestions(
    listings: list[ListingORM],
    suggestions: list[PriceProvenanceSuggestion],
) -> None:
    by_id = {int(listing.id): listing for listing in listings}
    for suggestion in suggestions:
        if not suggestion.would_update:
            continue
        listing = by_id[suggestion.listing_id]
        listing.price_uf = _decimal_or_none(suggestion.suggested_price_uf)
        listing.price_currency = suggestion.suggested_price_currency
        listing.price_uf_confidence = suggestion.suggested_price_uf_confidence
        listing.price_uf_source = suggestion.suggested_price_uf_source
        listing.price_recovery_method = suggestion.suggested_price_recovery_method
        metadata = dict(_metadata(listing))
        metadata["price_provenance_version"] = PRICE_RECOVERY_VERSION
        metadata["price_uf_source"] = suggestion.suggested_price_uf_source
        metadata["price_uf_confidence"] = suggestion.suggested_price_uf_confidence
        metadata["price_recovery_method"] = suggestion.suggested_price_recovery_method
        metadata["price_recovery_note"] = suggestion.recovery_note
        metadata["price_recovery_rate"] = suggestion.recovery_rate
        metadata["price_recovered_at"] = datetime.now(UTC).isoformat()
        listing.raw_metadata = metadata


def build_report(
    suggestions: list[PriceProvenanceSuggestion],
    *,
    apply: bool,
    examples: int,
) -> dict[str, Any]:
    updates = [item for item in suggestions if item.would_update]
    by_source = Counter(item.suggested_price_uf_source for item in suggestions)
    updates_by_source = Counter(item.suggested_price_uf_source for item in updates)
    by_confidence = Counter(str(item.suggested_price_uf_confidence or "not_applicable") for item in suggestions)
    recoverable = [
        item for item in suggestions
        if item.suggested_price_uf_source in {"recovered_exact", "recovered_high_confidence"}
    ]
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "apply" if apply else "dry-run",
        "price_recovery_version": PRICE_RECOVERY_VERSION,
        "total_suggestions": len(suggestions),
        "rows_with_changes": len(updates),
        "recoverable_exact_or_high_confidence": len(recoverable),
        "distribution_by_source": dict(sorted(by_source.items())),
        "updates_by_source": dict(sorted(updates_by_source.items())),
        "distribution_by_confidence": dict(sorted(by_confidence.items())),
        "examples_by_source": {
            source: [asdict(item) for item in _examples(suggestions, source, examples)]
            for source in sorted(PRICE_UF_SOURCES)
            if any(item.suggested_price_uf_source == source for item in suggestions)
        },
        "changed_examples": [asdict(item) for item in updates[:examples]],
    }


def write_report(report: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = "apply" if report["mode"] == "apply" else "dry_run"
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"price_provenance_{suffix}_{timestamp}.json"
    md_path = output_dir / f"price_provenance_{suffix}_{timestamp}.md"
    latest_json = output_dir / f"price_provenance_latest_{suffix}.json"
    latest_md = output_dir / f"price_provenance_latest_{suffix}.md"
    json_text = json.dumps(report, ensure_ascii=False, indent=2)
    md_text = markdown_report(report)
    for path in (json_path, latest_json):
        path.write_text(json_text, encoding="utf-8")
    for path in (md_path, latest_md):
        path.write_text(md_text, encoding="utf-8")


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Price Provenance Backfill",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Mode: `{report['mode']}`",
        f"- Version: `{report['price_recovery_version']}`",
        f"- Total suggestions: {report['total_suggestions']}",
        f"- Rows with changes: {report['rows_with_changes']}",
        f"- Recoverable exact/high confidence: {report['recoverable_exact_or_high_confidence']}",
        "",
        "## Distribution By Source",
        "",
        "| Source | Count |",
        "|---|---:|",
    ]
    for key, value in report["distribution_by_source"].items():
        lines.append(f"| {key} | {value} |")
    lines.extend(["", "## Updates By Source", "", "| Source | Count |", "|---|---:|"])
    for key, value in report["updates_by_source"].items():
        lines.append(f"| {key} | {value} |")
    lines.extend(["", "## Examples", ""])
    for source, items in report["examples_by_source"].items():
        lines.extend([f"### {source}", "", "| ID | External | Comuna | UF | Method | Note |", "|---:|---|---|---:|---|---|"])
        for item in items:
            note = str(item["recovery_note"]).replace("|", "/")[:120]
            lines.append(
                f"| {item['listing_id']} | {item['external_id']} | {item['comuna']} | "
                f"{item['suggested_price_uf'] or ''} | {item['suggested_price_recovery_method']} | {note} |"
            )
        lines.append("")
    return "\n".join(lines)


def print_summary(report: dict[str, Any]) -> None:
    print(f"mode\t{report['mode']}")
    print(f"total_suggestions\t{report['total_suggestions']}")
    print(f"rows_with_changes\t{report['rows_with_changes']}")
    print(f"recoverable_exact_or_high_confidence\t{report['recoverable_exact_or_high_confidence']}")
    print("distribution_by_source")
    for key, value in report["distribution_by_source"].items():
        print(f"{key}\t{value}")
    print("updates_by_source")
    for key, value in report["updates_by_source"].items():
        print(f"{key}\t{value}")


def _examples(
    suggestions: list[PriceProvenanceSuggestion],
    source: str,
    limit: int,
) -> list[PriceProvenanceSuggestion]:
    return [item for item in suggestions if item.suggested_price_uf_source == source][:limit]


def _metadata(listing: ListingORM) -> dict[str, Any]:
    return listing.raw_metadata if isinstance(listing.raw_metadata, dict) else {}


def _currency(metadata: dict[str, Any]) -> str | None:
    value = metadata.get("currency_original") or metadata.get("currency") or metadata.get("price_currency")
    return str(value).upper() if value else None


def _scraped_date(listing: ListingORM) -> str:
    value = listing.scraped_at
    return value.date().isoformat() if hasattr(value, "date") else str(value)[:10]


def _datetime_iso(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _parse_human_number(value: str) -> Decimal | None:
    normalized = value.strip()
    if "," in normalized:
        normalized = normalized.replace(".", "").replace(",", ".")
    else:
        parts = normalized.split(".")
        if len(parts) > 1 and all(len(part) == 3 for part in parts[1:]):
            normalized = "".join(parts)
    return _decimal_or_none(normalized)


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _quantize_rate(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _plausible_rate(value: Decimal) -> bool:
    return MIN_PLAUSIBLE_UF_RATE <= value <= MAX_PLAUSIBLE_UF_RATE


def _rate_for(listing: ListingORM, price_uf: Decimal) -> Decimal | None:
    price_clp = _decimal_or_none(listing.price_clp)
    if price_clp is None or price_uf <= 0:
        return None
    return _quantize_rate(price_clp / price_uf)


def _money_str(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _rate_str(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
