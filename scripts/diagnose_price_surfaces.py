"""Diagnose conservative AVM price surfaces."""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from domain.valuation.price_surface import build_price_surface_index, price_surface_diagnostics  # noqa: E402
from infrastructure.db.database import get_session_factory  # noqa: E402
from infrastructure.db.repositories.listing_repo import SqlAlchemyListingRepository  # noqa: E402


async def main() -> int:
    args = _parse_args()
    async with get_session_factory()() as session:
        repo = SqlAlchemyListingRepository(session)
        listings = list(await repo.list_active(limit=args.listing_limit))

    diagnostics = price_surface_diagnostics(listings, min_samples=args.min_samples, limit=args.limit)
    index = build_price_surface_index(listings, min_samples=args.min_samples)

    print("== AVM price surface diagnostic ==")
    print(f"active_total\t{len(listings)}")
    print(f"min_samples\t{args.min_samples}")
    print(f"comuna_segments\t{len(index.by_comuna)}")
    print(f"comuna_m2_bucket_segments\t{len(index.by_comuna_bucket)}")
    print(f"microzone_segments\t{len(index.by_microzone)}")
    print(f"microzone_m2_bucket_segments\t{len(index.by_microzone_bucket)}")

    _print_rows("\n== top microzones with enough data ==", diagnostics["top_microzones"])
    _print_rows("\n== high dispersion comunas ==", diagnostics["high_dispersion_comunas"])
    _print_counter("\n== insufficient segments ==", Counter(diagnostics["insufficient_segments"]))
    print("\n== fallback examples ==")
    _print_fallback_examples(index, listings, limit=args.limit)
    return 0


def _print_rows(title: str, rows: list[dict]) -> None:
    print(title)
    if not rows:
        print("none")
        return
    headers = list(rows[0])
    print("\t".join(headers))
    for row in rows:
        print("\t".join(str(row.get(header)) for header in headers))


def _print_counter(title: str, counter: Counter[str]) -> None:
    print(title)
    if not counter:
        print("none")
        return
    print("segment\tcount")
    for key, value in counter.most_common():
        print(f"{key}\t{value}")


def _print_fallback_examples(index, listings, *, limit: int) -> None:
    seen: set[str] = set()
    printed = 0
    for listing in listings:
        result = index.lookup(listing)
        key = result.level_used
        if key in seen:
            continue
        seen.add(key)
        print(
            f"{listing.id}\t{listing.property_type}\t{listing.comuna}\t"
            f"{result.level_used}\t{result.microzone_token or ''}\t"
            f"{result.surface_price_m2 or ''}\t{result.surface_dispersion or ''}"
        )
        printed += 1
        if printed >= limit:
            break


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose price surfaces from active listings.")
    parser.add_argument("--listing-limit", type=int, default=None)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--min-samples", type=int, default=5)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
