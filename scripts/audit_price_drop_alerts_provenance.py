"""Audit existing price_drop alerts against canonical PriceHistory provenance."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.models import AlertORM, ListingORM, PriceHistoryORM  # noqa: E402
from services.alerts import detect_price_drops  # noqa: E402


@dataclass(frozen=True)
class AlertAuditRow:
    alert_id: int
    listing_id: int
    created_at: str
    previous_price_clp: int | None
    new_price_clp: int | None
    price_currency: str | None
    canonical_match: bool
    artifact_suspected: bool
    reason: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit price_drop alerts against provenance.")
    parser.add_argument("--threshold-pct", type=float, default=5.0)
    parser.add_argument("--lookback-days", type=int, default=3650)
    parser.add_argument("--examples", type=int, default=50)
    parser.add_argument("--output-dir", default="reports/alerts_provenance")
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    async with get_session_factory()() as session:
        canonical_drops = await detect_price_drops(
            session,
            threshold_pct=args.threshold_pct,
            lookback_days=args.lookback_days,
        )
        canonical_keys = {
            (
                int(drop["listing_id"]),
                _payload_int(drop.get("previous_price_clp")),
                _payload_int(drop.get("new_price_clp")),
            )
            for drop in canonical_drops
        }
        rows = (
            await session.execute(
                select(AlertORM, ListingORM)
                .join(ListingORM, AlertORM.listing_id == ListingORM.id)
                .where(AlertORM.alert_type == "price_drop")
                .order_by(AlertORM.id.asc())
            )
        ).all()
        artifact_previous_prices = await _artifact_previous_prices(session)
        audit_rows = [
            _audit_alert(alert, listing, canonical_keys, artifact_previous_prices)
            for alert, listing in rows
        ]
        report = _build_report(audit_rows, canonical_count=len(canonical_drops), examples=args.examples)
        _write_report(report, Path(args.output_dir))
        print(json.dumps({k: report[k] for k in (
            "total_price_drop_alerts",
            "canonical_price_drop_events",
            "invalid_alerts",
            "artifact_suspected_alerts",
        )}, ensure_ascii=False, indent=2))
    return 0


async def _artifact_previous_prices(session) -> dict[int, set[int]]:
    rows = (
        await session.execute(
            select(PriceHistoryORM.listing_id, PriceHistoryORM.price_clp)
            .where(PriceHistoryORM.is_artifact.is_(True))
        )
    ).all()
    result: dict[int, set[int]] = {}
    for listing_id, price_clp in rows:
        result.setdefault(int(listing_id), set()).add(int(Decimal(str(price_clp))))
    return result


def _audit_alert(
    alert: AlertORM,
    listing: ListingORM,
    canonical_keys: set[tuple[int, int | None, int | None]],
    artifact_previous_prices: dict[int, set[int]],
) -> AlertAuditRow:
    payload = alert.payload if isinstance(alert.payload, dict) else {}
    previous_clp = _payload_int(payload.get("previous_price_clp"))
    new_clp = _payload_int(payload.get("new_price_clp"))
    key = (int(alert.listing_id), previous_clp, new_clp)
    canonical_match = key in canonical_keys
    artifact_suspected = previous_clp in artifact_previous_prices.get(int(alert.listing_id), set())
    if canonical_match:
        reason = "canonical_match"
    elif artifact_suspected:
        reason = "matches_artifact_price_history"
    else:
        reason = "not_found_in_canonical_detection"
    return AlertAuditRow(
        alert_id=int(alert.id),
        listing_id=int(alert.listing_id),
        created_at=_iso(alert.created_at),
        previous_price_clp=previous_clp,
        new_price_clp=new_clp,
        price_currency=listing.price_currency,
        canonical_match=canonical_match,
        artifact_suspected=artifact_suspected,
        reason=reason,
    )


def _build_report(rows: list[AlertAuditRow], *, canonical_count: int, examples: int) -> dict[str, Any]:
    invalid = [row for row in rows if not row.canonical_match]
    artifact = [row for row in rows if row.artifact_suspected]
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total_price_drop_alerts": len(rows),
        "canonical_price_drop_events": canonical_count,
        "invalid_alerts": len(invalid),
        "artifact_suspected_alerts": len(artifact),
        "invalid_examples": [asdict(row) for row in invalid[:examples]],
        "artifact_examples": [asdict(row) for row in artifact[:examples]],
    }


def _write_report(report: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = f"price_drop_alerts_provenance_{stamp}"
    json_payload = json.dumps(report, ensure_ascii=False, indent=2)
    (output_dir / f"{stem}.json").write_text(json_payload, encoding="utf-8")
    (output_dir / "price_drop_alerts_provenance_latest.json").write_text(json_payload, encoding="utf-8")
    md_payload = _markdown(report)
    (output_dir / f"{stem}.md").write_text(md_payload, encoding="utf-8")
    (output_dir / "price_drop_alerts_provenance_latest.md").write_text(md_payload, encoding="utf-8")


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Price Drop Alerts Provenance Audit",
        "",
        f"- Total price_drop alerts: {report['total_price_drop_alerts']}",
        f"- Canonical price_drop events now: {report['canonical_price_drop_events']}",
        f"- Invalid alerts: {report['invalid_alerts']}",
        f"- Artifact suspected alerts: {report['artifact_suspected_alerts']}",
        "",
        "## Invalid Examples",
        "",
        "| alert_id | listing_id | previous_clp | new_clp | reason |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for row in report["invalid_examples"]:
        lines.append(
            f"| {row['alert_id']} | {row['listing_id']} | {row['previous_price_clp']} | "
            f"{row['new_price_clp']} | {row['reason']} |"
        )
    return "\n".join(lines) + "\n"


def _payload_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(Decimal(str(value)))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _iso(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
