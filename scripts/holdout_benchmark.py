"""Permanent holdout benchmark for AVM-v2.

This benchmark separates:
- internal LOO: training listings valued against the training pool, excluding self
- holdout: permanent holdout listings valued only against the training pool

The holdout IDs are persisted and reused to avoid moving the goalposts.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from statistics import mean
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.entities.listing import Listing  # noqa: E402
from core.normalization.property_type import normalize_property_type  # noqa: E402
from domain.geocoding.quality import apply_geocoding_guardrails  # noqa: E402
from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.repositories.listing_repo import SqlAlchemyListingRepository  # noqa: E402
from scripts.evaluation_benchmark import EvaluationRow, _deduplicate_eval_targets, _evaluate_listing  # noqa: E402

DEFAULT_OUTPUT_DIR = Path("reports/benchmark")
DEFAULT_HOLDOUT_PATH = DEFAULT_OUTPUT_DIR / "holdout_ids.json"
DEFAULT_HOLDOUT_FRACTION = 0.20
DEFAULT_MIN_SEGMENT_SIZE = 10
DEFAULT_MIN_SAMPLES = 5
DEFAULT_SEED = 42


async def main() -> int:
    args = _parse_args()
    listings = await _load_active_listings(limit=args.limit)
    report = run_holdout_benchmark(
        listings,
        holdout_path=Path(args.holdout_path),
        output_dir=Path(args.output_dir),
        holdout_fraction=args.holdout_fraction,
        min_segment_size=args.min_segment_size,
        min_samples=args.min_samples,
        seed=args.seed,
        force_regenerate=args.force_regenerate,
        uf_to_clp=Decimal(str(args.uf_to_clp)),
    )
    md_path, json_path = write_holdout_report(report, output_dir=Path(args.output_dir))
    print("== AVM Holdout Benchmark ==")
    print(f"status\t{report['summary']['status']}")
    print(f"training_listings\t{report['summary']['training_listings']}")
    print(f"holdout_listings\t{report['summary']['holdout_listings']}")
    print(f"internal_loo_mape_pct\t{(report['internal_loo']['metrics'] or {}).get('mape_pct')}")
    print(f"holdout_mape_pct\t{(report['holdout']['metrics'] or {}).get('mape_pct')}")
    print(f"markdown\t{md_path}")
    print(f"json\t{json_path}")
    return 0 if report["summary"]["status"] != "insufficient_data" else 2


def run_holdout_benchmark(
    listings: Sequence[Listing],
    *,
    holdout_path: Path = DEFAULT_HOLDOUT_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    holdout_fraction: float = DEFAULT_HOLDOUT_FRACTION,
    min_segment_size: int = DEFAULT_MIN_SEGMENT_SIZE,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    seed: int = DEFAULT_SEED,
    force_regenerate: bool = False,
    uf_to_clp: Decimal | None = None,
) -> dict[str, Any]:
    if uf_to_clp is None:
        raise ValueError("uf_to_clp real requerido; no hay fallback UF operativo")
    active = _active_unique(listings)
    if force_regenerate or not holdout_path.exists():
        holdout = generate_stratified_holdout(
            active,
            fraction=holdout_fraction,
            min_segment_size=min_segment_size,
            seed=seed,
        )
        save_holdout(holdout, holdout_path=holdout_path, output_dir=output_dir)
    else:
        holdout = load_holdout(holdout_path)

    active_ids = {_listing_id(listing) for listing in active}
    holdout_ids = {int(item) for item in holdout["listing_ids"] if int(item) in active_ids}
    training = [listing for listing in active if _listing_id(listing) not in holdout_ids]
    holdout_targets = [listing for listing in active if _listing_id(listing) in holdout_ids]

    internal_rows = evaluate_internal_loo(training, uf_to_clp=uf_to_clp)
    holdout_rows = evaluate_holdout(holdout_targets, training, uf_to_clp=uf_to_clp)
    internal = summarize_rows(internal_rows, all_targets=training, min_samples=min_samples, uf_to_clp=uf_to_clp)
    holdout_summary = summarize_rows(holdout_rows, all_targets=holdout_targets, min_samples=min_samples, uf_to_clp=uf_to_clp)

    status = "ok" if holdout_summary["status"] == "ok" else "insufficient_data"
    return {
        "summary": {
            "status": status,
            "generated_at": datetime.now(UTC).isoformat(),
            "holdout_path": str(holdout_path),
            "total_active_listings": len(active),
            "training_listings": len(training),
            "holdout_listings": len(holdout_targets),
            "configured_holdout_ids": len(holdout["listing_ids"]),
            "stale_holdout_ids_not_active": len(set(int(item) for item in holdout["listing_ids"]) - active_ids),
            "min_samples": min_samples,
            "note": (
                "Holdout listings are excluded from the comparable pool. "
                "Internal LOO is reported only as a reference and remains less strict."
            ),
        },
        "holdout_definition": holdout,
        "internal_loo": internal,
        "holdout": holdout_summary,
        "rows": {
            "internal_loo": [asdict(row) for row in internal_rows],
            "holdout": [asdict(row) for row in holdout_rows],
        },
    }


def generate_stratified_holdout(
    listings: Sequence[Listing],
    *,
    fraction: float = DEFAULT_HOLDOUT_FRACTION,
    min_segment_size: int = DEFAULT_MIN_SEGMENT_SIZE,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    if not 0 < fraction < 1:
        raise ValueError("holdout fraction must be between 0 and 1")
    by_segment: dict[tuple[str, str], list[Listing]] = defaultdict(list)
    for listing in listings:
        if listing.id is None:
            continue
        by_segment[(listing.comuna, normalize_property_type(listing.property_type))].append(listing)

    rng = random.Random(seed)
    holdout_ids: list[int] = []
    strata: list[dict[str, Any]] = []
    for (comuna, property_type), rows in sorted(by_segment.items()):
        rows = sorted(rows, key=lambda listing: int(listing.id or 0))
        if len(rows) < min_segment_size:
            strata.append(
                {
                    "comuna": comuna,
                    "property_type": property_type,
                    "active_count": len(rows),
                    "holdout_count": 0,
                    "status": "insufficient_segment_size",
                }
            )
            continue
        sample_count = max(1, round(len(rows) * fraction))
        selected = sorted(rng.sample(rows, sample_count), key=lambda listing: int(listing.id or 0))
        selected_ids = [int(listing.id) for listing in selected if listing.id is not None]
        holdout_ids.extend(selected_ids)
        strata.append(
            {
                "comuna": comuna,
                "property_type": property_type,
                "active_count": len(rows),
                "holdout_count": len(selected_ids),
                "status": "ok",
            }
        )

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "seed": seed,
        "fraction": fraction,
        "min_segment_size": min_segment_size,
        "listing_ids": sorted(holdout_ids),
        "strata": strata,
    }


def evaluate_internal_loo(training: Sequence[Listing], *, uf_to_clp: Decimal) -> list[EvaluationRow]:
    return [_evaluate_listing(target, training, uf_to_clp=uf_to_clp) for target in training]


def evaluate_holdout(
    holdout_targets: Sequence[Listing],
    training_pool: Sequence[Listing],
    *,
    uf_to_clp: Decimal,
) -> list[EvaluationRow]:
    training_ids = {_listing_id(listing) for listing in training_pool}
    holdout_ids = {_listing_id(listing) for listing in holdout_targets}
    overlap = training_ids & holdout_ids
    if overlap:
        raise ValueError(f"holdout leakage into training pool: {sorted(overlap)[:10]}")
    return [_evaluate_listing(target, training_pool, uf_to_clp=uf_to_clp) for target in holdout_targets]


def summarize_rows(
    rows: Sequence[EvaluationRow],
    *,
    all_targets: Sequence[Listing],
    min_samples: int,
    uf_to_clp: Decimal,
) -> dict[str, Any]:
    successful = [row for row in rows if row.status == "ok"]
    status = "ok" if len(successful) >= min_samples else "insufficient_data"
    return {
        "status": status,
        "n_targets": len(rows),
        "n_evaluated": len(successful),
        "coverage_pct": _pct(len(successful), len(rows)),
        "insufficient_data_rate_pct": _pct(sum(row.status != "ok" for row in rows), len(rows)),
        "metrics": _metrics(successful, uf_to_clp=uf_to_clp) if status == "ok" else None,
        "skip_reasons": dict(Counter(row.reason or row.status for row in rows if row.status != "ok")),
        "by_comuna": _segment_metrics(rows, all_targets, lambda row: row.comuna, lambda listing: listing.comuna, min_samples, uf_to_clp),
        "by_property_type": _segment_metrics(
            rows,
            all_targets,
            lambda row: row.property_type,
            lambda listing: normalize_property_type(listing.property_type),
            min_samples,
            uf_to_clp,
        ),
        "by_comuna_property_type": _segment_metrics(
            rows,
            all_targets,
            lambda row: f"{row.comuna}|{row.property_type}",
            lambda listing: f"{listing.comuna}|{normalize_property_type(listing.property_type)}",
            min_samples,
            uf_to_clp,
        ),
    }


def training_pool_for_holdout(listings: Sequence[Listing], holdout_ids: set[int]) -> list[Listing]:
    return [listing for listing in listings if listing.id is not None and int(listing.id) not in holdout_ids]


def save_holdout(holdout: dict[str, Any], *, holdout_path: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    holdout_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(holdout, ensure_ascii=False, indent=2)
    holdout_path.write_text(payload, encoding="utf-8")


def load_holdout(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_holdout_report(report: dict[str, Any], *, output_dir: Path = DEFAULT_OUTPUT_DIR) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "holdout_report.json"
    md_path = output_dir / "holdout_report.md"
    json_path.write_text(json.dumps(_json_safe(report), ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_markdown_report(report), encoding="utf-8")
    return md_path, json_path


def _active_unique(listings: Sequence[Listing]) -> list[Listing]:
    active = apply_geocoding_guardrails([listing for listing in listings if listing.is_active and listing.id is not None])
    return _deduplicate_eval_targets(active)


def _segment_metrics(
    rows: Sequence[EvaluationRow],
    all_targets: Sequence[Listing],
    row_key,
    target_key,
    min_samples: int,
    uf_to_clp: Decimal,
) -> dict[str, Any]:
    grouped_rows: dict[str, list[EvaluationRow]] = defaultdict(list)
    grouped_targets: Counter[str] = Counter()
    for row in rows:
        grouped_rows[str(row_key(row) or "unknown")].append(row)
    for listing in all_targets:
        grouped_targets[str(target_key(listing) or "unknown")] += 1

    keys = sorted(set(grouped_rows) | set(grouped_targets))
    result = {}
    for key in keys:
        segment_rows = grouped_rows.get(key, [])
        successful = [row for row in segment_rows if row.status == "ok"]
        status = "ok" if len(successful) >= min_samples else "insufficient"
        result[key] = {
            "status": status,
            "n_targets": grouped_targets.get(key, len(segment_rows)),
            "n_evaluated": len(successful),
            "coverage_pct": _pct(len(successful), len(segment_rows)),
            "insufficient_data_rate_pct": _pct(sum(row.status != "ok" for row in segment_rows), len(segment_rows)),
            **(_metrics(successful, uf_to_clp=uf_to_clp) if status == "ok" else _empty_metrics()),
        }
    return result


def _metrics(rows: Sequence[EvaluationRow], *, uf_to_clp: Decimal) -> dict[str, Any]:
    abs_pct = [float(row.absolute_percentage_error) for row in rows if row.absolute_percentage_error is not None]
    abs_clp = [float(row.absolute_error_clp) for row in rows if row.absolute_error_clp is not None]
    return {
        "mae_clp": _round(mean(abs_clp)) if abs_clp else None,
        "mae_uf": _round(mean(abs_clp) / float(uf_to_clp)) if abs_clp else None,
        "mape_pct": _round(mean(abs_pct) * 100) if abs_pct else None,
        "median_ape_pct": _round(_percentile(abs_pct, 50) * 100) if abs_pct else None,
    }


def _empty_metrics() -> dict[str, None]:
    return {"mae_clp": None, "mae_uf": None, "mape_pct": None, "median_ape_pct": None}


def _listing_id(listing: Listing) -> int:
    if listing.id is None:
        raise ValueError("benchmark listing requires persisted id")
    return int(listing.id)


def _pct(part: int | float, total: int | float) -> float:
    if not total:
        return 0.0
    return round(float(part) / float(total) * 100, 2)


def _round(value: float, digits: int = 2) -> float:
    return round(float(value), digits)


def _percentile(values: Sequence[float], percentile: int) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _markdown_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    internal_metrics = report["internal_loo"]["metrics"] or {}
    holdout_metrics = report["holdout"]["metrics"] or {}
    lines = [
        "# AVM Permanent Holdout Benchmark",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Status: `{summary['status']}`",
        f"- Training listings: {summary['training_listings']}",
        f"- Holdout listings: {summary['holdout_listings']}",
        f"- Stale holdout ids not active: {summary['stale_holdout_ids_not_active']}",
        f"- Internal LOO MAPE: {internal_metrics.get('mape_pct')}",
        f"- Holdout MAPE: {holdout_metrics.get('mape_pct')}",
        f"- Internal LOO MAE CLP: {internal_metrics.get('mae_clp')}",
        f"- Holdout MAE CLP: {holdout_metrics.get('mae_clp')}",
        "",
        "## Interpretation",
        "",
        summary["note"],
        "",
        "## Holdout By Property Type",
        "",
        _markdown_table(_dict_rows(report["holdout"]["by_property_type"], "property_type")),
        "",
        "## Holdout By Comuna + Property Type",
        "",
        _markdown_table(_dict_rows(report["holdout"]["by_comuna_property_type"], "segment")),
        "",
        "## Internal LOO By Property Type",
        "",
        _markdown_table(_dict_rows(report["internal_loo"]["by_property_type"], "property_type")),
    ]
    return "\n".join(lines) + "\n"


def _dict_rows(values: dict[str, Any], key_name: str) -> list[dict[str, Any]]:
    rows = []
    for key, value in values.items():
        row = {key_name: key}
        row.update(value)
        rows.append(row)
    return rows


def _markdown_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "_No data._"
    columns = list(rows[0])
    lines = ["| " + " | ".join(columns) + " |", "|" + "|".join("---" for _ in columns) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(column)) for column in columns) + " |")
    return "\n".join(lines)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


async def _load_active_listings(limit: int | None) -> list[Listing]:
    async with get_session_factory()() as session:
        repo = SqlAlchemyListingRepository(session)
        return list(await repo.list_active(limit=limit))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run permanent holdout benchmark.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--holdout-path", default=str(DEFAULT_HOLDOUT_PATH))
    parser.add_argument("--holdout-fraction", type=float, default=DEFAULT_HOLDOUT_FRACTION)
    parser.add_argument("--min-segment-size", type=int, default=DEFAULT_MIN_SEGMENT_SIZE)
    parser.add_argument("--min-samples", type=int, default=DEFAULT_MIN_SAMPLES)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--uf-to-clp", type=float, required=True)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--force-regenerate", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
