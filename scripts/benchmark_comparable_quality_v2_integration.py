"""Read-only post-integration benchmark for CQ v2 guarded challenger."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Any

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from domain.valuation.quality_v2_challenger import QualityV2Config  # noqa: E402
from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.models import UFRateORM  # noqa: E402
from infrastructure.db.repositories.listing_repo import SqlAlchemyListingRepository  # noqa: E402
from scripts.audit_comparable_quality_v2 import run_audit  # noqa: E402

OUTPUT_JSON = "comparable_quality_v2_integration_latest.json"
OUTPUT_MD = "comparable_quality_v2_integration_latest.md"
BASELINE = "baseline"
SHADOW = "robust_weighted_median"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark CQ v2 integration modes.")
    parser.add_argument("--output-dir", default="reports/valuation")
    parser.add_argument("--property-type", default="apartment", choices=["apartment", "house"])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--uf-rate", type=Decimal)
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    start = perf_counter()
    async with get_session_factory()() as session:
        listings = list(await SqlAlchemyListingRepository(session).list_active())
        uf_rate = args.uf_rate or await latest_uf_rate(session)
    if uf_rate is None:
        raise SystemExit("No UF rate provided and no local uf_rates row found. Pass --uf-rate.")
    report = build_report(
        listings=listings,
        uf_rate=uf_rate,
        property_type=args.property_type,
        limit=args.limit,
        runtime_ms=0.0,
    )
    report["summary"]["runtime_ms"] = round((perf_counter() - start) * 1000, 2)
    json_path, md_path = write_outputs(report, Path(args.output_dir))
    print(
        json.dumps(
            {
                "evaluations": report["summary"]["evaluations"],
                "baseline_mape": report["benchmark"]["baseline"]["mape_pct"],
                "shadow_mape": report["benchmark"]["quality_v2_shadow"]["mape_pct"],
                "guarded_mape": report["benchmark"]["quality_v2_guarded"]["mape_pct"],
                "guarded_used_pct": report["benchmark"]["quality_v2_guarded"]["used_pct"],
                "json": str(json_path),
                "markdown": str(md_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def build_report(
    *,
    listings,
    uf_rate: Decimal,
    property_type: str,
    limit: int | None,
    runtime_ms: float,
) -> dict[str, Any]:
    audit = run_audit(
        listings,
        uf_rate=uf_rate,
        property_type=property_type,
        limit=limit,
        case_limit=20,
        runtime_ms=0.0,
    )
    rows = [row for row in audit["rows"] if row["status"] == "ok"]
    guarded = [guarded_outcome(row, QualityV2Config()) for row in rows]
    fallback_counts = Counter(item["fallback_reason"] or "used" for item in guarded)
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "summary": {
            "read_only": True,
            "productive_code_modified": False,
            "property_type": property_type,
            "uf_rate_used": str(uf_rate),
            "evaluations": len(rows),
            "runtime_ms": runtime_ms,
        },
        "implemented": {
            "engine": "comparables_quality_v2 / robust_weighted_median_guarded_v1",
            "default_mode": "off",
            "integration_points": [
                "config/valuation_flags.py",
                "domain/valuation/quality_v2_challenger.py",
                "services/valuation.py",
                "engine_results diagnostics payload",
            ],
            "no_db_writes": True,
            "no_migrations": True,
        },
        "flags": {
            "VALUATION_QUALITY_V2_APPLY_MODE": "off|shadow|guarded",
            "VALUATION_QUALITY_V2_ALLOWED_PROPERTY_TYPES": "apartment",
            "VALUATION_QUALITY_V2_BLOCKED_COMUNAS": "estacion central,la reina,macul",
            "VALUATION_QUALITY_V2_P90_RISK_COMUNAS": "la reina,las condes,maipu,nunoa",
            "VALUATION_QUALITY_V2_MIN_VALID_COMPARABLES": 5,
            "VALUATION_QUALITY_V2_MAX_POOL_DISPERSION": 75,
            "VALUATION_QUALITY_V2_MAX_DELTA_VS_BASELINE_PCT": 0.25,
        },
        "modes": {
            "off": "baseline behavior intact; CQ v2 is not calculated",
            "shadow": "CQ v2 calculated and exposed in engine_results; final estimate remains baseline",
            "guarded": "CQ v2 used only when guardrails pass; otherwise baseline fallback",
        },
        "guardrails": guardrails(),
        "benchmark": {
            "baseline": metric_block([row["variant_results"][BASELINE]["ape_pct"] for row in rows]),
            "quality_v2_shadow": metric_block([row["variant_results"][SHADOW]["ape_pct"] for row in rows]),
            "quality_v2_guarded": guarded_metric_block(guarded),
            "fallback_reasons": dict(fallback_counts),
            "blocked_comunas": blocked_comuna_summary(guarded),
        },
        "risks": [
            "Guarded mode can underuse CQ v2 in blocked/risk cohorts.",
            "High dispersion pools can still be unstable; monitor P90/P95 by comuna.",
            "Consensus mode is a separate flow; CQ v2 integration is in the legacy productive path.",
        ],
        "activation": {
            "shadow": "set VALUATION_QUALITY_V2_APPLY_MODE=shadow",
            "guarded": "set VALUATION_QUALITY_V2_APPLY_MODE=guarded",
            "off": "unset the variable or set VALUATION_QUALITY_V2_APPLY_MODE=off",
        },
        "tests_expected": [
            "ruff modified files",
            "pytest tests/unit/test_comparable_quality_v2.py tests/unit/test_valuation_service.py",
            "json.tool integration report",
        ],
    }
    return json_safe(report)


def guarded_outcome(row: dict[str, Any], config: QualityV2Config) -> dict[str, Any]:
    baseline = row["variant_results"][BASELINE]
    robust = row["variant_results"][SHADOW]
    actual = float(row["actual_clp"])
    reason = None
    estimate = robust["estimate_clp"]
    comuna = str(row["comuna"]).strip().lower().replace("_", " ")
    dispersion = row["baseline_contamination"]["price_m2_iqr_pct"]
    if row["property_type"] not in config.allowed_property_types:
        reason = "property_type_not_allowed"
    elif comuna in config.blocked_comunas:
        reason = "blocked_comuna"
    elif robust["comparable_count"] < config.min_valid_comparables:
        reason = "insufficient_valid_comparables"
    elif dispersion is not None and dispersion > config.max_pool_dispersion:
        reason = "pool_dispersion_too_high"
    else:
        delta = (estimate - baseline["estimate_clp"]) / baseline["estimate_clp"]
        if abs(delta) > config.max_delta_vs_baseline_pct:
            reason = "delta_vs_baseline_too_high"
    used = reason is None
    final_estimate = estimate if used else baseline["estimate_clp"]
    ape = abs(final_estimate - actual) / actual * 100 if actual > 0 else None
    return {
        "listing_id": row["listing_id"],
        "comuna": comuna,
        "used": used,
        "fallback_reason": reason,
        "ape_pct": round(ape, 4) if ape is not None else None,
        "baseline_ape_pct": baseline["ape_pct"],
        "shadow_ape_pct": robust["ape_pct"],
        "pool_dispersion": dispersion,
    }


def metric_block(values: Sequence[float | None]) -> dict[str, Any]:
    clean = [float(value) for value in values if value is not None]
    return {
        "n": len(clean),
        "mape_pct": round(mean(clean), 4) if clean else None,
        "median_ape_pct": rounded_percentile(clean, 50),
        "p90_ape_pct": rounded_percentile(clean, 90),
        "p95_ape_pct": rounded_percentile(clean, 95),
    }


def guarded_metric_block(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    block = metric_block([row["ape_pct"] for row in rows])
    block["used_count"] = sum(row["used"] for row in rows)
    block["fallback_count"] = sum(not row["used"] for row in rows)
    block["used_pct"] = pct(block["used_count"], len(rows))
    return block


def blocked_comuna_summary(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, Counter[str]] = {}
    for row in rows:
        comuna = row["comuna"]
        grouped.setdefault(comuna, Counter())
        grouped[comuna]["total"] += 1
        if row["fallback_reason"] == "blocked_comuna":
            grouped[comuna]["blocked"] += 1
    return [
        {"comuna": comuna, "total": counts["total"], "blocked": counts["blocked"]}
        for comuna, counts in sorted(grouped.items())
        if counts["blocked"]
    ]


def guardrails() -> list[str]:
    return [
        "allowed property_type only",
        "blocked_comunas fallback",
        "min_valid_comparables fallback",
        "max_pool_dispersion fallback",
        "max_delta_vs_baseline_pct fallback",
        "never use subject actual price, subject price_m2, APE/error or benchmark data for estimation",
    ]


def rounded_percentile(values: Sequence[float], pct_value: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return round(ordered[0], 4)
    position = (len(ordered) - 1) * pct_value / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    value = ordered[lower] * (1 - weight) + ordered[upper] * weight
    return round(value, 4)


def pct(numerator: int | float, denominator: int | float) -> float:
    return round(float(numerator) / float(denominator) * 100, 2) if denominator else 0.0


def write_outputs(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / OUTPUT_JSON
    md_path = output_dir / OUTPUT_MD
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(markdown_report(report), encoding="utf-8")
    return json_path, md_path


def markdown_report(report: dict[str, Any]) -> str:
    bench = report["benchmark"]
    lines = [
        "# Comparable Quality v2 Integration",
        "",
        f"Generated at: `{report['generated_at']}`",
        "",
        "## Summary",
        "",
        f"- Engine: `{report['implemented']['engine']}`",
        f"- Default mode: `{report['implemented']['default_mode']}`",
        f"- Evaluations: `{report['summary']['evaluations']}`",
        f"- Baseline MAPE: `{bench['baseline']['mape_pct']}`",
        f"- Shadow CQ v2 MAPE: `{bench['quality_v2_shadow']['mape_pct']}`",
        f"- Guarded CQ v2 MAPE: `{bench['quality_v2_guarded']['mape_pct']}`",
        f"- Guarded used: `{bench['quality_v2_guarded']['used_pct']}%`",
        f"- Fallback reasons: `{bench['fallback_reasons']}`",
        "",
        "## Flags",
        "",
    ]
    for key, value in report["flags"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Modes", ""])
    for key, value in report["modes"].items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Guardrails", ""])
    for item in report["guardrails"]:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## Activation",
            "",
            f"- Shadow: `{report['activation']['shadow']}`",
            f"- Guarded: `{report['activation']['guarded']}`",
            f"- Off: `{report['activation']['off']}`",
            "",
            "## Risks",
            "",
        ]
    )
    for item in report["risks"]:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## Productive Safety",
            "",
            "Feature flag defaults to off. No DB writes, migrations, Radar/frontend changes, scrapers, external geocoding or productive default behavior changes were made.",
            "",
        ]
    )
    return "\n".join(lines)


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, Decimal):
        return float(value)
    return value


async def latest_uf_rate(session) -> Decimal | None:
    result = await session.execute(select(UFRateORM).order_by(UFRateORM.date.desc()).limit(1))
    row = result.scalar_one_or_none()
    return Decimal(row.value_clp) if row is not None else None


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
