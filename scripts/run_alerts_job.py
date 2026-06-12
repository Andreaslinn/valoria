"""Manual entrypoint for independent alert evaluation.

Usage:
    python scripts/run_alerts_job.py --threshold-pct 5 --lookback-days 30
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from infrastructure.db.database import get_session_factory  # noqa: E402
from workers.alerts_job import run_alerts_job  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate persisted listing alerts.")
    parser.add_argument("--threshold-pct", type=float, default=5.0)
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=str(args.log_level).upper(),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    stats = await run_alerts_job(
        get_session_factory(),
        threshold_pct=args.threshold_pct,
        lookback_days=args.lookback_days,
    )
    print("== AVM alerts job ==")
    for key, value in stats.__dict__.items():
        print(f"{key}\t{value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
