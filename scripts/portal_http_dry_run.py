"""Bounded HTTP-only validation runner for Portal Inmobiliario.

It discovers RM listings, fetches a small, diverse sample of detail pages and
writes an aggregate sanitized report. It never imports persistence, pipeline,
Yapo, or scheduler code.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.comunas import is_known_comuna, normalize_comuna  # noqa: E402
from config.portal_targets import PORTAL_TARGETS, PortalTarget  # noqa: E402
from infrastructure.scrapers.base import RateLimiter  # noqa: E402
from infrastructure.scrapers.portalinmobiliario import (  # noqa: E402
    PortalInmobiliarioScraper,
    apply_portal_uf_conversion,
    build_portal_page_url,
    classify_portal_detail_page_state,
    classify_portal_page_state,
    parse_listing_detail_portal,
    portal_dedupe_key,
    validate_portal_rm_location,
)
from scripts.portal_smoke import DEFAULT_HEADERS  # noqa: E402

DEFAULT_REPORT_PATH = ROOT / "reports" / "portal_http_dry_run_latest.json"
MAX_DETAILS_HARD_LIMIT = 50
MAX_PAGES_HARD_LIMIT = 2
FIELD_COVERAGE = (
    "external_id", "canonical_url", "title", "price_uf", "price_clp",
    "usable_area_m2", "built_area_m2", "total_area_m2", "land_area_m2",
    "bedrooms", "bathrooms", "parking", "common_expenses_clp", "description",
    "comuna", "location", "seller",
)


@dataclass(frozen=True)
class Candidate:
    target: PortalTarget
    url: str
    external_id: str | None


@dataclass(frozen=True)
class PortalDryRunResult:
    report: dict[str, Any]
    accepted: tuple[dict[str, Any], ...]


def build_portal_target_url(target: PortalTarget) -> str:
    """Build a scoped RM result URL from a configurable target."""
    if not is_known_comuna(target["comuna"]):
        raise ValueError(f"Portal target comuna is not in the canonical RM catalogue: {target['comuna']}")
    property_path = "departamento" if target["property_type"] == "apartment" else "casa"
    comuna_path = normalize_comuna(target["comuna"]).replace("_", "-") + "-metropolitana"
    base = target["base_url"].rstrip("/") + "/"
    return urljoin(base, f"{target['operation']}/{property_path}/{comuna_path}")


def _canonical_url(url: str, base_url: str) -> str:
    absolute = urljoin(base_url, url)
    parts = urlsplit(absolute)
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def _seller_type(seller: str | None, target: PortalTarget) -> str:
    value = (seller or "").lower()
    if any(token in value for token in ("particular", "dueño", "dueno")):
        return "particular"
    if any(token in value for token in ("inmobiliaria", "propiedades", "corredor", "real estate")):
        return "professional"
    if target["property_type"] == "apartment" and "proyecto" in value:
        return "project"
    return "unknown"


def _safe_counter(counter: Counter[str]) -> dict[str, int]:
    return dict(sorted(counter.items()))


class PortalHttpDryRun:
    """Small, testable HTTP validation run with no persistence side effects."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        targets: Iterable[PortalTarget] = PORTAL_TARGETS,
        max_pages_per_target: int = 1,
        max_details: int = 20,
        pause_s: float = 1.0,
        uf_to_clp: Decimal | None = None,
    ) -> None:
        self._client = client
        self._targets = tuple(target for target in targets if target["enabled"])
        self._max_pages = max(1, min(int(max_pages_per_target), MAX_PAGES_HARD_LIMIT))
        self._max_details = max(1, min(int(max_details), MAX_DETAILS_HARD_LIMIT))
        self._rate = RateLimiter(pause_s)
        self._uf_to_clp = uf_to_clp

    async def run(self) -> dict[str, Any]:
        return (await self.run_with_records()).report

    async def run_with_records(self) -> PortalDryRunResult:
        metrics: dict[str, Any] = {
            "pages_requested": 0,
            "pages_failed": 0,
            "cards_detected": 0,
            "publications_unique": 0,
            "duplicates": 0,
            "details_ok": 0,
            "details_failed": 0,
            "details_requested": 0,
            "blocks": 0,
            "outside_rm": 0,
            "unknown_comuna": 0,
            "discovery_discards": Counter(),
            "block_reasons": Counter(),
            "block_events": [],
        }
        candidates: dict[str, list[Candidate]] = defaultdict(list)
        seen: set[str] = set()
        stopped_reason: str | None = None

        # Page-major order gives a capped run geographic breadth before depth.
        for page in range(1, self._max_pages + 1):
            for target in self._targets:
                if page > min(int(target["max_pages"]), self._max_pages):
                    continue
                url = build_portal_page_url(build_portal_target_url(target), page)
                await self._rate.wait()
                try:
                    response = await self._client.get(url)
                except httpx.HTTPError as exc:
                    metrics["pages_failed"] += 1
                    metrics["block_reasons"][f"http_error:{type(exc).__name__}"] += 1
                    continue
                metrics["pages_requested"] += 1
                page_state = classify_portal_page_state(response.text, status_code=response.status_code)
                if response.status_code != 200 or page_state not in {"authenticated"}:
                    metrics["blocks"] += 1
                    reason = f"http_{response.status_code}" if response.status_code in {403, 429} else page_state
                    metrics["block_reasons"][reason] += 1
                    metrics["block_events"].append({
                        "stage": "discovery",
                        "reason": reason,
                        "http_status": response.status_code,
                        "url": _canonical_url(url, url),
                    })
                    stopped_reason = reason
                    break
                parsed = PortalInmobiliarioScraper.parse_listings_detailed(response.text, uf_to_clp=self._uf_to_clp)
                metrics["cards_detected"] += parsed["cards_detected"]
                for discarded in parsed["discarded"]:
                    reason = discarded["reason"]
                    metrics["discovery_discards"][reason] += 1
                    if reason in {"missing_comuna", "unknown_comuna"}:
                        metrics["unknown_comuna"] += 1
                for item in parsed["items"]:
                    comuna = str(item.get("comuna") or "")
                    if not is_known_comuna(comuna):
                        metrics["unknown_comuna"] += 1
                        continue
                    detail_url = _canonical_url(str(item.get("url") or ""), str(response.url))
                    key = portal_dedupe_key(
                        source=str(item.get("source") or "portalinmobiliario"),
                        external_id=item.get("external_id"),
                        url=detail_url,
                    )
                    if not key:
                        metrics["discovery_discards"]["missing_dedupe_key"] += 1
                        continue
                    if key in seen:
                        metrics["duplicates"] += 1
                        continue
                    seen.add(key)
                    candidates[target["label"]].append(Candidate(target, detail_url, item.get("external_id")))
            if stopped_reason:
                break

        metrics["publications_unique"] = len(seen)
        accepted: list[dict[str, Any]] = []
        rejections: list[dict[str, str | None]] = []
        failures: Counter[str] = Counter()
        for candidate in _round_robin_candidates(candidates, self._max_details):
            await self._rate.wait()
            metrics["details_requested"] += 1
            try:
                response = await self._client.get(candidate.url)
            except httpx.HTTPError as exc:
                metrics["details_failed"] += 1
                failures[f"http_error:{type(exc).__name__}"] += 1
                continue
            state = classify_portal_detail_page_state(response.text, status_code=response.status_code)
            if response.status_code != 200 or state != "detail":
                metrics["details_failed"] += 1
                failures[f"detail_{state}" if response.status_code == 200 else f"http_{response.status_code}"] += 1
                if response.status_code in {403, 429} or state in {"captcha_visible", "verification_visible"}:
                    metrics["blocks"] += 1
                    reason = f"http_{response.status_code}" if response.status_code in {403, 429} else f"detail_{state}"
                    metrics["block_reasons"][reason] += 1
                    metrics["block_events"].append({
                        "stage": "detail",
                        "reason": reason,
                        "http_status": response.status_code,
                        "external_id": candidate.external_id,
                        "url": _canonical_url(candidate.url, candidate.url),
                    })
                    stopped_reason = reason
                    break
                continue
            detail = parse_listing_detail_portal(response.text, str(response.url))
            apply_portal_uf_conversion(detail, uf_to_clp=self._uf_to_clp)
            geography = validate_portal_rm_location(detail)
            if geography != "accepted_rm":
                metrics["details_failed"] += 1
                metrics["outside_rm" if geography == "outside_rm" else "unknown_comuna"] += 1
                failures[geography] += 1
                rejections.append({
                    "reason": geography,
                    "external_id": detail.get("external_id") or candidate.external_id,
                    "canonical_url": detail.get("canonical_url") or _canonical_url(candidate.url, candidate.url),
                })
                continue
            if not all(detail.get(field) for field in ("external_id", "canonical_url", "title")):
                metrics["details_failed"] += 1
                failures["missing_identity"] += 1
                rejections.append({
                    "reason": "missing_identity",
                    "external_id": detail.get("external_id") or candidate.external_id,
                    "canonical_url": detail.get("canonical_url") or _canonical_url(candidate.url, candidate.url),
                })
                continue
            if detail.get("price_uf") is None and detail.get("price_clp") is None:
                metrics["details_failed"] += 1
                failures["missing_price"] += 1
                rejections.append({
                    "reason": "missing_price",
                    "external_id": detail.get("external_id") or candidate.external_id,
                    "canonical_url": detail.get("canonical_url") or _canonical_url(candidate.url, candidate.url),
                })
                continue
            metrics["details_ok"] += 1
            accepted.append({"target": candidate.target, "detail": detail})

        report = _build_report(metrics, accepted, rejections, failures, stopped_reason)
        return PortalDryRunResult(report=report, accepted=tuple(accepted))


def _round_robin_candidates(groups: dict[str, list[Candidate]], limit: int) -> list[Candidate]:
    selected: list[Candidate] = []
    pending = [list(values) for _, values in sorted(groups.items())]
    while pending and len(selected) < limit:
        next_pending: list[list[Candidate]] = []
        for group in pending:
            if len(selected) >= limit:
                break
            selected.append(group.pop(0))
            if group:
                next_pending.append(group)
        pending = next_pending
    return selected


def _build_report(
    metrics: dict[str, Any],
    accepted: list[dict[str, Any]],
    rejections: list[dict[str, str | None]],
    failures: Counter[str],
    stopped_reason: str | None,
) -> dict[str, Any]:
    coverage = {field: sum(1 for row in accepted if row["detail"].get(field) not in (None, "", [])) for field in FIELD_COVERAGE}
    by_comuna: Counter[str] = Counter()
    by_seller: Counter[str] = Counter()
    by_property: Counter[str] = Counter()
    by_operation: Counter[str] = Counter()
    by_currency: Counter[str] = Counter()
    samples: list[dict[str, Any]] = []
    for row in accepted:
        target, detail = row["target"], row["detail"]
        by_comuna[str(detail.get("comuna"))] += 1
        by_seller[_seller_type(detail.get("seller"), target)] += 1
        by_property[target["property_type"]] += 1
        by_operation[target["operation"]] += 1
        by_currency[str(detail.get("currency_original") or "unknown")] += 1
        # Keep public identifiers only; descriptions and precise locations do not belong in reports.
        samples.append({
            "external_id": detail.get("external_id"), "canonical_url": detail.get("canonical_url"),
            "comuna": detail.get("comuna"), "property_type": target["property_type"],
            "operation": target["operation"], "seller_type": _seller_type(detail.get("seller"), target),
            "currency_original": detail.get("currency_original"), "price_uf": detail.get("price_uf"),
            "price_clp_published": detail.get("price_clp_published"),
            "price_clp_displayed": detail.get("price_clp_displayed"),
            "price_clp_derived": detail.get("price_clp_derived"), "uf_rate_used": detail.get("uf_rate_used"),
        })
    return {
        "source": "portalinmobiliario", "mode": "http_dry_run", "persisted": False,
        "generated_at": datetime.now(timezone.utc).isoformat(), "stopped_reason": stopped_reason,
        "accepted_all_in_canonical_rm": all(is_known_comuna(str(row["detail"].get("comuna") or "")) for row in accepted),
        "metrics": {
            **{key: value for key, value in metrics.items() if not isinstance(value, Counter)},
            "discovery_discards": _safe_counter(metrics["discovery_discards"]),
            "block_reasons": _safe_counter(metrics["block_reasons"]),
            "block_events": list(metrics["block_events"]),
            "detail_failures": _safe_counter(failures),
            "field_coverage": {field: {"present": count, "total": len(accepted)} for field, count in coverage.items()},
            "by_comuna": _safe_counter(by_comuna), "by_seller_type": _safe_counter(by_seller),
            "by_property_type": _safe_counter(by_property), "by_operation": _safe_counter(by_operation),
            "by_currency_original": _safe_counter(by_currency),
        },
        "samples": samples,
        "rejections": rejections,
    }


def _parse_uf_rate(value: str) -> Decimal | None:
    if not value.strip():
        return None
    try:
        rate = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("--uf-rate must be a decimal number") from exc
    if rate <= 0:
        raise ValueError("--uf-rate must be positive")
    return rate


async def _main_async(args: argparse.Namespace) -> dict[str, Any]:
    async with httpx.AsyncClient(headers=DEFAULT_HEADERS, follow_redirects=True, timeout=args.timeout_s) as client:
        runner = PortalHttpDryRun(
            client=client, max_pages_per_target=args.max_pages_per_target,
            max_details=args.max_details, pause_s=args.pause_s, uf_to_clp=_parse_uf_rate(args.uf_rate),
        )
        return await runner.run()


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded, non-persistent Portal HTTP dry-run.")
    parser.add_argument("--max-pages-per-target", type=int, default=1)
    parser.add_argument("--max-details", type=int, default=20)
    parser.add_argument("--pause-s", type=float, default=1.0)
    parser.add_argument("--uf-rate", default="", help="Optional UF->CLP rate for explicit runner conversion.")
    parser.add_argument("--timeout-s", type=float, default=30.0)
    parser.add_argument("--report", default=str(DEFAULT_REPORT_PATH))
    args = parser.parse_args()
    report = asyncio.run(_main_async(args))
    path = Path(args.report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))
    print(f"report={path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}")
    return 0 if report["metrics"]["details_ok"] >= 10 and not report["stopped_reason"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
