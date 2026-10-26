"""Bounded, additive Yapo discovery entrypoint for the daily systemd job."""
from __future__ import annotations

import argparse
import asyncio

from workers.scraper_job import print_job_summary, run_yapo_once


def main() -> int:
    parser = argparse.ArgumentParser(description="Run bounded additive Yapo discovery")
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--pause-s", type=float, default=3.0)
    args = parser.parse_args()
    if args.max_pages != 1:
        parser.error("daily discovery is limited to exactly one page per target")
    if args.pause_s < 3.0:
        parser.error("daily discovery requires a pause of at least 3 seconds")
    stats = asyncio.run(run_yapo_once(max_pages=args.max_pages, min_pause_s=args.pause_s))
    print_job_summary(stats)
    return 1 if stats.unexpected_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
