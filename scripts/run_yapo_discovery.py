"""Bounded, additive Yapo discovery entrypoint for the daily systemd job."""
from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from services.ingestion_state import safe_error, clean_counters

from workers.scraper_job import print_job_summary, run_yapo_once


def main() -> int:
    parser = argparse.ArgumentParser(description="Run bounded additive Yapo discovery")
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--pause-s", type=float, default=3.0)
    parser.add_argument("--max-targets", type=int, default=None)
    args = parser.parse_args()
    if args.max_pages != 1:
        parser.error("daily discovery is limited to exactly one page per target")
    if args.pause_s < 3.0:
        parser.error("daily discovery requires a pause of at least 3 seconds")
    try:
        stats = asyncio.run(run_yapo_once(max_pages=args.max_pages, min_pause_s=args.pause_s, max_targets=args.max_targets))
        print_job_summary(stats)
        print(json.dumps(clean_counters(asdict(stats))))
        return 1 if stats.unexpected_errors or stats.blocked_or_captcha or stats.fetch_errors or not stats.raw_scraped else 0
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(json.dumps({"error": safe_error(exc, stage="yapo_entrypoint")}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
